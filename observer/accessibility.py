"""UI Automation runs in a disposable process so a hung provider is bounded."""
import multiprocessing as mp
import time

from .models import Accessibility


def _read(auto, handle: int) -> dict:
    focused = auto.GetFocusedControl()
    if focused and focused.IsPassword:
        return {"sensitive": True, "status": "password_field"}
    root = auto.ControlFromHandle(handle)
    if not root:
        return {"status": "unavailable"}
    labels, seen = [], set()
    stack = [(root, 0)]
    count, truncated = 0, False
    deadline = time.monotonic() + 0.25
    safe_types = {"TextControl", "ButtonControl", "HyperlinkControl", "TabItemControl", "MenuItemControl", "WindowControl"}
    while stack:
        if count >= 100 or time.monotonic() > deadline:
            truncated = True
            break
        node, depth = stack.pop()
        count += 1
        if node.IsOffscreen:
            continue
        if node.IsPassword:
            return {"sensitive": True, "status": "password_field"}
        kind = node.ControlTypeName
        # Never request ValuePattern or TextPattern, nor names/children of inputs.
        if kind in {"EditControl", "ComboBoxControl"}:
            continue
        if kind in safe_types:
            name = node.Name.strip()[:400]
            if name and name not in seen:
                seen.add(name)
                labels.append(name)
        child = node.GetFirstChildControl() if depth < 5 else None
        if depth >= 5:
            truncated = True
        children = []
        while child and len(children) < 100 and time.monotonic() <= deadline:
            children.append((child, depth + 1))
            child = child.GetNextSiblingControl()
        if child:
            truncated = True
        stack.extend(reversed(children))
    return {"labels": labels[:40], "status": "available", "truncated": truncated or len(labels) > 40}


def _worker(connection) -> None:
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            connection.send("ready")
            while True:
                handle = connection.recv()
                if handle is None:
                    return
                try:
                    connection.send(_read(auto, handle))
                except Exception:
                    connection.send({"status": "unavailable"})
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class AccessibilityReader:
    def __init__(self):
        self.process = None
        self.connection = None
        self.retry_at = 0.0
        self.last_failure = None

    def _poll(self, duration, stop) -> bool:
        end = time.monotonic() + duration
        while time.monotonic() < end and not stop.is_set():
            if self.connection.poll(0.05):
                return True
        return False

    def read(self, handle: int, stop) -> Accessibility:
        if time.monotonic() < self.retry_at:
            return Accessibility(status="cooldown")
        stage = "worker_start"
        try:
            if self.process is None:
                context = mp.get_context("spawn")
                self.connection, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child,), daemon=True)
                self.process.start()
                child.close()
                if not self._poll(5.0, stop) or self.connection.recv() != "ready":
                    raise TimeoutError
            stage = "provider_read"
            self.connection.send(handle)
            if not self._poll(0.8, stop):
                raise TimeoutError
            return Accessibility(**self.connection.recv())
        except (OSError, EOFError, TimeoutError, BrokenPipeError) as error:
            self.last_failure = f"{stage}:{type(error).__name__}"
            self.close()
            self.retry_at = time.monotonic() + 10
            return Accessibility(status="unavailable")

    def close(self) -> None:
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=0.5)
            self.process.close()
            self.process = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

