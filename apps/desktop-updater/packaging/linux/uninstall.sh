#!/bin/sh
set -eu
prefix=${XDG_DATA_HOME:-"$HOME/.local/share"}
runtime="$prefix/vomar/runtime"
[ -f "$runtime/.vomar-runtime" ] || { echo 'No owned Vomar runtime found' >&2; exit 1; }
for name in vomar vomar-gui; do
  launcher="$HOME/.local/bin/$name"
  case "$name" in vomar) expected="$runtime/vomar-cli";; *) expected="$runtime/Vomar";; esac
  if [ -L "$launcher" ] && [ "$(readlink "$launcher")" = "$expected" ]; then rm -- "$launcher"; fi
done
for size in 16 24 32 48 64 128 256 512; do
  relative="${size}x${size}/apps/org.openvimar.updater.desktop.png"
  icon="$prefix/icons/hicolor/$relative"
  if [ ! -L "$icon" ] && cmp -s "$runtime/icons/$relative" "$icon"; then rm -- "$icon"; fi
done
rm -rf -- "$runtime"
rm -f -- "$prefix/applications/org.openvimar.updater.desktop.desktop"
echo 'Vomar runtime removed. Private sessions, originals and credentials were preserved.'
