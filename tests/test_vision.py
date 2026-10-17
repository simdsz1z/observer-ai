import json
import sys
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from observer.config import Settings
from observer.engine import Recorder
from observer.exporting import build_package
from observer.models import Accessibility, Observation, Window
from observer.privacy import Privacy
from observer.store import Store
from observer.vision import LocalQwenObserver, MODEL_NAME, ObserverFailure, VisionWorker, enforce_evidence_limits, parse_output, validate_interpretation


def interpretation(**updates):
    result = {"activity": "debugging", "description": "A build error is visible.",
              "visible_errors": ["TypeError: example"], "changes": [], "task_context": None,
              "event_type": "potential_error", "importance": 0.7, "confidence": 0.8,
              "requires_supervisor_review": True, "uncertainty": "Intent is unknown."}
    result.update(updates)
    return result


def wait_for(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out")


def test_schema_rejects_invalid_or_invented_fields():
    assert validate_interpretation(interpretation())
    for value in [interpretation(confidence=True), interpretation(confidence=float("nan")), interpretation(importance=2),
                  interpretation(activity=123), interpretation(event_type="execute_command"), interpretation(visible_errors="error"),
                  {**interpretation(), "command": "do something"}]:
        with pytest.raises(ValueError):
            validate_interpretation(value)


def test_parser_accepts_runtime_noise_and_rejects_partial_output():
    expected = interpretation()
    assert parse_output('runtime metadata {"version": 1}\n```json\n' + json.dumps(expected) + '\n```\nperformance: 4s') == expected
    with pytest.raises(ObserverFailure, match="invalid_model_output"):
        parse_output('{"activity":"debugging"}')


def test_observer_updates_preserve_raw_evidence_and_refresh_revision(tmp_path):
    store = Store(tmp_path)
    try:
        session = store.start_session("goal")
        event = Observation(session, "app", "original title", "window_change", ["raw label"])
        store.add(event)
        before = store.revision
        assert store.update_observer(event.id, interpretation=interpretation(), observer_status="complete")
        result = store.query()[0]
        assert result["window_title"] == "original title"
        assert result["visible_text"] == ["raw label"]
        assert result["interpretation"]["activity"] == "debugging"
        assert store.revision > before
        with pytest.raises(ValueError):
            store.update_observer(event.id, window_title="invented title")
    finally:
        store.close()


def test_missing_model_does_not_silently_start_raw_only_recording(tmp_path):
    store = Store(tmp_path)
    try:
        recorder = Recorder(store, Settings(observer_enabled=True), observer_check=lambda settings: (False, "Model missing"))
        assert not recorder.start("goal")
        assert not recorder.running
        assert store.sessions() == []
        assert recorder.state == "Model missing"
    finally:
        store.close()


class FakeObserver:
    def __init__(self, settings, directory):
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def analyze(self, image, evidence, previous, stop):
        self.started.set()
        while not self.release.wait(0.01):
            if stop.is_set():
                raise ObserverFailure("cancelled")
        return {"interpretation": interpretation(description="alice@example.com sees an error"),
                "observer_status": "complete", "observer_model": MODEL_NAME, "observer_latency_ms": 1.0, "observer_error": None}

    def close(self):
        self.closed = True


def test_worker_bounds_queue_cancels_and_never_archives_frames(tmp_path):
    store = Store(tmp_path)
    stop = threading.Event()
    settings = Settings(observer_interval_seconds=0.01)
    worker = VisionWorker(store, settings, Privacy(settings), stop, observer_factory=FakeObserver)
    try:
        session = store.start_session("goal")
        first = Observation(session, "app", "title", "window_change", observer_status="queued")
        store.add(first)
        worker.submit(first, Image.new("RGB", (200, 100)))
        assert worker.observer.started.wait(2)
        for index in range(12):
            event = Observation(session, "app", f"title {index}", "visual_change", observer_status="queued")
            store.add(event)
            worker.submit(event, Image.new("RGB", (200, 100)))
        assert len(worker.pending) <= 2
        assert worker.dropped >= 10
        worker.observer.release.set()
        wait_for(lambda: worker.completed >= 1)
        result = store.query()[0]
        assert "alice@example.com" not in json.dumps(result)
        assert result["interpretation"]["description"].startswith("[EMAIL]")
        assert not list((tmp_path / "screenshots").glob("*.jpg"))
        assert worker.close()
        assert all(e.get("observer_status") not in {"queued", "analyzing"} for e in store.query())
    finally:
        worker.close()
        store.close()


def test_cancelling_an_active_analysis_persists_no_interpretation(tmp_path):
    store = Store(tmp_path)
    stop = threading.Event()
    settings = Settings()
    worker = VisionWorker(store, settings, Privacy(settings), stop, observer_factory=FakeObserver)
    try:
        session = store.start_session("goal")
        event = Observation(session, "app", "title", "window_change", observer_status="queued")
        store.add(event)
        worker.submit(event, Image.new("RGB", (100, 100)))
        assert worker.observer.started.wait(2)
        assert worker.close()
        result = store.query()[0]
        assert result["observer_status"] == "cancelled"
        assert result.get("interpretation") is None
        assert worker.observer.closed
    finally:
        worker.close()
        store.close()


def test_real_subprocess_cancellation_is_prompt_and_reaped(tmp_path):
    runner = LocalQwenObserver(Settings(), tmp_path)
    stop = threading.Event()
    failure = []
    def invoke():
        try:
            runner._invoke([sys.executable, "-c", "import time; time.sleep(60)"], stop)
        except ObserverFailure as error:
            failure.append(error.code)
    thread = threading.Thread(target=invoke)
    thread.start()
    wait_for(lambda: runner.process is not None)
    stop.set()
    runner.close()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert failure == ["cancelled"]
    assert runner.process is None


def test_temporary_pixels_are_removed_when_inference_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("observer.vision.vision_gpu_available", lambda: False)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    settings = Settings(observer_executable=sys.executable, observer_model_path=str(model), observer_projector_path=str(model), observer_video=False)
    runner = LocalQwenObserver(settings, tmp_path / "temporary")
    def fail(args, stop):
        assert len(list(runner.directory.glob("*.jpg"))) == 1
        raise ObserverFailure("inference_timeout")
    monkeypatch.setattr(runner, "_invoke", fail)
    with pytest.raises(ObserverFailure, match="inference_timeout"):
        runner.analyze(Image.new("RGB", (100, 100)), {}, [], threading.Event())
    assert list(runner.directory.iterdir()) == []


def test_single_frame_cannot_establish_changes_or_user_intent():
    value, notes = enforce_evidence_limits(interpretation(changes=["The user executed the code"], task_context="Invented task"), {}, [])
    assert value["changes"] == []
    assert value["task_context"] is None
    assert len(notes) == 2
    value, notes = enforce_evidence_limits(interpretation(changes=["An error remains visible"], task_context="Invented task"),
                                          {"user_stated_goal": "Fix authentication"}, [{"description": "An error was visible"}])
    assert value["task_context"] == "Fix authentication"
    assert value["changes"] == ["An error remains visible"]


def test_scores_match_constrained_numeric_schema():
    with pytest.raises(ValueError):
        validate_interpretation(interpretation(importance=3))
    with pytest.raises(ValueError):
        validate_interpretation(interpretation(confidence=0.123))


def test_export_preserves_model_provenance_and_re_redacts_inferences(tmp_path):
    store = Store(tmp_path)
    try:
        session = store.start_session("goal")
        event = Observation(session, "app", "title", "window_change", interpretation=interpretation(description="Customer Alpha has a visible error"),
                            observer_model=MODEL_NAME, observer_status="complete", observer_latency_ms=1234)
        store.add(event)
        package = build_package(store, Privacy(Settings(redactions=["Customer Alpha"])), session, question="Next?")
        assert package.payload["schema_version"] == 2
        assert package.payload["observations"][0]["observer_model"] == MODEL_NAME
        assert "Customer Alpha" not in package.prompt
        assert "fallible" in package.prompt
        assert package.images == {}
    finally:
        store.close()


def make_pipeline(store, *, protected=None, video=False):
    window = Window(42, 987654321, "editor.exe", "Payment" if protected == "excluded" else "Example", (0, 0, 600, 400))
    desktop = SimpleNamespace(foreground=lambda: window, idle_seconds=lambda: 180 if protected == "idle" else 0, visible_windows=lambda: [])
    access = SimpleNamespace(read=lambda handle, stop: Accessibility(["Build failed"], "available", sensitive=protected == "password"), close=lambda: None)
    capture_count = []
    def grab(window, masks):
        capture_count.append(1)
        return Image.new("RGB", (600, 400), "navy")
    capture = SimpleNamespace(grab=grab, close=lambda: None)
    class ImmediateObserver(FakeObserver):
        def __init__(self, settings, directory):
            super().__init__(settings, directory)
            self.release.set()
    settings = Settings(interval_seconds=0.03, observer_interval_seconds=0.01, screenshots=False, observer_video=video)
    recorder = Recorder(store, settings, desktop_factory=lambda: desktop, accessibility_factory=lambda: access,
                        capture_factory=lambda: capture, observer_check=lambda settings: (True, "installed"),
                        vision_factory=lambda *args: VisionWorker(*args, observer_factory=ImmediateObserver))
    return recorder, capture_count


def test_full_recorder_pipeline_adds_interpretations_without_image_archives(tmp_path):
    store = Store(tmp_path)
    recorder, captures = make_pipeline(store)
    try:
        assert recorder.start("Fix the example")
        wait_for(lambda: store.count() > 0 and store.query()[0].get("interpretation"))
        assert recorder.stop()
        result = store.query()[0]
        assert result["observer_status"] == "complete"
        assert result["screenshot"] is None
        assert captures
        assert not list((tmp_path / "screenshots").glob("*.jpg"))
        package = build_package(store, Privacy(recorder.settings), recorder.session_id, question="What happened?")
        assert package.payload["observations"][0]["interpretation"]["activity"] == "debugging"
    finally:
        recorder.stop()
        store.close()


@pytest.mark.parametrize("protection", ["excluded", "password", "idle"])
def test_local_qwen_never_receives_protected_frames(tmp_path, protection):
    store = Store(tmp_path)
    recorder, captures = make_pipeline(store, protected=protection)
    try:
        assert recorder.start("goal")
        wait_for(lambda: "suspended" in recorder.state)
        assert recorder.stop()
        assert captures == []
        assert recorder.vision.completed == 0
        assert store.count() == 0
    finally:
        recorder.stop()
        store.close()
