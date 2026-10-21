#!/bin/sh
set -eu

if ! command -v podman >/dev/null 2>&1; then
  echo "Required command not found: podman" >&2
  exit 1
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
server_url=${OMNIGENT_SERVER_URL:-http://omnigent:8000}
containers=$(podman ps \
  --filter label=io.omnigent.managed=true \
  --filter label=io.omnigent.provider=podman \
  --filter status=running \
  --format '{{.ID}} {{.Names}} {{.Label "io.omnigent.session-name"}}')

if [ -z "$containers" ]; then
  echo "No running managed Podman session containers found."
  exit 0
fi

echo "Checking running managed session containers:"
printf '%s\n' "$containers" | while IFS=' ' read -r container_id container_name session_name; do
  [ -n "$container_id" ] || continue
  echo "  $container_name ($session_name)"
done

failed=0
while IFS=' ' read -r container_id container_name session_name; do
  [ -n "$container_id" ] || continue

  if ! podman exec -i "$container_id" python - "$server_url" "$session_name" \
    < "$script_dir/omnigent-reconnect-container.py"; then
    echo "Reconnect failed for $container_name ($session_name)." >&2
    failed=1
  fi
done <<EOF
$containers
EOF

if [ "$failed" -ne 0 ]; then
  echo "One or more managed session hosts remain offline." >&2
  exit 1
fi

echo "All running managed session hosts are connected."
