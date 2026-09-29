import io
import json
from pathlib import Path
import socket
import struct
import subprocess
import threading
import unittest
from unittest.mock import patch
from browser.native_host import idm_native_host as host


class NativeHostTests(unittest.TestCase):
    def test_truncated_message_is_rejected(self):
        with self.assertRaises(EOFError):
            host.read_exact(io.BytesIO(b'ab'), 4)

    def test_oversized_message_is_rejected(self):
        with patch.object(host.sys, 'stdin') as stdin:
            stdin.buffer = io.BytesIO(struct.pack('<I', 1000000))
            with self.assertRaises(ValueError):
                host.read_message()

    def test_frozen_bridge_forwards_app_acknowledgement(self):
        executable = Path(__file__).resolve().parents[1] / 'dist' / 'IDMClone' / 'IDMNativeHost.exe'
        if not executable.exists():
            self.skipTest('Build the Windows bundle to verify the compiled native bridge')
        server = socket.socket()
        try:
            server.bind(('127.0.0.1', 56789))
        except OSError:
            server.close()
            self.skipTest('Desktop app already owns the test bridge port')
        server.listen(1)
        server.settimeout(15)
        received = []
        def respond():
            with server:
                connection, _ = server.accept()
                with connection, connection.makefile('rb') as stream:
                    received.append(json.loads(stream.readline()))
                    connection.sendall(b'{"status":"error","message":"test acknowledgement"}\n')
        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        data = json.dumps({'action':'ping'}).encode()
        result = subprocess.run([str(executable)], input=struct.pack('<I', len(data)) + data, capture_output=True, timeout=20)
        thread.join(timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        size = struct.unpack('<I', result.stdout[:4])[0]
        reply = json.loads(result.stdout[4:4 + size])
        self.assertEqual(reply, {'status':'error', 'message':'test acknowledgement'})
        self.assertEqual(received, [{'action':'ping'}])
