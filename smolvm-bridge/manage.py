"""Set up and supervise the Mac bridge without a system-wide Python install."""

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / ".smolvm-bridge"
PYTHON = ROOT / "venv/bin/python"
PROVIDER = "git+https://github.com/cidrblock/omnigent-smolvm-provider@65a85dcc857c32fc52b61dcfafb7a51764d137ec"


def rpc(operation, **arguments):
    token = (ROOT / "client/token").read_text().strip()
    request = Request("http://127.0.0.1:8877/v1/rpc",
                      data=json.dumps({"operation": operation, **arguments}).encode(),
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(request, timeout=900) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(payload.get("message", "bridge error"))
    return payload["result"]


def setup():
    if sys.platform != "darwin":
        raise SystemExit("Run the bridge on the Mac, not in the Podman VM.")
    if not shutil.which("smolvm"):
        raise SystemExit("Install smolvm first: brew install smol-machines/tap/smolvm")
    ROOT.mkdir(mode=0o700, exist_ok=True)
    ROOT.chmod(0o700)
    (ROOT / "client").mkdir(mode=0o700, exist_ok=True)
    if not PYTHON.exists():
        subprocess.run(["uv", "venv", "--python", "3.13", str(ROOT / "venv")], check=True)
    subprocess.run(["uv", "pip", "install", "--python", str(PYTHON), PROVIDER], check=True)
    token = ROOT / "client/token"
    if not token.exists():
        token.write_text(secrets.token_urlsafe(48) + "\n")
    token.chmod(0o600)
    refresh_auth()
    if not (ROOT / "profile.json").exists():
        profile = {
            "image": str(ROOT / "runner-image.tar"),
            "binary": shutil.which("smolvm"),
            "cpus": 4, "memory_mib": 8192,
            "net_backend": "virtio-net", "block_private": True,
            "allow_private": ["100.96.0.0/30"],
            "environment": {"DO_NOT_TRACK": "1", "SMOLVM_USAGE": "0"},
            "mounts": [{"source": str(ROOT / "auth-root"), "target": "/mnt/omnigent-auth", "mode": "ro"}],
            "init": ["mkdir -p /root/.codex /root/.local/share/opencode; cp -R /mnt/omnigent-auth/. /root/; chown -R root:root /root/.codex /root/.local/share/opencode"],
            "dynamic_port_range": [30000, 40000], "dynamic_port_count": 10,
            "startup_timeout_s": 300,
        }
        (ROOT / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    print(f"Bridge configured in {ROOT}")


def refresh_auth():
    # Stage only auth files, never expose the user's whole home to a guest.
    auth_root = ROOT / "auth-root"
    auth_root.mkdir(mode=0o700, exist_ok=True)
    source = Path.home() / ".codex/auth.json"
    target = auth_root / ".codex/auth.json"
    if source.is_file():
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
    result = subprocess.run(["podman", "exec", "omnigent-host", "cat", "/root/.local/share/opencode/auth.json"],
                            capture_output=True, check=False)
    if result.returncode == 0:
        target = auth_root / ".local/share/opencode/auth.json"
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(result.stdout)
        target.chmod(0o600)


def start():
    if not (ROOT / "profile.json").is_file():
        raise SystemExit("Run sh scripts/omnigent-smolvm-bridge.sh setup first.")
    image_id = subprocess.check_output(["podman", "image", "inspect", "omnigent-local", "--format", "{{.Id}}"], text=True).strip()
    recorded = ROOT / "runner-image.id"
    if not recorded.exists() or recorded.read_text().strip() != image_id or not (ROOT / "runner-image.tar").is_file():
        export_image()
    refresh_auth()
    try:
        rpc("prepare")
        print("smolvm bridge is already running.")
        return
    except Exception:
        pass
    if not (ROOT / "runner-image.tar").is_file():
        raise SystemExit("Run sh scripts/omnigent-smolvm-bridge.sh export-image first.")
    environment = dict(os.environ, SMOLVM_USAGE="0", DO_NOT_TRACK="1")
    environment["PATH"] = "/opt/homebrew/bin:/opt/homebrew/opt/e2fsprogs/sbin:" + environment.get("PATH", "")
    with (ROOT / "bridge.log").open("ab") as log:
        process = subprocess.Popen([str(PYTHON), str(REPO / "smolvm-bridge/host.py"), "--root", str(ROOT)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True, env=environment)
    (ROOT / "bridge.pid").write_text(str(process.pid) + "\n")
    for _ in range(40):
        if process.poll() is not None:
            raise SystemExit(f"Bridge exited; inspect {ROOT / 'bridge.log'}")
        try:
            rpc("prepare")
            print("smolvm bridge is ready on Mac loopback port 8877.")
            return
        except Exception:
            time.sleep(0.25)
    raise SystemExit(f"Bridge did not become ready; inspect {ROOT / 'bridge.log'}")


def export_image():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    image_id = subprocess.check_output(["podman", "image", "inspect", "omnigent-local", "--format", "{{.Id}}"], text=True).strip()
    temporary = ROOT / "runner-image.next.tar"
    subprocess.run(["podman", "save", "--format", "docker-archive", "-o", str(temporary), image_id], check=True)
    temporary.replace(ROOT / "runner-image.tar")
    (ROOT / "runner-image.id").write_text(image_id + "\n")
    print("Runner image exported; new VMs will use it.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "start", "stop", "status", "export-image"])
    args = parser.parse_args()
    if args.action == "setup":
        setup()
    elif args.action == "start":
        start()
    elif args.action == "status":
        print(json.dumps(rpc("prepare")))
    elif args.action == "stop":
        pid = int((ROOT / "bridge.pid").read_text())
        # Refuse a recycled PID belonging to another process.
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        if str(REPO / "smolvm-bridge/host.py") not in result.stdout:
            raise SystemExit("Recorded PID no longer belongs to this bridge.")
        os.kill(pid, signal.SIGTERM)
        print("Bridge stopped; existing microVMs keep running.")
    elif args.action == "export-image":
        export_image()


if __name__ == "__main__":
    main()
