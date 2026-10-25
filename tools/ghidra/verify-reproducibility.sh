#!/bin/sh
set -eu

usage() {
    echo "usage: verify-reproducibility.sh [mesh|zigbee|all]" >&2
    exit 64
}

target=${1:-all}
[ "$#" -le 1 ] || usage
case "$target" in
    mesh|zigbee|all) ;;
    *) usage ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
git_common_dir=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)
common_repo=$(CDPATH= cd -- "$(dirname -- "$git_common_dir")" && pwd -P)
runner=${GHIDRA_RUNNER:-$script_dir/run-analysis.sh}
output_root=${GHIDRA_OUTPUT_ROOT:-$repo/analysis}
repro_root=${GHIDRA_REPRO_ROOT:-$common_repo/work/ghidra/reproducibility}
[ -x "$runner" ] || { echo "verify-reproducibility.sh: runner is not executable" >&2; exit 1; }
mkdir -p "$repro_root"

temporary=
cleanup() {
    if [ -n "$temporary" ]; then
        case "$temporary" in
            "$repro_root"/*) rm -rf -- "$temporary" ;;
            *) echo "verify-reproducibility.sh: unsafe cleanup path rejected" >&2 ;;
        esac
    fi
}
trap cleanup EXIT HUP INT TERM

hash_tree() {
    tree=$1
    destination=$2
    (
        cd "$tree"
        find . -type f -print | LC_ALL=C sort | while IFS= read -r file; do
            sha256sum "$file"
        done
    ) > "$destination"
}

verify_target() {
    current=$1
    temporary=$(mktemp -d "$repro_root/$current.XXXXXX")
    first=$temporary/first
    second=$temporary/second
    mkdir -p "$first" "$second"

    "$runner" "$current" --clean
    generated=$output_root/$current/generated
    [ -d "$generated" ] || {
        echo "$current: generated output directory is missing" >&2
        return 1
    }
    cp -a "$generated"/. "$first"/

    "$runner" "$current" --clean
    cp -a "$generated"/. "$second"/

    hash_tree "$first" "$temporary/first.sha256"
    hash_tree "$second" "$temporary/second.sha256"
    if ! diff -u "$temporary/first.sha256" "$temporary/second.sha256" \
            > "$temporary/difference"; then
        echo "$current: reproducibility mismatch" >&2
        sed -n '1,12p' "$temporary/difference" >&2
        return 1
    fi
    echo "$current: reproducible"
    rm -rf -- "$temporary"
    temporary=
}

case "$target" in
    mesh) verify_target mesh ;;
    zigbee) verify_target zigbee ;;
    all)
        verify_target mesh
        verify_target zigbee
        ;;
esac
