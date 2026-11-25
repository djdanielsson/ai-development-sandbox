"""Local authenticated RPC for the upstream provider. Run on macOS only."""

import argparse
import base64
import dataclasses
import hmac
import json
import os
import re
import tempfile
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

from relay import (
    GUEST_SOCKET,
    MAAS_HOST,
    MAAS_SOCKET,
    RHAI_MAAS_HOST,
    RHAI_MAAS_SOCKET,
    SERVER_ADDRESS,
    host_relay,
)

MAX_BODY = 12 * 1024 * 1024
MACHINE_ID = re.compile(r"omni-[A-Za-z0-9_.-]{1,48}-[a-f0-9]{8}\Z")


class Bridge:
    def __init__(self, launcher, root):
        self.launcher = launcher
        self.root = root
        self.lock = threading.RLock()
        self.registry_path = root / "machines.json"
        self.machines = set(json.loads(self.registry_path.read_text())) if self.registry_path.exists() else set()

    def save(self):
        path = self.registry_path.with_suffix(".tmp")
        path.write_text(json.dumps(sorted(self.machines)) + "\n")
        path.chmod(0o600)
        path.replace(self.registry_path)

    def dispatch(self, request):
        operation = request["operation"]
        if operation == "prepare":
            self.launcher.prepare()
            return {"provider": "smolvm", "protocol": 1}
        if operation == "list":
            # Do not enumerate or adopt machines created outside this bridge.
            with self.lock:
                machines = []
                for sandbox_id in sorted(self.machines):
                    machine = self.launcher._machine(sandbox_id)
                    if machine is not None:
                        machines.append({"sandbox_id": sandbox_id, "state": machine.get("state"),
                                         "created_at": machine.get("created_at"),
                                         "session_name": machine.get("labels", {}).get("omnigent.session-name")})
                return machines
        if operation == "provision":
            name = request["name"]
            if not isinstance(name, str) or not 1 <= len(name) <= 256:
                raise ValueError("invalid session name")
            with self.lock:
                sandbox_id = self.launcher.provision(name)
                self.machines.add(sandbox_id)
                self.save()
            return sandbox_id
        sandbox_id = request["sandbox_id"]
        if not isinstance(sandbox_id, str) or not MACHINE_ID.fullmatch(sandbox_id):
            raise ValueError("invalid machine identity")
        with self.lock:
            if sandbox_id not in self.machines:
                raise PermissionError("unknown machine")
        if operation == "run":
            command = request["command"]
            if not isinstance(command, str) or len(command) > MAX_BODY // 2:
                raise ValueError("invalid command")
            # Check labels as well as our persistent registry for every exec.
            if not self.launcher.is_running(sandbox_id):
                raise ValueError("machine is stopped")
            return dataclasses.asdict(self.launcher.run(sandbox_id, command, check=False))
        if operation == "put":
            remote = request["remote_path"]
            if not isinstance(remote, str) or not remote.startswith("/") or ".." in PurePosixPath(remote).parts or any(c in remote for c in "\x00\r\n"):
                raise ValueError("invalid guest path")
            if not self.launcher.is_running(sandbox_id):
                raise ValueError("machine is stopped")
            data = base64.b64decode(request["content"], validate=True)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("upload too large")
            with tempfile.TemporaryDirectory(prefix="omnigent-upload-") as directory:
                source = Path(directory) / "upload"
                source.write_bytes(data)
                self.launcher.put(sandbox_id, source, remote)
            return None
        if operation == "is_running":
            return self.launcher.is_running(sandbox_id)
        if operation == "resume":
            with self.lock:
                self.launcher.resume(sandbox_id)
            return None
        if operation == "delete_stopped":
            # Serialize against bridge resume/provision calls and reject running
            # VMs even if the caller's earlier maintenance scan saw them stopped.
            with self.lock:
                machine = self.launcher._machine(sandbox_id)
                if machine is None:
                    return None
                if machine.get("state") != "stopped":
                    raise ValueError("refusing to delete a VM that is not stopped")
                result = self.launcher._smolvm("machine", "delete", "-f", "--name", sandbox_id,
                                               sandbox_id=sandbox_id, timeout=120)
                if result.returncode:
                    raise RuntimeError("could not delete stopped machine")
            return None
        if operation == "stop":
            machine = self.launcher._machine(sandbox_id)
            if machine is not None and machine.get("state") == "running":
                result = self.launcher._smolvm("machine", "stop", "--name", sandbox_id,
                                               sandbox_id=sandbox_id, timeout=120)
                if result.returncode:
                    raise RuntimeError("could not stop machine")
            return None
        if operation == "terminate":
            # Keep the registry entry so repeated cleanup remains idempotent.
            self.launcher.terminate(sandbox_id)
            return None
        raise ValueError("unsupported operation")


