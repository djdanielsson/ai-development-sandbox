# Host-side AI Sandbox launcher. Source from ~/.zshrc:
#   source "$AIBOX_REPO/aibox.zsh"

__aibox_sync_repo() {
  local config_path="$HOME/.config/devcontainers/fedora-sandbox/devcontainer.json"
  local config_dir="${config_path:h}"
  local repo_root="${AIBOX_REPO:-${config_dir:A:h}}"

  [[ -d "$repo_root/.git" ]] || return 0

  echo "🔄 Pulling latest sandbox config from $repo_root..."
  if ! git -C "$repo_root" pull --ff-only; then
    echo "⚠️  git pull failed — continuing with current config."
  fi
}

aibox() {
  local CONFIG_PATH="$HOME/.config/devcontainers/fedora-sandbox/devcontainer.json"
  __aibox_sync_repo

  echo "👆 Requesting Vaultwarden Touch ID..."

  local -x BW_SESSION=$(bwbio unlock --raw)

  if [ -z "$BW_SESSION" ] || [[ "$BW_SESSION" == *"error"* ]]; then
    echo "❌ Touch ID canceled or failed."
    return 1
  fi

  echo "🔑 Vault unlocked! Fetching zero-footprint secrets..."

  local -x CURSOR_API_KEY=$(bw get password "Cursor API") || { echo "❌ Failed to fetch Cursor API key."; return 1; }
  local -x AI_GITHUB_TOKEN=$(bw get password "AI GitHub PAT")|| { echo "❌ Failed to fetch GitHub PAT."; return 1; }

  local GITHUB_PAT_JSON
  GITHUB_PAT_JSON=$(bw get item "AI GitHub PAT") || { echo "❌ Failed to fetch GitHub PAT item."; return 1; }
  local -x AI_GIT_NAME=$(echo "$GITHUB_PAT_JSON" | jq -r '.fields[] | select(.name == "Git Name").value')
  local -x AI_GIT_EMAIL=$(echo "$GITHUB_PAT_JSON" | jq -r '.fields[] | select(.name == "Git Email").value')
  unset GITHUB_PAT_JSON

  local -x AI_SSH_KEY_B64=$(bw get notes "AI SSH Key" | base64 -b 0) || { echo "❌ Failed to fetch SSH key."; return 1; }
  local -x AI_GPG_KEY_B64=$(bw get notes "AI GPG Key" | base64 -b 0) || { echo "❌ Failed to fetch GPG key."; return 1; }

  echo "🚀 Starting AI Sandbox for: $(pwd)"

  local rc=0
  if devcontainer up --workspace-folder . --config "$CONFIG_PATH" --docker-path podman; then
      echo "💻 Attaching to sandbox terminal..."
      devcontainer exec --workspace-folder . --config "$CONFIG_PATH" --docker-path podman zsh
  else
      echo "❌ Failed to start the AI Sandbox."
      rc=1
  fi

  # Always scrub secrets from the host shell, regardless of success or failure.
  unset BW_SESSION CURSOR_API_KEY AI_GITHUB_TOKEN
  unset AI_GIT_NAME AI_GIT_EMAIL AI_SSH_KEY_B64 AI_GPG_KEY_B64
  return $rc
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

    # Dynamically inject the Mac host username during the native attach!
    podman exec -e AIBOX_HOST_USER="$USER" -it "$target_id" zsh
  else
    echo "⚠️ Invalid selection."
  fi
}
