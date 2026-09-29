# IDM Clone

Python desktop download manager with a Microsoft Edge / Chrome extension.

## Run the Windows app (no terminal)

Extract **IDMClone-Windows-x64.zip** and double-click **IDMClone/IDMClone.exe**.
Keep the entire folder together, including `_internal`, `IDMNativeHost.exe`, and
`BrowserSetup.exe`. Python is included in the bundle and is not required on the
computer running it. Move the folder to its permanent location before browser setup.

## Connect Microsoft Edge

1. Open `edge://extensions` and enable Developer mode.
2. Choose **Load unpacked** and select this project's `browser/extension` folder
   (or the extracted bundle's `extension` folder).
3. Copy the extension's 32-letter ID.
4. Double-click **BrowserSetup.exe**, paste the ID, and confirm. This registers the
   native bridge for the current Windows user, without administrator access.
5. Reload the extension and refresh your video tabs. Play a video, then click
   **Download this video** over its top-left corner.

If updating an already loaded extension, reload its existing card instead of loading
another copy. Register that card's ID. Moving the app folder requires rerunning setup.
The same setup works for Chrome using `chrome://extensions`.

The extension popup can open the app, resolve a video from the current page, or show
media URLs detected during playback. For `blob:` players, choose a detected source
or **Resolve video from this page**. Multiple sources can belong to ads or different
players; choose the appropriate one. Right-click file links for **Download with IDM Clone**.

To hand off ordinary browser downloads, enable **Send browser downloads to IDM Clone**
in the extension popup. It is off by default. The browser keeps its download if the
native bridge cannot accept it. Acceptance means queued in the app; later HTTP or
extraction failures are shown in the desktop list. Disable capture for downloads
requiring browser-only cookies, POST requests, or browser-generated `blob:` data.

## What is supported

- HTTP(S) file URLs, redirects, server filenames, byte ranges, and unknown lengths.
- Download buttons on ordinary HTML video elements, including dynamically added
  players and frames; network media discovery for streaming players.
- Supported video-page URLs and HLS/DASH manifests via yt-dlp, instead of saving HTML.
- Pause/resume in the current session, cancellation, unique filenames, and progress.
- Automatic app launch when the extension sends a download.

Protected/DRM videos, live recordings, playlists, and automatic browser-cookie
transfer are not supported. Some sites need authentication, an external JavaScript
runtime, or extractor updates. FFmpeg, if available on PATH, enables separate audio
and video merging; without it, the app requests a combined format. FFmpeg is not
bundled. Not every streaming format or website has a combined downloadable format.
Native fullscreen video and closed shadow-DOM players may hide the overlay; use the
extension popup. Pause state does not survive app shutdown. Cancelled/failed partial
files are removed; completed files are never overwritten.

## Development

Requires Windows and Python 3.11 or newer.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe main.py
```

Run tests:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/extension.test.cjs
```

Build the portable bundle:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe scripts/build_windows.py
```

Output: `dist/IDMClone/IDMClone.exe` and `dist/IDMClone-Windows-x64.zip`.
Build products, browser registration paths, virtual environments, and local settings
are excluded from Git. The build is unsigned.

Architecture: Edge extension -> native messaging executable -> local TCP command
server (`127.0.0.1:56789`) -> Tk event queue -> async downloader / yt-dlp worker.
Only HTTP(S) download URLs are accepted. The native host waits for acknowledgement;
Tk widgets are updated only on the main UI thread. Cookies are not collected.

## References

- [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [Edge native messaging](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/native-messaging)
- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp#readme)
