FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git openssh-client ripgrep xz-utils unzip zip build-essential cmake ninja-build pkg-config libssl-dev zlib1g-dev libffi-dev libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev tk-dev uuid-dev openjdk-17-jdk-headless openjdk-21-jdk-headless python3 python3-venv openocd binutils-arm-none-eabi libusb-1.0-0 libdbus-1-3 libglib2.0-0 libfontconfig1 fonts-dejavu-core libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libxcb-xinerama0 xvfb sudo && rm -rf /var/lib/apt/lists/*
COPY .devcontainer/toolchain.json /tmp/toolchain.json
COPY tools/dev/bootstrap.py /tmp/bootstrap.py
RUN python3 /tmp/bootstrap.py image /tmp/toolchain.json && ln -s python3 /opt/python/bin/python
ENV PATH="/opt/python/bin:/opt/node/bin:/opt/assistants/node_modules/.bin:$PATH"
COPY .devcontainer/assistants/package*.json /opt/assistants/
RUN cd /opt/assistants && npm ci --omit=dev && codex --version && opencode --version && claude --version && devcontainer --version
RUN userdel -r ubuntu 2>/dev/null || true
RUN groupadd --force plugdev && useradd --create-home --uid 1000 --shell /bin/bash vscode && echo 'vscode ALL=(root) NOPASSWD:ALL' > /etc/sudoers.d/vscode && mkdir -p /home/vscode/.config/gh /home/vscode/.cache/vomar /home/vscode/.local/share/vomar-agents /home/vscode/.codex /home/vscode/.gradle && chown -R vscode:vscode /home/vscode
USER vscode
WORKDIR /workspaces/vomar
