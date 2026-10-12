from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

import click
import docker
from docker.errors import APIError, NotFound
from omnigent.onboarding.sandboxes.base import ExecModelHostLauncher, RemoteCommandResult
from omnigent.onboarding.sandboxes.types import SandboxCapabilities

from .config import PodmanConfig


class PodmanSandboxLauncher(ExecModelHostLauncher):
    provider = "podman"

    def __init__(self, *, config: PodmanConfig):
        self.config = config

    @property
    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            managed_launch=True,
            programmatic_terminate=True,
        )

    def _client(self) -> docker.DockerClient:
        try:
            return docker.from_env(timeout=30)
        except Exception as exc:
            raise click.ClickException(
                "Podman provider could not connect to the configured container socket"
            ) from exc

    def _read_credential(self, name: str) -> str | None:
        credentials_dir = Path(
            os.environ.get("OMNIGENT_CREDENTIALS_DIR", "/run/omnigent-secrets")
        )
        try:
            value = (credentials_dir / name).read_text().strip()
        except FileNotFoundError:
            return None
        return value or None

    def prepare(self) -> None:
        client = self._client()
        try:
            client.ping()
            client.images.get(self.config.image)
        except Exception as exc:
            raise click.ClickException(
                f"Podman provider cannot reach the socket or local image "
                f"{self.config.image!r}; check DOCKER_HOST and build the image first"
            ) from exc
        finally:
            client.close()

    def provision(self, name: str) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-.")[:48]
        safe_name = safe_name or "session"
        container_name = f"omni-{safe_name}-{secrets.token_hex(4)}"

        environment: dict[str, str] = {}
        bootstrap_environment: dict[str, str] = {}
        if cursor_key := self._read_credential("cursor_api_key"):
            environment["CURSOR_API_KEY"] = cursor_key
        if github_token := self._read_credential("github_token"):
            # Omnigent's managed runner launches agent commands in Bash
            # subprocesses. The host filters secrets by default, so explicitly
            # allow this credential through to session runners. Tmux-backed
            # interactive Zsh sessions may also lose inherited environment.
            environment["GH_TOKEN"] = github_token
            environment["OMNIGENT_RUNNER_ENV_PASSTHROUGH"] = "GH_TOKEN"
            bootstrap_environment["AI_GITHUB_TOKEN"] = github_token
        for env_name, file_name in (
            ("AI_SSH_KEY_B64", "ssh_key_b64"),
            ("AI_GPG_KEY_B64", "gpg_key_b64"),
            ("AI_GIT_NAME", "git_name"),
            ("AI_GIT_EMAIL", "git_email"),
        ):
            if value := self._read_credential(file_name):
                bootstrap_environment[env_name] = value

        auth_file = os.environ.get("CODEX_AUTH_FILE")
        volumes: dict[str, dict[str, str]] = {}
        if auth_file:
            volumes[auth_file] = {
                "bind": "/root/.codex/auth.json",
                "mode": "ro",
            }
        opencode_auth_volume = os.environ.get("OPENCODE_AUTH_VOLUME")
        if opencode_auth_volume:
            volumes[opencode_auth_volume] = {
                "bind": "/root/.local/share/opencode",
                "mode": "ro",
            }

        client = self._client()
        container = None
        try:
            container = client.containers.create(
                image=self.config.image,
                name=container_name,
                command=[],
                entrypoint=["/bin/sh", "-lc", "exec sleep infinity"],
                environment=environment,
                labels={
                    "io.omnigent.managed": "true",
                    "io.omnigent.provider": "podman",
                    "io.omnigent.session-name": name[:128],
                },
                network=self.config.network,
                volumes=volumes,
                tmpfs={
                    "/run/omnigent-secrets": "rw,noexec,nosuid,size=1m,mode=0700"
                },
                healthcheck={"Test": ["NONE"]},
            )
            container.start()
            result = container.exec_run(
                ["/usr/local/bin/agent-container-init.sh"],
                environment=bootstrap_environment,
                demux=True,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    "credential initialization failed "
                    f"(exit code {result.exit_code})"
                )
            return container.id
        except Exception as exc:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            raise click.ClickException(
                f"Podman could not create a container for session {safe_name!r}"
            ) from exc
        finally:
            client.close()

    def run(
        self, sandbox_id: str, command: str, *, check: bool = True
    ) -> RemoteCommandResult:
        command_environment = {}
        if github_token := self._read_credential("github_token"):
            command_environment["GH_TOKEN"] = github_token

        client = self._client()
        try:
            container = client.containers.get(sandbox_id)
            result = container.exec_run(
                ["/bin/sh", "-lc", command],
                environment=command_environment or None,
                demux=True,
            )
        except NotFound as exc:
            raise click.ClickException("Podman session container no longer exists") from exc
        except APIError as exc:
            raise click.ClickException("Podman failed to execute a command in the session") from exc
        finally:
            client.close()

        stdout, stderr = result.output or (None, None)
        command_result = RemoteCommandResult(
            returncode=result.exit_code if result.exit_code is not None else 1,
            stdout=(stdout or b"").decode(errors="replace"),
            stderr=(stderr or b"").decode(errors="replace"),
        )
        if check and command_result.returncode != 0:
            raise click.ClickException(
                f"Podman session command failed with exit code {command_result.returncode}"
            )
        return command_result

    def terminate(self, sandbox_id: str) -> None:
        client = self._client()
        try:
            try:
                container = client.containers.get(sandbox_id)
            except NotFound:
                return
            container.remove(force=True)
        except APIError as exc:
            raise click.ClickException("Podman failed to remove the session container") from exc
        finally:
            client.close()
