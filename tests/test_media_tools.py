import asyncio
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from core.downloader import DownloadTask, MultiConnectionDownloader
from core.media_tools import media_options, find_media_tool, explain_media_error


class MediaConfigurationTests(unittest.TestCase):
    def test_bundled_tools_work_without_path(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'media-tools').mkdir()
            for tool in ('ffmpeg.exe', 'deno.exe'):
                (folder / 'media-tools' / tool).touch()
            with patch('core.media_tools.sys.frozen', True, create=True), patch('core.media_tools.sys.executable', str(folder / 'IDMClone.exe')), patch('core.media_tools.shutil.which', return_value=None):
                options = media_options()
            self.assertEqual(options['ffmpeg_location'], str(folder / 'media-tools/ffmpeg.exe'))
            self.assertEqual(options['js_runtimes']['deno']['path'], str(folder / 'media-tools/deno.exe'))
            self.assertEqual(options['format'], 'bestvideo*+bestaudio/best')

    def test_missing_merger_reports_actionable_error(self):
        message = explain_media_error('Requested format is not available', {}, [])
        self.assertIn('FFmpeg is missing', message)
        self.assertIn('media-tools', message)

    def test_split_only_formats_are_selected(self):
        with patch('core.media_tools.find_media_tool', side_effect=lambda name: f'C:/{name}.exe'):
            options = media_options()
        with YoutubeDL({'quiet': True}) as ydl:
            selector = ydl.build_format_selector(options['format'])
            selected = list(selector({'formats': [
                {'format_id': 'a', 'url': 'https://example/audio', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'aac', 'protocol': 'https'},
                {'format_id': 'v', 'url': 'https://example/video', 'ext': 'mp4', 'vcodec': 'h264', 'acodec': 'none', 'protocol': 'https'},
            ], 'has_merged_format': False, 'incomplete_formats': False}))
        self.assertEqual({f['format_id'] for f in selected[0]['requested_formats']}, {'v', 'a'})

    def test_youtube_403_retries_hls_once_in_a_fresh_directory(self):
        self.check_retry(always_fail=False)

    def test_youtube_403_retry_is_bounded(self):
        self.check_retry(always_fail=True)

    def check_retry(self, always_fail):
        calls = []
        class FakeYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, url, download=False):
                if len(calls) == 1 or always_fail:
                    raise DownloadError('HTTP Error 403: Forbidden')
                return {'id': 'fixture'}
            def process_info(self, info):
                (Path(self.options['outtmpl']).parent / 'output.mp4').write_bytes(b'merged')
        with tempfile.TemporaryDirectory() as directory:
            task = DownloadTask('https://youtube.com/watch?v=fixture', str(Path(directory) / 'pending'))
            with patch('yt_dlp.YoutubeDL', FakeYDL), patch('core.downloader.media_options', return_value={'format':'bestvideo*+bestaudio/best', 'ffmpeg_location':'ffmpeg.exe'}):
                if always_fail:
                    with self.assertRaisesRegex(ValueError, '403'):
                        MultiConnectionDownloader()._download_media(task, None)
                else:
                    MultiConnectionDownloader()._download_media(task, None)
                    self.assertEqual(Path(task.save_path).read_bytes(), b'merged')
            self.assertEqual(len(calls), 2)
            self.assertIn('m3u8', calls[1]['format'])
            self.assertNotEqual(calls[0]['outtmpl'], calls[1]['outtmpl'])
            self.assertFalse(list(Path(directory).glob('.idm-media-*')))


class SplitStreamIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_split_streams_are_merged_with_audio(self):
        ffmpeg, ffprobe = find_media_tool('ffmpeg'), find_media_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            self.skipTest('Run scripts/prepare_media_tools.py for the split-stream integration test')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=10', '-t', '0.5', '-an', '-c:v', 'mpeg4', str(root / 'video.mp4')], check=True, capture_output=True)
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '0.5', '-vn', '-c:a', 'aac', str(root / 'audio.m4a')], check=True, capture_output=True)
            app = web.Application()
            async def serve(request):
                return web.FileResponse(root / request.match_info['name'])
            app.router.add_get('/{name}', serve)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
            info = {'id':'split-fixture', 'title':'Split fixture', 'formats':[
                {'format_id':'audio','url':base + '/audio.m4a','ext':'m4a','vcodec':'none','acodec':'aac'},
                {'format_id':'video','url':base + '/video.mp4','ext':'mp4','vcodec':'mpeg4','acodec':'none','height':360},
            ]}
            def extract(ydl, url, download=False):
                return ydl.process_ie_result(copy.deepcopy(info), download=download)
            task = DownloadTask(base + '/page', str(root / 'output/pending'))
            try:
                with patch.object(YoutubeDL, 'extract_info', extract):
                    await asyncio.to_thread(MultiConnectionDownloader(format_picker=lambda task, title, choices: choices[0])._download_media, task, None)
                self.assertEqual(task.video_choice.extension, 'mp4')
                self.assertEqual(task.video_choice.height, 360)
                result = subprocess.run([ffprobe, '-v','error','-show_entries','stream=codec_type,height','-of','json', task.save_path], capture_output=True, text=True, check=True)
                streams = json.loads(result.stdout)['streams']
                self.assertEqual({stream['codec_type'] for stream in streams}, {'video','audio'})
                self.assertEqual(next(s['height'] for s in streams if s['codec_type'] == 'video'), 360)
                self.assertEqual(Path(task.save_path).suffix, '.mp4')
                self.assertEqual(len(list((root / 'output').iterdir())), 1)
            finally:
                await runner.cleanup()
