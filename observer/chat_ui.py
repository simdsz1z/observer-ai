"""Native chat interface; model work stays off the Qt UI thread."""
from html import escape
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPlainTextEdit,
                              QPushButton, QLabel, QCheckBox, QFileDialog, QDoubleSpinBox)

from .chat import LocalQwenChat, screen_context
from .privacy import Privacy
from .vision import ObserverFailure, installation_status


class ChatPanel(QWidget):
    def __init__(self, store, settings_provider, parent=None, *, runner_factory=LocalQwenChat):
        super().__init__(parent)
        self.store, self.settings_provider, self.runner_factory = store, settings_provider, runner_factory
        self.thread = None
        self.runner = None
        self.stop = threading.Event()
        self.results = queue.SimpleQueue()
        self.video_path = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        row = QHBoxLayout()
        title = QLabel("Chat with local Qwen")
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        row.addWidget(title, 1)
        self.save_button = QPushButton("Save chat…")
        self.save_button.clicked.connect(self.save_chat)
        row.addWidget(self.save_button)
        self.clear_button = QPushButton("Clear chat")
        self.clear_button.clicked.connect(self.clear_chat)
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        explanation = QLabel("Ask questions, discuss saved screen observations, or attach a video. Replies stay on this computer. Screen capture can continue; model tasks take turns.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.transcript = QTextBrowser()
        self.transcript.setMinimumHeight(180)
        self.transcript.setOpenExternalLinks(False)
        layout.addWidget(self.transcript, 1)
        options = QHBoxLayout()
        self.include_screen = QCheckBox("Include recent saved screen observations")
        self.include_screen.setChecked(True)
        self.include_screen.setToolTip("Includes up to four completed observations; this does not capture a new screenshot.")
        options.addWidget(self.include_screen, 1)
        self.attach_button = QPushButton("Attach video…")
        self.attach_button.clicked.connect(self.pick_video)
        options.addWidget(self.attach_button)
        self.remove_button = QPushButton("Remove video")
        self.remove_button.clicked.connect(lambda: self.attach_video(None))
        options.addWidget(self.remove_button)
        layout.addLayout(options)
        self.video_label = QLabel("No video attached")
        self.video_label.setWordWrap(True)
        layout.addWidget(self.video_label)
        self.range_row = QWidget()
        ranges = QHBoxLayout(self.range_row)
        ranges.setContentsMargins(0, 0, 0, 0)
        self.video_start, self.video_end = QDoubleSpinBox(), QDoubleSpinBox()
        for name, spin in [("Start", self.video_start), ("End", self.video_end)]:
            spin.setRange(0, 3600000)
            spin.setDecimals(1)
            spin.setSuffix(" sec")
            ranges.addWidget(QLabel(name))
            ranges.addWidget(spin)
        self.video_end.setSpecialValueText("Whole remaining video")
        self.video_fps = QDoubleSpinBox()
        self.video_fps.setRange(0.125, 2)
        self.video_fps.setDecimals(3)
        self.video_fps.setValue(1)
        self.video_fps.setSuffix(" frames/sec")
        ranges.addWidget(QLabel("Sample"))
        ranges.addWidget(self.video_fps)
        layout.addWidget(self.range_row)
        self.video_help = QLabel("The whole selected range is analyzed in sections. Lower sampling misses brief actions. Visual frames only; no audio.")
        self.video_help.setWordWrap(True)
        layout.addWidget(self.video_help)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Message Qwen… e.g. What happened on my screen? Or: Explain what changes in this video.")
        self.prompt.setMaximumHeight(60)
        layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        self.status = QLabel("Ready · local Qwen · no new screen capture from chat")
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.cancel)
        actions.addWidget(self.stop_button)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)
        self.attach_video(None)
        self.set_busy(False)
        self.render_history()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def set_busy(self, value):
        for widget in (self.send_button, self.clear_button, self.attach_button, self.remove_button,
                       self.range_row, self.include_screen, self.prompt):
            widget.setEnabled(not value)
        self.stop_button.setEnabled(value)

    def render_history(self):
        rows = self.store.chat_history()
        if not rows:
            self.transcript.setHtml('<p style="color:#a4b2c6">Start a conversation with Qwen. You can also attach a video and ask what happens in it.</p>')
            return
        blocks = []
        for message in rows:
            name = {"user": "You", "assistant": "Qwen", "notice": "Status"}[message["role"]]
            color = "#a0f0d8" if message["role"] == "assistant" else "#dce8fc"
            attachment = f'<p style="color:#a4b2c6">Video: {escape(message["attachment"])}</p>' if message.get("attachment") else ""
            text = escape(message["content"]).replace("\n", "<br>")
            blocks.append(f'<div style="margin-bottom:18px"><b style="color:{color}">{name}</b>{attachment}<p>{text}</p></div>')
        self.transcript.setHtml("".join(blocks))
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def pick_video(self):
        name, _ = QFileDialog.getOpenFileName(self, "Choose a video for local Qwen", "",
                                              "Videos (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv);;All files (*)")
        if name:
            self.attach_video(Path(name))

    def attach_video(self, path):
        self.video_path = Path(path) if path else None
        attached = self.video_path is not None
        self.video_label.setText(f"Attached: {self.video_path.name}" if attached else "No video attached")
        self.video_label.setToolTip(str(self.video_path) if attached else "")
        self.remove_button.setVisible(attached)
        self.range_row.setVisible(attached)
        self.video_help.setVisible(attached)
        self.video_start.setValue(0)
        self.video_end.setValue(0)

    def send(self):
        if self.busy:
            return
        question = self.prompt.toPlainText().strip()
        if not question and not self.video_path:
            self.status.setText("Write a message or attach a video first.")
            return
        if len(question) > 4000:
            self.status.setText("Please shorten this message to 4,000 characters.")
            return
        settings = self.settings_provider()
        ready, message = installation_status(settings)
        if not ready:
            self.status.setText(message)
            return
        if self.video_path and not self.video_path.is_file():
            self.status.setText("The selected video file is no longer available.")
            return
        if self.video_path and self.video_end.value() and self.video_end.value() <= self.video_start.value():
            self.status.setText("The video end must be after its start, or zero for the remaining video.")
            return
        privacy = Privacy(settings)
        question = privacy.redact(question or "Describe this video and its important changes.")
        history = privacy.redact_value(self.store.chat_history(limit=8))
        context = screen_context(self.store, privacy) if self.include_screen.isChecked() else []
        video = self.video_path
        start, end, fps = self.video_start.value(), self.video_end.value(), self.video_fps.value()
        self.store.save_chat("user", question, privacy.redact(video.name) if video else None)
        self.prompt.clear()
        self.render_history()
        self.stop.clear()
        self.runner = self.runner_factory(settings, self.store.directory / "inference-temp")
        runner = self.runner
        self.status.setText("Waiting for local Qwen…")
        self.set_busy(True)
        def run():
            try:
                result = runner.reply(question, history, context, self.stop, video=video, start=start, end=end, fps=fps,
                                      progress=lambda text: self.results.put(("progress", text)))
                self.results.put(("result", result))
            except ObserverFailure as error:
                self.results.put(("error", (error.code, error.detail if error.code == "invalid_video_range" else "")))
            except Exception:
                self.results.put(("error", ("chat_failed", "")))
            finally:
                runner.close()
        self.thread = threading.Thread(target=run, name="observer-chat", daemon=True)
        self.thread.start()

    def poll(self):
        while True:
            try:
                kind, value = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.status.setText(value)
                continue
            privacy = Privacy(self.settings_provider())
            if kind == "result" and not self.stop.is_set():
                extra = ""
                answer = value["answer"]
                if value.get("video"):
                    meta = value["video"]
                    extra = f" · {meta['sections_analyzed']} video sections · {meta['start_seconds']:.1f}–{meta['end_seconds']:.1f} sec at {meta['sample_fps']:g} frames/sec"
                    answer += f"\n\nVideo reviewed: {meta['start_seconds']:.1f}–{meta['end_seconds']:.1f} sec · {meta['sample_fps']:g} sampled frames/sec · visual frames only."
                    self.attach_video(None)
                self.store.save_chat("assistant", privacy.redact(answer))
                self.status.setText(f"Answered locally in {value['elapsed_seconds']:.1f} sec{extra}")
            else:
                code, detail = value if kind == "error" else ("cancelled", "")
                text = "Stopped. You can send another message." if code == "cancelled" else "Qwen could not finish: " + code.replace("_", " ") + (f". {detail}" if detail else "")
                self.store.save_chat("notice", text)
                self.status.setText(text)
            self.render_history()
            self.set_busy(False)

    def cancel(self):
        self.stop.set()
        if self.runner:
            self.runner.close()
        self.status.setText("Stopping local Qwen…")

    def clear_chat(self):
        if self.busy:
            return
        self.store.clear_chat()
        self.render_history()
        self.status.setText("Chat cleared. Ready for a new conversation.")

    def save_chat(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Qwen conversation", "qwen-chat.txt", "Text (*.txt)")
        if path:
            rows = self.store.chat_history(limit=10000)
            text = "\n\n".join(f"{m['role'].upper()} · {m['timestamp']}\n" +
                                (f"Video: {m['attachment']}\n" if m.get("attachment") else "") + m['content'] for m in rows)
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.status.setText("Conversation saved. This file is a separate local copy.")
            except OSError:
                self.status.setText("Could not save to that location. Choose another folder.")

    def shutdown(self):
        self.cancel()
        if self.thread:
            self.thread.join(timeout=3)
        if self.busy:
            return False
        self.timer.stop()
        return True
