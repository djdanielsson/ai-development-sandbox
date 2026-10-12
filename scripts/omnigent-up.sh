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

PODMAN_SOCKET="$PODMAN_SOCKET" podman compose up -d --build

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
