#!/usr/bin/env bash
set -euo pipefail
#
# Resolves the latest available version for each DNF package in the Containerfile
# and prints an updated DNF_PACKAGES block you can paste in.
#
# Usage: Run inside the container (or any Fedora system matching the base image):
#   bash scripts/update-dnf-versions.sh
#

PACKAGES=(
  podman curl git tar sudo procps-ng findutils gh zsh fzf eza zoxide
  vim-enhanced gettext-envsubst jq unzip nodejs
)

# shellcheck disable=SC1003
echo 'ARG DNF_PACKAGES="\'
for pkg in "${PACKAGES[@]}"; do
  resolved=$(dnf repoquery --latest-limit=1 --qf '%{name}-%{epoch}:%{version}-%{release}' "$pkg" 2>/dev/null | head -1)
  # Strip "0:" epoch prefix (dnf convention for epoch=0)
  resolved="${resolved//-0:/-}"
  if [ -z "$resolved" ]; then
    echo "    # WARNING: could not resolve $pkg" >&2
    echo "    $pkg \\"
  else
    echo "    ${resolved} \\"
  fi
done
echo '"'
echo ""
echo "# Paste the above block into the Containerfile, replacing the existing DNF_PACKAGES ARG."
