import customtkinter as ctk
import asyncio
import threading
from tkinter import filedialog, messagebox
from pathlib import Path
from core.downloader import MultiConnectionDownloader, DownloadTask, DownloadStatus
from core.command_server import CommandServer

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DownloadManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("IDM Clone - Download Manager")
        self.geometry("1000x600")
        self.minsize(900, 500)

        self.downloader = MultiConnectionDownloader(max_connections=8)
        self.loop = asyncio.new_event_loop()
        self.tasks_ui = {}  # url -> ui widgets

        # Start asyncio loop in background thread
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
    
        self.command_server = CommandServer(self.add_download_from_browser)
        asyncio.run_coroutine_threadsafe(
            self.command_server.start(),
            self.loop
        )
    
        self._build_ui()
    def on_closing(self):
        asyncio.run_coroutine_threadsafe(self.command_server.stop(), self.loop)
        asyncio.run_coroutine_threadsafe(self.downloader.close(), self.loop)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.destroy()

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _build_ui(self):
        # Top bar
        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=10, pady=10)

        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="Enter download URL...", height=36)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(top_frame, text="Add Download", width=120, command=self.add_download).pack(side="left", padx=(0, 5))
        ctk.CTkButton(top_frame, text="Browse...", width=90, command=self.browse_save_path).pack(side="left")

        # Save path
        path_frame = ctk.CTkFrame(self)
        path_frame.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(path_frame, text="Save to:").pack(side="left", padx=(5, 5))
        self.save_path_var = ctk.StringVar(value=str(Path.home() / "Downloads"))
        self.save_path_entry = ctk.CTkEntry(path_frame, textvariable=self.save_path_var, height=32)
        self.save_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # Downloads list
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Downloads")
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Bottom controls
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkButton(bottom, text="Pause All", command=self.pause_all).pack(side="left", padx=5)
        ctk.CTkButton(bottom, text="Resume All", command=self.resume_all).pack(side="left", padx=5)
        ctk.CTkButton(bottom, text="Clear Completed", command=self.clear_completed).pack(side="left", padx=5)

    def browse_save_path(self):
        path = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if path:
            self.save_path_var.set(path)
    def add_download_from_browser(self, url: str):
        def _add():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self.add_download()
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
            except Exception:
                pass

        self.after(0, _add)
    def add_download(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a URL")
            return

        filename = url.split("/")[-1].split("?")[0] or "download"
        save_path = str(Path(self.save_path_var.get()) / filename)

        task = DownloadTask(url=url, save_path=save_path, connections=8)
        self.downloader.tasks[url] = task

        self._create_task_ui(task)
        self.url_entry.delete(0, "end")

        # Start download
        asyncio.run_coroutine_threadsafe(
            self.downloader.download(task, self.on_progress),
            self.loop
        )

    def _create_task_ui(self, task: DownloadTask):
        frame = ctk.CTkFrame(self.list_frame)
        frame.pack(fill="x", pady=5, padx=5)

        name_label = ctk.CTkLabel(frame, text=Path(task.save_path).name, anchor="w")
        name_label.pack(fill="x", padx=10, pady=(5, 0))

        progress = ctk.CTkProgressBar(frame)
        progress.set(0)
        progress.pack(fill="x", padx=10, pady=5)

        info_label = ctk.CTkLabel(frame, text="Starting...", anchor="w")
        info_label.pack(fill="x", padx=10)

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)

        pause_btn = ctk.CTkButton(btn_frame, text="Pause", width=70,
                                  command=lambda: self.toggle_pause(task))
        pause_btn.pack(side="left", padx=3)

        cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", width=70, fg_color="#c0392b",
                                   command=lambda: self.cancel_task(task))
        cancel_btn.pack(side="left", padx=3)

        self.tasks_ui[task.url] = {
            "frame": frame,
            "progress": progress,
            "info": info_label,
            "pause_btn": pause_btn
        }

    def on_progress(self, task: DownloadTask):
        if task.url not in self.tasks_ui:
            return

        ui = self.tasks_ui[task.url]

        def update():
            if task.total_size > 0:
                percent = task.downloaded / task.total_size
                ui["progress"].set(percent)
            else:
                ui["progress"].set(0)

            downloaded_mb = task.downloaded / (1024 * 1024)
            total_mb = task.total_size / (1024 * 1024)
            speed_mb = task.speed / (1024 * 1024)

            if task.status == DownloadStatus.COMPLETED:
                text = f"Completed • {total_mb:.1f} MB"
                ui["pause_btn"].configure(state="disabled")
            elif task.status == DownloadStatus.PAUSED:
                text = f"Paused • {downloaded_mb:.1f}/{total_mb:.1f} MB"
            elif task.status == DownloadStatus.FAILED:
                text = f"Failed: {task.error}"
            elif task.status == DownloadStatus.CANCELLED:
                text = "Cancelled"
            else:
                eta_min = int(task.eta // 60)
                eta_sec = int(task.eta % 60)
                text = f"{downloaded_mb:.1f}/{total_mb:.1f} MB • {speed_mb:.1f} MB/s • ETA {eta_min:02d}:{eta_sec:02d}"

            ui["info"].configure(text=text)

        self.after(0, update)

    def toggle_pause(self, task: DownloadTask):
        if task.status == DownloadStatus.DOWNLOADING:
            self.downloader.pause(task)
            self.tasks_ui[task.url]["pause_btn"].configure(text="Resume")
        elif task.status == DownloadStatus.PAUSED:
            self.downloader.resume(task)
            self.tasks_ui[task.url]["pause_btn"].configure(text="Pause")
            # Restart the download coroutine if needed (simple version)
            asyncio.run_coroutine_threadsafe(
                self.downloader.download(task, self.on_progress),
                self.loop
            )

    def cancel_task(self, task: DownloadTask):
        self.downloader.cancel(task)
        if task.url in self.tasks_ui:
            self.tasks_ui[task.url]["frame"].destroy()
            del self.tasks_ui[task.url]

    def pause_all(self):
        for task in self.downloader.tasks.values():
            if task.status == DownloadStatus.DOWNLOADING:
                self.downloader.pause(task)
                if task.url in self.tasks_ui:
                    self.tasks_ui[task.url]["pause_btn"].configure(text="Resume")

    def resume_all(self):
        for task in self.downloader.tasks.values():
            if task.status == DownloadStatus.PAUSED:
                self.downloader.resume(task)
                if task.url in self.tasks_ui:
                    self.tasks_ui[task.url]["pause_btn"].configure(text="Pause")
                asyncio.run_coroutine_threadsafe(
                    self.downloader.download(task, self.on_progress),
                    self.loop
                )

    def clear_completed(self):
        to_remove = []
        for url, task in self.downloader.tasks.items():
            if task.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED):
                if url in self.tasks_ui:
                    self.tasks_ui[url]["frame"].destroy()
                    del self.tasks_ui[url]
                to_remove.append(url)
        for url in to_remove:
            del self.downloader.tasks[url]

    def on_closing(self):
        asyncio.run_coroutine_threadsafe(self.downloader.close(), self.loop)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.destroy()