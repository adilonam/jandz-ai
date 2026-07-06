FROM mcr.microsoft.com/devcontainers/python:3.8

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Base image ships a Yarn apt source whose key can go stale and breaks `apt update`.
# This project does not need Yarn from apt; drop it so apt stays usable.
RUN sudo rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn-stable.list \
    && sudo rm -f /etc/apt/sources.list.d/*yarn*

# Install ngrok CLI, GitHub CLI, and PostgreSQL client
RUN curl -fsSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
        | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
    && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
        | sudo tee /etc/apt/sources.list.d/ngrok.list >/dev/null \
    && sudo mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null \
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null \
    && sudo apt-get update \
    && sudo apt-get install -y --no-install-recommends ngrok gh postgresql-client \
    && sudo rm -rf /var/lib/apt/lists/*

