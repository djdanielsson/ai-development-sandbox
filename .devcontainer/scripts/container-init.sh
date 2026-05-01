#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Container post-start initialization
# Configures SSH, GPG, Git signing, and pre-commit hooks.
# Runs every time the container starts (not just on first build).
# ------------------------------------------------------------------

# Restrictive umask so secret files (SSH keys, GPG keyring) are never
# created world-readable, even momentarily before chmod runs.
umask 077

# --- SSH Setup ---
mkdir -p /root/.ssh

# Embed GitHub's published SSH host keys directly instead of running ssh-keyscan,
# which is vulnerable to MITM on first use.
# Source: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
cat > /root/.ssh/known_hosts <<'KNOWN_HOSTS'
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
KNOWN_HOSTS
chmod 600 /root/.ssh/known_hosts

if [ -n "${AI_SSH_KEY_B64:-}" ]; then
  { printf '%s' "$AI_SSH_KEY_B64" | base64 -d | sed -n '/-----BEGIN/,/-----END/p'; echo; } > /root/.ssh/id_ed25519
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

# --- Scrub secret env vars ---
# Keys have been written to disk / imported into keyrings. The base64
# payloads are set via containerEnv (so they're available to postStartCommand)
# which means unset here only clears them for this process. The decoded keys
# on disk (/root/.ssh/id_ed25519, GPG keyring) are equally accessible, so
# the containerEnv exposure doesn't widen the attack surface.
unset AI_SSH_KEY_B64 AI_GPG_KEY_B64

# --- Pre-commit Hooks ---
if [ -d .git ]; then
  if [ ! -f .pre-commit-config.yaml ] && [ -f /tmp/default-pre-commit-config.yaml ]; then
    cp /tmp/default-pre-commit-config.yaml .pre-commit-config.yaml
  fi
  /root/.local/bin/prek install || echo "[init] WARNING: prek install failed."
fi

echo "[init] Container initialization complete."
