import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent

from observer.models import Observation
from observer.ui import MainWindow


def test_offscreen_manual_handoff_flow(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "ui-data")
    window.show()
    app.processEvents()
    assert not window.recorder.running
    assert not window.consent.isChecked()
    assert not window.settings.screenshots
    window.use_one_second_clips()
    proposed = window.proposed_settings()
    assert proposed.interval_seconds == .5
    assert proposed.observer_video_frames == 2
    assert proposed.observer_interval_seconds == 1
    assert "approximately 1 seconds" in window.clip_description.text()
    session = window.store.start_session("Debug the example")
    window.store.add(Observation(session, "editor.exe", "Example", "window_change", ["Build failed"]))
    window.store.end_session(session)
    window.refresh_sessions()
    window.refresh()
    window.prepare_context()
    assert "Build failed" in window.prompt_preview.toPlainText()
    assert window.copy_button.isEnabled()
    assert window.table.rowCount() == 1
    window.question.setText("What error was visible?")
    assert window.package is None
    assert not window.copy_button.isEnabled()
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
