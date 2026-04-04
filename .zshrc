#!/usr/bin/env zsh
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
export GPG_TTY=$(tty)
__gitca() {
  git add .
  git commit -am "$(git status | grep -e 'modified:\|deleted:\|added:\|renamed:\|new file:')"
  git push origin $(git status | grep -i "on branch" | awk '{ print $3}')
}

# ==============================================================================
# AI Box Launcher - Biometric Sandbox
# ==============================================================================
aibox() {
  echo "👆 Requesting Vaultwarden Touch ID..."

  local -x BW_SESSION=$(bwbio unlock --raw)

  if [ -z "$BW_SESSION" ] || [[ "$BW_SESSION" == *"error"* ]]; then
    echo "❌ Touch ID canceled or failed."
    return 1
  fi

  echo "🔑 Vault unlocked! Fetching zero-footprint secrets..."

#  local -x ANTHROPIC_API_KEY=$(bw get password "Anthropic API")|| { echo "❌ Failed to fetch Anthropic API key."; return 1; }
  local -x CURSOR_API_KEY=$(bw get password "Cursor API") || { echo "❌ Failed to fetch Cursor API key."; return 1; }
  local -x AI_GITHUB_TOKEN=$(bw get password "AI GitHub PAT")|| { echo "❌ Failed to fetch GitHub PAT."; return 1; }

  local GITHUB_PAT_JSON
  GITHUB_PAT_JSON=$(bw get item "AI GitHub PAT") || { echo "❌ Failed to fetch GitHub PAT item."; return 1; }
  AI_GIT_NAME=$(echo "$GITHUB_PAT_JSON" | jq -r '.fields[] | select(.name == "Git Name").value')
  AI_GIT_EMAIL=$(echo "$GITHUB_PAT_JSON" | jq -r '.fields[] | select(.name == "Git Email").value')
  unset GITHUB_PAT_JSON

  local -x AI_SSH_KEY_B64=$(bw get notes "AI SSH Key" | base64 -b 0) || { echo "❌ Failed to fetch SSH key."; return 1; }
  local -x AI_GPG_KEY_B64=$(bw get notes "AI GPG Key" | base64 -b 0) || { echo "❌ Failed to fetch GPG key."; return 1; }

  local CONFIG_PATH="$HOME/.config/devcontainers/fedora-sandbox/devcontainer.json"
  echo "🚀 Starting AI Sandbox for: $(pwd)"

  if devcontainer up --workspace-folder . --config "$CONFIG_PATH" --docker-path podman; then
      echo "💻 Attaching to sandbox terminal..."
      devcontainer exec --workspace-folder . --config "$CONFIG_PATH" --docker-path podman zsh
  else
      echo "❌ Failed to start the AI Sandbox."
      unset BW_SESSION ANTHROPIC_API_KEY CURSOR_API_KEY AI_GITHUB_TOKEN
      unset AI_GIT_NAME AI_GIT_EMAIL AI_SSH_KEY_B64 AI_GPG_KEY_B64
  fi
}

# Attach to an existing AI Sandbox
aiattach() {
  # Grab the IDs of all running dev containers
  local containers=$(podman ps -q --filter "label=devcontainer.local_folder")

  if [ -z "$containers" ]; then
    echo "❌ No active AI Sandboxes found."
    return 0
  fi

  echo "🔍 Active AI Sandboxes:"

  # Arrays to hold our menu data
  local i=1
  local id_array=()
  local name_array=()

  # Loop through IDs to get the human-readable folder names
  for id in $(echo "$containers"); do
    local folder=$(podman inspect --format='{{index .Config.Labels "devcontainer.local_folder"}}' "$id")
    local name=$(basename "$folder")

    echo "  $i) $name"
    id_array[$i]="$id"
    name_array[$i]="$name"
    i=$((i + 1))
  done

  echo "  q) Quit"
  echo -n "Select a sandbox to attach to: "
  read choice

  if [[ "$choice" == "q" || "$choice" == "Q" ]]; then
    echo "Aborted."
    return 0
  fi

  local target_id="${id_array[$choice]}"
  local target_name="${name_array[$choice]}"

  if [[ -n "$target_id" ]]; then
    echo "🚀 Attaching to $target_name..."
    # Drop cleanly into the running container natively!
    podman exec -it "$target_id" zsh
  else
    echo "⚠️ Invalid selection."
  fi
}

alias -- gitca=__gitca
alias -- gitcm='git add . ;git gen-commit'
alias -- ll='eza -l'
alias -- ls=eza
alias -- lt='eza -a --tree --level=1'
alias -- devc-update='curl -fsSL https://raw.githubusercontent.com/devcontainers/cli/main/scripts/install.sh | sh -s -- --update'
ZSH_HIGHLIGHT_HIGHLIGHTERS+=()
