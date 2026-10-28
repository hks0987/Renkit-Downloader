"""START HERE:  python main.py"""
import sys
import ctypes
import traceback
from common import (_TKINTER_AVAILABLE, log_error, show_fatal_dialog)
from app import MainDownloadManagerApp


def main():
    if not _TKINTER_AVAILABLE:
        show_fatal_dialog("Missing Tkinter", "Tkinter is required. Reinstall Python from python.org and tick 'tcl/tk and IDLE'.")
        sys.exit(1)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
    except Exception:
        pass
    try:
        app = MainDownloadManagerApp()
        app.mainloop()
    except Exception:
        log_error("startup/mainloop")
        show_fatal_dialog("Startup Error", traceback.format_exc())


if __name__ == "__main__":
    main()
