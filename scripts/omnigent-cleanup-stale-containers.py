#!/usr/bin/env python3
"""Stop managed Podman containers no longer used by an unarchived session.

Run inside the omnigent-server container, where both the local API and Podman
socket are available. The shell wrapper defaults to a report-only dry run.
"""

from __future__ import annotations

import sys
from typing import Any

import docker
import httpx
from docker.errors import APIError, DockerException, NotFound


def get_json(
    client: httpx.Client,
    server_url: str,
    path: str,
    *,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    response = client.get(server_url + path, params=params)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected response from {path}")
    return result


def active_session_host_names(
    client: httpx.Client, server_url: str
) -> set[str]:
    """Return host names referenced by all unarchived sessions.

    The default session listing excludes archived sessions. Include child
    sessions because they may have their own managed host. Idle and failed
    sessions remain active here: they retain history and can be resumed.
    """
    session_host_ids: set[str] = set()
    seen_session_ids: set[str] = set()
    after: str | None = None
    seen_cursors: set[str] = set()

    while True:
        params: dict[str, str | int] = {
            "kind": "any",
            "limit": 1000,
            "sort_by": "created_at",
            "order": "desc",
            "visibility": "all",
        }
        if after is not None:
            params["after"] = after

        page = get_json(client, server_url, "/v1/sessions", params=params)
        sessions = page.get("data")
        if not isinstance(sessions, list):
            raise RuntimeError("Omnigent returned an invalid session list")

        for session in sessions:
            if not isinstance(session, dict):
                raise RuntimeError("Omnigent returned an invalid session entry")
            session_id = session.get("id")
            if not isinstance(session_id, str) or not session_id:
                raise RuntimeError("Omnigent returned a session without an ID")
            if session_id in seen_session_ids:
                raise RuntimeError("Omnigent returned a duplicate session")
            seen_session_ids.add(session_id)

            host_id = session.get("host_id")
            if host_id is not None:
                if not isinstance(host_id, str) or not host_id:
                    raise RuntimeError(
                        f"Omnigent returned an invalid host ID for session {session_id}"
                    )
                session_host_ids.add(host_id)

        has_more = page.get("has_more")
        if not isinstance(has_more, bool):
            raise RuntimeError("Omnigent returned no valid session pagination state")
        if not has_more:
            break

        last_id = page.get("last_id")
        if not isinstance(last_id, str) or not last_id or last_id in seen_cursors:
            raise RuntimeError("Omnigent returned an invalid session pagination cursor")
        seen_cursors.add(last_id)
        after = last_id

    hosts_response = get_json(client, server_url, "/v1/hosts")
    hosts = hosts_response.get("hosts")
    if not isinstance(hosts, list):
        raise RuntimeError("Omnigent returned an invalid host list")

    host_names: dict[str, str] = {}
    for host in hosts:
        if not isinstance(host, dict):
            raise RuntimeError("Omnigent returned an invalid host entry")
        host_id = host.get("host_id")
        if not isinstance(host_id, str) or not host_id:
            raise RuntimeError("Omnigent returned a host without an ID")
        name = host.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError(f"Omnigent returned no name for host {host_id}")
        if host_id in host_names:
            raise RuntimeError(f"Omnigent returned duplicate host ID {host_id}")
        host_names[host_id] = name

    missing_host_ids = session_host_ids.difference(host_names)
    if missing_host_ids:
        missing = ", ".join(sorted(missing_host_ids))
        raise RuntimeError(
            "Cannot reconcile active sessions with Omnigent hosts; "
            f"these host IDs are missing: {missing}"
        )

    return {host_names[host_id] for host_id in session_host_ids}


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"--dry-run", "--apply"}:
        print("Usage: cleanup-helper.py [--dry-run|--apply] SERVER_URL", file=sys.stderr)
        return 2

    mode = sys.argv[1]
    server_url = sys.argv[2].rstrip("/")
    if not server_url:
        print("Server URL cannot be empty.", file=sys.stderr)
        return 2

    try:
        with httpx.Client(timeout=10.0, trust_env=False) as api:
            me = get_json(api, server_url, "/v1/me")
            if me.get("user_id") != "local" or me.get("is_admin") is not True:
                print(
                    "Refusing cleanup: the server is not in local single-user mode.",
                    file=sys.stderr,
                )
                return 1

            active_names = active_session_host_names(api, server_url)

            podman = docker.from_env(timeout=30)
            try:
                containers = podman.containers.list(
                    filters={
                        "label": [
                            "io.omnigent.managed=true",
                            "io.omnigent.provider=podman",
                        ]
                    }
                )
                stale: list[tuple[Any, str, str]] = []
                unlabelled = 0
                for container in containers:
                    labels = container.labels or {}
                    session_name = labels.get("io.omnigent.session-name")
                    if not isinstance(session_name, str) or not session_name:
                        unlabelled += 1
                        print(
                            f"Skipping {container.name}: missing session-name label.",
                            file=sys.stderr,
                        )
                        continue
                    if session_name not in active_names:
                        stale.append((container, container.id, session_name))

                print(
                    f"Found {len(active_names)} active host name(s) and "
                    f"{len(containers)} running managed Podman container(s)."
                )
                if not stale:
                    print("No stale managed containers found.")
                    return 0

                print("Containers with no active-session host match:")
                for container, _, session_name in stale:
                    print(f"  {container.name} ({session_name})")

                if mode == "--dry-run":
                    suffix = " Pass --apply to stop these containers."
                    if unlabelled:
                        suffix += f" {unlabelled} container(s) were skipped."
                    print("Dry run; no containers were stopped." + suffix)
                    return 0

                stopped = 0
                failed = 0
                for container, container_id, session_name in stale:
                    # Re-read server state before each stop to reduce the chance
                    # of stopping a sandbox that became active during the scan.
                    try:
                        current_active_names = active_session_host_names(api, server_url)
                    except Exception as exc:  # noqa: BLE001 - stop safely on API errors
                        print(
                            f"Cannot recheck sessions before stopping {container.name}: {exc}",
                            file=sys.stderr,
                        )
                        return 1
                    if session_name in current_active_names:
                        print(f"Keeping {container.name}: its host now has an active session.")
                        continue

                    try:
                        container.reload()
                        labels = container.labels or {}
                        if container.status != "running":
                            print(f"Skipping {container.name}: it is no longer running.")
                            continue
                        if (
                            labels.get("io.omnigent.managed") != "true"
                            or labels.get("io.omnigent.provider") != "podman"
                            or labels.get("io.omnigent.session-name") != session_name
                        ):
                            print(
                                f"Skipping {container.name}: its managed-session labels changed.",
                                file=sys.stderr,
                            )
                            continue
                        container.stop(timeout=10)
                        stopped += 1
                        print(f"Stopped {container.name} ({session_name}).")
                    except NotFound:
                        print(f"Skipping {container_id[:12]}: it no longer exists.")
                    except (APIError, DockerException) as exc:
                        failed += 1
                        print(
                            f"Could not stop {container.name}: {exc}",
                            file=sys.stderr,
                        )

                print(f"Stopped {stopped} stale container(s).")
                return 1 if failed else 0
            finally:
                podman.close()
    except Exception as exc:  # noqa: BLE001 - report API/socket failures and fail closed
        print(f"Cleanup aborted without stopping containers: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
