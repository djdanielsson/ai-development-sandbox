from omnigent.onboarding.sandboxes.registry import (
    SandboxProviderContribution,
    SandboxProviderMetadata,
)

from .config import PodmanConfig


def get_contribution() -> SandboxProviderContribution:
    return SandboxProviderContribution(
        name="omnigent-podman-provider",
        providers={
            "podman": SandboxProviderMetadata(
                name="podman",
                launcher_class=(
                    "omnigent.community.sandbox.podman.launcher:PodmanSandboxLauncher"
                ),
                config_model=PodmanConfig,
            ),
        },
    )
