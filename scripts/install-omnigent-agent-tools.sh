#!/usr/bin/env bash
set -euo pipefail

ARCH_RAW=$(uname -m)
case "$ARCH_RAW" in
  x86_64)
    ARCH=amd64
    ARCH_OC=x86_64
    ARCH_TKN=x86_64
    ARCH_EZA=x86_64
    NODE_ARCH=x64
    ;;
  aarch64)
    ARCH=arm64
    ARCH_OC=aarch64
    ARCH_TKN=aarch64
    ARCH_EZA=aarch64
    NODE_ARCH=arm64
    ;;
  *)
    echo "Unsupported architecture: $ARCH_RAW" >&2
    exit 1
    ;;
esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  bash ca-certificates curl git gnupg jq libatomic1 openssh-client tar tmux unzip vim xz-utils zsh

# Use the vendors' apt repositories for these packages so each image build
# picks up the latest published package, not Debian's potentially older copy.
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://apt.releases.hashicorp.com/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/hashicorp-archive-keyring.gpg
chmod 0644 /etc/apt/keyrings/hashicorp-archive-keyring.gpg
. /etc/os-release
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com ${VERSION_CODENAME} main" \
  > /etc/apt/sources.list.d/hashicorp.list

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
chmod 0644 /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  > /etc/apt/sources.list.d/github-cli.list

apt-get update
apt-get install -y --no-install-recommends gh terraform

echo '==> Installing latest stable kubectl'
KUBECTL_VERSION=$(curl -fsSL https://dl.k8s.io/release/stable.txt)
curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" \
  -o /usr/local/bin/kubectl
chmod 0755 /usr/local/bin/kubectl

echo '==> Installing latest Helm 4'
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4 \
  | bash

echo '==> Installing latest Argo CD CLI'
curl -fsSL "https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-${ARCH}" \
  -o /usr/local/bin/argocd
chmod 0755 /usr/local/bin/argocd

echo '==> Installing latest Kustomize'
curl -fsSL https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh \
  | bash
install -m 0755 kustomize /usr/local/bin/kustomize
rm kustomize

echo '==> Installing latest OpenShift CLI'
curl -fsSL "https://mirror.openshift.com/pub/openshift-v4/${ARCH_OC}/clients/ocp/latest/openshift-client-linux.tar.gz" \
  | tar -xz -C /usr/local/bin oc
chmod 0755 /usr/local/bin/oc

echo '==> Installing latest virtctl stable release'
VIRTCTL_VERSION=$(curl -fsSL https://storage.googleapis.com/kubevirt-prow/release/kubevirt/kubevirt/stable.txt)
curl -fsSL "https://github.com/kubevirt/kubevirt/releases/download/${VIRTCTL_VERSION}/virtctl-${VIRTCTL_VERSION}-linux-${ARCH}" \
  -o /usr/local/bin/virtctl
chmod 0755 /usr/local/bin/virtctl

echo '==> Installing latest Tekton CLI'
TKN_RELEASE=$(curl -fsSL https://api.github.com/repos/tektoncd/cli/releases/latest)
TKN_ASSET=$(jq -r --arg arch "$ARCH_TKN" '.assets[] | select(.name | test("_Linux_" + $arch + "\\.tar\\.gz$")) | .browser_download_url' <<< "$TKN_RELEASE" | head -n 1)
test -n "$TKN_ASSET"
curl -fsSL "$TKN_ASSET" | tar -xz -C /usr/local/bin tkn

echo '==> Installing latest eza'
mkdir -p /tmp/eza
curl -fsSL "https://github.com/eza-community/eza/releases/latest/download/eza_${ARCH_EZA}-unknown-linux-gnu.tar.gz" \
  | tar -xz -C /tmp/eza
install -m 0755 /tmp/eza/eza /usr/local/bin/eza
rm -rf /tmp/eza

echo '==> Installing latest fzf'
FZF_RELEASE=$(curl -fsSL https://api.github.com/repos/junegunn/fzf/releases/latest)
FZF_VERSION=$(jq -r .tag_name <<< "$FZF_RELEASE")
FZF_VERSION=${FZF_VERSION#v}
curl -fsSL "https://github.com/junegunn/fzf/releases/download/v${FZF_VERSION}/fzf-${FZF_VERSION}-linux_${ARCH}.tar.gz" \
  | tar -xz -C /usr/local/bin fzf

echo '==> Installing latest zoxide'
curl -fsSL https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | sh
install -m 0755 /root/.local/bin/zoxide /usr/local/bin/zoxide

echo '==> Installing latest Node.js and bundled npm'
NODE_VERSION=$(curl -fsSL https://nodejs.org/dist/index.json | jq -r '.[0].version')
curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
  | tar -xJ --strip-components=1 -C /usr/local --wildcards "node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/node" "node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/npm" "node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/npx" "node-${NODE_VERSION}-linux-${NODE_ARCH}/lib/node_modules/npm/*"

echo '==> Installing latest uv and tox'
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --upgrade tox

echo '==> Installing latest Oh My Zsh'
git clone --depth 1 https://github.com/ohmyzsh/ohmyzsh.git /root/.oh-my-zsh

# Log versions at build time so a rebuild clearly shows what floating tags
# resolved to. These CLIs and dependencies intentionally remain unpinned.
kubectl version --client
helm version --short
terraform version
argocd version --client
kustomize version
oc version --client
virtctl version --client
tkn version
gh --version | head -n 1
zsh --version
eza --version | head -n 1
fzf --version
zoxide --version
vim --version | head -n 1
jq --version
uv --version
tox --version
node --version
npm --version

apt-get clean
rm -rf /var/lib/apt/lists/* /root/.cache/uv
