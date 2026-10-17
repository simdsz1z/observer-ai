"""Render our own widgets with synthetic evidence, without capturing the desktop."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent
from observer.models import Observation
from observer.ui import MainWindow


def main():
    output = Path(__file__).resolve().parents[1] / "qa"
    output.mkdir(exist_ok=True)
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="observer-preview-") as folder:
        window = MainWindow(Path(folder))
        window.show()
        app.processEvents()
        window.grab().save(str(output / "overview.png"))
        session = window.store.start_session("Investigate an authentication error")
        for application, title, event_type, texts in [
            ("Code.exe", "auth.ts — example project", "window_change", ["TypeScript", "Type 'string' is not assignable to type 'number'"]),
            ("Code.exe", "auth.ts — example project", "error_text_visible", ["Build failed", "Check the declared return type"]),
            ("browser.exe", "TypeScript reference", "window_change", ["Type compatibility", "Documentation"]),
        ]:
            window.store.add(Observation(session, application, title, event_type, texts))
        window.store.end_session(session)
        window.refresh_sessions()
        window.refresh()
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(output / "timeline.png"))
        window.tabs.setCurrentIndex(2)
        window.prepare_context()
        app.processEvents()
        window.grab().save(str(output / "handoff.png"))
        window.tabs.setCurrentIndex(3)
        app.processEvents()
        window.grab().save(str(output / "settings.png"))
        window.tabs.setCurrentIndex(4)
        result_file = output / "local-video" / "result.json"
        if result_file.exists():
            window.model_result.setPlainText(result_file.read_text(encoding="utf-8"))
        app.processEvents()
        window.grab().save(str(output / "local-qwen.png"))
        window.tabs.setCurrentIndex(5)
        window.store.save_chat("user", "What changes in this video?", "example-transition.mp4")
        window.store.save_chat("assistant", "The screen initially shows a red TypeError panel. Later it shows a green BUILD SUCCEEDED panel with 0 errors. The visible state changed, but the video does not prove which action caused it.")
        window.chat_panel.render_history()
        window.chat_panel.attach_video(output / "chat-test" / "example-transition.mp4")
        app.processEvents()
        window.grab().save(str(output / "chat.png"))
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    print(output)


if __name__ == "__main__":
    main()
