#!/bin/sh
# Run from any directory; native state and credentials stay out of Git.
set -eu
repo_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 "$repo_dir/smolvm-bridge/manage.py" "$@"
