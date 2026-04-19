from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from pathlib import Path

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_TRAYICON = WM_USER + 20
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
WPARAM = getattr(wintypes, "WPARAM", ctypes.c_size_t)
LPARAM = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HINSTANCE = getattr(wintypes, "HINSTANCE", wintypes.HANDLE)

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]


WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", HICON),
    ]


class SystemTrayController:
    def __init__(self, app) -> None:
        self.app = app
        self.thread: threading.Thread | None = None
        self.hwnd = None
        self.class_name = f"CleanerProTrayWindow-{id(self)}"
        self.window_proc_ref = WNDPROC(self._window_proc)
        self.running = False
        self.icon_handle = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._message_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _message_loop(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASS()
        window_class.lpfnWndProc = self.window_proc_ref
        window_class.lpszClassName = self.class_name
        window_class.hInstance = hinstance
        user32.RegisterClassW(ctypes.byref(window_class))

        self.hwnd = user32.CreateWindowExW(
            0,
            self.class_name,
            self.class_name,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            hinstance,
            None,
        )
        self._add_icon()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._remove_icon()
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON and lparam in {WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP}:
            self.app.after(0, self.app.toggle_quick_panel_from_tray)
            return 0

        if msg == WM_CLOSE:
            self._remove_icon()
            user32.DestroyWindow(hwnd)
            return 0

        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, WPARAM(wparam), LPARAM(lparam))

    def _add_icon(self) -> None:
        if not self.hwnd:
            return

        notify_data = self._notify_data()
        notify_data.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        notify_data.hIcon = self._load_icon_handle()
        notify_data.szTip = "CleanerPro"
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(notify_data))

    def _remove_icon(self) -> None:
        if not self.hwnd:
            return
        notify_data = self._notify_data()
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notify_data))

    def _notify_data(self) -> NOTIFYICONDATA:
        notify_data = NOTIFYICONDATA()
        notify_data.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        notify_data.hWnd = self.hwnd
        notify_data.uID = 1
        notify_data.uCallbackMessage = WM_TRAYICON
        return notify_data

    def _load_icon_handle(self):
        if self.icon_handle:
            return self.icon_handle

        try:
            from .assets import asset_path

            icon_path = Path(asset_path("cleanerpro.ico"))
            if icon_path.exists():
                handle = user32.LoadImageW(
                    0,
                    str(icon_path),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
                if handle:
                    self.icon_handle = handle
                    return handle
        except Exception:
            pass

        self.icon_handle = user32.LoadIconW(0, IDI_APPLICATION)
        return self.icon_handle
