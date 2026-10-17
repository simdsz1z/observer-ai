import json
import threading
import time
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from observer.capture import difference, fingerprint
from observer.config import Settings
from observer.engine import Recorder
from observer.exporting import build_package
from observer.models import Accessibility, Observation, Window
from observer.privacy import Privacy
from observer.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "data")
    yield result
    result.close()


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for recorder")


class FakeDesktop:
    def __init__(self, title="Example editor", idle=0):
        self.window = Window(42, 987654321, "editor.exe", title, (0, 0, 800, 600))
        self.idle = idle

    def foreground(self):
        return self.window

    def idle_seconds(self):
        return self.idle

    def visible_windows(self):
        return []


class FakeAccessibility:
    def __init__(self, result=None):
        self.result = result or Accessibility(["Build failed", "user@example.com"], "available")

    def read(self, handle, stop):
        return self.result

    def close(self):
        pass


class FakeCapture:
    def __init__(self):
        self.calls = 0

    def grab(self, window, excluded):
        self.calls += 1
        return Image.new("RGB", (200, 100), "navy")

    def close(self):
        pass


def recorder_for(store, desktop=None, access=None, capture=None, screenshots=False):
    settings = Settings(interval_seconds=0.03, screenshots=screenshots, observer_enabled=False)
    return Recorder(store, settings, desktop_factory=lambda: desktop or FakeDesktop(),
                    accessibility_factory=lambda: access or FakeAccessibility(),
                    capture_factory=lambda: capture or FakeCapture())


def test_exclusions_case_insensitive_and_blank_rules():
    privacy = Privacy(Settings(excluded_apps=["secret", ""], excluded_titles=["payment", ""]))
    window = FakeDesktop().window
    assert not privacy.excluded(window)
    assert privacy.excluded(replace(window, application="SecretApp.exe"))
    assert privacy.excluded(replace(window, title="Payment complete"))


def test_redaction_keeps_evidence_readable():
    privacy = Privacy(Settings(redactions=["Customer Alpha"]))
    source = "Customer Alpha alice@example.com sk-12345678901234567890 password=hello 4111 1111 1111 1111 Build failed"
    result = privacy.redact(source)
    for secret in ("Customer Alpha", "alice@example.com", "sk-12345678901234567890", "hello", "4111"):
        assert secret not in result
    assert "Build failed" in result


def test_settings_round_trip_and_invalid_values(tmp_path):
    settings = Settings(screenshots=False, redactions=["private"])
    settings.save(tmp_path)
    assert Settings.load(tmp_path) == settings
    with pytest.raises(ValueError):
        Settings(interval_seconds=0.01).save(tmp_path)


def test_store_search_sessions_and_order(store):
    session = store.start_session("Debug")
    a = Observation(session, "editor", "first", "window_change", ["error 100%"])
    b = Observation(session, "browser", "second", "window_change", ["docs"])
    store.add(a)
    store.add(b)
    assert [x["id"] for x in store.query(session_id=session)] == [a.id, b.id]
    assert [x["id"] for x in store.query(search="100%")] == [a.id]
    assert store.query(search="' OR 1=1 --") == []
    assert store.query(limit=1)[0]["id"] == b.id


def test_recording_requires_start_and_stops_persisting(store):
    recorder = recorder_for(store)
    assert not recorder.running
    assert store.count() == 0
    recorder.start("goal")
    try:
        wait_for(lambda: recorder.metrics["samples"] >= 4)
    finally:
        assert recorder.stop()
    assert store.count() == 1  # unchanged error visibility is not repeated attempts
    assert recorder.metrics["duplicates"] >= 3
    assert "user@example.com" not in json.dumps(store.query())
    count = store.count()
    time.sleep(0.1)
    assert store.count() == count
    assert store.sessions()[0]["ended_at"]


@pytest.mark.parametrize("mode", ["excluded", "password", "idle"])
def test_protected_windows_never_capture_or_store(store, mode):
    capture = FakeCapture()
    desktop = FakeDesktop(title="Payment details" if mode == "excluded" else "Editor", idle=180 if mode == "idle" else 0)
    access = FakeAccessibility(Accessibility(sensitive=True, status="password_field") if mode == "password" else None)
    recorder = recorder_for(store, desktop, access, capture, screenshots=True)
    recorder.start("goal")
    try:
        wait_for(lambda: "suspended" in recorder.state)
    finally:
        assert recorder.stop()
    assert capture.calls == 0
    assert store.count() == 0
    assert not list((store.directory / "screenshots").glob("*.jpg"))


