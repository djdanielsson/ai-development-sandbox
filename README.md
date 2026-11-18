# AI development environments

Two local setups for working with AI coding agents:

| Setup | Purpose | Documentation |
|---|---|---|
| Devcontainer | Ephemeral Fedora sandbox launched with `aibox`, with Podman, developer tools, and AI CLIs. | [Setup and usage](devcontainer/README.md) |
| Omnigent | Local Omnigent server and runner hosts, with per-project Podman containers or smolvm microVMs. | [Setup and usage](omnigent/README.md) |

Both setups retrieve credentials from Vaultwarden through Touch ID on macOS.

## Repository layout

- `devcontainer/`: container definition, host launcher, shell configuration, and initialization scripts.
- `omnigent/`: Compose stack, runner image, providers, policies, agent configuration, and management scripts.
- `.github/`: CI, dependency updates, and bot PR auto-merge workflows.

## Automated maintenance

Dependabot updates container dependencies, GitHub Actions, and pre-commit hooks.
Scheduled workflows update CLI tools, extensions, Oh My Zsh, prek, SSH host keys,
and the digest of the latest Omnigent server image.

Bot update PRs merge only after CI and the SBOM workflow succeed for the current
revision and no other registered check is failing or pending. Branch protection
and required reviews still apply. Workflow-created PRs explicitly dispatch checks
using the built-in GitHub token; no extra bot service or PAT is needed.

Omnigent updates are checked daily. After pulling a merged update, run
`sh omnigent/scripts/omnigent-up.sh` to rebuild against the updated image.

Existing installs should update their shell source and devcontainer symlink to
use `devcontainer/`; see the [devcontainer installation steps](devcontainer/README.md#installation--usage).
The Omnigent Compose project remains `ai-development`, preserving volume and
network names. Private `.smolvm-bridge/` state remains at the repository root.
