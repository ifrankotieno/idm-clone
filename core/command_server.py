import asyncio
import json
from core.downloader import validate_url

HOST = "127.0.0.1"
PORT = 56789


class CommandServer:
    def __init__(self, on_command):
        self.on_command = on_command
        self._server = None

    async def handle_client(self, reader, writer):
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=5)
            message = json.loads(data)
            action = message.get("action")
            if action == "download":
                validate_url(message.get("url", ""))
                headers = message.get("headers", {})
                if not isinstance(headers, dict):
                    raise ValueError("Invalid headers")
                message["headers"] = {key: value for key, value in headers.items()
                                      if key in ("Referer", "User-Agent") and isinstance(value, str)
                                      and "\r" not in value and "\n" not in value}
            elif action not in ("open", "ping"):
                raise ValueError("Unknown action")
            if action != "ping":
                self.on_command(message)
            response = {"status": "ok", "message": "Accepted by IDM Clone"}
        except Exception as exc:
            response = {"status": "error", "message": str(exc)}
        try:
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        self._server = await asyncio.start_server(self.handle_client, HOST, PORT)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