def test_accessibility_failure_withholds_pixels(store):
    capture = FakeCapture()
    recorder = recorder_for(store, access=FakeAccessibility(Accessibility(status="unavailable")), capture=capture, screenshots=True)
    recorder.start("goal")
    try:
        wait_for(lambda: store.count() == 1)
    finally:
        assert recorder.stop()
    assert capture.calls == 0
    assert store.query()[0]["screenshot"] is None
    assert store.query()[0]["accessibility_status"] == "unavailable"


def test_screenshot_saved_once_and_export_frozen(store):
    recorder = recorder_for(store, screenshots=True)
    recorder.start("Investigate build")
    try:
        wait_for(lambda: recorder.metrics["samples"] >= 3)
    finally:
        assert recorder.stop()
    package = build_package(store, Privacy(Settings()), recorder.session_id, question="Help", include_images=True)
    assert len(package.images) == 1
    archive = store.directory.parent / "evidence.zip"
    image_name, image_bytes = next(iter(package.images.items()))
    store.clear()
    package.write_zip(archive)
    with zipfile.ZipFile(archive) as result:
        assert result.read(image_name) == image_bytes
        assert json.loads(result.read("context.json"))["observations"][0]["id"]
        assert len(result.read("observations.jsonl").decode().splitlines()) == 1


def test_frame_change_discriminates_small_noise():
    a = fingerprint(Image.new("RGB", (200, 100), "black"))
    b = fingerprint(Image.new("RGB", (200, 100), "white"))
    assert difference(a, a) == 0
    assert difference(a, b) == 1


def test_focus_race_discards_all_data(store):
    class RacingDesktop(FakeDesktop):
        def foreground(self):
            self.window = replace(self.window, title=self.window.title + ".")
            return self.window
    capture = FakeCapture()
    recorder = recorder_for(store, desktop=RacingDesktop(), capture=capture, screenshots=True)
    recorder.start("goal")
    time.sleep(0.15)
    assert recorder.stop()
    assert store.count() == 0
    assert capture.calls == 0


def test_export_limits_re_redacts_and_does_not_mutate_database(store):
    session = store.start_session("Customer Alpha")
    for index in range(5):
        store.add(Observation(session, "editor", f"Customer Alpha {index}", "ui_text_change", ["x" * 300]))
    package = build_package(store, Privacy(Settings(redactions=["Customer Alpha"])), session, question="next", limit=3, max_characters=1400)
    assert "Customer Alpha" not in package.prompt
    assert "Customer Alpha" not in package.json_text
    assert package.payload["selection"]["events_omitted_for_size"] > 0
    assert len(package.payload["observations"]) < 3
    assert "Customer Alpha" in store.query()[0]["window_title"]


def test_export_never_reads_paths_outside_screenshot_folder(store):
    secret = store.directory.parent / "secret.txt"
    secret.write_text("OUTSIDE_FILE_SECRET_987", encoding="utf-8")
    session = store.start_session("test")
    store.add(Observation(session, "app", "title", "window_change", screenshot="../secret.txt"))
    package = build_package(store, Privacy(Settings()), session, question="help", include_images=True)
    assert package.images == {}
    assert "OUTSIDE_FILE_SECRET_987" not in package.json_text


def test_current_exclusions_remove_historical_events_from_export(store):
    session = store.start_session("goal")
    store.add(Observation(session, "sensitive-app.exe", "private window", "window_change", ["private label"]))
    store.add(Observation(session, "editor.exe", "public window", "window_change", ["public label"]))
    package = build_package(store, Privacy(Settings(excluded_apps=["sensitive-app"])), session, question="help")
    assert len(package.payload["observations"]) == 1
    assert package.payload["selection"]["events_omitted_by_privacy"] == 1
    assert "private label" not in package.json_text
    assert store.count() == 2


def test_retention_and_clear_remove_images_and_responses(store):
    session = store.start_session("old")
    event = Observation(session, "app", "old", "window_change", screenshot="screenshots/old.jpg",
                        timestamp=(datetime.now(timezone.utc) - timedelta(days=9)).isoformat())
    store.add(event)
    (store.directory / event.screenshot).write_bytes(b"old image")
    store.save_response(session, "website", "Advice", [event.id])
    store.maintain(7, 16)
    assert store.count() == 0
    assert not (store.directory / event.screenshot).exists()
    store.clear()
    assert not store.sessions()
    assert not store.responses()


def test_manual_advice_is_data_and_traceable(store):
    session = store.start_session("goal")
    event = Observation(session, "app", "title", "window_change")
    store.add(event)
    store.save_response(session, "Claude", "Try reading the exact error.", [event.id])
    package = build_package(store, Privacy(Settings()), session, question="Next?")
    assert json.loads(package.payload["previous_unverified_ai_responses"][0]["evidence_ids"]) == [event.id]
    assert "UNTRUSTED" in package.prompt

