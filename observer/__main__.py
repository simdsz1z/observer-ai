import argparse
import multiprocessing
import sys


def main():
    parser = argparse.ArgumentParser(description="Observer AI — local recording, manual website handoff")
    parser.add_argument("--data-dir", type=str, help="Override the local per-user storage folder")
    parser.add_argument("--chat", action="store_true", help="Open directly to Chat with Qwen")
    args = parser.parse_args()
    from pathlib import Path
    from PySide6.QtCore import QEvent, QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .config import default_data_dir
    from .ui import MainWindow
    from .windows import enable_dpi_awareness
    enable_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Observer AI")
    app.setOrganizationName("ObserverAI")
    directory = Path(args.data_dir) if args.data_dir else default_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "observer.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "Observer AI", "Observer is already open for this data folder.")
        return 1
    window = MainWindow(directory)
    if args.chat:
        window.tabs.setCurrentWidget(window.chat_panel)
    window.show()
    result = app.exec()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return result


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
