"""Fetch checksum-pinned Windows media dependencies from their upstream releases."""
import hashlib
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "ffmpeg": (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-29-13-10/ffmpeg-N-126965-gd85cdd2597-win64-lgpl-shared.zip",
        "8151d57bc4fe66ca669eb54a5b468afef8f126d622372c866610ec665e38974c",
    ),
    "deno": (
        "https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-pc-windows-msvc.zip",
        "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238",
    ),
}


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare():
    cache = ROOT / ".tools" / "downloads"
    destination = ROOT / ".tools" / "media-tools"
    cache.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in PACKAGES.items():
        archive = cache / f"{name}.zip"
        if not archive.exists() or checksum(archive) != digest:
            print(f"Downloading {name}...", flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError(f"Checksum mismatch: {name}")
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                basename = Path(item.filename).name
                if (name == "deno" and basename == "deno.exe") or (name == "ffmpeg" and "/bin/" in item.filename and (basename in ("ffmpeg.exe", "ffprobe.exe") or basename.endswith(".dll"))):
                    with package.open(item) as source, (destination / basename).open("wb") as output:
                        shutil.copyfileobj(source, output)
                elif name == "ffmpeg" and basename == "LICENSE.txt":
                    (destination / "FFmpeg-LICENSE.txt").write_bytes(package.read(item))
    license_url = "https://raw.githubusercontent.com/denoland/deno/v2.9.7/LICENSE.md"
    with urllib.request.urlopen(license_url, timeout=30) as response:
        (destination / "Deno-LICENSE.txt").write_bytes(response.read())
    (destination / "THIRD-PARTY.txt").write_text(
        "FFmpeg shared LGPL build (unmodified): BtbN/FFmpeg-Builds, autobuild-2026-09-29-13-10.\n"
        "Build scripts: https://github.com/BtbN/FFmpeg-Builds/tree/autobuild-2026-09-29-13-10\n"
        "FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/d85cdd2597\n"
        "Linked dependency sources and build configuration are in the build scripts above.\n"
        "Deno v2.9.7 (MIT): https://github.com/denoland/deno/tree/v2.9.7\n"
        "See the accompanying license files. These are separate, unmodified executables.\n"
        + "\n".join(f"{name}: {url}\nSHA256: {digest}" for name, (url, digest) in PACKAGES.items()),
        encoding="utf-8",
    )
    print("Media dependencies ready:", destination)


if __name__ == "__main__":
    prepare()
