"""Omnigent transport to the loopback-only, Mac-hosted smolvm provider."""

import base64
import json
import os
import shlex
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import click
from pydantic import BaseModel, ConfigDict, Field
from omnigent.onboarding.sandboxes.base import (
    ExecModelHostLauncher, RemoteCommandResult, SandboxGoneError,
)
from omnigent.onboarding.sandboxes.registry import (
    SandboxProviderContribution, SandboxProviderMetadata,
)
from omnigent.onboarding.sandboxes.types import SandboxCapabilities


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = "http://host.containers.internal:8877"
    token_file: str = "/run/omnigent-smolvm/token"
    timeout_s: int = Field(default=900, ge=1, le=3600)


class SmolvmBridgeLauncher(ExecModelHostLauncher):
    provider = "smolvm"

    def __init__(self, *, config: BridgeConfig):
        self.config = config

    @property
    def capabilities(self):
        return SandboxCapabilities(
            managed_launch=True, programmatic_terminate=True, resume_stopped=True,
            multi_repo=True, git_clone_options=True, file_copy=True,
        )

    def _rpc(self, operation, **arguments):
        try:
            token = Path(self.config.token_file).read_text().strip()
            if not token:
                raise ValueError("empty bridge token")
            request = Request(
                self.config.endpoint.rstrip("/") + "/v1/rpc",
                data=json.dumps({"operation": operation, **arguments}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            # Never send bridge credentials through an inherited HTTP proxy.
            with build_opener(ProxyHandler({})).open(request, timeout=self.config.timeout_s) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise click.ClickException(f"smolvm bridge HTTP error {exc.code}") from None
        except (OSError, URLError, ValueError):
            raise click.ClickException("smolvm bridge unavailable; run sh omnigent/scripts/omnigent-smolvm-bridge.sh start on the Mac") from None
        if payload.get("error") == "gone":
            raise SandboxGoneError("Managed smolvm sandbox no longer exists")
        if payload.get("error"):
            raise click.ClickException(payload.get("message", "smolvm bridge operation failed"))
        return payload.get("result")

    def _credentials(self):
        root = Path(os.environ.get("OMNIGENT_CREDENTIALS_DIR", "/run/omnigent-secrets"))
        names = {
            "CURSOR_API_KEY": "cursor_api_key", "MAAS_API_KEY": "maas_api_key",
            "RHAI_MAAS_API_KEY": "rhai_maas_api_key",
            "GH_TOKEN": "github_token", "AI_SSH_KEY_B64": "ssh_key_b64",
            "AI_GPG_KEY_B64": "gpg_key_b64", "AI_GIT_NAME": "git_name",
            "AI_GIT_EMAIL": "git_email",
        }
        result = {}
        for name, filename in names.items():
            try:
                value = (root / filename).read_text().strip()
            except FileNotFoundError:
                continue
            if value:
                result[name] = value
        return result

    def prepare(self):
        self._rpc("prepare")

    def provision(self, name):
        sandbox_id = self._rpc("provision", name=name)
        try:
            # Reuse the existing image's Git/SSH/GPG initialization. Payloads
            # travel in the authenticated request body, never native process argv.
            values = self._credentials()
            if "GH_TOKEN" in values:
                values["AI_GITHUB_TOKEN"] = values["GH_TOKEN"]
            prefix = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())
            result = self._rpc("run", sandbox_id=sandbox_id,
                               command=prefix + "/usr/local/bin/agent-container-init.sh\n")
            if result["returncode"]:
                raise click.ClickException("smolvm sandbox credential initialization failed")
        except BaseException:
            self.terminate(sandbox_id)
            raise
        return sandbox_id

    def is_running(self, sandbox_id):
        return self._rpc("is_running", sandbox_id=sandbox_id)

    def resume(self, sandbox_id):
        self._rpc("resume", sandbox_id=sandbox_id)

    def terminate(self, sandbox_id):
        self._rpc("terminate", sandbox_id=sandbox_id)

    def run(self, sandbox_id, command, *, check=True):
        values = {key: value for key, value in self._credentials().items()
                  if key in {"GH_TOKEN", "MAAS_API_KEY", "RHAI_MAAS_API_KEY", "CURSOR_API_KEY"}}
        if values:
            values["OMNIGENT_RUNNER_ENV_PASSTHROUGH"] = ",".join(values)
        prefix = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())
        result = RemoteCommandResult(**self._rpc(
            "run", sandbox_id=sandbox_id, command=prefix + command, check=False,
        ))
        if check and result.returncode:
            # Output can contain model credentials or the host launch token.
            raise click.ClickException(f"smolvm sandbox command failed (exit {result.returncode})")
        return result

    def put(self, sandbox_id, local_path, remote_path):
        data = Path(local_path).read_bytes()
        if len(data) > 8 * 1024 * 1024:
            raise click.ClickException("smolvm bridge file upload exceeds 8 MiB")
        self._rpc("put", sandbox_id=sandbox_id, remote_path=remote_path,
                  content=base64.b64encode(data).decode())


def get_contribution():
    return SandboxProviderContribution(
        name="omnigent-local-smolvm-bridge",
        providers={"smolvm": SandboxProviderMetadata(
            name="smolvm", config_model=BridgeConfig,
            launcher_class="omnigent.community.sandbox.smolvm_bridge:SmolvmBridgeLauncher",
        )},
    )
