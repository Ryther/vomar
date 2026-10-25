#!/bin/sh
set -eu
prefix=${XDG_DATA_HOME:-"$HOME/.local/share"}
runtime="$prefix/vomar/runtime"
[ -f "$runtime/.vomar-runtime" ] || { echo 'No owned Vomar runtime found' >&2; exit 1; }
for name in vomar vomar-gui; do
  launcher="$HOME/.local/bin/$name"
  case "$name" in vomar) expected="$runtime/vomar";; *) expected="$runtime/Vomar";; esac
  if [ -L "$launcher" ] && [ "$(readlink "$launcher")" = "$expected" ]; then rm -- "$launcher"; fi
done
rm -rf -- "$runtime"
rm -f -- "$prefix/applications/org.openvimar.updater.desktop.desktop"
echo 'Vomar runtime removed. Private sessions, originals and credentials were preserved.'
