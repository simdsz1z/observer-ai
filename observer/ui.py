import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .config import Settings
from .engine import Recorder
from .exporting import build_package
from .models import Observation
from .privacy import Privacy
from .store import Store
from .sample import sample_screen, sample_video
from .chat_ui import ChatPanel
from .vision import LocalQwenObserver, ObserverFailure, SYSTEM_PROMPT, installation_status, runtime_paths


STYLE = """
QMainWindow, QDialog { background: #0d1420; color: #e9eef6; }
QWidget { color: #e9eef6; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#eyebrow { color: #70d9c4; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#muted { color: #a4b2c6; }
QLabel#status { background: #17263a; border-radius: 8px; padding: 12px; font-weight: 600; }
QFrame#card { background: #131e2e; border: 1px solid #263347; border-radius: 10px; }
QLabel#metric { font-size: 23px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #263347; border-radius: 8px; background: #101a29; }
QTabBar::tab { background: #0d1420; color: #9eafc5; padding: 13px 22px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #7de2cd; border-bottom: 2px solid #7de2cd; }
QPushButton { background: #21324b; border: 1px solid #324761; border-radius: 6px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #2b4160; }
QPushButton#primary { background: #78ddc6; color: #092a27; border: none; }
QPushButton#danger { background: #492731; border-color: #79404d; }
QPushButton:disabled { background: #1a2432; color: #68798f; border-color: #263347; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #0e1725; border: 1px solid #304057; border-radius: 5px; padding: 7px; selection-background-color: #356d74; }
QPlainTextEdit { font-family: 'Cascadia Code', 'Consolas'; font-size: 12px; }
QTableWidget { background: #101a29; border: 0; gridline-color: #243146; alternate-background-color: #142033; }
QHeaderView::section { background: #1a293d; color: #a9b9cd; border: none; padding: 9px; }
QTableWidget::item { padding: 7px; }
QTableWidget::item:selected { background: #234b55; }
QScrollArea { border: none; background: transparent; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #758aa4; border-radius: 3px; background: #0e1725; }
QCheckBox::indicator:checked { background: #78ddc6; border-color: #78ddc6; }
QToolTip { background: #21324b; color: white; border: 1px solid #425574; }
"""


def label(text, kind="muted"):
    obj = QLabel(text)
    obj.setObjectName(kind)
    obj.setWordWrap(True)
    obj.setTextFormat(Qt.TextFormat.PlainText)
    return obj


def button(text, callback, kind=None):
    obj = QPushButton(text)
    if kind:
        obj.setObjectName(kind)
    obj.clicked.connect(callback)
    return obj


def local_time(value):
    return datetime.fromisoformat(value).astimezone().strftime("%m/%d %H:%M:%S")


def configure_application():
    app = QApplication.instance()
    app.setStyle("Fusion")
    # Qt's offscreen Windows plugin does not discover system fonts automatically.
    if not QFontDatabase.families():
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#101a29"), (QPalette.ColorRole.Base, "#0e1725"),
                        (QPalette.ColorRole.AlternateBase, "#142033"), (QPalette.ColorRole.WindowText, "#e9eef6"),
                        (QPalette.ColorRole.Text, "#e9eef6"), (QPalette.ColorRole.Button, "#21324b"),
                        (QPalette.ColorRole.ButtonText, "#e9eef6"), (QPalette.ColorRole.Highlight, "#234b55"),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, "#8a9bb2")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


