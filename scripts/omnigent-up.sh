#!/bin/sh
set -eu

for command_name in bw bwbio jq podman; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

cleanup_secrets() {
  unset BW_SESSION CURSOR_API_KEY AI_GITHUB_TOKEN AI_GIT_NAME AI_GIT_EMAIL
  unset AI_SSH_KEY_B64 AI_GPG_KEY_B64
}
trap cleanup_secrets EXIT HUP INT TERM

echo "Requesting Vaultwarden Touch ID..."
BW_SESSION=$(bwbio unlock --raw)
if [ -z "$BW_SESSION" ] || printf '%s' "$BW_SESSION" | grep -qi 'error'; then
  echo "Vaultwarden unlock was canceled or failed." >&2
  exit 1
fi
export BW_SESSION

echo "Fetching runner credentials from Vaultwarden..."
CURSOR_API_KEY=$(bw get password "Cursor API")
AI_GITHUB_TOKEN=$(bw get password "AI GitHub PAT")
GITHUB_PAT_JSON=$(bw get item "AI GitHub PAT")
AI_GIT_NAME=$(printf '%s' "$GITHUB_PAT_JSON" | jq -r '.fields[]? | select(.name == "Git Name") | .value // empty')
AI_GIT_EMAIL=$(printf '%s' "$GITHUB_PAT_JSON" | jq -r '.fields[]? | select(.name == "Git Email") | .value // empty')
unset GITHUB_PAT_JSON
AI_SSH_KEY_B64=$(bw get notes "AI SSH Key" | base64 | tr -d '\n')
AI_GPG_KEY_B64=$(bw get notes "AI GPG Key" | base64 | tr -d '\n')

MACHINE=${PODMAN_MACHINE:-podman-machine-default}
MACHINE_UID=$(podman machine ssh "$MACHINE" id -u)
PODMAN_SOCKET=${OMNIGENT_PODMAN_SOCKET:-/run/user/${MACHINE_UID}/podman/podman.sock}

if ! podman machine ssh "$MACHINE" curl --connect-timeout 2 --max-time 3 -fsS \
  --unix-socket "$PODMAN_SOCKET" http://d/v1.40/_ping >/dev/null; then
  echo "Podman API socket is not ready at $PODMAN_SOCKET in machine $MACHINE" >&2
  exit 1
fi

BASE_IMAGE=ghcr.io/omnigent-ai/omnigent-server:latest

check_base_image_update() {
  local_arch=$(podman info --format '{{.Host.Arch}}')
  case "$local_arch" in
    aarch64) local_arch=arm64 ;;
    x86_64) local_arch=amd64 ;;
  esac

  if ! remote_manifest=$(podman manifest inspect "$BASE_IMAGE" 2>/dev/null); then
    echo "Could not check for an Omnigent server image update; continuing with the installed version." >&2
    return 0
  fi

  remote_manifest_digest=$(printf '%s' "$remote_manifest" | jq -r \
    --arg arch "$local_arch" \
    '.manifests[]? | select(.platform.os == "linux" and .platform.architecture == $arch) | .digest' \
    | head -n 1)
  if [ -n "$remote_manifest_digest" ] && [ "$remote_manifest_digest" != "null" ]; then
    if ! remote_image_manifest=$(podman manifest inspect "$BASE_IMAGE@$remote_manifest_digest" 2>/dev/null); then
      echo "Could not inspect the latest Omnigent image; continuing with the installed version." >&2
      return 0
    fi
    remote_config_digest=$(printf '%s' "$remote_image_manifest" | jq -r '.config.digest // empty')
  else
    remote_config_digest=$(printf '%s' "$remote_manifest" | jq -r '.config.digest // empty')
  fi
  if [ -z "$remote_config_digest" ]; then
    echo "Could not identify the Omnigent image for architecture $local_arch; continuing with the installed version." >&2
    return 0
  fi

  local_config_digest=$(podman image inspect "$BASE_IMAGE" --format '{{.Id}}' 2>/dev/null || true)
  if [ -n "$local_config_digest" ] && [ "$local_config_digest" = "$remote_config_digest" ]; then
    echo "Omnigent server image is up to date."
    return 0
  fi

  echo "A newer Omnigent server image is available."
  printf "Pull and install it now? [y/N] "
  read answer || answer=
  case "$answer" in
    y|Y|yes|YES|Yes)
      echo "Pulling the latest Omnigent server image and rebuilding the stack..."
      podman pull "$BASE_IMAGE"
      PODMAN_SOCKET="$PODMAN_SOCKET" podman compose build
      ;;
    *)
      echo "Keeping the installed Omnigent server image."
      ;;
  esac
}

check_base_image_update
PODMAN_SOCKET="$PODMAN_SOCKET" podman compose up -d
sh scripts/omnigent-reconnect.sh

# Keep secret values off the long-lived runner's container environment/config.
# Send them over stdin into a tmpfs inside omnigent-server instead.
printf '%s\n' \
  "$CURSOR_API_KEY" \
  "$AI_GITHUB_TOKEN" \
  "$AI_SSH_KEY_B64" \
  "$AI_GPG_KEY_B64" \
  "$AI_GIT_NAME" \
  "$AI_GIT_EMAIL" \
  | podman exec -i omnigent-server /usr/local/bin/write-omnigent-secrets.py

echo "Runner credentials loaded into tmpfs; new project sandboxes can now use them."
