"""Reconnect and stop stale managed VMs through the authenticated Mac bridge."""

import argparse
import json
import os
import secrets
import shlex
import subprocess
import sys
import time

from manage import REPO, rpc


def active_names():
    # Reuse the existing fail-closed, paginated reconciliation on the server,
    # including its local-admin check. Nothing is inferred from host liveness.
    script = (REPO / "scripts/omnigent-cleanup-stale-containers.py").read_bytes()
    url = os.environ.get("OMNIGENT_CLEANUP_SERVER_URL", "http://127.0.0.1:8000")
    result = subprocess.run(["podman", "exec", "-i", "omnigent-server", "python", "-",
                             "--active-hosts", url], input=script, capture_output=True,
                            timeout=60, check=False)
    if result.returncode:
        raise RuntimeError("Cannot reconcile active sessions; refusing further VM cleanup. "
                           + result.stderr.decode(errors="replace").strip())
    names = json.loads(result.stdout)
    if not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names):
        raise RuntimeError("Invalid active-host snapshot; refusing further VM cleanup.")
    return set(names)


def stale_candidate(machine, active, now, states=("running",)):
    name = machine.get("session_name")
    if machine.get("state") not in states or not isinstance(name, str) or not name:
        return False
    created = machine.get("created_at")
    try:
        age = now - int(created)
    except (TypeError, ValueError):
        return False  # Never stop a VM with missing/unrecognized age metadata.
    # A newly provisioned VM may not yet have its host bound to a session.
    return age >= 300 and name not in active


def prune(apply=False):
    active = active_names()
    machines = rpc("list")
    candidates = [m for m in machines if stale_candidate(m, active, time.time())]
    print(f"Found {len(machines)} registered smolvm VM(s), {len(candidates)} stale running candidate(s).")
    print("VMs younger than five minutes or with unknown creation time are kept.")
    for machine in candidates:
        print(f"  {machine['sandbox_id']} ({machine['session_name']})")
    if not apply:
        print("Dry run; no VMs were stopped. Pass --apply to stop stale VMs and retain their disks.")
        return 0
    for candidate in candidates:
        # Reconcile sessions and owned metadata immediately before each stop.
        active = active_names()
        current = next((m for m in rpc("list") if m["sandbox_id"] == candidate["sandbox_id"]), None)
        if current is None or current.get("session_name") != candidate["session_name"] or not stale_candidate(current, active, time.time()):
            print(f"Keeping {candidate['sandbox_id']}: its state or session changed.")
            continue
        rpc("stop", sandbox_id=current["sandbox_id"])
        print(f"Stopped {current['sandbox_id']}; disks retained.")
    return 0


def reconnect():
    machines = rpc("list")
    running = [m for m in machines if m.get("state") == "running"]
    if not running:
        print("No running managed smolvm VMs found.")
        return 0
    source = (REPO / "scripts/omnigent-reconnect-container.py").read_text()
    url = os.environ.get("OMNIGENT_SMOLVM_SERVER_URL", "http://100.96.0.1:8000")
    failed = False
    for machine in running:
        name = machine.get("session_name")
        if not isinstance(name, str) or not name:
            print(f"Skipping {machine['sandbox_id']}: no session-name label.", file=sys.stderr)
            failed = True
            continue
        marker = "OMNIGENT_RECONNECT_" + secrets.token_hex(16)
        command = shlex.join(["python3", "-", url, name, "smolvm"]) + f" <<'{marker}'\n{source}\n{marker}\n"
        result = rpc("run", sandbox_id=machine["sandbox_id"], command=command)
        print(result["stdout"], end="")
        print(result["stderr"], end="", file=sys.stderr)
        failed |= result["returncode"] != 0
    return int(failed)


def delete_stopped():
    # A fresh listing includes VMs just stopped by the preceding prune phase.
    active = active_names()
    candidates = [m for m in rpc("list") if stale_candidate(m, active, time.time(), ("stopped",))]
    removed = 0
    for candidate in candidates:
        active = active_names()
        current = next((m for m in rpc("list") if m["sandbox_id"] == candidate["sandbox_id"]), None)
        if current is None or current.get("session_name") != candidate["session_name"] or not stale_candidate(current, active, time.time(), ("stopped",)):
            print(f"Keeping {candidate['sandbox_id']}: its state or session changed.")
            continue
        rpc("delete_stopped", sandbox_id=current["sandbox_id"])
        removed += 1
        print(f"Removed stopped VM {current['sandbox_id']} and its disks.")
    print(f"Removed {removed} stopped stale VM(s).")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prune", "reconnect"])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--delete", action="store_true", help="Stop stale VMs, then rescan and delete stopped stale VMs and disks")
    group.add_argument("--delete-stopped", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.action == "reconnect":
            return reconnect()
        if args.delete_stopped:
            return delete_stopped()
        if args.delete:
            result = prune(True)
            return result or delete_stopped()
        return prune(args.apply)
    except Exception as exc:
        print(f"smolvm {args.action} aborted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