class MainWindow(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        configure_application()
        self.directory = directory
        self.settings_error = None
        try:
            self.settings = Settings.load(directory)
        except (ValueError, TypeError, OSError) as error:
            self.settings = Settings()
            self.settings_error = "Settings could not be read. Recording is disabled until you review and save Privacy & settings."
        self.store = Store(directory)
        self.store.maintain(self.settings.retention_days, self.settings.screenshot_budget_mb)
        self.recorder = Recorder(self.store, self.settings)
        self.package = None
        self.events = []
        self.last_count = -1
        self.last_revision = -1
        self.last_displayed_model_id = None
        self.observer_test_thread = None
        self.observer_test_stop = threading.Event()
        self.observer_test_runner = None
        self.observer_test_results = queue.Queue(maxsize=1)
        self.process = psutil.Process()
        self.process.cpu_percent()
        self.resource_read_at = time.monotonic()
        self.cpu_usage = None
        self.setWindowTitle("Observer AI · Local evidence recorder")
        self.resize(1180, 820)
        self.setMinimumSize(960, 700)
        self.setStyleSheet(STYLE)
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(16)
        header = QHBoxLayout()
        names = QVBoxLayout()
        names.addWidget(label("OBSERVER / LOCAL FIRST", "eyebrow"))
        names.addWidget(label("Your work, in context.", "title"))
        names.addWidget(label("Qwen observes locally. Your chosen AI website provides the bigger picture."))
        header.addLayout(names, 1)
        badge = label("LOCAL QWEN + WEBSITE AI\nNo cloud API connection", "status")
        header.addWidget(badge)
        outer.addLayout(header)
        self.status = label(self.recorder.state, "status")
        outer.addWidget(self.status)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.build_dashboard()
        self.build_timeline()
        self.build_handoff()
        self.build_settings()
        self.build_local_observer()
        self.chat_panel = ChatPanel(self.store, lambda: self.settings, self)
        self.tabs.addTab(self.chat_panel, "Chat with Qwen")
        outer.addWidget(label("Evidence stays on this computer until you copy or export it. Monitoring starts paused."))
        self.setCentralWidget(container)
        self.recording_badge = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.recording_badge.setWindowTitle("Observer AI recording indicator")
        self.recording_badge.setStyleSheet("QWidget { background: #183c38; color: #d4fff4; font: 12px 'Segoe UI'; } QPushButton { background: #2b5b52; color: white; padding: 6px 12px; border: 1px solid #7bdcc4; border-radius: 4px; }")
        badge_layout = QHBoxLayout(self.recording_badge)
        badge_layout.addWidget(label("●  Observer is recording", "heading"))
        badge_layout.addWidget(button("Pause", self.toggle_recording))
        screen = QApplication.primaryScreen().availableGeometry()
        self.recording_badge.adjustSize()
        self.recording_badge.move(screen.right() - self.recording_badge.width() - 20, screen.top() + 20)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(750)
        self.refresh_sessions()
        self.refresh()
        if self.settings_error:
            self.status.setText(self.settings_error)

    def page(self, name):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self.tabs.addTab(page, name)
        return layout

    def build_dashboard(self):
        page_layout = self.page("Overview")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(12)
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        cards = QHBoxLayout()
        self.app_metric, self.events_metric, self.resource_metric = label("—", "metric"), label("0", "metric"), label("—", "metric")
        for title, value in [("ACTIVE APPLICATION", self.app_metric), ("RECORDED EVENTS", self.events_metric), ("UI MEMORY / CPU", self.resource_metric)]:
            card = QFrame()
            card.setObjectName("card")
            card.setMinimumHeight(100)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(18, 16, 18, 16)
            inner.addWidget(label(title, "eyebrow"))
            inner.addWidget(value)
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        layout.addWidget(label("What are you working toward?", "heading"))
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Optional — e.g. Find why my app fails to sign in")
        self.goal.setMaxLength(1000)
        layout.addWidget(self.goal)
        self.consent = QCheckBox("I allow local capture of permitted windows, accessibility labels, and selected images for Qwen analysis.")
        self.consent.setChecked(False)
        layout.addWidget(self.consent)
        layout.addWidget(label("Selected images are analyzed locally when Qwen is enabled. Keeping screenshot files is a separate option, off by default. Privacy exclusions and password detection apply before capture."))
        controls = QHBoxLayout()
        self.start_button = button("Start recording", self.toggle_recording, "primary")
        controls.addWidget(self.start_button)
        self.bookmark_button = button("Mark this moment", self.bookmark)
        controls.addWidget(self.bookmark_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.observer_dashboard = label("Local Qwen: waiting for a session", "status")
        layout.addWidget(self.observer_dashboard)
        self.activity_summary = label("No local visual interpretation yet.")
        layout.addWidget(self.activity_summary)
        self.metrics_text = label("Qwen watches permitted screen clips locally; your website AI receives the package you choose to share.")
        layout.addWidget(self.metrics_text)
        layout.addWidget(label("A simple handoff", "heading"))
        layout.addWidget(label("1    Start a session and work normally.\n2    Pause, then open AI handoff to review raw evidence and Qwen interpretations.\n3    Copy the prompt or export the files and share them yourself.\n4    Optionally paste the AI’s response back into the session."))
        layout.addStretch()

    def build_timeline(self):
        layout = self.page("Activity timeline")
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search recorded labels, titles, applications, or notes…")
        self.search.returnPressed.connect(self.refresh_timeline)
        controls.addWidget(self.search, 1)
        controls.addWidget(button("Search", self.refresh_timeline))
        controls.addWidget(button("Refresh", self.refresh_timeline))
        layout.addLayout(controls)
        layout.addWidget(label("Latest 500 matching events across sessions. Select a row to inspect its raw evidence."))
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Application", "Event", "Qwen activity / state", "Window"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 190)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_event)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("The selected observation will appear here.")
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setSizes([350, 200])
        layout.addWidget(splitter, 1)

    def build_handoff(self):
        layout = self.page("AI handoff")
        row = QHBoxLayout()
        self.sessions_box = QComboBox()
        self.sessions_box.setMinimumWidth(260)
        row.addWidget(self.sessions_box, 1)
        row.addWidget(label("Last"))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 1440)
        self.minutes.setValue(30)
        self.minutes.setSuffix(" min")
        row.addWidget(self.minutes)
        self.event_limit = QSpinBox()
        self.event_limit.setRange(1, 200)
        self.event_limit.setValue(50)
        self.event_limit.setSuffix(" events max")
        row.addWidget(self.event_limit)
        layout.addLayout(row)
        self.question = QLineEdit("What was I working on, and what should I do next?")
        self.question.setMaxLength(4000)
        layout.addWidget(self.question)
        controls = QHBoxLayout()
        self.include_images = QCheckBox("Include saved screenshots (up to 12; inspect every image)")
        controls.addWidget(self.include_images, 1)
        controls.addWidget(button("Build / refresh context", self.prepare_context, "primary"))
        layout.addLayout(controls)
        self.package_info = label("Choose a session and build a context package. Nothing is sent automatically.")
        layout.addWidget(self.package_info)
        self.preview_tabs = QTabWidget()
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setPlaceholderText("A prepared prompt with your selected evidence will appear here.")
        self.raw_preview = QPlainTextEdit()
        self.raw_preview.setReadOnly(True)
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        self.image_selector = QComboBox()
        self.image_selector.currentIndexChanged.connect(self.show_package_image)
        image_controls = QHBoxLayout()
        image_controls.addWidget(self.image_selector, 1)
        image_controls.addWidget(button("Inspect full image…", self.inspect_image))
        image_layout.addLayout(image_controls)
        self.image_preview = QLabel("No images selected")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumHeight(100)
        self.image_preview.setTextFormat(Qt.TextFormat.PlainText)
        image_layout.addWidget(self.image_preview, 1)
        self.preview_tabs.addTab(self.prompt_preview, "Prompt (editable)")
        self.preview_tabs.addTab(self.raw_preview, "Raw JSON")
        self.preview_tabs.addTab(image_page, "Images")
        layout.addWidget(self.preview_tabs, 1)
        layout.addWidget(label("Prompt edits affect the copied prompt and .md file only. Raw JSON, JSONL, and images retain the evidence shown in their tabs. Change session, time, or image selection and rebuild to change those files."))
        actions = QHBoxLayout()
        self.copy_button = button("Copy prompt", self.copy_prompt)
        self.export_button = button("Export reviewed package…", self.export_context)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.export_button)
        actions.addWidget(button("Paste / save AI response…", self.save_ai_response))
        layout.addLayout(actions)
        # Selection changes invalidate the package to avoid sharing a stale selection.
        self.sessions_box.currentIndexChanged.connect(self.invalidate_package)
        self.minutes.valueChanged.connect(self.invalidate_package)
        self.event_limit.valueChanged.connect(self.invalidate_package)
        self.include_images.toggled.connect(self.invalidate_package)
        self.question.textChanged.connect(self.invalidate_package)

    def build_settings(self):
        layout = self.page("Privacy & settings")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setVerticalSpacing(14)
        self.interval_setting = QDoubleSpinBox()
        self.interval_setting.setRange(0.5, 30)
        self.interval_setting.setSingleStep(0.5)
        self.interval_setting.setValue(self.settings.interval_seconds)
        self.interval_setting.setSuffix(" sec")
        form.addRow("Sample interval", self.interval_setting)
        self.retention_setting = QSpinBox()
        self.retention_setting.setRange(1, 365)
        self.retention_setting.setValue(self.settings.retention_days)
        self.retention_setting.setSuffix(" days")
        form.addRow("Keep local memory", self.retention_setting)
        self.budget_setting = QSpinBox()
        self.budget_setting.setRange(16, 4096)
        self.budget_setting.setValue(self.settings.screenshot_budget_mb)
        self.budget_setting.setSuffix(" MB")
        form.addRow("Screenshot disk budget", self.budget_setting)
        self.access_setting = QCheckBox("Read visible accessibility labels; never request input values")
        self.access_setting.setChecked(self.settings.accessibility)
        form.addRow("Accessibility", self.access_setting)
        self.screenshot_setting = QCheckBox("Save active-window images locally (may contain sensitive pixels)")
        self.screenshot_setting.setChecked(self.settings.screenshots)
        form.addRow("Screenshots", self.screenshot_setting)
        form.addRow("", label("Local Qwen can inspect selected frames without keeping screenshot archives. It uses temporary image files that are deleted after inference. Visual capture requires accessibility to respond. Recognized excluded windows are masked. Text redaction cannot remove secrets inside pixels; review images before sharing."))
        self.apps_setting = QPlainTextEdit("\n".join(self.settings.excluded_apps))
        self.titles_setting = QPlainTextEdit("\n".join(self.settings.excluded_titles))
        self.redactions_setting = QPlainTextEdit("\n".join(self.settings.redactions))
        for editor in (self.apps_setting, self.titles_setting, self.redactions_setting):
            editor.setMaximumHeight(90)
        form.addRow("Excluded app names\n(one substring per line)", self.apps_setting)
        form.addRow("Excluded window titles\n(one substring per line)", self.titles_setting)
        form.addRow("Redact these text fragments\n(one per line)", self.redactions_setting)
        form.addRow("", label("Email addresses, common access-token patterns, secret assignments, and long numbers are masked in text. These checks are best effort. Rules apply to new records and rebuilt exports; existing records are not rewritten."))
        form.addRow("Local storage", label(str(self.directory.resolve())))
        form.addRow("", label("The local database and images are not encrypted. Use a trusted Windows account and disk encryption. Deleting local memory does not delete exported packages, clipboard contents, backups, or website conversations."))
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Save settings", self.apply_settings, "primary"))
        actions.addWidget(button("Open data folder", lambda: os.startfile(self.directory)))
        actions.addStretch()
        actions.addWidget(button("Delete local memory…", self.delete_memory, "danger"))
        layout.addLayout(actions)

    def build_local_observer(self):
        layout = self.page("Local Qwen")
        self.local_model_status = label("Checking local model files…", "status")
        layout.addWidget(self.local_model_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setVerticalSpacing(12)
        self.observer_enabled_setting = QCheckBox("Use Qwen3-VL to watch permitted screen activity locally")
        self.observer_enabled_setting.setChecked(self.settings.observer_enabled)
        form.addRow("Visual observer", self.observer_enabled_setting)
        self.observer_video_setting = QCheckBox("Watch a continuous sequence of screen frames as video")
        self.observer_video_setting.setChecked(self.settings.observer_video)
        form.addRow("Live screen video", self.observer_video_setting)
        self.observer_video_frames_setting = QSpinBox()
        self.observer_video_frames_setting.setRange(2, 16)
        self.observer_video_frames_setting.setValue(self.settings.observer_video_frames)
        self.observer_video_frames_setting.setSuffix(" frames per clip")
        form.addRow("Video clip size", self.observer_video_frames_setting)
        form.addRow("Quick setup", button("Use 1-second video clips", self.use_one_second_clips))
        self.clip_description = label("")
        form.addRow("", self.clip_description)
        self.interval_setting.valueChanged.connect(self.update_clip_description)
        self.observer_video_frames_setting.valueChanged.connect(self.update_clip_description)
        self.update_clip_description()
        self.observer_interval_setting = QSpinBox()
        self.observer_interval_setting.setRange(1, 300)
        self.observer_interval_setting.setValue(int(self.settings.observer_interval_seconds))
        self.observer_interval_setting.setSuffix(" sec minimum")
        form.addRow("Time between analyses", self.observer_interval_setting)
        self.observer_gpu_setting = QSpinBox()
        self.observer_gpu_setting.setRange(0, 99)
        self.observer_gpu_setting.setValue(self.settings.observer_gpu_layers)
        form.addRow("GPU layers (0 = CPU)", self.observer_gpu_setting)
        self.observer_vision_gpu_setting = QCheckBox("Accelerate the vision encoder when at least 3 GB of GPU memory is free")
        self.observer_vision_gpu_setting.setChecked(self.settings.observer_vision_gpu)
        form.addRow("Vision acceleration", self.observer_vision_gpu_setting)
        self.observer_resident_setting = QCheckBox("Keep Qwen loaded between observations; release it on pause or when chat needs the model")
        self.observer_resident_setting.setChecked(self.settings.observer_keep_loaded)
        form.addRow("Faster monitoring", self.observer_resident_setting)
        self.observer_threads_setting = QSpinBox()
        self.observer_threads_setting.setRange(1, 32)
        self.observer_threads_setting.setValue(self.settings.observer_threads)
        form.addRow("CPU threads", self.observer_threads_setting)
        paths = runtime_paths(self.settings)
        self.observer_executable_setting = QLineEdit(self.settings.observer_executable)
        self.observer_model_setting = QLineEdit(self.settings.observer_model_path)
        self.observer_projector_setting = QLineEdit(self.settings.observer_projector_path)
        for editor, path in zip((self.observer_executable_setting, self.observer_model_setting, self.observer_projector_setting), paths):
            editor.setPlaceholderText(str(path))
        form.addRow("Runtime executable", self.observer_executable_setting)
        form.addRow("Qwen model file", self.observer_model_setting)
        form.addRow("Vision encoder file", self.observer_projector_setting)
        form.addRow("", label("Blank paths use installed defaults. Local files and pipes carry video to Qwen; no AI API is called. At most two clips wait. Temporary videos are deleted after inference. GPU failures retry on CPU. The resident helper keeps weights loaded while monitoring; pause releases them. Without the helper, the CLI fallback reloads for each clip."))
        self.observer_prompt_setting = QPlainTextEdit(self.settings.observer_prompt or SYSTEM_PROMPT)
        self.observer_prompt_setting.setMaximumHeight(100)
        form.addRow("Observer system prompt", self.observer_prompt_setting)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Save observer settings", self.apply_settings, "primary"))
        actions.addWidget(button("Check installation", self.check_observer_installation))
        self.test_observer_button = button("Test screen video", self.test_local_observer)
        actions.addWidget(self.test_observer_button)
        layout.addLayout(actions)
        layout.addWidget(label("The test shows a generated error-to-success video without reading your desktop. Model statements can be wrong; scores are uncalibrated. Nothing is executed or uploaded."))
        self.model_result = QPlainTextEdit()
        self.model_result.setReadOnly(True)
        self.model_result.setMaximumHeight(170)
        self.model_result.setPlaceholderText("The latest local interpretation or test result will appear here.")
        layout.addWidget(self.model_result)
        self.check_observer_installation()

    def update_clip_description(self, *_):
        interval = self.interval_setting.value()
        frames = self.observer_video_frames_setting.value()
        self.clip_description.setText(f"Current target: {1 / interval:g} captured frames/sec, {frames} frames per clip, approximately {frames * interval:g} seconds per video. "
                                      "Qwen receives ordered video frames and timestamps. Capture continues during analysis and passive viewing. "
                                      "Older waiting clips can be skipped when processing falls behind. Only permitted active-window content is captured.")

    def use_one_second_clips(self):
        self.interval_setting.setValue(0.5)
        self.observer_video_setting.setChecked(True)
        self.observer_video_frames_setting.setValue(2)
        self.observer_interval_setting.setValue(1)
        self.local_model_status.setText("1-second target: two frames at 2 frames/sec, one analysis allowed per second. Save settings while paused. Actual speed depends on measured inference time.")

    def proposed_settings(self):
        values = self.settings.__dict__.copy()
        values.update(interval_seconds=self.interval_setting.value(), retention_days=self.retention_setting.value(),
                      screenshot_budget_mb=self.budget_setting.value(), accessibility=self.access_setting.isChecked(),
                      screenshots=self.screenshot_setting.isChecked(),
                      excluded_apps=self.apps_setting.toPlainText().splitlines(), excluded_titles=self.titles_setting.toPlainText().splitlines(),
                      redactions=self.redactions_setting.toPlainText().splitlines(),
                      observer_enabled=self.observer_enabled_setting.isChecked(), observer_interval_seconds=self.observer_interval_setting.value(),
                      observer_video=self.observer_video_setting.isChecked(), observer_video_frames=self.observer_video_frames_setting.value(),
                      observer_gpu_layers=self.observer_gpu_setting.value(), observer_threads=self.observer_threads_setting.value(),
                      observer_vision_gpu=self.observer_vision_gpu_setting.isChecked(),
                      observer_keep_loaded=self.observer_resident_setting.isChecked(),
                      observer_executable=self.observer_executable_setting.text().strip(), observer_model_path=self.observer_model_setting.text().strip(),
                      observer_projector_path=self.observer_projector_setting.text().strip(), observer_prompt=self.observer_prompt_setting.toPlainText())
        proposed = Settings(**values)
        proposed.validate()
        return proposed

    def check_observer_installation(self):
        try:
            proposed = self.proposed_settings()
            ready, message = installation_status(proposed)
            self.observer_ready = ready
            self.local_model_status.setText(message + (" · ready for local analysis" if ready else ""))
        except (ValueError, OSError) as error:
            self.local_model_status.setText(str(error))

    def test_local_observer(self):
        if self.recorder.running or (self.observer_test_thread and self.observer_test_thread.is_alive()):
            self.info("Pause recording and wait for the current local test before starting another test.")
            return
        try:
            settings = self.proposed_settings()
            ready, message = installation_status(settings)
            if not ready:
                self.info(message)
                return
        except (ValueError, OSError) as error:
            self.info(str(error))
            return
        self.observer_test_stop.clear()
        self.local_model_status.setText("Testing real Qwen inference on a synthetic screen sequence…")
        self.test_observer_button.setEnabled(False)
        self.observer_test_runner = LocalQwenObserver(settings, self.directory / "inference-temp")
        runner = self.observer_test_runner
        def run_test():
            try:
                result = runner.analyze(sample_video() if settings.observer_video else sample_screen(), {"application": "Example Editor", "window_title": "authentication.ts", "test_only": True}, [], self.observer_test_stop)
                self.observer_test_results.put({"test_only": True, **result})
            except ObserverFailure as error:
                self.observer_test_results.put({"test_only": True, "error": error.code, "runtime_detail": error.detail})
            except Exception as error:
                self.observer_test_results.put({"test_only": True, "error": type(error).__name__})
            finally:
                runner.close()
        self.observer_test_thread = threading.Thread(target=run_test, name="observer-sample-test", daemon=True)
        self.observer_test_thread.start()

    def info(self, message):
        QMessageBox.information(self, "Observer AI", message)

    def toggle_recording(self):
        if self.observer_test_thread and self.observer_test_thread.is_alive():
            self.info("Wait for the local sample test to finish before recording.")
            return
        if self.recorder.running:
            self.recorder.stop()
            self.refresh_sessions()
        else:
            if self.settings_error:
                self.info(self.settings_error)
                return
            if not self.consent.isChecked():
                self.info("Enable the consent checkbox before starting a recording session.")
                return
            self.recorder.start(self.goal.text().strip())
            self.refresh_sessions()
        self.refresh()

    def bookmark(self):
        if not self.recorder.running:
            return
        self.store.add(Observation(session_id=self.recorder.session_id, application="user", window_title="",
                                   event_type="user_bookmark", note="User marked this moment for review."))
        self.refresh_timeline()

    def refresh(self):
        while not self.recorder.updates.empty():
            try:
                self.recorder.updates.get_nowait()
            except Exception:
                break
        running = self.recorder.running
        self.status.setText(self.settings_error or self.recorder.state)
        self.status.setStyleSheet("color: #78ddc6;" if running else "color: #c6d4e5;")
        self.start_button.setText("Pause recording" if running else "Start recording")
        self.bookmark_button.setEnabled(running and not self.recorder.stop_event.is_set())
        self.goal.setEnabled(not running)
        self.consent.setEnabled(not running)
        self.recording_badge.setVisible(running)
        self.app_metric.setText(self.recorder.current_application)
        count = self.store.count()
        self.events_metric.setText(str(count))
        if time.monotonic() - self.resource_read_at >= 1:
            self.cpu_usage = self.process.cpu_percent() / max(1, psutil.cpu_count() or 1)
            self.resource_read_at = time.monotonic()
        cpu = f"{self.cpu_usage:.1f}%" if self.cpu_usage is not None else "—"
        self.resource_metric.setText(f"{self.process.memory_info().rss / 1024**2:.0f} MB / {cpu}")
        self.metrics_text.setText(f"{self.recorder.metrics['samples']} samples · {self.recorder.metrics['duplicates']} unchanged samples skipped · "
                                  f"{self.recorder.metrics['last_sample_ms']:.0f} ms last capture sample")
        if self.settings.observer_video:
            self.metrics_text.setText(f"Screen stream: {self.recorder.stream_frames} frames captured · "
                                      f"{self.recorder.stream_buffered}/{self.settings.observer_video_frames} frames in next clip · "
                                      f"{self.recorder.stream_clips} video clips submitted")
        vision = self.recorder.vision
        if vision:
            self.observer_dashboard.setText(f"Local Qwen: {vision.status} · {vision.completed} interpreted · {vision.dropped} skipped while busy · {len(vision.pending)} waiting")
            if vision.last_result:
                result = vision.last_result
                runtime = (result.get("observer_input") or {}).get("runtime") or {}
                if runtime.get("device"):
                    self.observer_dashboard.setText(self.observer_dashboard.text() + f" · {runtime['device']} · resident model")
                ended_at = (result.get("observer_input") or {}).get("ended_at", result["observed_at"])
                try:
                    delay = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(ended_at)).total_seconds())
                    self.observer_dashboard.setText(self.observer_dashboard.text() + f" · latest analyzed frame {delay:.0f}s ago")
                except (TypeError, ValueError):
                    pass
                observation = result["interpretation"]
                self.activity_summary.setText(f"Last Qwen observation · {local_time(result['observed_at'])} · {observation['activity'] or 'unknown activity'}: {observation['description'] or 'No description'}")
                if self.last_displayed_model_id != result["observation_id"]:
                    self.model_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                    self.last_displayed_model_id = result["observation_id"]
        else:
            self.observer_dashboard.setText(("Local Qwen ready · start a session to analyze permitted frames" if getattr(self, "observer_ready", False) else "Local Qwen not installed · open the Local Qwen tab") if self.settings.observer_enabled else "Local Qwen disabled · raw evidence only")
        try:
            result = self.observer_test_results.get_nowait()
        except queue.Empty:
            result = None
        if result:
            self.model_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.local_model_status.setText("Sample test completed locally" if "interpretation" in result else f"Sample test failed: {result.get('error', 'unknown')}")
            self.test_observer_button.setEnabled(True)
        self.copy_button.setEnabled(self.package is not None)
        self.export_button.setEnabled(self.package is not None)
        if count != self.last_count or self.last_revision != self.store.revision:
            self.last_count = count
            self.last_revision = self.store.revision
            self.refresh_timeline()

    def refresh_timeline(self):
        self.events = self.store.query(search=self.search.text().strip(), limit=500)
        self.table.setRowCount(len(self.events))
        for row, event in enumerate(reversed(self.events)):
            interpretation = event.get("interpretation") or {}
            activity = interpretation.get("activity") or event.get("observer_status", "not analyzed")
            for col, text in enumerate([local_time(event["timestamp"]), event["application"], event["event_type"].replace("_", " "), activity, event["window_title"]]):
                item = QTableWidgetItem(text)
                if col == 2 and event["event_type"] == "error_text_visible":
                    item.setForeground(QColor("#efbc75"))
                self.table.setItem(row, col, item)

    def select_event(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.events):
            self.details.setPlainText(json.dumps(list(reversed(self.events))[row], ensure_ascii=False, indent=2))

    def refresh_sessions(self):
        current = self.sessions_box.currentData()
        self.sessions_box.blockSignals(True)
        self.sessions_box.clear()
        for session in self.store.sessions():
            self.sessions_box.addItem(f"{local_time(session['started_at'])} · {session['goal'][:45] or 'Untitled session'}", session["id"])
        index = self.sessions_box.findData(current)
        self.sessions_box.setCurrentIndex(max(0, index))
        self.sessions_box.blockSignals(False)
        self.invalidate_package()

    def invalidate_package(self, *_):
        self.package = None
        self.prompt_preview.clear()
        self.raw_preview.clear()
        self.image_selector.clear()
        self.image_preview.clear()
        self.package_info.setText("Selection changed. Build a new context package to review it.")
        self.copy_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def prepare_context(self):
        session_id = self.sessions_box.currentData()
        if not session_id:
            self.info("Record a session first. Start from Overview.")
            return
        # For completed sessions the interval ends at session end, not the current clock.
        session = next(s for s in self.store.sessions() if s["id"] == session_id)
        end = datetime.fromisoformat(session["ended_at"]) if session["ended_at"] else datetime.now(timezone.utc)
        since = (end - timedelta(minutes=self.minutes.value())).isoformat(timespec="milliseconds")
        try:
            self.package = build_package(self.store, Privacy(self.settings), session_id, question=self.question.text(), since=since,
                                         limit=self.event_limit.value(), include_images=self.include_images.isChecked())
        except (OSError, ValueError) as error:
            self.info(str(error))
            return
        self.prompt_preview.setPlainText(self.package.prompt)
        self.raw_preview.setPlainText(self.package.json_text)
        self.image_selector.clear()
        self.image_selector.addItems(list(self.package.images))
        self.show_package_image()
        total = len(self.package.prompt)
        selected = self.package.payload["selection"]
        self.package_info.setText(f"{selected['events_included']} events · {len(self.package.images)} images · {total:,} characters · "
                                  f"{selected['events_omitted_for_size']} omitted for size · {selected['events_omitted_by_privacy']} excluded. Review all tabs before sharing.")
        self.copy_button.setEnabled(True)
        self.export_button.setEnabled(True)

    def show_package_image(self, *_):
        if not self.package or not self.image_selector.currentText():
            self.image_preview.clear()
            self.image_preview.setText("No images included")
            return
        data = self.package.images.get(self.image_selector.currentText())
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.image_preview.setPixmap(pixmap.scaled(850, 255, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def copy_prompt(self):
        if self.package:
            QApplication.clipboard().setText(self.prompt_preview.toPlainText())
            self.package_info.setText("Prompt copied. Paste it into your chosen AI website; attach reviewed images separately if needed.")

    def inspect_image(self):
        if not self.package or not self.image_selector.currentText():
            return
        image = QPixmap()
        if not image.loadFromData(self.package.images[self.image_selector.currentText()]):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Inspect image pixels before sharing")
        dialog.resize(1000, 750)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        pixels = QLabel()
        pixels.setPixmap(image)
        scroll.setWidget(pixels)
        layout.addWidget(scroll)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def export_context(self):
        if not self.package:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export reviewed evidence", str(Path.home() / "Desktop" / "observer-context.zip"), "ZIP package (*.zip)")
        if path:
            try:
                self.package.write_zip(Path(path), self.prompt_preview.toPlainText())
                self.package_info.setText(f"Exported to {path}. Review and share the extracted files yourself.")
            except OSError as error:
                self.info(f"Export failed: {error}")

    def save_ai_response(self):
        session_id = self.sessions_box.currentData()
        if not session_id:
            self.info("Choose a recorded session first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Save a response from your AI website")
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        provider = QLineEdit()
        provider.setPlaceholderText("Source — e.g. Claude, ChatGPT, DeepSeek")
        provider.setMaxLength(100)
        layout.addWidget(provider)
        layout.addWidget(label("Paste the response manually. It is stored as unverified advice and never executed."))
        response = QPlainTextEdit()
        layout.addWidget(response, 1)
        previous = self.store.responses(session_id)
        if previous:
            history = QPlainTextEdit()
            history.setReadOnly(True)
            history.setPlainText("\n\n".join(f"{r['provider']} · {local_time(r['timestamp'])}\n{r['response']}" for r in previous))
            history.setMaximumHeight(120)
            layout.addWidget(history)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() and response.toPlainText().strip():
            privacy = Privacy(self.settings)
            ids = [e["id"] for e in self.package.payload["observations"]] if self.package else []
            self.store.save_response(session_id, privacy.redact(provider.text() or "AI website"),
                                     privacy.redact(response.toPlainText()[:32000]), ids)
            self.invalidate_package()

    def apply_settings(self):
        if self.recorder.running or self.chat_panel.busy or (self.observer_test_thread and self.observer_test_thread.is_alive()):
            self.info("Pause recording and wait for local chat or video analysis before changing settings.")
            return
        try:
            proposed = self.proposed_settings()
            if (proposed.screenshots or proposed.observer_enabled) and not proposed.accessibility:
                self.info("Enable accessibility for visual capture, or turn off both local Qwen and screenshot saving.")
                return
            proposed.save(self.directory)
            self.settings = proposed
            self.settings_error = None
            self.recorder = Recorder(self.store, proposed)
            self.store.maintain(proposed.retention_days, proposed.screenshot_budget_mb)
            self.invalidate_package()
            self.check_observer_installation()
            self.info("Settings saved. New records and rebuilt exports use these privacy rules.")
        except (OSError, ValueError) as error:
            self.info(str(error))

    def delete_memory(self):
        if self.recorder.running or self.chat_panel.busy or (self.observer_test_thread and self.observer_test_thread.is_alive()):
            self.info("Pause recording before deleting local memory.")
            return
        answer = QMessageBox.question(self, "Delete local memory?", "Delete all recorded sessions, events, images, Qwen chats, and saved AI responses?\nExported files, clipboard contents, and website conversations are separate.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self.chat_panel.render_history()
            self.invalidate_package()
            self.refresh_sessions()
            self.details.clear()
            self.refresh()

    def closeEvent(self, event):
        if not self.chat_panel.shutdown():
            self.info("Local chat is stopping. Try closing again in a moment.")
            event.ignore()
            return
        if self.observer_test_thread and self.observer_test_thread.is_alive():
            self.observer_test_stop.set()
            if self.observer_test_runner:
                self.observer_test_runner.close()
            self.observer_test_thread.join(timeout=3)
            if self.observer_test_thread.is_alive():
                self.info("The local model test is stopping. Try closing again in a moment.")
                event.ignore()
                return
        if not self.recorder.stop():
            self.info("Windows capture is still stopping. Try closing again in a moment.")
            event.ignore()
            return
        self.timer.stop()
        self.recording_badge.close()
        self.recording_badge.deleteLater()
        self.store.close()
        event.accept()

