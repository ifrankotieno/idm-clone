#!/usr/bin/env python3
import sys
import json
import struct
import socket

HOST = "127.0.0.1"
PORT = 56789

def send_message(message: dict):
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()

def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length or len(raw_length) < 4:
        return None
    length = struct.unpack("<I", raw_length)[0]
    data = sys.stdin.buffer.read(length)
    if not data:
        return None
    return json.loads(data.decode("utf-8"))

def forward_to_app(message: dict):
    try:
        with socket.create_connection((HOST, PORT), timeout=2) as s:
            s.sendall((json.dumps(message) + "\n").encode("utf-8"))
            return {"status": "ok", "message": "Download sent to IDM Clone"}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not reach IDM Clone. Start the app first. ({e})"
        }

def main():
    while True:
        message = read_message()
        if message is None:
            break

        if message.get("action") == "download" and message.get("url"):
            send_message(forward_to_app(message))
        else:
            send_message({"status": "error", "message": "Unknown action"})

if __name__ == "__main__":
    main()