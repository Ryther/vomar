#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
prefix=${XDG_DATA_HOME:-"$HOME/.local/share"}
runtime="$prefix/vomar/runtime"
[ -f "$source_dir/.vomar-runtime" ] || { echo 'Missing Vomar package marker' >&2; exit 1; }
[ ! -e "$runtime" ] || { echo 'Uninstall the existing owned runtime first; private data is preserved.' >&2; exit 1; }
for launcher in "$HOME/.local/bin/vomar" "$HOME/.local/bin/vomar-gui"; do
  [ ! -e "$launcher" ] && [ ! -L "$launcher" ] || { echo 'An existing launcher must be reviewed before installation.' >&2; exit 1; }
done
mkdir -p "$prefix/vomar" "$HOME/.local/bin" "$prefix/applications"
cp -R "$source_dir" "$runtime"
ln -s "$runtime/vomar" "$HOME/.local/bin/vomar"
ln -s "$runtime/Vomar" "$HOME/.local/bin/vomar-gui"
exec_path=$(printf '%s' "$runtime/Vomar" | sed 's/[\\`"$]/\\&/g; s/%/%%/g')
printf '[Desktop Entry]\nType=Application\nName=Vomar\nExec="%s"\nTerminal=false\nCategories=Utility;\n' "$exec_path" > "$prefix/applications/org.openvimar.updater.desktop.desktop"
echo 'Vomar installed for the current user. Originals and sessions are stored separately.'
