#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Container post-start initialization
# Configures SSH, GPG, Git signing, and pre-commit hooks.
# Runs every time the container starts (not just on first build).
# ------------------------------------------------------------------

# --- SSH Setup ---
mkdir -p /root/.ssh
chmod 700 /root/.ssh

# Embed GitHub's published SSH host keys directly instead of running ssh-keyscan,
# which is vulnerable to MITM on first use.
# Source: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
cat > /root/.ssh/known_hosts <<'KNOWN_HOSTS'
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Gy4Pjc2HCT+UGRrSMEsOGZpFb9BJnHxjRMoF+HJgcqFNgmRwIUyb4VG+0bRYKEg0/dBQKJFgjMHQg78CZp3qaETO8qHD5vBIqSRoIh/pOoQC4VKBYkGCjLFdarCBnG0kRO1jcA75kEOSCWFCbdEq9/cWEjPz0FPvCAL2JMi/VModyr4b4FNhH0NMx6J/5MIBn/92a3JJMg0yWTcGJMBpLEkbzLUaRIchNVblH8QhxBBBEAGFibB0NheVLiXHbHLfbBN6b0MHcOHR1+LNTpBnaFgelEPq/1O5eVaalPMbGSVT9B4xhQMVpB5yBBjBBkEMbvCKRWRIosNn3b7sNP4LaxneDkH3A38dYbHGbHMGm8zt4DRkFfUEfrS75rS+r29XpoJHnKPnGIhoKkabSGMxGIlaKEnJW5TtRl9frrMuGo0NXADFE3cJhNf0FnMU0x8SAIdEYPKQ=
KNOWN_HOSTS
chmod 600 /root/.ssh/known_hosts

if [ -n "${AI_SSH_KEY_B64:-}" ]; then
  echo "$AI_SSH_KEY_B64" | base64 -d > /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519
  echo "[init] SSH key configured."
else
  echo "[init] WARNING: AI_SSH_KEY_B64 not set, SSH key not configured."
fi

# --- GPG Setup ---
if [ -n "${AI_GPG_KEY_B64:-}" ]; then
  echo "$AI_GPG_KEY_B64" | base64 -d | gpg --batch --import 2>/dev/null
  echo "[init] GPG key imported."
else
  echo "[init] WARNING: AI_GPG_KEY_B64 not set, GPG key not imported."
fi

GPG_KEY=$(gpg --list-secret-keys --with-colons 2>/dev/null | grep '^sec:' | head -n 1 | cut -d ':' -f 5 || true)

# --- Git Config ---
git config --global user.name "${AI_GIT_NAME:-AI Agent}"
git config --global user.email "${AI_GIT_EMAIL:-noreply@example.com}"
git config --global url."git@github.com:".insteadOf "https://github.com/"

if [ -n "$GPG_KEY" ]; then
  git config --global commit.gpgsign true
  git config --global user.signingkey "$GPG_KEY"
  echo "[init] Git commit signing enabled with key $GPG_KEY."
else
  echo "[init] WARNING: No GPG key found, commit signing disabled."
fi

# --- Pre-commit Hooks ---
if [ -d .git ]; then
  if [ ! -f .pre-commit-config.yaml ] && [ -f /tmp/default-pre-commit-config.yaml ]; then
    cp /tmp/default-pre-commit-config.yaml .pre-commit-config.yaml
  fi
  /root/.local/bin/prek install || echo "[init] WARNING: prek install failed."
fi

echo "[init] Container initialization complete."
