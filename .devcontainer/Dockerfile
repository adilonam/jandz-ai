FROM mcr.microsoft.com/devcontainers/python:3.8

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Base image ships a Yarn apt source whose key can go stale and breaks `apt update`.
# This project does not need Yarn from apt; drop it so apt stays usable.
RUN sudo rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn-stable.list \
    && sudo rm -f /etc/apt/sources.list.d/*yarn*

# Install ngrok CLI from the official apt repository
RUN curl -fsSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
        | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
    && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
        | sudo tee /etc/apt/sources.list.d/ngrok.list >/dev/null \
    && sudo apt-get update \
    && sudo apt-get install -y --no-install-recommends ngrok \
    && sudo rm -rf /var/lib/apt/lists/*
