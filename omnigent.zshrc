export ZSH=/root/.oh-my-zsh
ZSH_THEME="robbyrussell"
plugins=(git)
source "$ZSH/oh-my-zsh.sh"

if [[ -r /run/omnigent-secrets/github_token ]]; then
  export GH_TOKEN="$(< /run/omnigent-secrets/github_token)"
fi

eval "$(zoxide init zsh)"
if [[ -o interactive && -t 0 ]]; then
  eval "$(fzf --zsh)"
fi
