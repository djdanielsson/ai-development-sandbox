#!/usr/bin/env bash
set -euo pipefail

# Each tool is installed then its version is recorded.
# If a tool doesn't install cleanly, the build fails (set -e).

# echo "==> Installing Claude CLI..."
# curl -fsSL https://claude.ai/install.sh | bash
# claude --version 2>/dev/null || echo "WARNING: claude version check unavailable"

echo "==> Installing Cursor CLI..."
curl -fsSL https://cursor.com/install | bash
cursor --version 2>/dev/null || echo "WARNING: cursor version check unavailable"

# echo "==> Installing OpenCode CLI..."
# curl -fsSL https://opencode.ai/install | bash
# opencode --version 2>/dev/null || echo "WARNING: opencode version check unavailable"

echo "==> All tools installed."
