"""Direct-file downloads and supported web-video extraction."""
import asyncio
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlsplit

import aiofiles
import aiohttp


class DownloadStatus(Enum):
    PENDING = "Pending"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Use an HTTP or HTTPS file or video-page URL.")
    return url


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", unquote(name)).strip(" .")
    if not name:
        name = "download"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}:
        name = "_" + name
    return name[:180]


def reserve_path(directory, name):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(safe_filename(name))
    for index in range(10000):
        candidate = directory / (name.name if not index else f"{name.stem} ({index}){name.suffix}")
        try:
            candidate.open("xb").close()
            return candidate
        except FileExistsError:
            continue
    raise OSError("Too many files with the same name")


@dataclass
class DownloadTask:
    url: str
    save_path: str
    connections: int = 8
    headers: dict = field(default_factory=dict)
    status: DownloadStatus = DownloadStatus.PENDING
    total_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    eta: float = 0.0
    error: str | None = None
    _pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _cancel: bool = False
    _running: bool = False
    _last_time: float = 0.0
    _last_downloaded: int = 0

    def __post_init__(self):
        self._pause_event.set()


class MultiConnectionDownloader:
    def __init__(self, max_connections=8):
        self.max_connections = max_connections
        self.tasks = {}
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, connect=30, sock_read=60),
                auto_decompress=False,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"},
            )
        return self._session

    @staticmethod
    def _is_media_page(response, prefix=b""):
        kind = response.headers.get("Content-Type", "").split(";")[0].lower()
        return (kind in {"text/html", "application/xhtml+xml", "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl", "application/dash+xml"}
                or urlsplit(str(response.url)).path.lower().endswith((".m3u8", ".mpd"))
                or prefix.lstrip().lower().startswith((b"<!doctype html", b"<html", b"#extm3u", b"<mpd")))

    def _progress(self, task, callback):
        now = time.monotonic()
        elapsed = now - task._last_time
        if elapsed >= 0.2:
            task.speed = (task.downloaded - task._last_downloaded) / elapsed
            task.eta = max(0, task.total_size - task.downloaded) / task.speed if task.speed else 0
            task._last_time, task._last_downloaded = now, task.downloaded
            if callback:
                callback(task)

    async def _checkpoint(self, task):
        while not task._pause_event.is_set() and not task._cancel:
            await asyncio.sleep(0.1)
        if task._cancel:
            raise asyncio.CancelledError()

    async def download(self, task, progress_callback=None):
        if task._running or task._cancel:
            return
        task._running = True
        task.status = DownloadStatus.DOWNLOADING
        task._last_time = time.monotonic()
        target = None
        try:
            validate_url(task.url)
            session = await self._get_session()
            async with session.get(task.url, headers={**task.headers, "Range": "bytes=0-511"}) as response:
                if response.status == 416:
                    ranged, size, metadata, page = False, 0, {}, False
                else:
                    response.raise_for_status()
                    prefix = await response.content.read(512)
                    page = self._is_media_page(response, prefix)
                    match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    ranged = (response.status == 206 and match is not None
                              and int(match[1]) == min(511, int(match[2]) - 1))
                    size = int(match[2]) if ranged else int(response.headers.get("Content-Length", 0))
                    metadata = response.headers.copy()
                    disposition = response.content_disposition
                    if disposition and disposition.filename:
                        metadata["Resolved-Filename"] = disposition.filename
            await self._checkpoint(task)
            if page:
                await asyncio.to_thread(self._download_media, task, progress_callback)
            else:
                name = metadata.get("Resolved-Filename") or Path(urlsplit(task.url).path).name or "download"
                if not Path(name).suffix:
                    name += mimetypes.guess_extension(metadata.get("Content-Type", "").split(";")[0]) or ""
                target = reserve_path(Path(task.save_path).parent, name)
                task.save_path = str(target)
                task.total_size = size
                if progress_callback:
                    progress_callback(task)
                with tempfile.TemporaryDirectory(prefix=".idm-", dir=target.parent) as scratch:
                    part = Path(scratch) / "download.part"
                    if ranged and size > 1 and task.connections > 1:
                        with part.open("wb") as file:
                            file.truncate(size)
                        count = min(task.connections, self.max_connections, size)
                        async with asyncio.TaskGroup() as group:
                            for index in range(count):
                                start = size * index // count
                                end = size * (index + 1) // count - 1
                                group.create_task(self._chunk(session, task, part, start, end, progress_callback))
                    else:
                        await self._single(session, task, part, progress_callback)
                    await self._checkpoint(task)
                    os.replace(part, target)
            task.status = DownloadStatus.COMPLETED
            task.total_size = task.downloaded
        except asyncio.CancelledError:
            task.status = DownloadStatus.CANCELLED
        except Exception as exc:
            task.status = DownloadStatus.CANCELLED if task._cancel else DownloadStatus.FAILED
            if isinstance(exc, BaseExceptionGroup):
                exc = exc.exceptions[0]
            task.error = str(exc)
        finally:
            if target and task.status != DownloadStatus.COMPLETED:
                target.unlink(missing_ok=True)
            task.speed = task.eta = 0
            task._running = False
            if progress_callback:
                progress_callback(task)

    async def _chunk(self, session, task, path, start, end, callback):
        async with session.get(task.url, headers={**task.headers, "Range": f"bytes={start}-{end}"}) as response:
            expected = f"bytes {start}-{end}/{task.total_size}"
            if response.status != 206 or response.headers.get("Content-Range") != expected:
                raise ValueError("Server returned an invalid byte range. Retry with one connection.")
            received = 0
            async with aiofiles.open(path, "r+b") as file:
                await file.seek(start)
                async for data in response.content.iter_chunked(65536):
                    await self._checkpoint(task)
                    received += len(data)
                    if received > end - start + 1:
                        raise ValueError("Server sent more bytes than requested")
                    await file.write(data)
                    task.downloaded += len(data)
                    self._progress(task, callback)
            if received != end - start + 1:
                raise ValueError("Download ended before the requested range was complete")

    async def _single(self, session, task, path, callback):
        async with session.get(task.url, headers=task.headers) as response:
            response.raise_for_status()
            prefix = await response.content.read(512)
            if self._is_media_page(response, prefix):
                raise ValueError("The server returned a webpage instead of a file. Use the video-page URL or sign in to the site.")
            task.total_size = int(response.headers.get("Content-Length", 0))
            async with aiofiles.open(path, "wb") as file:
                await self._checkpoint(task)
                await file.write(prefix)
                task.downloaded += len(prefix)
                async for data in response.content.iter_chunked(65536):
                    await self._checkpoint(task)
                    await file.write(data)
                    task.downloaded += len(data)
                    self._progress(task, callback)
            if task.total_size and task.downloaded != task.total_size:
                raise ValueError("Incomplete download")

    def _download_media(self, task, callback):
        from yt_dlp import YoutubeDL

        class QuietLogger:
            def debug(self, message): pass
            def warning(self, message): pass
            def error(self, message): pass

        def hook(info):
            task._pause_event.wait()
            if task._cancel:
                raise ValueError("Download cancelled")
            task.downloaded = info.get("downloaded_bytes", task.downloaded)
            task.total_size = info.get("total_bytes") or info.get("total_bytes_estimate") or 0
            self._progress(task, callback)

        directory = Path(task.save_path).parent
        directory.mkdir(parents=True, exist_ok=True)
        target = None
        try:
            with tempfile.TemporaryDirectory(prefix=".idm-media-", dir=directory) as scratch:
                options = {
                    "format": "bestvideo+bestaudio/best" if shutil.which("ffmpeg") else "best",
                    "outtmpl": str(Path(scratch) / "%(title).120B.%(ext)s"),
                    "windowsfilenames": True, "noplaylist": True,
                    "quiet": True, "no_warnings": True, "logger": QuietLogger(),
                    "http_headers": task.headers, "progress_hooks": [hook],
                    "socket_timeout": 30, "retries": 2,
                }
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(task.url, download=False)
                    if not info or info.get("_type") in ("playlist", "multi_video"):
                        raise ValueError("Use a single video URL, not a playlist.")
                    if info.get("is_live"):
                        raise ValueError("Live stream recording is not supported yet.")
                    if info.get("has_drm"):
                        raise ValueError("This video is DRM protected.")
                    hook({})
                    ydl.process_info(info)
                files = [path for path in Path(scratch).iterdir() if path.suffix not in (".part", ".ytdl", ".temp")]
                if len(files) != 1:
                    raise ValueError("Could not produce a single media file; this format may require FFmpeg.")
                if task._cancel:
                    raise ValueError("Download cancelled")
                source = files[0]
                target = reserve_path(directory, source.name)
                task.save_path = str(target)
                os.replace(source, target)
                task.downloaded = target.stat().st_size
        except Exception:
            if target:
                target.unlink(missing_ok=True)
            raise

    def pause(self, task):
        if task.status == DownloadStatus.DOWNLOADING:
            task.status = DownloadStatus.PAUSED
            task._pause_event.clear()

    def resume(self, task):
        if task.status == DownloadStatus.PAUSED:
            task.status = DownloadStatus.DOWNLOADING
            task._pause_event.set()

    def cancel(self, task):
        task._cancel = True
        task.status = DownloadStatus.CANCELLED
        task._pause_event.set()

    async def close(self):
        for task in self.tasks.values():
            if task._running:
                self.cancel(task)
        while any(task._running for task in self.tasks.values()):
            await asyncio.sleep(0.1)
        if self._session and not self._session.closed:
            await self._session.close()
