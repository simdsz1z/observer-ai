"""Measure the local pipeline. Synthetic mode never accesses the desktop."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil
from PIL import Image

from observer.capture import difference, fingerprint
from observer.config import Settings
from observer.engine import Recorder
from observer.exporting import build_package
from observer.models import Observation
from observer.privacy import Privacy
from observer.store import Store
from observer.windows import enable_dpi_awareness


def synthetic(directory, events):
    process = psutil.Process()
    started = time.perf_counter()
    store = Store(directory)
    try:
        session = store.start_session("Synthetic benchmark — no desktop access")
        database_start = time.perf_counter()
        for index in range(events):
            store.add(Observation(session, "synthetic.exe", f"Synthetic frame {index}", "ui_text_change",
                                  ["Synthetic build failed", "Synthetic diagnostics" * 8]))
        database_seconds = time.perf_counter() - database_start
        a = fingerprint(Image.new("RGB", (1440, 900), "black"))
        image = Image.new("RGB", (1440, 900), "white")
        frame_start = time.perf_counter()
        for _ in range(300):
            difference(a, fingerprint(image))
        frame_seconds = time.perf_counter() - frame_start
        package_start = time.perf_counter()
        package = build_package(store, Privacy(Settings()), session, question="Summarize synthetic evidence", limit=100)
        package.write_zip(directory / "benchmark.zip")
        export_seconds = time.perf_counter() - package_start
        return {"mode": "synthetic_no_desktop_access", "events_written": events,
                "database_write_seconds": round(database_seconds, 4),
                "events_per_second": round(events / database_seconds, 1),
                "frame_diff_mean_ms": round(frame_seconds / 300 * 1000, 3),
                "context_and_zip_ms": round(export_seconds * 1000, 3),
                "events_in_context": len(package.payload["observations"]),
                "rss_mb": round(process.memory_info().rss / 1024**2, 1),
                "total_seconds": round(time.perf_counter() - started, 3),
                "limitations": "Synthetic processing only. Not a screen-capture, UIA, idle CPU, GPU, or long-duration benchmark."}
    finally:
        store.close()


def live(directory, seconds, screenshots):
    enable_dpi_awareness()
    store = Store(directory)
    recorder = Recorder(store, Settings(screenshots=screenshots, observer_enabled=False))
    print("RECORDING LOCAL DESKTOP EVIDENCE. Ctrl+C stops. No uploads. Keep sensitive windows excluded.", flush=True)
    recorder.start("User-requested live performance benchmark")
    process = psutil.Process()
    process.cpu_percent()
    cpus, memory = [], []
    start = time.monotonic()
    try:
        while time.monotonic() - start < seconds:
            time.sleep(1)
            children = process.children(recursive=True)
            memory.append((process.memory_info().rss + sum(p.memory_info().rss for p in children if p.is_running())) / 1024**2)
            cpus.append(process.cpu_percent())
            print(f"RECORDING · {recorder.state} · {recorder.metrics['events']} events", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if not recorder.stop():
            raise RuntimeError("Capture has not stopped; wait before deleting its data.")
        store.close()
    return {"mode": "live_user_opt_in", "seconds": round(time.monotonic() - start, 2),
            "main_process_cpu_mean_percent": round(sum(cpus) / max(1, len(cpus)), 2),
            "rss_with_uia_child_peak_mb": round(max(memory, default=0), 1),
            "recorder_metrics": recorder.metrics,
            "limitations": "CPU excludes UIA child. GPU usage and event accuracy are not measured."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable live desktop evidence recording for this benchmark")
    parser.add_argument("--screenshots", action="store_true", help="With --live, consent to save active-window screenshots")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--data-dir", type=Path, help="Keep evidence here; otherwise use a temporary folder")
    args = parser.parse_args()
    if not 1 <= args.events <= 10000 or not 1 <= args.seconds <= 300:
        parser.error("Use 1–10000 events and 1–300 seconds.")
    if args.screenshots and not args.live:
        parser.error("--screenshots requires explicit --live recording.")
    if args.data_dir:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        result = live(args.data_dir, args.seconds, args.screenshots) if args.live else synthetic(args.data_dir, args.events)
    else:
        with tempfile.TemporaryDirectory(prefix="observer-benchmark-") as directory:
            result = live(Path(directory), args.seconds, args.screenshots) if args.live else synthetic(Path(directory), args.events)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()

