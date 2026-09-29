"""Reproducible Windows portable bundle; run with the project virtual environment."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build")]
    subprocess.run([*common, "--onedir", "--windowed", "--name", "IDMClone", "--collect-all", "customtkinter", "--collect-all", "yt_dlp", str(ROOT / "main.py")], cwd=ROOT, check=True)
    for name, source, mode in [("IDMNativeHost", "idm_native_host.py", "--console"), ("BrowserSetup", "setup_browser.py", "--windowed")]:
        subprocess.run([*common, "--onefile", mode, "--name", name, str(ROOT / "browser" / "native_host" / source)], cwd=ROOT, check=True)
        shutil.copy2(ROOT / "dist" / f"{name}.exe", ROOT / "dist" / "IDMClone")
    shutil.copytree(ROOT / "browser" / "extension", ROOT / "dist" / "IDMClone" / "extension", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.zip"))
    shutil.copy2(ROOT / "README.md", ROOT / "dist" / "IDMClone" / "README.md")
    shutil.make_archive(str(ROOT / "dist" / "IDMClone-Windows-x64"), "zip", ROOT / "dist", "IDMClone")
    print("Ready:", ROOT / "dist" / "IDMClone" / "IDMClone.exe")


if __name__ == "__main__":
    build()
