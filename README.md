# Ephemeral AI Sandbox (Fedora DevContainer)

A secure, version-locked Podman DevContainer for AI agents (Cursor, Claude, OpenCode). Secrets are pulled from Vaultwarden via Touch ID and injected into the container's environment at runtime.

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

## Vaultwarden Configuration

Your Bitwarden/Vaultwarden Desktop app must be running, unlocked, and have **"Allow browser integration"** checked in settings.

Create the following entries in your vault:

| Vault Item Name | Type | Content |
|---|---|---|
| **Anthropic API** | Login | Password field: `<API_KEY>` |
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
git clone <repo-url> ~/path/to/ai-development
mkdir -p ~/.config/devcontainers
ln -sfn ~/path/to/ai-development/.devcontainer ~/.config/devcontainers/fedora-sandbox
```

Append the `aibox` function (and helpers) from `.zshrc` into your `~/.zshrc`, then run `source ~/.zshrc`.

Override the repo path with `AIBOX_REPO` if your clone lives elsewhere:

```bash
export AIBOX_REPO=~/path/to/ai-development
```

### Option B: Copy the config

1. Copy the `.devcontainer` directory to `~/.config/devcontainers/fedora-sandbox/`.
2. Append the `aibox` function from `.zshrc` into your `~/.zshrc`.
3. Run `source ~/.zshrc`.

Copied installs skip the automatic `git pull` (no repo detected).

**To launch:**
```bash
cd /path/to/any/project
aibox
```

Touch ID authenticates you, the container builds (or reuses cache), secrets are injected, Git signing is configured, and a terminal attaches.

## Version Pinning Strategy

Everything in this setup is pinned to enable reproducible builds and security auditing:

| Component | How It's Pinned | How to Update |
|---|---|---|
| Base image (`fedora:43`) | Version tag + SHA256 digest in `Containerfile` | Dependabot opens PRs automatically |
| DNF packages | Exact `name-version-release` strings | CI workflow opens PRs automatically (weekly) |
| Oh My Zsh | Git commit SHA | CI workflow opens PRs automatically (weekly) |
| prek | Release version tag | CI workflow opens PRs automatically (weekly) |
| VS Code extensions | Pinned `publisher.name@version` | CI workflow opens PRs automatically (weekly) |
| GitHub SSH host keys | Embedded in `container-init.sh` | CI workflow verifies monthly, opens PR on rotation |
| AI CLIs (Claude, Cursor, OpenCode) | Installed via `curl\|bash` (see note below) | Rebuild to pick up new versions |

**Note on AI CLI installers:** Claude, Cursor, and OpenCode are installed via vendor `curl|bash` scripts which cannot be version-pinned. The install script logs installed versions during build. Review the build log to audit what was installed.

## Keeping Dependencies Updated

This repo uses a combination of **Dependabot** and **GitHub Actions workflows** to keep every pinned dependency current. All updates arrive as PRs for human review — nothing auto-merges.

### Dependabot (`.github/dependabot.yml`)

- **Fedora base image** — new digest PRs (docker ecosystem)
- **DevContainer features** — version updates (devcontainers ecosystem)
- **Pre-commit hooks** — revision updates (pre-commit ecosystem)

### CI Update Workflows (`.github/workflows/`)

| Workflow | Schedule | What It Updates |
|---|---|---|
| `update-dnf-versions.yml` | Weekly (Mon) | DNF package version pins in `Containerfile` |
| `update-ohmyzsh.yml` | Weekly (Mon) | `OHMYZSH_COMMIT` SHA in `Containerfile` |
| `update-prek.yml` | Weekly (Mon) | `PREK_VERSION` tag in `Containerfile` |
| `update-extensions.yml` | Weekly (Mon) | Extension versions in `devcontainer.json` |
| `verify-github-ssh-keys.yml` | Monthly (1st) | SSH host keys in `container-init.sh` |

All update workflows can also be triggered manually via `workflow_dispatch`.

### CI Quality Gates

Every push and PR runs:

- **Pre-commit hooks** — trailing whitespace, EOF fixer, large file check, gitleaks
- **ShellCheck** — static analysis of all shell scripts
- **Container build** — validates the Containerfile builds successfully (catches broken version pins)

### SBOM & Vulnerability Scanning

On every push to `main` and on PRs, the CI:

1. Builds the container image
2. Generates a **CycloneDX SBOM** using [Syft](https://github.com/anchore/syft) (uploaded as a build artifact)
3. Scans the SBOM for known vulnerabilities using [Grype](https://github.com/anchore/grype) (results uploaded to GitHub Security tab)

### Manual Fallback

For DNF packages, the update script can still be run manually inside a Fedora container:
```bash
bash scripts/update-dnf-versions.sh
```
Then paste the output into the Containerfile.

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