def make_handler(bridge, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log request bodies, headers, commands or credentials.

        def do_POST(self):
            if self.path != "/v1/rpc" or self.headers.get("Origin"):
                self.send_error(404)
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self.send_error(413)
                    return
                self.connection.settimeout(30)
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError("truncated request")
                result = {"result": bridge.dispatch(json.loads(payload))}
            except Exception as exc:
                # Native error output can contain credentials. Keep details local
                # and structural, without echoing the command or native stderr.
                kind = type(exc).__name__
                print(f"Bridge operation failed ({kind})", flush=True)
                result = {"error": "gone" if kind == "SandboxGoneError" else "failed",
                          "message": f"smolvm bridge operation failed ({kind}); check the Mac bridge log"}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ["SMOLVM_USAGE"] = "0"
    from omnigent.community.sandbox.smolvm.config import SmolvmConfig
    from omnigent.community.sandbox.smolvm.launcher import SmolvmSandboxLauncher

    class BoundedLauncher(SmolvmSandboxLauncher):
        def _create_args(self, *args, **kwargs):
            return [
                *super()._create_args(*args, **kwargs),
                "--mount-socket", f"{relay_socket}:{GUEST_SOCKET}",
                "--mount-socket", f"{maas_socket}:{MAAS_SOCKET}",
                "--mount-socket", f"{rhai_maas_socket}:{RHAI_MAAS_SOCKET}",
            ]

        def _start_relay(self, sandbox_id):
            guest_script = "/tmp/omnigent-server-relay.py"
            self.put(sandbox_id, Path(__file__).with_name("relay.py"), guest_script)
            result = self._smolvm(
                "machine", "exec", "--name", sandbox_id, "--detach", "--",
                "python3", guest_script, sandbox_id=sandbox_id,
            )
            if result.returncode:
                raise self._failed("smolvm could not start the Omnigent relay", result)
            self.run(
                sandbox_id,
                "curl -fsS --noproxy '*' --retry 5 --retry-connrefused --max-time 2 "
                "http://127.0.0.1:8000/health",
            )

        def provision(self, name):
            sandbox_id = super().provision(name)
            try:
                self._start_relay(sandbox_id)
            except Exception:
                self.terminate(sandbox_id)
                raise
            return sandbox_id

        def resume(self, sandbox_id):
            was_running = self.is_running(sandbox_id)
            super().resume(sandbox_id)
            if not was_running:
                socket_available = self.run(sandbox_id, f"test -S {GUEST_SOCKET}", check=False)
                if socket_available.returncode == 0:
                    self._start_relay(sandbox_id)

        def _smolvm(self, *args, **kwargs):
            if kwargs.get("timeout", 60) is None:
                kwargs["timeout"] = 600
            return super()._smolvm(*args, **kwargs)

    config = SmolvmConfig.model_validate_json((args.root / "profile.json").read_text())
    relay_socket = args.root / "server.sock"
    maas_socket = args.root / "maas.sock"
    rhai_maas_socket = args.root / "rhai-maas.sock"
    launcher = BoundedLauncher(config=config)
    launcher.prepare()
    token = (args.root / "client/token").read_text().strip()
    if len(token) < 40:
        raise ValueError("bridge token is missing or too short")
    bridge = Bridge(launcher, args.root)
    with ExitStack() as stack:
        server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(bridge, token)))
        for path, upstream in (
            (relay_socket, SERVER_ADDRESS),
            (maas_socket, (MAAS_HOST, 443)),
            (rhai_maas_socket, (RHAI_MAAS_HOST, 443)),
        ):
            path.unlink(missing_ok=True)
            relay = stack.enter_context(host_relay(path, upstream))
            threading.Thread(target=relay.serve_forever, daemon=True).start()
        print(f"smolvm bridge listening on 127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
