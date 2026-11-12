#!/bin/sh
set -eu

if ! command -v podman >/dev/null 2>&1; then
  echo "Required command not found: podman" >&2
  exit 1
fi

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

mode=${1:---dry-run}
case "$mode" in
  --dry-run|--apply) ;;
  *)
    echo "Usage: $0 [--dry-run|--apply]" >&2
    exit 2
    ;;
esac

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
server_url=${OMNIGENT_CLEANUP_SERVER_URL:-http://127.0.0.1:8000}

exec podman exec -i omnigent-server python - "$mode" "$server_url" \
  < "$script_dir/omnigent-cleanup-stale-containers.py"
