"""Register the bundled native host for the user's Edge/Chrome extension."""
import json
from pathlib import Path
import re
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog
import winreg


def register(extension_id, directory):
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise ValueError("Copy the 32-letter extension ID from edge://extensions.")
    host = directory / "IDMNativeHost.exe"
    if not host.exists():
        raise ValueError("Keep BrowserSetup.exe beside IDMNativeHost.exe and IDMClone.exe.")
    manifest = directory / "com.idmclone.host.json"
    origins = set()
    if manifest.exists():
        origins.update(json.loads(manifest.read_text()).get("allowed_origins", []))
    origins.add(f"chrome-extension://{extension_id}/")
    manifest.write_text(json.dumps({"name": "com.idmclone.host", "description": "IDM Clone browser bridge",
                                   "path": str(host), "type": "stdio", "allowed_origins": sorted(origins)}, indent=2))
    for browser in (r"Microsoft\Edge", r"Google\Chrome"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\{browser}\NativeMessagingHosts\com.idmclone.host") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))


def main():
    root = tk.Tk()
    root.withdraw()
    extension_id = simpledialog.askstring("IDM Clone — Browser Setup",
        "In Edge, open edge://extensions, enable Developer mode, and load the extension folder.\n\nPaste the extension ID shown there:")
    if extension_id:
        try:
            directory = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "dist" / "IDMClone"
            register(extension_id.strip(), directory)
            messagebox.showinfo("Ready", "Browser integration registered for Edge and Chrome.\nReload the extension and your video tabs.")
        except Exception as exc:
            messagebox.showerror("Setup failed", str(exc))
    root.destroy()


if __name__ == "__main__":
    main()
