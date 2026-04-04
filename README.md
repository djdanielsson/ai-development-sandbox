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

1. Copy this entire directory to your preferred config location (default in script is `~/.config/devcontainers/fedora-sandbox/`).
2. Append the `aibox` function from `.zshrc` into your `~/.zshrc`.
3. Run `source ~/.zshrc`.

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
| DNF packages | Exact `name-version-release` strings | Run `scripts/update-dnf-versions.sh` inside the container |
| Oh My Zsh | Git commit SHA | Update `OHMYZSH_COMMIT` ARG in Containerfile |
| prek | Release version tag | Update `PREK_VERSION` ARG in Containerfile |
| VS Code extensions | Pinned `publisher.name@version` | Update versions in `devcontainer.json` |
| AI CLIs (Claude, Cursor, OpenCode) | Installed via `curl\|bash` (see note below) | Rebuild to pick up new versions |

**Note on AI CLI installers:** Claude, Cursor, and OpenCode are installed via vendor `curl|bash` scripts which cannot be version-pinned. The install script logs installed versions during build. Review the build log to audit what was installed.

## Keeping Dependencies Updated

This repo uses **GitHub Dependabot** (`.github/dependabot.yml`) to automatically open PRs when:

- The Fedora base image has a new digest
- DevContainer features are updated (if any are added)

For DNF packages, run the update script inside a running container:
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

This means the container boundary is **not a strong security boundary**. The sandbox relies on Podman's rootless mode and the ephemeral nature of the container for isolation.

### Secret Handling

- Secrets are fetched from Vaultwarden via Touch ID and passed as environment variables
- The `postStartCommand` writes the SSH key to the container filesystem (inside a volume)
- GPG keys are imported into the container's GPG keyring (inside a volume)
- On the host, shell variables are explicitly `unset` when the launcher function exits; however, this does **not** guarantee the memory pages are zeroed by the OS

### SSH Host Key Verification

GitHub's SSH host keys are embedded directly in `scripts/container-init.sh` rather than using `ssh-keyscan` at runtime. This prevents MITM attacks during first connection. If GitHub rotates their keys, update the `known_hosts` block in that script.
