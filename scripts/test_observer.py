"""Run real local Qwen on our synthetic error screen, never the user's desktop."""
import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from observer.config import Settings
from observer.exporting import build_package
from observer.models import Observation
from observer.privacy import Privacy
from observer.sample import sample_screen, sample_video
from observer.store import Store
from observer.vision import LocalQwenObserver, ObserverFailure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-layers", type=int, default=99)
    parser.add_argument("--video", action="store_true", help="Test real native video inference on an error-to-success sequence")
    parser.add_argument("--output-dir", type=Path, default=Path("qa/local-observer"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image = sample_screen()
    image.save(args.output_dir / "sample-screen.png")
    settings = Settings(observer_gpu_layers=args.gpu_layers)
    with tempfile.TemporaryDirectory(prefix="observer-real-test-") as folder:
        store = Store(Path(folder))
        runner = LocalQwenObserver(settings, store.directory / "inference-temp")
        try:
            session = store.start_session("Investigate the synthetic authentication error")
            event = Observation(session, "Example Editor", "authentication.ts", "window_change", observer_status="analyzing")
            store.add(event)
            evidence = event.to_dict()
            evidence["test_only"] = True
            result = runner.analyze(sample_video() if args.video else image, evidence, [], threading.Event())
            store.update_observer(event.id, **result)
            store.end_session(session)
            package = build_package(store, Privacy(settings), session, question="What error is visible and what should I investigate?")
            package.write_zip(args.output_dir / "sample-context.zip")
            report = {"test_only": True, "desktop_pixels_captured": 0, **result,
                      "export_contains_local_interpretation": bool(package.payload["observations"][0].get("interpretation")),
                      "temporary_images_remaining": len(list((store.directory / "inference-temp").glob("*.jpg")))}
            report["temporary_files_remaining"] = len(list((store.directory / "inference-temp").iterdir()))
            (args.output_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except ObserverFailure as error:
            print(json.dumps({"error": error.code, "runtime_detail": error.detail}, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        finally:
            runner.close()
            store.close()


if __name__ == "__main__":
    main()
