#!/bin/sh
# Optional hardware acceleration for the Android emulator.
#   host:      runs as initializeCommand in the workspace folder. Docker maps the
#              selected node to /dev/kvm: the host KVM device when present,
#              otherwise /dev/null, so hosts without KVM still start.
#   container: runs at container start. Removes the /dev/null placeholder and
#              lets the non-root user open a real KVM device.
set -eu
node=${VOMAR_KVM_NODE:-/dev/kvm}
case "${1:-host}" in
host)
    device=${VOMAR_KVM_DEVICE:-/dev/kvm}
    [ -c "$device" ] || device=/dev/null
    mkdir -p _test/devcontainer
    ln -sfn "$device" _test/devcontainer/kvm
    ;;
container)
    # KVM is character device 10:232; anything else is the placeholder.
    if [ -c "$node" ] && [ "$(stat -L -c %t:%T "$node")" = "a:e8" ]; then
        sudo chmod 0666 "$node"
    else
        sudo rm -f "$node"
    fi
    ;;
*)
    echo "usage: kvm.sh [host|container]" >&2
    exit 2
    ;;
esac
