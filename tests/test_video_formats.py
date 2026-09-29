import unittest
from yt_dlp import YoutubeDL
from core.video_formats import VideoChoice, available_choices, choice_options


def video(ext, height, audio='none', protocol='https'):
    return dict(format_id=f'{ext}-{height}-{protocol}', ext=ext, height=height,
                vcodec='h264' if ext == 'mp4' else 'vp9', acodec=audio,
                url='https://example.com/video', protocol=protocol)


def audio(ext):
    return dict(format_id=ext, ext=ext, vcodec='none', acodec='aac',
                url='https://example.com/audio', protocol='https')


class FormatTests(unittest.TestCase):
    def test_lists_only_available_types_and_heights(self):
        formats = [audio('m4a'), audio('webm'), video('mp4',360), video('mp4',1080),
                   video('mp4',360), video('webm',480), dict(video('mp4',720),has_drm=True)]
        self.assertEqual(available_choices({'formats':formats}),
                         [VideoChoice('mp4',1080), VideoChoice('mp4',360), VideoChoice('webm',480)])

    def test_excludes_silent_formats_without_compatible_audio(self):
        self.assertEqual(available_choices({'formats':[video('mp4',1080),audio('webm')]}), [])
        self.assertEqual(available_choices({'formats':[video('mp4',1080),video('mp4',360,'aac')]}),[VideoChoice('mp4',360)])

    def test_without_merger_only_combined_formats_are_listed(self):
        self.assertEqual(available_choices({'formats':[video('mp4',1080),audio('m4a'),video('mp4',360,'aac')]},False),[VideoChoice('mp4',360)])

    def test_selector_preserves_exact_type_height_and_audio(self):
        for ext,height in [('mp4',360),('mp4',1080),('webm',480)]:
            formats = [audio('m4a'),audio('webm'),video('mp4',360),video('webm',480),video('mp4',1080)]
            with YoutubeDL({'quiet':True}) as ydl:
                selected = list(ydl.build_format_selector(choice_options(VideoChoice(ext,height))['format'])(
                    {'formats':formats,'has_merged_format':False,'incomplete_formats':False}))
            streams = selected[0]['requested_formats']
            self.assertEqual(streams[0]['ext'],ext)
            self.assertEqual(streams[0]['height'],height)
            self.assertNotEqual(streams[1]['acodec'],'none')

    def test_unavailable_quality_does_not_silently_change(self):
        with YoutubeDL({'quiet':True}) as ydl:
            selected = list(ydl.build_format_selector(choice_options(VideoChoice('mp4',480))['format'])(
                {'formats':[audio('m4a'),video('mp4',1080)],'has_merged_format':False,'incomplete_formats':False}))
        self.assertEqual(selected,[])

    def test_hls_retry_preserves_choice(self):
        options = choice_options(VideoChoice('mp4',360),hls=True)
        with YoutubeDL({'quiet':True}) as ydl:
            selected = list(ydl.build_format_selector(options['format'])(
                {'formats':[dict(audio('mp4'),protocol='m3u8_native'),video('mp4',360,protocol='m3u8_native'),video('mp4',1080,protocol='m3u8_native')], 'has_merged_format':False,'incomplete_formats':False}))
        self.assertEqual(selected[0]['requested_formats'][0]['height'],360)

    def test_picker_type_switch_download_and_cancel(self):
        import customtkinter as ctk
        from gui.video_picker import VideoPicker
        root = ctk.CTk()
        root.withdraw()
        chosen = []
        try:
            picker = VideoPicker(root,'Test video',[VideoChoice('mp4',1080),VideoChoice('mp4',360),VideoChoice('webm',480)],chosen.append)
            root.update()
            picker.extension.set('WEBM')
            picker.update_resolutions('WEBM')
            self.assertEqual(picker.resolution.get(),'480p')
            picker.download()
            self.assertEqual(chosen,[VideoChoice('webm',480)])
            picker = VideoPicker(root,'Cancel test',[VideoChoice('mp4',360)],chosen.append)
            picker.finish(None)
            self.assertIsNone(chosen[-1])
        finally:
            root.destroy()
