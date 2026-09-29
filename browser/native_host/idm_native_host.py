"""Native messaging bridge. Built as a console executable for binary stdio."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

HOST, PORT = "127.0.0.1", 56789


def send_message(message):
    data = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def read_exact(stream, length):
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            raise EOFError("Incomplete native message")
        data.extend(chunk)
    return bytes(data)


def read_message():
    header = sys.stdin.buffer.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Invalid native message header")
    length = struct.unpack("<I", header)[0]
    if length > 65536:
        raise ValueError("Message is too large")
    return json.loads(read_exact(sys.stdin.buffer, length))


def exchange(message):
    with socket.create_connection((HOST, PORT), timeout=3) as connection:
        connection.sendall((json.dumps(message) + "\n").encode())
        with connection.makefile("rb") as stream:
            reply = stream.readline(65536)
        if not reply:
            raise OSError("The app closed before acknowledging the request")
        return json.loads(reply)


def start_app():
    if getattr(sys, "frozen", False):
        command = [str(Path(sys.executable).with_name("IDMClone.exe"))]
    else:
        python = Path(sys.executable).with_name("pythonw.exe")
        command = [str(python if python.exists() else sys.executable),
                   str(Path(__file__).resolve().parents[2] / "main.py")]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def forward_to_app(message):
    try:
        return exchange(message)
    except (ConnectionRefusedError, TimeoutError):
        start_app()
        for _ in range(80):
            time.sleep(0.25)
            try:
                return exchange(message)
            except (ConnectionRefusedError, TimeoutError):
                pass
        raise OSError("IDM Clone did not start within 20 seconds. Open IDMClone.exe and retry.")


def main():
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        message = read_message()
        if message is not None:
            send_message(forward_to_app(message))
    except Exception as exc:
        send_message({"status": "error", "message": str(exc)})


if __name__ == "__main__":
    main()
