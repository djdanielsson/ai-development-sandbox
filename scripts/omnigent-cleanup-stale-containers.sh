#!/bin/sh
set -eu

if ! command -v podman >/dev/null 2>&1; then
  echo "Required command not found: podman" >&2
  exit 1
fi

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [--dry-run|--apply|--delete]" >&2
  exit 2
fi

mode=${1:---dry-run}
case "$mode" in
  --dry-run|--apply|--delete) ;;
  *)
    echo "Usage: $0 [--dry-run|--apply|--delete]" >&2
    exit 2
    ;;
esac

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
server_url=${OMNIGENT_CLEANUP_SERVER_URL:-http://127.0.0.1:8000}

cleanup_phase() {
  phase=$1
  failed=0
  podman exec -i omnigent-server python - "$phase" "$server_url" \
    < "$script_dir/omnigent-cleanup-stale-containers.py" || failed=1
  if [ -f "$script_dir/../.smolvm-bridge/profile.json" ]; then
    python3 "$script_dir/../smolvm-bridge/maintenance.py" prune "$phase" || failed=1
  fi
  return "$failed"
}

if [ "$mode" = --delete ]; then
  # Finish stops for both providers before either provider rescans for deletion.
  # A failed stop/reconciliation phase prevents all deletion.
  cleanup_phase --apply || exit 1
  cleanup_phase --delete-stopped
else
  cleanup_phase "$mode"
fi
