from gui.main_window import DownloadManagerApp

if __name__ == "__main__":
    app = DownloadManagerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()