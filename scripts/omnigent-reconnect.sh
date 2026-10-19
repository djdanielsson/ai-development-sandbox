#!/bin/sh
set -eu

if ! command -v podman >/dev/null 2>&1; then
  echo "Required command not found: podman" >&2
  exit 1
fi

if ! podman container exists omnigent-host; then
  echo "Omnigent runner host container 'omnigent-host' was not found." >&2
  echo "Start the local stack with: sh scripts/omnigent-up.sh" >&2
  exit 1
fi

sessions=$(podman ps \
  --filter label=io.omnigent.managed=true \
  --filter status=running \
  --format '{{.Names}} ({{.Label "io.omnigent.session-name"}})')

if [ -n "$sessions" ]; then
  echo "Running managed session containers:"
  printf '%s\n' "$sessions"
else
  echo "No running managed session containers found."
fi

echo "Restarting the Omnigent runner host to reconnect it to the server..."
podman restart omnigent-host
echo "Runner host restarted. Check Omnigent to confirm the sessions are online."
