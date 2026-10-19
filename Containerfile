FROM ghcr.io/omnigent-ai/omnigent-server:latest

USER root

ENV PATH="/root/.opencode/bin:/root/.local/bin:${PATH}" \
    SHELL=/bin/zsh \
    DO_NOT_TRACK=1 \
    OMNIGENT_ANALYTICS=0 \
    OMNIGENT_DISABLE_TELEMETRY=true \
    OMNIGENT_TELEMETRY_ENABLED=false \
    OTEL_SDK_DISABLED=true \
    OTEL_TRACES_EXPORTER=none \
    OTEL_METRICS_EXPORTER=none \
    OTEL_LOGS_EXPORTER=none

# Install the current upstream versions of the project/developer CLIs in the
# runner image inherited by each managed project sandbox. No nested Podman.
COPY scripts/install-omnigent-agent-tools.sh /tmp/install-omnigent-agent-tools.sh
RUN bash /tmp/install-omnigent-agent-tools.sh && \
    rm /tmp/install-omnigent-agent-tools.sh
COPY omnigent.zshrc /root/.zshrc
COPY scripts/agent-container-init.sh /usr/local/bin/agent-container-init.sh
COPY scripts/write-omnigent-secrets.py /usr/local/bin/write-omnigent-secrets.py
RUN chmod 0755 /usr/local/bin/agent-container-init.sh /usr/local/bin/write-omnigent-secrets.py

# Register the server-wide sub-agent model/harness policy.
COPY policies/same_subagent_model.py /opt/omnigent-local-policies/omnigent_same_subagent_model.py
ENV PYTHONPATH="/opt/omnigent-local-policies:${PYTHONPATH}"

# Install the local Podman managed-sandbox provider.
COPY podman-provider /tmp/omnigent-podman-provider
RUN pip install /tmp/omnigent-podman-provider && \
    rm -rf /tmp/omnigent-podman-provider

# Install Codex CLI in the runner image. The host auth file is mounted at runtime.
RUN CODEX_NON_INTERACTIVE=1 curl --proto '=https' --tlsv1.2 -fsSL \
    https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh && \
    codex --version

COPY codex-config.toml /root/.codex/config.toml

# Install OpenCode CLI and set the OpenCode Zen default model.
RUN curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path && \
    opencode --version
COPY opencode-config.json /root/.config/opencode/opencode.json

# Install Cursor Agent CLI; authentication is supplied at runtime.
RUN curl --proto '=https' --tlsv1.2 -fsSL https://cursor.com/install | bash && \
    cursor-agent --version && \
    ln -sf /root/.local/bin/codex /usr/local/bin/codex && \
    ln -sf /root/.local/bin/cursor-agent /usr/local/bin/cursor-agent && \
    ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    ln -sf /opt/venv/bin/omni /usr/local/bin/omni && \
    ln -sf /opt/venv/bin/omni /usr/local/bin/omnigent && \
    omni --version
