#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# install-tools.sh — installs all non-dnf tools into the container image.
#
# Architecture is detected at run time so the same script works for both
# x86_64 and aarch64 builds.
#
# Pinned versions live here (not in the Containerfile) so the companion
# GitHub Actions update workflows only need to patch this one file.
# ---------------------------------------------------------------------------

# --- Pinned versions (update workflows patch these lines) ---
OHMYZSH_COMMIT="e42ac8c57bc7eb473b689ffcbb98473ba45dbab8"
PREK_VERSION="v0.3.8"
KUBECTL_VERSION="v1.36.0"
HELM_VERSION="v4.1.4"
TERRAFORM_VERSION="v1.15.1"
ARGOCD_VERSION="v3.3.9"
KUSTOMIZE_VERSION="v5.8.1"
OC_VERSION="latest"
VIRTCTL_VERSION="v1.8.2"
TKN_VERSION="v0.44.1"

# --- Architecture detection ---
ARCH_RAW=$(uname -m)
case "$ARCH_RAW" in
  x86_64)
    ARCH="amd64"          # kubectl, helm, terraform, argocd, kustomize, virtctl
    ARCH_OC="x86_64"      # OpenShift mirror path segment
    ARCH_TKN="x86_64"     # Tekton tarball naming
    ;;
  aarch64)
    ARCH="arm64"
    ARCH_OC="aarch64"
    ARCH_TKN="aarch64"
    ;;
  *)
    echo "ERROR: unsupported architecture $ARCH_RAW" >&2
    exit 1
    ;;
esac

echo "==> Detected architecture: $ARCH_RAW (normalized: $ARCH)"

# --- Oh My Zsh (pinned to commit) ---
echo "==> Installing Oh My Zsh @ ${OHMYZSH_COMMIT}..."
git clone --depth 1 https://github.com/ohmyzsh/ohmyzsh.git /root/.oh-my-zsh
cd /root/.oh-my-zsh
git fetch --depth 1 origin "$OHMYZSH_COMMIT"
git checkout "$OHMYZSH_COMMIT"
cd /

# --- prek (pre-commit runner) ---
echo "==> Installing prek ${PREK_VERSION}..."
curl --proto '=https' --tlsv1.2 -LsSf \
  "https://github.com/j178/prek/releases/download/${PREK_VERSION}/prek-installer.sh" | sh

# --- kubectl ---
echo "==> Installing kubectl ${KUBECTL_VERSION}..."
curl -sSL -o /usr/local/bin/kubectl \
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl"
chmod +x /usr/local/bin/kubectl
kubectl version --client

# --- helm ---
echo "==> Installing helm ${HELM_VERSION}..."
curl -sSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz" \
  | tar -xz --strip-components=1 -C /usr/local/bin "linux-${ARCH}/helm"
helm version

# --- terraform ---
echo "==> Installing terraform ${TERRAFORM_VERSION}..."
TERRAFORM_VERSION_BARE="${TERRAFORM_VERSION#v}"
curl -sSL -o /tmp/terraform.zip \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION_BARE}/terraform_${TERRAFORM_VERSION_BARE}_linux_${ARCH}.zip"
unzip -o /tmp/terraform.zip -d /usr/local/bin
rm /tmp/terraform.zip
terraform version

# --- ArgoCD CLI ---
echo "==> Installing argocd ${ARGOCD_VERSION}..."
curl -sSL -o /usr/local/bin/argocd \
  "https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/argocd-linux-${ARCH}"
chmod +x /usr/local/bin/argocd
argocd version --client

# --- kustomize ---
echo "==> Installing kustomize ${KUSTOMIZE_VERSION}..."
curl -sSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_${ARCH}.tar.gz" \
  | tar -xz -C /usr/local/bin kustomize
kustomize version

# --- OpenShift CLI (oc) ---
echo "==> Installing oc (OpenShift CLI, ${OC_VERSION})..."
curl -sSL "https://mirror.openshift.com/pub/openshift-v4/${ARCH_OC}/clients/ocp/${OC_VERSION}/openshift-client-linux.tar.gz" \
  | tar -xz -C /usr/local/bin oc
oc version --client

# --- virtctl (KubeVirt) ---
echo "==> Installing virtctl ${VIRTCTL_VERSION}..."
curl -sSL -o /usr/local/bin/virtctl \
  "https://github.com/kubevirt/kubevirt/releases/download/${VIRTCTL_VERSION}/virtctl-${VIRTCTL_VERSION}-linux-${ARCH}"
chmod +x /usr/local/bin/virtctl
virtctl version --client

# --- tkn (Tekton CLI) ---
echo "==> Installing tkn ${TKN_VERSION}..."
TKN_VERSION_BARE="${TKN_VERSION#v}"
curl -sSL "https://github.com/tektoncd/cli/releases/download/${TKN_VERSION}/tkn_${TKN_VERSION_BARE}_Linux_${ARCH_TKN}.tar.gz" \
  | tar -xz -C /usr/local/bin tkn
tkn version

# --- AI agent CLIs ---
echo "==> Installing Cursor CLI..."
curl --proto '=https' --tlsv1.2 -fsSL https://cursor.com/install | bash
cursor --version 2>/dev/null || echo "WARNING: cursor version check unavailable"

echo "==> All tools installed."
