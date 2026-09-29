import asyncio
import queue
import threading
import uuid
from concurrent.futures import Future, TimeoutError
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import urlsplit

import customtkinter as ctk
from core.downloader import MultiConnectionDownloader, DownloadTask, DownloadStatus, safe_filename, validate_url
from core.command_server import CommandServer
from gui.video_picker import VideoPicker

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class DownloadManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("IDM Clone - Download Manager")
        self.geometry("1000x600")
        self.minsize(900, 500)
        self.downloader = MultiConnectionDownloader(format_picker=self.choose_video_format)
        self.pickers = {}
        self.loop = asyncio.new_event_loop()
        self.events = queue.Queue()
        self.tasks_ui = {}
        self.closing = False
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()
        self._build_ui()
        self.command_server = CommandServer(lambda message: self.events.put(("command", message)))
        future = asyncio.run_coroutine_threadsafe(self.command_server.start(), self.loop)
        future.add_done_callback(self._server_started)
        self.after(100, self._poll)

    def _server_started(self, future):
        try:
            future.result()
            self.events.put(("status", "Browser bridge ready"))
        except Exception as exc:
            self.events.put(("status", f"Browser bridge unavailable: {exc}"))

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def _build_ui(self):
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=10, pady=10)
        self.url_entry = ctk.CTkEntry(top, placeholder_text="Paste a file URL or supported video-page URL", height=36)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(top, text="Add Download", command=self.add_download).pack(side="left", padx=5)
        path = ctk.CTkFrame(self)
        path.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(path, text="Save to:").pack(side="left", padx=5)
        self.save_path_var = ctk.StringVar(value=str(Path.home() / "Downloads"))
        ctk.CTkEntry(path, textvariable=self.save_path_var).pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(path, text="Browse…", width=90, command=self.browse_save_path).pack(side="left", padx=5)
        self.connections_var = ctk.StringVar(value="8")
        ctk.CTkLabel(path, text="Connections:").pack(side="left", padx=5)
        ctk.CTkOptionMenu(path, variable=self.connections_var, values=["1", "2", "4", "8"], width=65).pack(side="left", padx=5)
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Downloads")
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        for label, command in (("Pause All", self.pause_all), ("Resume All", self.resume_all), ("Clear Finished", self.clear_completed)):
            ctk.CTkButton(bottom, text=label, command=command, width=120).pack(side="left", padx=5, pady=5)
        self.status_label = ctk.CTkLabel(bottom, text="Starting browser bridge…")
        self.status_label.pack(side="right", padx=10)

    def browse_save_path(self):
        path = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if path:
            self.save_path_var.set(path)

    def _poll(self):
        for _ in range(100):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "command":
                if not self.closing and value["action"] == "download":
                    self.add_download(value["url"], value.get("headers", {}))
                self.deiconify()
                self.lift()
            elif kind == "progress":
                self._update_task(value)
            elif kind == "formats":
                task, title, choices, result = value
                if self.closing or task._cancel or result.done():
                    if not result.done():
                        result.set_result(None)
                else:
                    def complete(choice, result=result, key=id(task)):
                        self.pickers.pop(key, None)
                        if not result.done():
                            result.set_result(choice)
                    self.pickers[id(task)] = VideoPicker(self, title, choices, complete)
            elif kind == "status":
                self.status_label.configure(text=value)
            elif kind == "closed":
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.destroy()
                return
        self.after(100, self._poll)

    def add_download(self, url=None, headers=None):
        if self.closing:
            return
        url = url or self.url_entry.get().strip()
        try:
            validate_url(url)
            directory = Path(self.save_path_var.get()).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot add download", str(exc))
            return
        for existing in self.downloader.tasks.values():
            if existing.url == url and existing.status in (DownloadStatus.PENDING, DownloadStatus.SELECTING, DownloadStatus.DOWNLOADING, DownloadStatus.PAUSED):
                self.status_label.configure(text="That URL is already in the download list")
                return
        filename = safe_filename(Path(urlsplit(url).path).name or "Resolving video…")
        task = DownloadTask(url, str(directory / filename), int(self.connections_var.get()), headers or {})
        task_id = uuid.uuid4().hex
        self.downloader.tasks[task_id] = task
        self._create_task_ui(task_id, task)
        self.url_entry.delete(0, "end")
        asyncio.run_coroutine_threadsafe(self.downloader.download(task, lambda _: self.events.put(("progress", task_id))), self.loop)

    def choose_video_format(self, task, title, choices):
        result = Future()
        self.events.put(("formats", (task, title, choices, result)))
        while not task._cancel:
            try:
                return result.result(timeout=0.2)
            except TimeoutError:
                continue
        result.cancel()
        return None

    def _create_task_ui(self, task_id, task):
        frame = ctk.CTkFrame(self.list_frame)
        frame.pack(fill="x", pady=5, padx=5)
        name = ctk.CTkLabel(frame, text=Path(task.save_path).name, anchor="w")
        name.pack(fill="x", padx=10, pady=(5, 0))
        progress = ctk.CTkProgressBar(frame)
        progress.set(0)
        progress.pack(fill="x", padx=10, pady=5)
        info = ctk.CTkLabel(frame, text="Resolving download…", anchor="w", wraplength=820)
        info.pack(fill="x", padx=10)
        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=5)
        pause = ctk.CTkButton(buttons, text="Pause", width=70, command=lambda: self.toggle_pause(task_id))
        pause.pack(side="left", padx=3)
        cancel = ctk.CTkButton(buttons, text="Cancel", width=70, fg_color="#c0392b", command=lambda: self.cancel_task(task_id))
        cancel.pack(side="left", padx=3)
        self.tasks_ui[task_id] = dict(frame=frame, name=name, progress=progress, info=info, pause=pause, cancel=cancel)

    def _update_task(self, task_id):
        if task_id not in self.tasks_ui:
            return
        task, ui = self.downloader.tasks[task_id], self.tasks_ui[task_id]
        selected = f"  [{task.video_choice.label}]" if task.video_choice else ""
        ui["name"].configure(text=Path(task.save_path).name + selected)
        ui["progress"].set(1 if task.status == DownloadStatus.COMPLETED else min(1, task.downloaded / task.total_size) if task.total_size else 0)
        mb = task.downloaded / 1048576
        total = f"{task.total_size / 1048576:.1f} MB" if task.total_size else "unknown size"
        text = f"{task.status.value} • {mb:.1f} MB / {total} • {task.speed / 1048576:.1f} MB/s"
        if task.status == DownloadStatus.FAILED:
            text = f"Failed: {task.error}"
        elif task.status == DownloadStatus.SELECTING:
            text = "Choose a file type and resolution in the video format window."
        ui["info"].configure(text=text)
        finished = task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED)
        ui["pause"].configure(text="Resume" if task.status == DownloadStatus.PAUSED else "Pause", state="disabled" if finished or task.status == DownloadStatus.SELECTING else "normal")
        ui["cancel"].configure(state="disabled" if finished else "normal")

    def toggle_pause(self, task_id):
        task = self.downloader.tasks[task_id]
        if task.status == DownloadStatus.PAUSED:
            self.downloader.resume(task)
        else:
            self.downloader.pause(task)
        self._update_task(task_id)

    def cancel_task(self, task_id):
        self.downloader.cancel(self.downloader.tasks[task_id])
        picker = self.pickers.get(id(self.downloader.tasks[task_id]))
        if picker:
            picker.finish(None)
        self._update_task(task_id)

    def pause_all(self):
        for task_id, task in self.downloader.tasks.items():
            self.downloader.pause(task)
            self._update_task(task_id)

    def resume_all(self):
        for task_id, task in self.downloader.tasks.items():
            self.downloader.resume(task)
            self._update_task(task_id)

    def clear_completed(self):
        for task_id, task in list(self.downloader.tasks.items()):
            if not task._running and task.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED):
                self.tasks_ui.pop(task_id)["frame"].destroy()
                del self.downloader.tasks[task_id]

    def on_closing(self):
        if self.closing:
            return
        self.closing = True
        for picker in list(self.pickers.values()):
            picker.finish(None)
        self.status_label.configure(text="Stopping downloads…")
        async def shutdown():
            await self.command_server.stop()
            await self.downloader.close()
            self.events.put(("closed", None))
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
