#!/usr/bin/env python3
"""Reconnect one running local managed session host without stopping its runner."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx


def main() -> int:
    server_url = sys.argv[1].rstrip("/")
    session_name = sys.argv[2]
    client = httpx.Client(timeout=10.0, trust_env=False)

    def get_json(path: str) -> dict[str, object]:
        response = client.get(server_url + path)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected response from {path}")
        return result

    try:
        me = get_json("/v1/me")
    except Exception as exc:  # noqa: BLE001 - report the endpoint failure to the caller
        print(f"Cannot reach Omnigent at {server_url}: {exc}", file=sys.stderr)
        return 1

    if me.get("user_id") != "local" or me.get("is_admin") is not True:
        print(
            "Refusing token-free reconnect: the server is not in local single-user mode.",
            file=sys.stderr,
        )
        return 1

    try:
        hosts = get_json("/v1/hosts").get("hosts", [])
    except Exception as exc:  # noqa: BLE001 - report the endpoint failure to the caller
        print(f"Cannot list Omnigent hosts: {exc}", file=sys.stderr)
        return 1

    if not isinstance(hosts, list):
        print("Omnigent returned an invalid host list.", file=sys.stderr)
        return 1

    matches = [
        host
        for host in hosts
        if isinstance(host, dict)
        and host.get("name") == session_name
        and host.get("sandbox_provider") == "podman"
    ]
    if len(matches) != 1:
        print(
            f"Expected one Podman host named {session_name!r}; found {len(matches)}.",
            file=sys.stderr,
        )
        return 1

    host = matches[0]
    host_id = host.get("host_id")
    if not isinstance(host_id, str) or not host_id:
        print(f"Omnigent returned no host ID for {session_name}.", file=sys.stderr)
        return 1
    if host.get("status") == "online":
        print(f"{session_name}: already online; leaving its host process alone.")
        return 0

    # A managed launch token can expire while its Podman session remains alive.
    # Use a separate daemon registry so reconnecting does not stop the existing
    # host's runner zygote or any runner processes it owns.
    env = os.environ.copy()
    env["OMNIGENT_HOST_ID"] = host_id
    env["OMNIGENT_HOST_NAME"] = session_name
    env["OMNIGENT_DATA_DIR"] = f"/root/.omnigent/reconnect/{host_id}"
    env.pop("OMNIGENT_HOST_TOKEN", None)

    start = subprocess.run(
        [
            "omnigent",
            "host",
            "--server",
            server_url,
            "--no-open",
            "--background",
            "--non-interactive",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if start.returncode != 0:
        print(start.stdout, end="", file=sys.stderr)
        print(start.stderr, end="", file=sys.stderr)
        print(f"Could not start the reconnect daemon for {session_name}.", file=sys.stderr)
        return start.returncode

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            current_hosts = get_json("/v1/hosts").get("hosts", [])
            current = next(
                item
                for item in current_hosts
                if isinstance(item, dict) and item.get("host_id") == host_id
            )
        except (httpx.HTTPError, StopIteration, KeyError, RuntimeError, ValueError):
            time.sleep(1)
            continue
        if current.get("status") == "online":
            print(f"{session_name}: server reports host online.")
            return 0
        time.sleep(1)

    print(f"{session_name}: host did not come online within 30 seconds.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
