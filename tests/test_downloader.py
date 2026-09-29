import asyncio
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web

from core.downloader import DownloadTask, DownloadStatus, MultiConnectionDownloader, safe_filename
from core.command_server import CommandServer

DATA = bytes(range(256)) * 2048


class DownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.downloader = MultiConnectionDownloader()
        self.requests = []
        app = web.Application()
        app.router.add_get('/{name}', self.serve)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        self.base = f'http://127.0.0.1:{self.site._server.sockets[0].getsockname()[1]}'

    async def asyncTearDown(self):
        await self.downloader.close()
        await self.runner.cleanup()
        self.temp.cleanup()

    async def serve(self, request):
        name = request.match_info['name']
        self.requests.append((name, request.headers.get('Range')))
        if name == 'missing':
            raise web.HTTPNotFound()
        if name == 'redirect':
            raise web.HTTPFound('/file')
        if name == 'page':
            return web.Response(text='<html><body>Not a file</body></html>', content_type='text/html')
        if name == 'video-page':
            return web.Response(text=f'<html><title>Fixture video</title><video controls src="{self.base}/fixture.mp4"></video></html>', content_type='text/html')
        if name == 'headers' and request.headers.get('Referer') != self.base + '/page':
            raise web.HTTPForbidden()
        data = b'abc' if name == 'tiny' else b'' if name == 'empty' else b'<html>not a video</html>' if name == 'disguised' else DATA
        if name == 'stream':
            response = web.StreamResponse(headers={'Content-Type': 'application/octet-stream'})
            await response.prepare(request)
            try:
                for offset in range(0, len(data), 8192):
                    await response.write(data[offset:offset + 8192])
                    await asyncio.sleep(0.005)
                await response.write_eof()
            except (ConnectionResetError, OSError):
                pass
            return response
        headers = {'Content-Type': 'video/mp4' if name == 'fixture.mp4' else 'application/octet-stream',
                   'Content-Disposition': 'attachment; filename="test.bin"'}
        byte_range = request.headers.get('Range')
        if byte_range and name not in ('single', 'empty'):
            start, end = map(int, re.fullmatch(r'bytes=(\d+)-(\d+)', byte_range).groups())
            end = min(end, len(data) - 1)
            if name == 'lying' and start != 0:
                return web.Response(body=data, headers=headers)
            headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
            return web.Response(body=data[start:end + 1], status=206, headers=headers)
        return web.Response(body=data, headers=headers)

    def task(self, name, **kwargs):
        task = DownloadTask(f'{self.base}/{name}', str(self.directory / 'placeholder'), **kwargs)
        self.downloader.tasks[name] = task
        return task

    async def test_ranges_are_byte_exact(self):
        task = self.task('file')
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.COMPLETED, task.error)
        self.assertEqual(Path(task.save_path).read_bytes(), DATA)
        self.assertEqual(task.downloaded, len(DATA))

    async def test_single_redirect_tiny_empty_and_unknown_length(self):
        for name, data in [('single', DATA), ('redirect', DATA), ('tiny', b'abc'), ('empty', b''), ('stream', DATA)]:
            with self.subTest(name=name):
                task = self.task(name)
                await self.downloader.download(task)
                self.assertEqual(task.status, DownloadStatus.COMPLETED, task.error)
                self.assertEqual(Path(task.save_path).read_bytes(), data)

    async def test_existing_file_is_preserved(self):
        (self.directory / 'test.bin').write_bytes(b'keep')
        task = self.task('file')
        await self.downloader.download(task)
        self.assertEqual((self.directory / 'test.bin').read_bytes(), b'keep')
        self.assertEqual(Path(task.save_path).name, 'test (1).bin')

    async def test_invalid_ranges_fail_without_corrupt_output(self):
        task = self.task('lying')
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.FAILED)
        self.assertFalse(Path(task.save_path).exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_http_errors_do_not_create_files(self):
        task = self.task('missing')
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.FAILED)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_html_is_resolved_not_saved(self):
        task = self.task('page')
        with patch.object(self.downloader, '_download_media', side_effect=ValueError('No video found')) as resolver:
            await self.downloader.download(task)
            resolver.assert_called_once()
        self.assertEqual(task.status, DownloadStatus.FAILED)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_real_video_page_extraction(self):
        task = self.task('video-page')
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.COMPLETED, task.error)
        self.assertEqual(Path(task.save_path).suffix, '.mp4')
        self.assertEqual(Path(task.save_path).read_bytes(), DATA)

    async def test_mislabeled_html_is_not_saved_as_a_file(self):
        task = self.task('disguised')
        with patch.object(self.downloader, '_download_media', side_effect=ValueError('No video')) as resolver:
            await self.downloader.download(task)
            resolver.assert_called_once()
        self.assertEqual(task.status, DownloadStatus.FAILED)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_referrer_reaches_probe_and_chunks(self):
        task = self.task('headers', headers={'Referer': self.base + '/page'})
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.COMPLETED, task.error)

    async def test_pause_resume_does_not_start_a_second_download(self):
        task = self.task('stream')
        job = asyncio.create_task(self.downloader.download(task))
        async with asyncio.timeout(5):
            while task.downloaded == 0:
                if job.done():
                    self.fail(task.error)
                await asyncio.sleep(0.01)
        self.downloader.pause(task)
        await asyncio.sleep(0.05)
        paused = task.downloaded
        await asyncio.sleep(0.08)
        self.assertEqual(task.downloaded, paused)
        self.downloader.resume(task)
        await self.downloader.download(task)  # duplicate starts are ignored
        await job
        self.assertEqual(task.status, DownloadStatus.COMPLETED, task.error)
        self.assertEqual(Path(task.save_path).read_bytes(), DATA)
        self.assertEqual(sum(name == 'stream' for name, _ in self.requests), 2)

    async def test_cancel_while_paused_removes_partial(self):
        task = self.task('stream')
        job = asyncio.create_task(self.downloader.download(task))
        async with asyncio.timeout(5):
            while task.downloaded == 0:
                if job.done():
                    self.fail(task.error)
                await asyncio.sleep(0.01)
        self.downloader.pause(task)
        self.downloader.cancel(task)
        await asyncio.wait_for(job, 3)
        self.assertEqual(task.status, DownloadStatus.CANCELLED)
        self.assertEqual(list(self.directory.iterdir()), [])

    async def test_reject_non_http(self):
        task = DownloadTask('file:///etc/passwd', str(self.directory / 'bad'))
        await self.downloader.download(task)
        self.assertEqual(task.status, DownloadStatus.FAILED)

    def test_windows_names(self):
        self.assertEqual(safe_filename('CON'), '_CON')
        self.assertNotIn('/', safe_filename('../../bad.exe'))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledges_and_validates_messages(self):
        messages = []
        handler = CommandServer(messages.append)
        server = await asyncio.start_server(handler.handle_client, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            for url, status in [('https://example.com/file.zip', 'ok'), ('blob:123', 'error')]:
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                writer.write((json.dumps({'action': 'download', 'url': url}) + '\n').encode())
                await writer.drain()
                response = json.loads(await reader.readline())
                self.assertEqual(response['status'], status)
                writer.close()
                await writer.wait_closed()
            self.assertEqual(len(messages), 1)
        finally:
            server.close()
            await server.wait_closed()
