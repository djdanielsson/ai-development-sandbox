"""Boundary checks for the Mac RPC service, without starting native VMs."""

import base64
import dataclasses
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from host import Bridge, ThreadingHTTPServer, make_handler

MACHINE = "omni-test-1234abcd"


@dataclasses.dataclass
class Result:
    returncode: int = 0
    stdout: str = "ok"
    stderr: str = ""


class Launcher:
    def __init__(self):
        self.commands = []
        self.upload = None

    def prepare(self):
        pass

    def provision(self, name):
        return MACHINE

    def is_running(self, sandbox_id):
        return True

    def run(self, sandbox_id, command, check=False):
        self.commands.append(command)
        return Result()

    def put(self, sandbox_id, source, remote):
        self.upload = (source.read_bytes(), remote)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.launcher = Launcher()
        self.bridge = Bridge(self.launcher, Path(self.directory.name))
        self.bridge.dispatch({"operation": "provision", "name": "test"})

    def tearDown(self):
        self.directory.cleanup()

    def test_registry_survives_restart(self):
        restored = Bridge(self.launcher, Path(self.directory.name))
        self.assertTrue(restored.dispatch({"operation": "is_running", "sandbox_id": MACHINE}))

    def test_foreign_and_path_traversal_ids_never_reach_native_launcher(self):
        for sandbox_id in ["../outside", "/tmp/elsewhere", "omni-other-1234abcd"]:
            with self.subTest(sandbox_id=sandbox_id), self.assertRaises((ValueError, PermissionError)):
                self.bridge.dispatch({"operation": "run", "sandbox_id": sandbox_id, "command": "id"})
        self.assertEqual(self.launcher.commands, [])

    def test_upload_uses_supplied_bytes_not_a_caller_selected_host_path(self):
        self.bridge.dispatch({"operation": "put", "sandbox_id": MACHINE,
                              "remote_path": "/tmp/file", "content": base64.b64encode(b"payload").decode()})
        self.assertEqual(self.launcher.upload, (b"payload", "/tmp/file"))
        with self.assertRaises(KeyError):
            self.bridge.dispatch({"operation": "put", "sandbox_id": MACHINE,
                                  "remote_path": "/tmp/file", "local_path": "/etc/passwd"})

    def test_upload_rejects_guest_traversal(self):
        with self.assertRaises(ValueError):
            self.bridge.dispatch({"operation": "put", "sandbox_id": MACHINE,
                                  "remote_path": "/tmp/../etc/file", "content": ""})

    def test_authentication_and_browser_origin_rejected_before_dispatch(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.bridge, "secret-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/v1/rpc"
            for headers, status in [({}, 401), ({"Authorization": "Bearer wrong"}, 401),
                                    ({"Authorization": "Bearer secret-token", "Origin": "https://example.com"}, 404)]:
                with self.subTest(headers=headers), self.assertRaises(HTTPError) as error:
                    build_opener(ProxyHandler({})).open(Request(url, data=b'{"operation":"prepare"}', headers=headers))
                self.assertEqual(error.exception.code, status)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
