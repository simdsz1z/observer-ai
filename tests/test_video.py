import json
import threading

import pytest
from PIL import Image

from observer.config import Settings
from observer.exporting import build_package
from observer.models import Observation
from observer.privacy import Privacy
from observer.sample import sample_video
from observer.store import Store
from observer.video import ClipBuffer, ScreenClip
from observer.vision import LocalQwenObserver, ObserverFailure, enforce_evidence_limits
from test_vision import interpretation, make_pipeline, wait_for


def test_clip_buffer_preserves_order_across_apps_and_bounds_memory():
    buffer = ClipBuffer(3, 1)
    for index in range(3):
        clip = buffer.add(Image.new("RGB", (200, 100), (index, 0, 0)), str(index), float(index), f"app{index}", f"title{index}")
    assert isinstance(clip, ScreenClip)
    assert buffer.frames == []
    assert [f.application for f in clip.frames] == ["app0", "app1", "app2"]
    assert clip.metadata()["span_seconds"] == 2
    assert len(clip.rgb_bytes()) == 3 * 960 * 672 * 3
    assert clip.fps == 1


def test_withheld_frames_and_long_gaps_do_not_join_sequences():
    buffer = ClipBuffer(3, 1)
    image = Image.new("RGB", (20, 20))
    buffer.add(image, "first", 0, "app", "title")
    buffer.clear()  # privacy boundary
    buffer.add(image, "second", 1, "app", "title")
    buffer.add(image, "after gap", 20, "app", "title")
    assert len(buffer.frames) == 1
    assert buffer.frames[0].timestamp == "after gap"


def test_video_allows_observed_changes_without_inventing_intent():
    result, _ = enforce_evidence_limits(interpretation(changes=["Red error changes to green success"]),
                                       {"video": {"frame_count": 8}}, [])
    assert result["changes"] == ["Red error changes to green success"]
    assert result["task_context"] is None


def test_stream_delivers_unchanged_frames_to_video_model(tmp_path):
    store = Store(tmp_path)
    recorder, captures = make_pipeline(store, video=True)
    try:
        assert recorder.start("Watch the example")
        wait_for(lambda: recorder.vision and recorder.vision.completed >= 1)
        assert recorder.stream_frames >= 8
        assert recorder.stream_clips >= 1
        assert any(e["event_type"] == "screen_video" and e.get("interpretation") for e in store.query())
        assert recorder.metrics["duplicates"] > 0
        assert recorder.stop()
        assert recorder.stream_buffered == 0
        assert not list((tmp_path / "screenshots").glob("*.jpg"))
    finally:
        recorder.stop()
        store.close()


def test_video_native_flag_and_cleanup_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("observer.vision.video_tools", lambda: ("ffmpeg.exe", "ffprobe.exe"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    settings = Settings(observer_executable=__file__, observer_model_path=str(model), observer_projector_path=str(model))
    runner = LocalQwenObserver(settings, tmp_path / "temporary")
    monkeypatch.setattr("observer.vision.vision_gpu_available", lambda: False)
    calls = []
    def invoke(args, stop, input_data=None):
        calls.append(args)
        if input_data is not None:
            assert input_data
            return ""
        assert "--video" in args
        assert "--image" not in args
        assert len(list(runner.directory.glob("*.mp4"))) == 1
        raise ObserverFailure("inference_timeout")
    monkeypatch.setattr(runner, "_invoke", invoke)
    with pytest.raises(ObserverFailure, match="inference_timeout"):
        runner.analyze(sample_video(), {}, [], threading.Event())
    assert len(calls) == 2
    assert list(runner.directory.iterdir()) == []


def test_new_privacy_rules_cover_all_video_frames(tmp_path):
    store = Store(tmp_path)
    try:
        session = store.start_session("goal")
        meta = sample_video().metadata()
        meta["frames"][0]["application"] = "secret.exe"
        event = Observation(session, "editor", "public", "screen_video", observer_input=meta)
        store.add(event)
        package = build_package(store, Privacy(Settings(excluded_apps=["secret"])), session, question="next")
        assert package.payload["observations"] == []
        assert package.payload["selection"]["events_omitted_by_privacy"] == 1
        package = build_package(store, Privacy(Settings(redactions=["authentication"])), session, question="next")
        assert "authentication" not in package.json_text
    finally:
        store.close()


def test_old_default_migrates_to_video_without_changing_custom_interval(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"observer_interval_seconds": 20}))
    assert Settings.load(tmp_path).observer_video
    assert Settings.load(tmp_path).observer_interval_seconds == 5
    (tmp_path / "settings.json").write_text(json.dumps({"observer_interval_seconds": 35}))
    assert Settings.load(tmp_path).observer_interval_seconds == 35
