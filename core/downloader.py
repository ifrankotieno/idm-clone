import asyncio
import aiohttp
import aiofiles
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum

class DownloadStatus(Enum):
    PENDING = "Pending"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

@dataclass
class DownloadTask:
    url: str
    save_path: str
    connections: int = 8
    status: DownloadStatus = DownloadStatus.PENDING
    total_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    eta: float = 0.0
    error: Optional[str] = None
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _cancel: bool = field(default=False, repr=False)
    _start_time: float = field(default=0.0, repr=False)
    _last_downloaded: int = field(default=0, repr=False)
    _last_time: float = field(default=0.0, repr=False)

    def __post_init__(self):
        self._pause_event.set()  # Not paused by default

class MultiConnectionDownloader:
    def __init__(self, max_connections: int = 8):
        self.max_connections = max_connections
        self.tasks: dict[str, DownloadTask] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=None, connect=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IDM-Clone/1.0"}
            )
        return self._session

    async def get_file_info(self, url: str) -> tuple[int, bool]:
        """Return (file_size, supports_range)"""
        session = await self._get_session()
        try:
            async with session.head(url, allow_redirects=True) as resp:
                size = int(resp.headers.get("Content-Length", 0))
                accept_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
                return size, accept_ranges
        except Exception:
            # Fallback to GET with range
            try:
                headers = {"Range": "bytes=0-0"}
                async with session.get(url, headers=headers, allow_redirects=True) as resp:
                    if resp.status == 206:
                        content_range = resp.headers.get("Content-Range", "")
                        if "/" in content_range:
                            size = int(content_range.split("/")[-1])
                            return size, True
                    size = int(resp.headers.get("Content-Length", 0))
                    return size, False
            except Exception as e:
                raise Exception(f"Could not get file info: {e}")

    async def download_chunk(
        self,
        session: aiohttp.ClientSession,
        url: str,
        start: int,
        end: int,
        file_path: str,
        task: DownloadTask,
        progress_callback: Optional[Callable] = None
    ):
        headers = {"Range": f"bytes={start}-{end}"}
        mode = "r+b" if os.path.exists(file_path) else "wb"

        async with session.get(url, headers=headers) as resp:
            if resp.status not in (200, 206):
                raise Exception(f"Chunk failed with status {resp.status}")

            async with aiofiles.open(file_path, mode) as f:
                await f.seek(start)
                async for data in resp.content.iter_chunked(1024 * 64):  # 64KB chunks
                    if task._cancel:
                        return
                    await task._pause_event.wait()  # Wait if paused

                    await f.write(data)
                    task.downloaded += len(data)

                    # Update speed & ETA
                    now = time.time()
                    if now - task._last_time >= 0.5:
                        elapsed = now - task._last_time
                        diff = task.downloaded - task._last_downloaded
                        task.speed = diff / elapsed if elapsed > 0 else 0
                        remaining = task.total_size - task.downloaded
                        task.eta = remaining / task.speed if task.speed > 0 else 0
                        task._last_downloaded = task.downloaded
                        task._last_time = now

                        if progress_callback:
                            progress_callback(task)

    async def download(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        task.status = DownloadStatus.DOWNLOADING
        task._start_time = time.time()
        task._last_time = task._start_time
        task._last_downloaded = task.downloaded
        task._cancel = False
        task._pause_event.set()

        try:
            # total_size, supports_range = await self.get_file_info(task.url)
            # task.total_size = total_size

            # if total_size == 0:
            #     raise Exception("Could not determine file size")

            # # Create empty file if it doesn't exist
            # Path(task.save_path).parent.mkdir(parents=True, exist_ok=True)
            # if not os.path.exists(task.save_path):
            #     async with aiofiles.open(task.save_path, "wb") as f:
            #         await f.truncate(total_size)

            # session = await self._get_session()
            # connections = min(task.connections, self.max_connections)

            # if not supports_range or connections == 1:
            #     # Single connection fallback
            #     await self.download_chunk(session, task.url, 0, total_size - 1, task.save_path, task, progress_callback)
            # else:
            #     chunk_size = total_size // connections
            #     tasks = []

            #     for i in range(connections):
            #         start = i * chunk_size
            #         end = start + chunk_size - 1 if i < connections - 1 else total_size - 1

            #         # Skip already downloaded parts (simple resume)
            #         if task.downloaded > end:
            #             continue

            #         if task.downloaded > start:
            #             start = task.downloaded

            #         tasks.append(
            #             self.download_chunk(session, task.url, start, end, task.save_path, task, progress_callback)
            #         )

            #     await asyncio.gather(*tasks)

            # if not task._cancel:
            #     task.status = DownloadStatus.COMPLETED
            #     task.speed = 0
            #     task.eta = 0
            #     if progress_callback:
            #         progress_callback(task)

            total_size, supports_range = await self.get_file_info(task.url)
            task.total_size = total_size

            Path(task.save_path).parent.mkdir(parents=True, exist_ok=True)
            session = await self._get_session()

            if total_size <= 0 or not supports_range:
                await self.download_single(session, task, progress_callback)
            else:
                if not os.path.exists(task.save_path):
                    async with aiofiles.open(task.save_path, "wb") as f:
                        await f.truncate(total_size)

                connections = min(task.connections, self.max_connections)
                chunk_size = total_size // connections
                jobs = []

                for i in range(connections):
                    start = i * chunk_size
                    end = start + chunk_size - 1 if i < connections - 1 else total_size - 1
                    jobs.append(
                        self.download_chunk(
                            session, task.url, start, end, task.save_path, task, progress_callback
                        )
                    )

                await asyncio.gather(*jobs)

            if not task._cancel:
                task.status = DownloadStatus.COMPLETED
                task.speed = 0
                task.eta = 0
                if progress_callback:
                    progress_callback(task)
        except Exception as e:
            if not task._cancel:
                task.status = DownloadStatus.FAILED
                task.error = str(e)
                if progress_callback:
                    progress_callback(task)

    def pause(self, task: DownloadTask):
        task.status = DownloadStatus.PAUSED
        task._pause_event.clear()

    def resume(self, task: DownloadTask):
        task.status = DownloadStatus.DOWNLOADING
        task._pause_event.set()

    def cancel(self, task: DownloadTask):
        task._cancel = True
        task.status = DownloadStatus.CANCELLED
        task._pause_event.set()  # Unblock if paused

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def download_single(self, session, task, progress_callback=None):
        async with session.get(task.url) as resp:
            if resp.status != 200:
                raise Exception(f"Download failed with status {resp.status}")

            if task.total_size <= 0:
                task.total_size = int(resp.headers.get("Content-Length", 0))

            async with aiofiles.open(task.save_path, "wb") as f:
                async for data in resp.content.iter_chunked(1024 * 64):
                    if task._cancel:
                        return
                    await task._pause_event.wait()
                    await f.write(data)
                    task.downloaded += len(data)

                    now = time.time()
                    if now - task._last_time >= 0.5:
                        elapsed = now - task._last_time
                        diff = task.downloaded - task._last_downloaded
                        task.speed = diff / elapsed if elapsed > 0 else 0
                        if task.total_size > 0 and task.speed > 0:
                            task.eta = (task.total_size - task.downloaded) / task.speed
                        task._last_downloaded = task.downloaded
                        task._last_time = now
                        if progress_callback:
                            progress_callback(task)


