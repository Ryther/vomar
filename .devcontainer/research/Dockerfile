FROM vomar-development:local
USER root
RUN apt-get update && apt-get install -y --no-install-recommends gdb-multiarch binwalk wireshark-common && rm -rf /var/lib/apt/lists/*
USER vscode
# Install a reviewed Ghidra release separately; never import firmware automatically.
