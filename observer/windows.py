"""Read-only Windows metadata. This module never sends input to applications."""
import ctypes
import os
from ctypes import wintypes

import psutil

from .models import Window


class WindowsDesktop:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Desktop recording requires Windows 10 or 11.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong

    def _window(self, handle: int) -> Window | None:
        if not handle or not self.user32.IsWindowVisible(handle) or self.user32.IsIconic(handle):
            return None
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        try:
            application = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        text = ctypes.create_unicode_buffer(min(self.user32.GetWindowTextLengthW(handle) + 1, 4096))
        self.user32.GetWindowTextW(handle, text, len(text))
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(handle, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return Window(int(handle), pid.value, application, text.value,
                      (rect.left, rect.top, rect.right, rect.bottom))

    def foreground(self) -> Window | None:
        return self._window(self.user32.GetForegroundWindow())

    def visible_windows(self) -> list[Window]:
        result = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(handle, _):
            item = self._window(handle)
            if item:
                result.append(item)
            return True

        self.user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user32.EnumWindows(callback, 0)
        return result

    def idle_seconds(self) -> float:
        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        value = LastInput()
        value.cbSize = ctypes.sizeof(value)
        if not self.user32.GetLastInputInfo(ctypes.byref(value)):
            return 0.0
        return ((self.kernel32.GetTickCount64() - value.dwTime) & 0xFFFFFFFF) / 1000


def enable_dpi_awareness() -> None:
    if os.name == "nt":
        # PER_MONITOR_AWARE_V2; Qt may already have selected this context.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass

