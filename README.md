# Ephemeral AI Sandbox (Fedora DevContainer)

A secure, version-locked Podman DevContainer for AI agent harnesses (Cursor, OpenCode, Pi, Codex). Secrets are pulled from Vaultwarden via Touch ID and injected into the container's environment at runtime.

## Prerequisites (macOS Host)

1. **Podman & DevContainers CLI**:
   ```bash
   brew install podman
   npm install -g @devcontainers/cli
   ```
2. **Bitwarden CLI & jq**:
   ```bash
   brew install bitwarden-cli jq
   ```
3. **Biometric Bridge (`bwbio`)**:
   ```bash
   brew install jeanregisser/tap/bitwarden-cli-bio
   ```
4. **Codex CLI** (for auth bind-mount into the sandbox):
   ```bash
   curl -fsSL https://chatgpt.com/codex/install.sh | sh
   codex login
   ```
   The sandbox bind-mounts `~/.codex/auth.json` from your Mac. macOS Keychain
   credentials are not visible inside the Linux container, so auth must be
   file-based. If `~/.codex/auth.json` is missing after login, add this to
   `~/.codex/config.toml` and sign in again:
   ```toml
   cli_auth_credentials_store = "file"
   ```
   ```bash
   codex logout && codex login
   ```

## Vaultwarden Configuration

Your Bitwarden/Vaultwarden Desktop app must be running, unlocked, and have **"Allow browser integration"** checked in settings.

Create the following entries in your vault:

| Vault Item Name | Type | Content |
|---|---|---|
| **Cursor API** | Login | Password field: `<API_KEY>` |
| **AI GitHub PAT** | Login | Password field: `<GITHUB_PAT>` |
| *Custom Field* | Text | Name: `Git Name`, Value: `<Your Name>` |
| *Custom Field* | Text | Name: `Git Email`, Value: `<Your Verified GitHub Email>` |
| **AI SSH Key** | Secure Note | The full `id_ed25519` private block |
| **AI GPG Key** | Secure Note | The full exported `.asc` private block |

## Installation & Usage

### Option A: Symlink your clone (recommended)

Keeps your install in sync with local edits and Dependabot merges — `aibox` also runs `git pull --ff-only` on every launch.

```bash
git clone git@github.com:djdanielsson/ai-development.git ~/path/to/ai-development
export AIBOX_REPO=~/path/to/ai-development
mkdir -p ~/.config/devcontainers
ln -sfn "$AIBOX_REPO/.devcontainer" ~/.config/devcontainers/fedora-sandbox
```

Add this line to your `~/.zshrc`, then run `source ~/.zshrc`:

```bash
source "$AIBOX_REPO/aibox.zsh"
```

If your clone lives elsewhere, change `AIBOX_REPO` before running `ln`. Persist `AIBOX_REPO` in `~/.zshrc` (or `~/.zshenv`) so the `source` line keeps working in new shells.

### Option B: Copy the config

1. Copy the `.devcontainer` directory to `~/.config/devcontainers/fedora-sandbox/`.
2. Copy `aibox.zsh` somewhere on your machine and `source` it from `~/.zshrc` (set `AIBOX_REPO` to that directory if you use the symlink install path above).
3. Run `source ~/.zshrc`.

Copied installs skip the automatic `git pull` (no repo detected).

**To launch:**
```bash
cd /path/to/any/project
aibox
```

Touch ID authenticates you, the container builds (or reuses cache), secrets are injected, Git signing is configured, and a terminal attaches.

## Omnigent local server (Podman)

The Compose stack runs the Omnigent server, database, and a separate runner-host
container. The runner host registers with the server automatically, so Omnigent
itself does not need to be installed on the Mac. The host container mounts the
projects directory at `/projects` and stays running while the stack is up.

Start or refresh the stack with `sh scripts/omnigent-up.sh` from this checkout.
It requests Vaultwarden Touch ID, fetches the runner credentials, uses the
installed Podman CLI to verify and mount the Podman machine's rootless Unix API
socket, then starts the Omnigent server and runner host. The server talks to the
Podman VM over that socket; its web port is published on localhost only.
`PODMAN_MACHINE` and `OMNIGENT_PODMAN_SOCKET` can override the machine and its
in-VM socket path.

Since this Compose setup has `OMNIGENT_AUTH_ENABLED=0`, no Omnigent login step
is needed. The project directory defaults to `~/projects`; set `PROJECTS_DIR`
in the environment (or a Compose `.env` file) to override it.

The managed `podman` provider creates a separate container for each **New
Sandbox** session, using the local image and Podman socket. Choose **New
Sandbox** in Omnigent to get a per-project container; selecting the always-on
local runner host reuses the `omnigent-host` container. Project containers join
the Compose network so they can connect back to the server. If you change the
Compose project name, update `sandbox.podman.network` in `config.yaml` to match.

The runner image also installs Codex CLI and mounts `${HOME}/.codex/auth.json`
read-only at `/root/.codex/auth.json`. Sign in on the Mac with Codex's file
credential store before starting the stack; the file must exist for the bind
mount to work. Rebuild with `podman compose up -d --build` after changing the
image. Codex defaults to `gpt-6-luna` with `xhigh` reasoning, configured in
`codex-config.toml`.

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

The Omnigent launcher reads `Cursor API`, `AI GitHub PAT`, `AI SSH Key`, and
`AI GPG Key` from Vaultwarden at stack start. The GitHub PAT item's `Git Name`
and `Git Email` fields configure commits. GitHub authentication is passed to
new project sandboxes as `GH_TOKEN`; private keys are imported into the
sandbox's private home only when that sandbox starts. The launcher sends the
values through stdin into a memory-backed directory in the Omnigent server
container; they are not baked into the image or stored in this repository. Run
the helper again after unlocking Vaultwarden to refresh these runtime values.

Managed project sandboxes also inherit the current versions of `kubectl`, Helm,
Terraform, Argo CD, Kustomize, `oc`, `virtctl`, `tkn`, GitHub CLI, zsh/Oh My Zsh,
eza, fzf, zoxide, vim, jq, uv/tox, and Node.js/npm. These resolve to the latest
available releases when the image is built; rebuild with
`podman compose up -d --build` to refresh them. Podman itself is intentionally
not installed in the runner image (no Podman-in-Podman).

The regular Codex agent keeps the default from `codex-config.toml`
(`gpt-6-luna`, `xhigh`); OpenCode has its separate default in
`opencode-config.json`.

## Version Pinning Strategy

Pinned components enable reproducible builds and security auditing. DNF system packages are intentionally **not** version-pinned — Fedora container repos only carry the latest release of each package, so pinning causes builds to fail once the repo rolls forward.

| Component | How It's Pinned | How to Update |
|---|---|---|
| Base image (`fedora:44`) | Version tag + SHA256 digest in `Containerfile` | Dependabot opens PRs automatically |
| DNF packages | Unpinned package names; `dnf update` at build time | Rebuild to pick up Fedora repo updates |
| Oh My Zsh | Git commit SHA in `install-tools.sh` | CI workflow opens PRs automatically (weekly) |
| prek | Release version tag in `install-tools.sh` | CI workflow opens PRs automatically (weekly) |
| Infra CLIs (kubectl, helm, …) | Release version tags in `install-tools.sh` | CI workflow opens PRs automatically (weekly) |
| VS Code extensions | Pinned `publisher.name@version` | CI workflow opens PRs automatically (weekly) |
| GitHub SSH host keys | Embedded in `container-init.sh` | CI workflow verifies monthly, opens PR on rotation |
| AI harnesses (Cursor, OpenCode, Pi, Codex) | Installed via `curl\|bash` (see note below) | Rebuild to pick up new versions |

**Note on AI harness installers:** Cursor, OpenCode, Pi, and Codex are installed via vendor `curl|bash` scripts which cannot be version-pinned. The install script logs installed versions during build. Review the build log to audit what was installed.

## Keeping Dependencies Updated

This repo uses a combination of **Dependabot** and **GitHub Actions workflows** to keep every pinned dependency current. All updates arrive as PRs for human review — nothing auto-merges.

### Dependabot (`.github/dependabot.yml`)

- **Fedora base image** — new digest PRs (docker ecosystem)
- **DevContainer features** — version updates (devcontainers ecosystem)
- **Pre-commit hooks** — revision updates (pre-commit ecosystem)

### CI Update Workflows (`.github/workflows/`)

| Workflow | Schedule | What It Updates |
|---|---|---|
| `update-ohmyzsh.yml` | Weekly (Mon) | `OHMYZSH_COMMIT` SHA in `install-tools.sh` |
| `update-prek.yml` | Weekly (Mon) | `PREK_VERSION` tag in `install-tools.sh` |
| `update-cli-tools.yml` | Weekly (Mon) | Infra CLI versions in `install-tools.sh` |
| `update-extensions.yml` | Weekly (Mon) | Extension versions in `devcontainer.json` |
| `verify-github-ssh-keys.yml` | Monthly (1st) | SSH host keys in `container-init.sh` |

All update workflows can also be triggered manually via `workflow_dispatch`.

### CI Quality Gates

Every push and PR runs:

- **Pre-commit hooks** — trailing whitespace, EOF fixer, large file check, gitleaks
- **ShellCheck** — static analysis of all shell scripts
- **Container build** — validates the Containerfile builds successfully

### SBOM & Vulnerability Scanning

On every push to `main` and on PRs, the CI:

1. Builds the container image
2. Generates a **CycloneDX SBOM** using [Syft](https://github.com/anchore/syft) (uploaded as a build artifact)
3. Scans the SBOM for known vulnerabilities using [Grype](https://github.com/anchore/grype) (results uploaded to GitHub Security tab)

## Security Model

### Container Isolation Trade-offs

The `runArgs` in `devcontainer.json` intentionally weaken container isolation to support Podman-in-Podman:

- `--security-opt=seccomp=unconfined` -- Allows all syscalls (needed for nested containers)
- `--security-opt=systempaths=unconfined` -- Exposes `/proc` and `/sys` paths
- `--userns=host` -- Shares the host user namespace
- `--cgroupns=host` -- Shares the host cgroup namespace (required for nested Podman cgroup delegation)

The inner Podman is configured via `/etc/containers/containers.conf` in the image to use `cgroupfs` (not `systemd`) as its cgroup manager, and `k8s-file` as its log driver so `podman logs` works without journald.

This means the container boundary is **not a strong security boundary**. The sandbox relies on Podman's rootless mode and the ephemeral nature of the container for isolation.

### Secret Handling

- Secrets are fetched from Vaultwarden via Touch ID and passed as environment variables
- The `postStartCommand` writes the SSH key to the container filesystem (inside a volume) under `umask 077` (no world-readable window)
- GPG keys are imported into the container's GPG keyring (inside a volume)
- After SSH/GPG setup, the base64-encoded secret env vars (`AI_SSH_KEY_B64`, `AI_GPG_KEY_B64`) are unset so they don't linger for child processes
- On the host, shell variables are explicitly `unset` when the launcher function exits (both success and failure paths); however, this does **not** guarantee the memory pages are zeroed by the OS
- All `curl|bash` installers enforce `--proto '=https' --tlsv1.2` to prevent TLS downgrade attacks

### SSH Host Key Verification

GitHub's SSH host keys are embedded directly in `scripts/container-init.sh` rather than using `ssh-keyscan` at runtime. This prevents MITM attacks during first connection. The `verify-github-ssh-keys` CI workflow checks monthly for key rotations and opens a PR if they change.
