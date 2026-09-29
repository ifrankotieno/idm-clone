from multiprocessing import freeze_support
from browser.native_host.idm_native_host import exchange


def main():
    try:
        if exchange({"action": "open"}).get("status") == "ok":
            return
    except (OSError, ValueError):
        pass
    from gui.main_window import DownloadManagerApp
    app = DownloadManagerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    freeze_support()
    main()
