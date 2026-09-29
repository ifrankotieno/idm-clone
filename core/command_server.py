import asyncio
import json
from typing import Callable, Optional

HOST = "127.0.0.1"
PORT = 56789

class CommandServer:
    def __init__(self, on_download: Callable[[str], None]):
        self.on_download = on_download
        self._server: Optional[asyncio.AbstractServer] = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.readline()
            if not data:
                return

            message = json.loads(data.decode("utf-8").strip())
            if message.get("action") == "download" and message.get("url"):
                self.on_download(message["url"])
                response = {"status": "ok"}
            else:
                response = {"status": "error", "message": "Invalid request"}

            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
        except Exception as e:
            try:
                writer.write((json.dumps({"status": "error", "message": str(e)}) + "\n").encode("utf-8"))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        self._server = await asyncio.start_server(self.handle_client, HOST, PORT)
        print(f"Command server listening on {HOST}:{PORT}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()