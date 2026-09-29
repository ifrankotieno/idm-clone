"""Available video choices and selectors that preserve the user's choice."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoChoice:
    extension: str
    height: int

    @property
    def label(self):
        return f"{self.extension.upper()} / {self.height}p"


def available_choices(info, can_merge=True):
    formats = info.get("formats") or [info]
    audio_extensions = {f.get("ext") for f in formats
                        if f.get("acodec") not in (None, "none") and f.get("vcodec") == "none"
                        and not f.get("has_drm")}
    choices = set()
    for item in formats:
        ext, height = item.get("ext"), item.get("height")
        if (ext not in ("mp4", "webm", "mkv") or not height
                or item.get("vcodec") in (None, "none") or item.get("has_drm")):
            continue
        combined = item.get("acodec") not in (None, "none")
        compatible_audio = (ext == "mp4" and bool(audio_extensions & {"m4a", "mp4"})
                            or ext == "webm" and "webm" in audio_extensions
                            or ext == "mkv" and bool(audio_extensions))
        if combined or (can_merge and compatible_audio):
            choices.add(VideoChoice(ext, int(height)))
    return sorted(choices, key=lambda c: (c.extension != "mp4", c.extension, -c.height))


def choice_options(choice, hls=False):
    if choice.extension not in ("mp4", "webm", "mkv") or choice.height <= 0:
        raise ValueError("Invalid video format selection")
    protocol = "[protocol^=m3u8]" if hls else ""
    video = f"[ext={choice.extension}][height={choice.height}]{protocol}"
    audio = {"mp4": "[ext=m4a]/bestaudio[ext=mp4]", "webm": "[ext=webm]", "mkv": ""}[choice.extension]
    # Parentheses keep the MP4 audio fallback inside the merge expression.
    audio_selector = (f"(bestaudio[ext=m4a]{protocol}/bestaudio[ext=mp4]{protocol})"
                      if choice.extension == "mp4" else f"bestaudio{audio}{protocol}")
    return {"format": f"bestvideo{video}+{audio_selector}/best{video}",
            "merge_output_format": choice.extension}
