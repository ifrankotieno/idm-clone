"""Locate portable media tools without depending on the user's terminal PATH."""
from pathlib import Path
import shutil
import sys


def find_media_tool(name):
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).parent / "media-tools"
    else:
        directory = Path(__file__).resolve().parents[1] / ".tools" / "media-tools"
    executable = directory / (name + ".exe" if sys.platform == "win32" else name)
    if executable.is_file():
        return str(executable)
    return shutil.which(name)


def media_options():
    ffmpeg = find_media_tool("ffmpeg")
    options = {
        # YouTube commonly supplies separate video/audio streams, with no 'best'
        # (pre-combined) format at all. Keep a combined-format fallback for sites
        # that offer one, and let yt-dlp schedule the required merger.
        "format": "bestvideo*+bestaudio/best" if ffmpeg else "best",
        "js_runtimes": {},
    }
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
    for runtime in ("deno", "node"):
        executable = find_media_tool(runtime)
        if executable:
            options["js_runtimes"] = {runtime: {"path": executable}}
            break
    return options


def explain_media_error(error, options, warnings):
    message = str(error)
    if "Requested format is not available" in message:
        if not options.get("ffmpeg_location"):
            return ("This video has separate audio and video streams. FFmpeg is missing. "
                    "Use the complete updated IDM Clone folder, including media-tools.")
        if not options.get("js_runtimes"):
            return ("YouTube extraction needs the bundled JavaScript runtime. "
                    "Restore the media-tools folder from the updated app package.")
        if any("challenge" in warning.lower() or "ejs" in warning.lower() for warning in warnings):
            return ("YouTube's JavaScript extraction failed. Update the app's yt-dlp "
                    "and yt-dlp-ejs components together and keep media-tools beside the app.")
        return ("No downloadable audio/video format was returned for this video. "
                "The video may be restricted, or the YouTube extractor may need an update.")
    return message
