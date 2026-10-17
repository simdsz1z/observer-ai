"""Test native bindings against an owned hidden window; no desktop pixels are read."""
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.name != "nt":
        raise SystemExit("This integration check requires Windows.")
    from observer.windows import WindowsDesktop, enable_dpi_awareness
    import mss
    import uiautomation as auto
    enable_dpi_awareness()
    desktop = WindowsDesktop()
    user32 = desktop.user32
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    # Hidden standard control, owned by this process, containing only a test label.
    handle = user32.CreateWindowExW(0, "STATIC", "Observer controlled UIA integration check", 0,
                                    0, 0, 100, 100, None, None, None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        with auto.UIAutomationInitializerInThread():
            control = auto.ControlFromHandle(int(handle))
            assert control.Name == "Observer controlled UIA integration check"
            assert not control.IsPassword
            kind = control.ControlTypeName
        assert desktop._window(handle) is None  # hidden windows are rejected
        with mss.MSS() as backend:
            monitor_count = len(backend.monitors) - 1
        print(json.dumps({"win32_bindings": "passed", "uia_owned_hidden_control": "passed",
                          "uia_control_type": kind, "mss_display_enumeration": "passed",
                          "display_count": monitor_count, "desktop_pixels_captured": 0}, indent=2))
    finally:
        user32.DestroyWindow(handle)


if __name__ == "__main__":
    main()
