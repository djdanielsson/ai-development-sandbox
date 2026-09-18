#!/usr/bin/env zsh

# Bail out early for non-interactive shells (scripts, AI agent commands, pipes).
# This prevents Oh My Zsh, themes, and prompt tooling from polluting stdout or
# hanging on TTY operations when an agent runs shell commands.
[[ ! -o interactive ]] && return

export ZSH="$HOME/.oh-my-zsh"

# oh-my-zsh configuration
plugins=(git)

ZSH_THEME="agnoster"
source $ZSH/oh-my-zsh.sh

# History options should be set in .zshrc and after oh-my-zsh sourcing.
# See https://github.com/nix-community/home-manager/issues/177.
HISTSIZE="10000"
SAVEHIST="10000"

HISTFILE="$HOME/.zsh_history"
mkdir -p "$(dirname "$HISTFILE")"

setopt HIST_FCNTL_LOCK
unsetopt APPEND_HISTORY
setopt HIST_IGNORE_DUPS
unsetopt HIST_IGNORE_ALL_DUPS
unsetopt HIST_SAVE_NO_DUPS
unsetopt HIST_FIND_NO_DUPS
setopt HIST_IGNORE_SPACE
unsetopt HIST_EXPIRE_DUPS_FIRST
setopt SHARE_HISTORY
unsetopt EXTENDED_HISTORY
setopt autocd

export EDITOR=vim
export PATH="$HOME/.devcontainers/bin:$PATH"
export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
export GPG_TTY=$(tty 2>/dev/null || true)

if [[ -n "${AIBOX_REPO:-}" && -f "${AIBOX_REPO}/aibox.zsh" ]]; then
  source "${AIBOX_REPO}/aibox.zsh"
elif [[ -f "${${(%):-%x}:A:h}/aibox.zsh" ]]; then
  source "${${(%):-%x}:A:h}/aibox.zsh"
fi

__gitca() {
  git add .
  git commit -am "$(git status | grep -e 'modified:\|deleted:\|added:\|renamed:\|new file:')"
  git push origin $(git status | grep -i "on branch" | awk '{ print $3}')
}

# ==============================================================================
# AI Box Reverse Tunnel - Dynamically open ports to Mac Host
# ==============================================================================

tunnel() {
    echo -n "🔌 Enter the port number to expose (e.g. 8080): "
    read PORT

    # Validate input is a number
    if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
        echo "❌ Error: Port must be a number."
        return 1
    fi

    # Strict duplicate check using ${PORT} to prevent Bash boundary errors
    if ps aux | grep -q "[s]sh -f -N -R ${PORT}:localhost:${PORT}"; then
        echo "✅ Tunnel for port $PORT is already active!"
        return 0
    fi

    echo "🚀 Initiating reverse tunnel for port $PORT..."

    # Use strict ${} wrapping and quotes to guarantee the colon survives
    ssh -R "${PORT}:localhost:${PORT}" "$AIBOX_HOST_USER@host.containers.internal"

    if [ $? -eq 0 ]; then
        echo "✨ Success! Port $PORT is now mapped."
        echo "   Access it on your Mac at: http://localhost:$PORT"
        echo "   To stop this tunnel later, run: pkill -f 'ssh.*-R ${PORT}'"
    else
        echo "❌ Failed to create tunnel."
    fi
}

alias -- gitca=__gitca
alias -- gitcm='git add . ;git gen-commit'
alias -- ll='eza -l'
alias -- ls=eza
alias -- lt='eza -a --tree --level=1'
alias -- devc-update='curl --proto "=https" --tlsv1.2 -fsSL https://raw.githubusercontent.com/devcontainers/cli/main/scripts/install.sh | sh -s -- --update'
ZSH_HIGHLIGHT_HIGHLIGHTERS+=()
