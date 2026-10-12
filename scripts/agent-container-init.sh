#!/usr/bin/env bash
set -euo pipefail

umask 077
mkdir -p /root/.ssh /root/.gnupg
chmod 700 /root/.ssh /root/.gnupg

if [[ -n "${AI_GITHUB_TOKEN:-}" ]]; then
  mkdir -p /run/omnigent-secrets
  chmod 700 /run/omnigent-secrets
  printf '%s' "$AI_GITHUB_TOKEN" > /run/omnigent-secrets/github_token
  chmod 600 /run/omnigent-secrets/github_token
  # Omnigent's shell helper intentionally strips credential environment
  # variables, so make gh's normal per-container credential store available
  # as well. Keep it private; this container is isolated to one session.
  mkdir -p /root/.config/gh
  chmod 700 /root/.config/gh
  env -u GH_TOKEN gh auth login --hostname github.com --git-protocol https \
    --with-token < /run/omnigent-secrets/github_token >/dev/null
fi

# Pin GitHub's public host keys in the sandbox rather than trusting a
# first-connection ssh-keyscan from the network.
cat > /root/.ssh/known_hosts <<'KNOWN_HOSTS'
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
KNOWN_HOSTS
chmod 600 /root/.ssh/known_hosts

if [[ -n "${AI_SSH_KEY_B64:-}" ]]; then
  printf '%s' "$AI_SSH_KEY_B64" | base64 --decode \
    | sed -n '/-----BEGIN/,/-----END/p' > /root/.ssh/id_ed25519
  test -s /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519
  cat > /root/.ssh/config <<'SSH_CONFIG'
Host github.com
  User git
  IdentityFile /root/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking yes
  UserKnownHostsFile /root/.ssh/known_hosts
SSH_CONFIG
  chmod 600 /root/.ssh/config
  git config --global url."git@github.com:".insteadOf "https://github.com/"
fi

if [[ -n "${AI_GPG_KEY_B64:-}" ]]; then
  printf '%s' "$AI_GPG_KEY_B64" | base64 --decode | gpg --batch --import >/dev/null
fi

git config --global user.name "${AI_GIT_NAME:-AI Agent}"
git config --global user.email "${AI_GIT_EMAIL:-noreply@example.com}"

GPG_KEY=$(gpg --list-secret-keys --with-colons 2>/dev/null \
  | awk -F: '$1 == "sec" { print $5; exit }')
if [[ -n "$GPG_KEY" ]]; then
  git config --global commit.gpgsign true
  git config --global user.signingkey "$GPG_KEY"
else
  git config --global commit.gpgsign false
fi

# The private key material is now in the sandbox's private home. Keep the
# one token gh needs for API operations, but remove the bootstrap payloads.
unset AI_GITHUB_TOKEN AI_SSH_KEY_B64 AI_GPG_KEY_B64 AI_GIT_NAME AI_GIT_EMAIL
echo "Agent sandbox credentials initialized."
