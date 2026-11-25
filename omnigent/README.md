# Omnigent local stack

[Back to repository overview](../README.md)

All commands below run from the repository root. Prerequisites are Podman with a running machine, a Compose provider, Python 3, Bitwarden CLI (`bw`), `bwbio`, and `jq`. Configure Vaultwarden as described in the [shared credential setup](../devcontainer/README.md#vaultwarden-configuration).

## Server and runners

The Compose stack runs the Omnigent server, database, and a separate runner-host
container. The runner host registers with the server automatically, so Omnigent
itself does not need to be installed on the Mac. The host container mounts the
projects directory at `/projects` and stays running while the stack is up.

Start or refresh the stack with `sh omnigent/scripts/omnigent-up.sh` from the repository root.
It requests Vaultwarden Touch ID, fetches the runner credentials, uses the
installed Podman CLI to verify and mount the Podman machine's rootless Unix API
socket, then starts the Omnigent server and runner host. The server talks to the
Podman VM over that socket; its web port is published on localhost only.
`PODMAN_MACHINE` and `OMNIGENT_PODMAN_SOCKET` can override the machine and its
in-VM socket path.

If Omnigent marks sessions as disconnected after the computer sleeps, run
`sh omnigent/scripts/omnigent-reconnect.sh`. It finds running managed Podman session
containers and registered smolvm VMs, then starts a reconnect daemon for each offline host without stopping
the existing host or its runner processes, and waits for the server to report
the host online. This local-stack recovery uses the same host identity through
the local single-user server path when a managed launch token has expired. It
refuses that fallback if the server is not in local single-user mode.

To find running managed containers or VMs whose sessions were archived or deleted,
run `sh omnigent/scripts/omnigent-cleanup-stale-containers.sh`. Every unarchived session
counts as active, including idle or failed sessions that may be resumed. The
script reports candidates by default; pass `--apply` to stop them. It only
stops sandboxes and keeps Omnigent session history intact. Stopped VMs retain
their disks. VMs younger than five minutes, or with unknown creation times,
are kept to protect launches still registering with the server. The same
checks are repeated before each VM stop; API failures abort VM cleanup.

Pass `--delete` to stop stale running sandboxes across both providers first,
then rescan and remove stopped stale containers and VMs, including VM disks.
This includes sandboxes stopped by an earlier cleanup run. Unarchived sessions
remain protected even when their sandboxes are stopped. Deletion rechecks
session ownership and sandbox state; a failed stop phase prevents deletion.
The default remains report-only, and `--apply` continues to stop without deleting.

Archiving a managed session stops its sandbox container and preserves its
history. The launcher builds the local Omnigent image when it is missing.
When the local image exists, the launcher checks the upstream server image and
asks before pulling and rebuilding if a newer version is available.
The stop-before-archive behavior is included in the current server.

Since this Compose setup has `OMNIGENT_AUTH_ENABLED=0`, no Omnigent login step
is needed. The project directory defaults to `~/projects`; set `PROJECTS_DIR`
in the environment (or a Compose `.env` file) to override it.

The managed `podman` provider creates a separate container for each **New
Sandbox** session, using the local image and Podman socket. Choose **New
Sandbox** in Omnigent to get a per-project container; selecting the always-on
local runner host reuses the `omnigent-host` container. Project containers join
the Compose network so they can connect back to the server. If you change the
Compose project name, update `sandbox.podman.network` in `omnigent/config.yaml` to match.

### smolvm microVM provider (macOS Apple Silicon)

The **New Sandbox** picker offers both `podman` and `smolvm`; Podman is the
default. The server stays in Podman. A small authenticated bridge on Mac
loopback port 8877 runs the upstream
[smolvm provider](https://github.com/cidrblock/omnigent-smolvm-provider) natively,
so each smolvm session gets its own Linux microVM through Hypervisor.framework.

For a new installation, install the native runtime and configure the bridge:

```bash
brew install smol-machines/tap/smolvm
sh omnigent/scripts/omnigent-smolvm-bridge.sh setup
sh omnigent/scripts/omnigent-up.sh
```

`uv` must be installed on the Mac. Setup installs provider commit
`65a85dcc857c32fc52b61dcfafb7a51764d137ec` into a separate Python environment
because its Omnigent dependency differs from the server's. The native runtime
installed and tested for this integration is smolvm 1.35.1.

The normal stack launcher starts the bridge when configured, refreshes staged
Codex/OpenCode auth, and exports the local runner image when it changes. Exports
take several GB of disk space. State, the bridge token, staged auth, logs, and
the image archive live in the ignored, private `.smolvm-bridge/` directory.
Vaultwarden credentials are delivered from server tmpfs to the guest through
the authenticated bridge; values are not passed in native process arguments.

The bridge accepts fixed lifecycle operations for its own registered VMs.
Uploads carry file contents rather than arbitrary Mac source paths. Guests
receive only a staged auth directory, with no project or home-directory mount.
Their private disks persist across stops. Published development ports are
allocated from 30000–40000, ten per VM, and recorded in `/root/sandbox-info.md`.
Private-network egress is blocked. New VMs reach Omnigent at
`http://127.0.0.1:8000` through a dedicated socket mounted by smolvm. The Mac
bridge forwards that socket to Omnigent's loopback port.
New VMs use dedicated sockets to reach `models.corp.redhat.com:443` and
`maas.apps.ocp.cloud.rhai-tmm.dev:443` through the Mac's network connection.
Pi verifies the MaaS TLS certificates using the CA bundled in the image.

Manage the bridge independently with:

```bash
sh omnigent/scripts/omnigent-smolvm-bridge.sh status
sh omnigent/scripts/omnigent-smolvm-bridge.sh start
sh omnigent/scripts/omnigent-smolvm-bridge.sh stop
```

Stopping the bridge leaves existing microVMs running. It starts again on the
next stack launch; it does not install a Mac login service. Host configuration
is in `.smolvm-bridge/profile.json`; restart the bridge after editing it.
The private `.smolvm-bridge/` state directory remains at the repository root to preserve existing VM paths and Python environments.

Boundary tests run with `python3 -m unittest discover -s omnigent/smolvm-bridge`.

The runner image also installs Codex CLI and mounts `${HOME}/.codex/auth.json`
read-only at `/root/.codex/auth.json`. Sign in on the Mac with Codex's file
credential store before starting the stack; the file must exist for the bind
mount to work. Rebuild with `podman compose -f omnigent/docker-compose.yml up -d --build` after changing the
image. Codex defaults to `gpt-6-luna` with `xhigh` reasoning, configured in
`omnigent/codex-config.toml`.

The runner image installs Pi with a Red Hat MaaS provider configured for
`https://models.corp.redhat.com/oai/v1/chat/completions`. Pi queries the
provider's `/models` endpoint at startup and lists the returned models. Pi
defaults to `deepseek-4-1-flash`, which remains available if model discovery is
unavailable. The Omnigent launcher fetches the `maas` password from Vaultwarden
and passes it to new project sandboxes as `MAAS_API_KEY`. The runner image trusts
the verified Red Hat internal root CA so Pi can validate the MaaS TLS chain.
Before building, provision that CA locally at
`omnigent/certs/redhat-internal-root-ca.crt`; the certificate is excluded from Git.
Pi also applies rolling per-model limits of 30 requests and 300,000 estimated
tokens per minute. Prompt size is estimated before sending and adjusted to the
reported usage after each completed response. This local limiter assumes one
active MaaS Pi process; MaaS continues to enforce its own quotas.

Pi's `/model` picker also lists models from the `rhai-maas` provider. Pi retries
discovery at `https://maas.apps.ocp.cloud.rhai-tmm.dev/v1/models` and uses the
configured fallback catalog if the gateway returns no models.
The launcher reads the password of the Vaultwarden login
`rh-ai.apps.ocp.cloud.rhai-tmm.dev` and supplies it as `RHAI_MAAS_API_KEY`.
The existing MaaS provider is available if this additional password is missing.
New project sandboxes pick up the provider after rebuilding and relaunching the
stack. Restart the smolvm bridge first if it is already running so newly
created VMs get the new gateway socket.

The runner image also installs OpenCode CLI, with OpenCode Zen's Muse Spark
1.3 Contributor Free (`opencode/muse-spark-1.3-contributor-free`) as its
default. To authenticate without installing OpenCode on the Mac, run
`podman exec -it omnigent-host opencode auth login --provider opencode` and
follow the prompt. Credentials are stored in a persistent Podman volume and
mounted read-only into project sandboxes.

Telemetry is disabled in the local image: Omnigent analytics and OpenTelemetry
are off, Codex analytics and OTel export are off, and `DO_NOT_TRACK=1` is set
for tools that honor the standard opt-out signal. This does not block normal
network traffic needed for model inference, authentication, or repository access.

The runner image also installs Cursor Agent CLI. The Omnigent helper fetches
the `Cursor API` value from Vaultwarden and passes it to the runner and newly
created project sandboxes as `CURSOR_API_KEY`; no Cursor login file is mounted.

The Omnigent launcher reads `Cursor API`, `maas`,
`rh-ai.apps.ocp.cloud.rhai-tmm.dev`, `AI GitHub PAT`, `AI SSH Key`, and
`AI GPG Key` from Vaultwarden at stack start. The GitHub PAT item's `Git Name`
and `Git Email` fields configure commits. GitHub authentication is passed to
new project sandboxes as `GH_TOKEN`; private keys are imported into the
sandbox's private home only when that sandbox starts. The launcher sends the
values through stdin into a memory-backed directory in the Omnigent server
container; they are not baked into the image or stored in this repository. Run
the helper again after unlocking Vaultwarden to refresh these runtime values.

Managed project sandboxes also inherit the current versions of `kubectl`, Helm,
Terraform, Argo CD, Kustomize, `oc`, `virtctl`, `tkn`, GitHub CLI, zsh/Oh My Zsh,
eza, fzf, zoxide, vim, jq, uv/tox, and Node.js/npm. The pinned `prek` release
is installed alongside them and updated by the weekly prek workflow. Rebuild with
`podman compose -f omnigent/docker-compose.yml up -d --build` to refresh them. Podman itself is intentionally
not installed in the runner image (no Podman-in-Podman).

Every sandbox uses a global Git pre-commit hook backed by `prek`. A repository's
`prek.toml`, `.pre-commit-config.yaml`, or `.pre-commit-config.yml` takes
precedence, including configs in nested monorepo projects. If none is present,
the hook uses
`omnigent/config/prek-default.yaml` from this repo's image, with trailing-whitespace,
end-of-file, large-file, and Gitleaks checks. The fallback config is not copied
into the project, so it does not change that repository's tracked files.

The regular Codex agent keeps the default from `omnigent/codex-config.toml`
(`gpt-6-luna`, `xhigh`); OpenCode has its separate default in
`omnigent/opencode-config.json`.

### Sub-agent model policy

The Omnigent server applies `same_subagent_model` by default. It denies any
resolved model whose name contains `astra`, including routed and sub-agent
requests. It allows a sub-agent launch that leaves model and harness selection
to Omnigent, and asks for approval when a launch explicitly selects a different
or unverifiable model/harness. Approve that exception only when the user or an
applicable skill directly requested it. The policy checks both
`sys_session_send` and `sys_session_create` calls.

The policy handler is bundled into the local server image, and its default
attachment is configured in `omnigent/config.yaml`. Rebuild and restart the server with `podman compose -f omnigent/docker-compose.yml up -d --build omnigent` to activate changes to the policy code or registration.


## Automated updates and validation

`update-omnigent.yml` checks the upstream `latest` server image daily and pins
its manifest digest in `Containerfile`. The first run adds the digest pin;
subsequent runs open a PR only when it changes. `update-prek.yml` updates the
runner's prek version weekly. Both workflows also support manual runs.

Update PRs auto-merge after CI and SBOM checks pass. Pull the merged update and
run `sh omnigent/scripts/omnigent-up.sh`; accept the image refresh prompt to
pull and rebuild. This updates repository pins without restarting a running
local stack automatically.

CI builds the Omnigent image with a temporary test CA and checks provider imports.
Your real MaaS CA remains a local prerequisite; CI cannot verify access to the
corporate MaaS endpoint or your Vaultwarden credentials.
