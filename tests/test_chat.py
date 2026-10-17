import json
import os
from pathlib import Path
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent

from observer.chat import LocalQwenChat, conversation_prompt, screen_context
from observer.chat_ui import ChatPanel
from observer.config import Settings
from observer.models import Observation
from observer.privacy import Privacy
from observer.store import Store
from observer.vision import ObserverFailure, model_slot


def test_chat_storage_clear_and_delete_memory(tmp_path):
    store = Store(tmp_path)
    store.save_chat("user", "hello", "example.mp4")
    store.save_chat("assistant", "hi")
    assert [m["role"] for m in store.chat_history()] == ["user", "assistant"]
    assert store.chat_history()[0]["attachment"] == "example.mp4"
    store.close()
    store = Store(tmp_path)
    assert len(store.chat_history()) == 2
    store.clear_chat()
    assert store.chat_history() == []
    store.save_chat("user", "another")
    store.clear()
    assert store.chat_history() == []
    store.close()


def test_recent_screen_context_respects_nested_exclusions_and_redactions(tmp_path):
    store = Store(tmp_path)
    try:
        session = store.start_session("goal")
        store.add(Observation(session, "editor", "public", "screen_video", interpretation={"description": "alice@example.com"}))
        store.add(Observation(session, "editor", "public", "screen_video", interpretation={"description": "private"},
                              observer_input={"frames": [{"application": "secret.exe", "window_title": "secret"}]}))
        context = screen_context(store, Privacy(Settings(excluded_apps=["secret"])))
        assert len(context) == 1
        assert "alice@example.com" not in json.dumps(context)
        assert "private" not in json.dumps(context)
        prompt = conversation_prompt("What next?", [{"role": "user", "content": "Earlier question"}], context)
        assert "Earlier question" in prompt
        assert prompt.endswith("What next?")
    finally:
        store.close()


def test_video_all_sections_are_analyzed_and_chronological_reply_keeps_each(tmp_path, monkeypatch):
    runner = LocalQwenChat(Settings(), tmp_path)
    monkeypatch.setattr(runner, "probe_video", lambda path, stop: 18.0)
    monkeypatch.setattr("observer.chat.video_tools", lambda: ("ffmpeg", "ffprobe"))
    encoded = []
    def invoke(args, stop):
        encoded.append(float(args[args.index("-ss") + 1]))
    monkeypatch.setattr(runner, "_invoke", invoke)
    prompts = []
    def reply(prompt, stop, **kwargs):
        prompts.append((prompt, kwargs))
        return f"Section {len(prompts)} evidence"
    monkeypatch.setattr(runner, "_reply", reply)
    result = runner.reply("Describe changes", [], [], threading.Event(), video=tmp_path / "video.mp4")
    assert encoded == [0, 8, 16]
    assert result["video"]["sections_analyzed"] == 3
    assert result["video"]["end_seconds"] == 18
    assert len(prompts) == 3
    assert all(f"Section {i} evidence" in result["answer"] for i in [1, 2, 3])
    assert result["answer"].index("Original seconds 0.0") < result["answer"].index("Original seconds 16.0")
    assert list(tmp_path.iterdir()) == []


def test_video_range_and_stop_do_not_leave_temporary_files(tmp_path, monkeypatch):
    runner = LocalQwenChat(Settings(), tmp_path)
    monkeypatch.setattr(runner, "probe_video", lambda path, stop: 20.0)
    with pytest.raises(ObserverFailure, match="invalid_video_range"):
        runner.reply("describe", [], [], threading.Event(), video="example.mp4", start=21)
    stop = threading.Event()
    stop.set()
    def unexpected_probe(path, stop):
        pytest.fail("An already-cancelled request must not inspect the video")
    monkeypatch.setattr(runner, "probe_video", unexpected_probe)
    with pytest.raises(ObserverFailure, match="cancelled"):
        runner.reply("describe", [], [], stop, video="example.mp4")
    assert list(tmp_path.iterdir()) == []


def test_waiting_for_model_slot_can_be_cancelled():
    stop = threading.Event()
    other = threading.Event()
    entered = threading.Event()
    def occupy():
        with model_slot(other):
            entered.set()
            other.wait(2)
    thread = threading.Thread(target=occupy)
    thread.start()
    assert entered.wait(1)
    stop.set()
    try:
        with pytest.raises(ObserverFailure, match="cancelled"):
            with model_slot(stop):
                pass
    finally:
        other.set()
        thread.join(2)


def test_native_chat_ui_sends_saves_followups_and_cancels(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path)
    requests = []
    class Runner:
        def __init__(self, settings, directory):
            pass
        def reply(self, question, history, context, stop, **kwargs):
            requests.append((question, history, kwargs))
            if question == "wait":
                stop.wait(3)
                raise ObserverFailure("cancelled")
            return {"answer": "Local reply", "elapsed_seconds": 0.1}
        def close(self):
            pass
    monkeypatch.setattr("observer.chat_ui.installation_status", lambda settings: (True, "ready"))
    panel = ChatPanel(store, lambda: Settings(), runner_factory=Runner)
    panel.show()
    def finish():
        deadline = time.monotonic() + 2
        while panel.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        panel.poll()
        app.processEvents()
    try:
        panel.prompt.setPlainText("hello")
        panel.send()
        finish()
        assert "Local reply" in panel.transcript.toPlainText()
        panel.prompt.setPlainText("follow up")
        panel.send()
        finish()
        assert requests[-1][1][-1]["content"] == "Local reply"
        panel.prompt.setPlainText("wait")
        panel.send()
        panel.cancel()
        finish()
        assert "Stopped" in panel.transcript.toPlainText()
        assert panel.send_button.isEnabled()
        panel.clear_chat()
        assert store.chat_history() == []
    finally:
        assert panel.shutdown()
        panel.close()
        panel.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        store.close()
