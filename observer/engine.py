import os
import queue
import re
import threading
import time

from .accessibility import AccessibilityReader
from .capture import ScreenCapture, difference, fingerprint
from .models import Accessibility, Observation, now_iso
from .privacy import Privacy
from .vision import VisionWorker, installation_status
from .windows import WindowsDesktop
from .video import ClipBuffer


class Recorder:
    def __init__(self, store, settings, *, desktop_factory=WindowsDesktop,
                 accessibility_factory=AccessibilityReader, capture_factory=ScreenCapture,
                 vision_factory=VisionWorker, observer_check=installation_status):
        self.store, self.settings = store, settings
        self.privacy = Privacy(settings)
        self.desktop_factory, self.accessibility_factory, self.capture_factory = desktop_factory, accessibility_factory, capture_factory
        self.vision_factory, self.observer_check = vision_factory, observer_check
        self.vision = None
        self.stop_event = threading.Event()
        self.thread = None
        self.session_id = None
        self.updates = queue.Queue(maxsize=32)
        self.metrics = {"samples": 0, "events": 0, "duplicates": 0, "failures": 0, "last_sample_ms": 0.0}
        self.stream_frames = 0
        self.stream_buffered = 0
        self.stream_clips = 0
        self.state = "Paused · nothing is being collected"
        self.current_application = "—"

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def notify(self, text):
        self.state = text
        if self.updates.full():
            try:
                self.updates.get_nowait()
            except queue.Empty:
                pass
        self.updates.put_nowait(text)

    def start(self, goal):
        if self.running:
            return True
        if self.settings.observer_enabled:
            if not self.settings.accessibility:
                self.notify("Enable accessibility before starting the local visual observer")
                return False
            ready, message = self.observer_check(self.settings)
            if not ready:
                self.notify(message)
                return False
        self.stop_event.clear()
        self.session_id = self.store.start_session(self.privacy.redact(goal))
        self.thread = threading.Thread(target=self._run, name="observer-recorder", daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                self.notify("Stopping · waiting for Windows capture to return")
                return False
            self.thread = None
        self.notify("Paused · nothing is being collected")
        self.current_application = "—"
        return True

    def _run(self):
        accessibility, capture, vision = None, None, None
        previous_window, previous_labels, previous_frame = None, None, None
        last_event, last_maintenance = 0.0, 0.0
        error_signature = None
        clips = ClipBuffer(self.settings.observer_video_frames, self.settings.interval_seconds)
        try:
            desktop = self.desktop_factory()
            accessibility = self.accessibility_factory() if self.settings.accessibility else None
            if self.settings.screenshots or self.settings.observer_enabled:
                capture = self.capture_factory()
            if self.settings.observer_enabled:
                vision = self.vision_factory(self.store, self.settings, self.privacy, self.stop_event)
                self.vision = vision
            self.notify("Recording locally")
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    if not (self.settings.observer_enabled and self.settings.observer_video) and desktop.idle_seconds() >= self.settings.idle_seconds:
                        clips.clear()
                        self.stream_buffered = 0
                        self.current_application = "—"
                        self.notify("Idle · collection suspended")
                        self.stop_event.wait(3)
                        continue
                    window = desktop.foreground()
                    if not window or window.pid == os.getpid() or self.privacy.excluded(window):
                        clips.clear()
                        self.stream_buffered = 0
                        self.current_application = "—"
                        self.notify("Protected or Observer window · collection suspended")
                        previous_window, previous_labels, previous_frame = None, None, None
                        self.stop_event.wait(self.settings.interval_seconds)
                        continue
                    access = accessibility.read(window.handle, self.stop_event) if accessibility else Accessibility(status="disabled")
                    if self.stop_event.is_set():
                        break
                    if access.sensitive:
                        clips.clear()
                        self.stream_buffered = 0
                        self.current_application = "—"
                        self.notify("Password field detected · collection suspended")
                        previous_window, previous_labels, previous_frame = None, None, None
                        self.stop_event.wait(self.settings.interval_seconds)
                        continue
                    # Exclusions are applied before storage. Reject focus/title/geometry races.
                    if desktop.foreground() != window:
                        clips.clear()
                        self.stream_buffered = 0
                        self.stop_event.wait(0.05)
                        continue
                    image, frame, change = None, None, None
                    if capture and access.status == "available":
                        masks = [w for w in desktop.visible_windows() if self.privacy.excluded(w) or w.pid == os.getpid()]
                        try:
                            image = capture.grab(window, masks)
                        except Exception:
                            self.metrics["failures"] += 1
                            image = None
                        if desktop.foreground() != window or self.stop_event.is_set():
                            clips.clear()
                            self.stream_buffered = 0
                            self.stop_event.wait(0.05)
                            continue
                        if image is not None:
                            frame = fingerprint(image)
                            change = difference(previous_frame, frame)
                    labels = [self.privacy.redact(x) for x in access.labels]
                    title = self.privacy.redact(window.title)
                    signature = (window.handle, window.application, title)
                    switched = signature != previous_window
                    text_changed = tuple(labels) != previous_labels
                    now = time.monotonic()
                    errors = tuple(x for x in labels if re.search(r"\b(error|exception|failed|traceback)\b", x, re.I))
                    new_error = bool(errors and errors != error_signature)
                    if switched:
                        event_type = "window_change"
                    elif new_error:
                        event_type = "error_text_visible"
                    elif now - last_event >= 2 and text_changed:
                        event_type = "ui_text_change"
                    elif now - last_event >= 2 and change is not None and change >= 0.03:
                        event_type = "visual_change"
                    elif now - last_event >= self.settings.heartbeat_seconds:
                        event_type = "still_visible"
                    else:
                        event_type = None
                    self.metrics["samples"] += 1
                    self.current_application = self.privacy.redact(window.application)
                    self.notify("Recording locally" if not capture or image else "Recording text · visual evidence unavailable or withheld")
                    if event_type and not self.stop_event.is_set():
                        event = Observation(session_id=self.session_id, application=self.current_application,
                                            window_title=title, event_type=event_type, visible_text=labels,
                                            frame_change=round(change, 4) if change is not None else None,
                                            accessibility_status=access.status, accessibility_truncated=access.truncated,
                                            observer_status=(("in_video_stream" if self.settings.observer_video else "queued") if image is not None else "no_visual_evidence") if vision else "disabled")
                        if image is not None and self.settings.screenshots:
                            event.screenshot = f"screenshots/{event.id}.jpg"
                            image.save(self.store.directory / event.screenshot, quality=78)
                        if self.stop_event.is_set():
                            if event.screenshot:
                                (self.store.directory / event.screenshot).unlink(missing_ok=True)
                            break
                        self.store.add(event)
                        if vision and image is not None and not self.settings.observer_video:
                            vision.submit(event, image)
                        self.metrics["events"] += 1
                        last_event = now
                        previous_labels, previous_window, previous_frame = tuple(labels), signature, frame
                        error_signature = errors
                    else:
                        self.metrics["duplicates"] += 1
                    if vision and self.settings.observer_video:
                        if image is None:
                            clips.clear()
                        else:
                            clip = clips.add(image, now_iso(), now, self.current_application, title)
                            self.stream_frames += 1
                            if clip is not None and not self.stop_event.is_set():
                                event = Observation(session_id=self.session_id, application=self.current_application,
                                                    window_title=title, event_type="screen_video", visible_text=labels,
                                                    accessibility_status=access.status, observer_status="queued",
                                                    observer_input=clip.metadata())
                                self.store.add(event)
                                vision.submit(event, clip)
                                self.stream_clips += 1
                                self.metrics["events"] += 1
                        self.stream_buffered = len(clips.frames)
                    if now - last_maintenance >= 60:
                        self.store.maintain(self.settings.retention_days, self.settings.screenshot_budget_mb)
                        last_maintenance = now
                except Exception:
                    clips.clear()
                    self.stream_buffered = 0
                    self.metrics["failures"] += 1
                    self.current_application = "—"
                    self.notify("A Windows data source failed · retrying; no error content recorded")
                    self.stop_event.wait(2)
                finally:
                    self.metrics["last_sample_ms"] = round((time.monotonic() - started) * 1000, 1)
                self.stop_event.wait(max(0.05, self.settings.interval_seconds - (time.monotonic() - started)))
        except Exception:
            self.notify("Recorder could not start · check Windows and installed dependencies")
            self.metrics["failures"] += 1
        finally:
            clips.clear()
            self.stream_buffered = 0
            if vision:
                while not vision.close():
                    self.notify("Stopping · waiting for local Qwen to release its resources")
            if accessibility:
                accessibility.close()
            if capture:
                capture.close()
            self.store.end_session(self.session_id)
