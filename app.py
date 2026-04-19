from __future__ import annotations

import ctypes

from cleaner_app.assets import asset_path
from cleaner_app.ui import CleanerApp


def enable_high_dpi_support() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def set_windows_app_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CleanerPro.Desktop")
    except Exception:
        pass


if __name__ == "__main__":
    enable_high_dpi_support()
    set_windows_app_id()
    app = CleanerApp()
    try:
        app.iconbitmap(default=str(asset_path("cleanerpro.ico")))
    except Exception:
        pass
    app.mainloop()
