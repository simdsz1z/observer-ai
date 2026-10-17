"""Measure actual one-second Qwen throughput on file frames or opt-in desktop capture."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time

import psutil
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observer.config import Settings, default_data_dir
from observer.accessibility import AccessibilityReader
from observer.engine import Recorder
from observer.models import Observation, now_iso
from observer.privacy import Privacy
from observer.store import Store
from observer.video import ClipBuffer, video_tools
from observer.vision import VisionWorker
from observer.windows import enable_dpi_awareness


def gpu_sample():
    try:
        p = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return dict(zip(["vram_mb", "gpu_percent", "temperature_c", "power_w"], map(float, p.stdout.splitlines()[0].split(","))))
    except Exception:
        return {}


def file_feed(path, settings, store, worker, stop, seconds, counts):
    ffmpeg, _ = video_tools()
    args = [ffmpeg, "-v", "error", "-i", str(path.resolve()), "-an", "-vf",
            "fps=2,scale=960:672:force_original_aspect_ratio=decrease,pad=960:672:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    session = store.start_session("Benchmark real outdoor footage: report visible activity, do not invent user intent")
    buffer = ClipBuffer(2, .5)
    started = time.monotonic()
    frame_index = 0
    try:
        while not stop.is_set() and time.monotonic() - started < seconds:
            raw = process.stdout.read(960 * 672 * 3)
            if len(raw) != 960 * 672 * 3:
                break
            target = started + frame_index * .5
            if stop.wait(max(0, target - time.monotonic())):
                break
            now = time.monotonic()
            clip = buffer.add(Image.frombytes("RGB", (960, 672), raw), now_iso(), now, "real video", "OpenCV vtest outdoor footage")
            frame_index += 1
            counts["frames"] = frame_index
            if clip:
                event = Observation(session, "real video", "OpenCV vtest outdoor footage", "screen_video", observer_status="queued", observer_input=clip.metadata())
                store.add(event)
                worker.submit(event, clip)
                counts["clips"] += 1
    finally:
        process.kill()
        process.communicate(timeout=3)
        store.end_session(session)


def measure(args):
    settings = Settings.load(default_data_dir())
    settings.interval_seconds = .5
    settings.observer_video_frames = 2
    settings.observer_interval_seconds = 1
    settings.observer_enabled = settings.observer_video = True
    settings.screenshots = False
    settings.validate()
    enable_dpi_awareness()
    with tempfile.TemporaryDirectory(prefix="observer-real-benchmark-") as directory:
        store = Store(Path(directory))
        stop = threading.Event()
        recorder = None
        counts = {"frames": 0, "clips": 0}
        producer = None
        accessibility_counts = Counter()
        access = None
        resources = []
        parent = psutil.Process()
        baseline = gpu_sample()
        started = time.monotonic()
        if args.live:
            class MeasuredAccessibility(AccessibilityReader):
                def read(self, handle, stopped):
                    result = super().read(handle, stopped)
                    accessibility_counts[result.status] += 1
                    if accessibility_counts[result.status] == 1:
                        print(json.dumps({"accessibility_status": result.status, "last_failure": self.last_failure}), flush=True)
                    return result
            access = MeasuredAccessibility()
            recorder = Recorder(store, settings, accessibility_factory=lambda: access)
            if not recorder.start("User-authorized real desktop one-second monitoring benchmark"):
                raise RuntimeError(recorder.state)
            worker = None
        else:
            worker = VisionWorker(store, settings, Privacy(settings), stop)
            producer = threading.Thread(target=file_feed, args=(args.video, settings, store, worker, stop, args.seconds, counts), daemon=True)
            producer.start()
        try:
            while time.monotonic() - started < args.seconds:
                stop.wait(1)
                if recorder:
                    worker = recorder.vision
                    counts = {"frames": recorder.stream_frames, "clips": recorder.stream_clips}
                processes = [parent]
                try:
                    processes.extend(parent.children(recursive=True))
                except psutil.Error:
                    pass
                rss = 0
                for process in processes:
                    try:
                        rss += process.memory_info().rss / 1024**2
                    except psutil.Error:
                        pass
                sample = {"at_seconds": round(time.monotonic() - started, 2), "rss_tree_mb": round(rss, 1),
                          "system_cpu_percent": psutil.cpu_percent(), **gpu_sample()}
                resources.append(sample)
                if len(resources) % 10 == 0:
                    print(json.dumps({"elapsed": sample["at_seconds"], **counts, "completed": worker.completed if worker else 0,
                                      "skipped": worker.dropped if worker else 0, "rss_tree_mb": sample["rss_tree_mb"],
                                      "state": recorder.state if recorder else "file streaming"}), flush=True)
        finally:
            active_seconds = time.monotonic() - started
            if recorder:
                while not recorder.stop():
                    time.sleep(.1)
                worker = recorder.vision
            else:
                stop.set()
                producer.join(timeout=4)
                while not worker.close():
                    time.sleep(.1)
        events = [e for e in store.query(limit=10000) if e["event_type"] == "screen_video"]
        all_events = store.query(limit=10000)
        statuses = dict(Counter(e["observer_status"] for e in events))
        completed = [e for e in events if e.get("observer_latency_ms") is not None]
        latencies = [e["observer_latency_ms"] / 1000 for e in completed]
        def peak(key):
            return max((r.get(key, 0) for r in resources), default=0)
        report = {"mode": "native_live_desktop" if args.live else "real_video_file_paced_in_real_time",
                  "seconds": round(active_seconds, 2), "target_clip_seconds": 1, "target_capture_fps": 2,
                  "source": "current permitted foreground window" if args.live else "https://github.com/opencv/opencv/blob/4.x/samples/data/vtest.avi",
                  **counts, "completed": len(completed), "statuses": statuses,
                  "actual_capture_fps": round(counts["frames"] / active_seconds, 3),
                  "observed_application_event_counts": dict(Counter(e["application"] for e in all_events)),
                  "skipped_percent": round(100 * statuses.get("skipped_busy", 0) / max(1, len(events)), 1),
                  "completed_clips_per_second": round(len(completed) / active_seconds, 3),
                  "processing_seconds_mean": round(statistics.mean(latencies), 3) if latencies else None,
                  "processing_seconds_median": round(statistics.median(latencies), 3) if latencies else None,
                  "processing_seconds_max": round(max(latencies), 3) if latencies else None,
                  "processing_seconds_all": [round(x, 3) for x in latencies],
                  "native_runtime_samples": [(e.get("observer_input") or {}).get("runtime") for e in completed],
                  "rss_process_tree_peak_mb": peak("rss_tree_mb"), "gpu_baseline": baseline,
                  "gpu_vram_peak_mb": peak("vram_mb"), "gpu_utilization_peak_percent": peak("gpu_percent"),
                  "gpu_temperature_peak_c": peak("temperature_c"), "gpu_power_peak_w": peak("power_w"),
                  "system_cpu_mean_percent": round(statistics.mean(r["system_cpu_percent"] for r in resources), 1),
                  "capture_metrics": recorder.metrics if recorder else None,
                  "accessibility_status_counts": dict(accessibility_counts),
                  "accessibility_last_failure": access.last_failure if access else None,
                  "temporary_files_remaining": len(list((store.directory / "inference-temp").iterdir())),
                  "keeps_up_without_skipping": bool(len(events) >= 10 and statuses.get("skipped_busy", 0) == 0 and
                                                    len(completed) >= len(events) - 3 and statistics.mean(latencies) <= 1),
                  "limitations": "Short performance test, not long-duration stability. GPU/CPU device metrics include other apps. Capture includes native privacy/UIA checks only in live mode. Ending cancels unfinished work; classifications are fallible."}
        if not args.live:
            report["sample_descriptions"] = [e["interpretation"]["description"] for e in completed[:3]]
        store.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sample_descriptions"}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Consent to capture permitted current desktop pixels locally")
    group.add_argument("--video", type=Path)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 300:
        parser.error("Use 10–300 seconds.")
    measure(args)
