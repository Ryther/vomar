#!/bin/sh
set -eu

usage() {
    echo "usage: run-analysis.sh {mesh|zigbee} [--clean] [--dry-run]" >&2
    exit 64
}

[ "$#" -ge 1 ] || usage
target=$1
shift
case "$target" in
    mesh|zigbee) ;;
    *) echo "run-analysis.sh: unknown target: $target" >&2; usage ;;
esac

clean=0
dry_run=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --clean) clean=1 ;;
        --dry-run) dry_run=1 ;;
        *) echo "run-analysis.sh: unknown option: $1" >&2; usage ;;
    esac
    shift
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
preflight_json=$(python3 "$script_dir/preflight.py" --target "$target" --json)

json_field() {
    printf '%s' "$preflight_json" | python3 -c \
        'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

source_path=$repo/$(json_field source_path)
source_relative=$(json_field source_path)
source_sha256=$(json_field sha256)
image_base=$(json_field image_base)
reset_handler=$(json_field reset_handler)
analyze_headless=$(json_field analyze_headless)
[ "$analyze_headless" != "None" ] && [ -x "$analyze_headless" ] || {
    echo "run-analysis.sh: analyzeHeadless is unavailable" >&2
    exit 1
}

git_common_dir=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)
common_repo=$(CDPATH= cd -- "$(dirname -- "$git_common_dir")" && pwd -P)
branch_name=$(git -C "$repo" branch --show-current | tr -c 'A-Za-z0-9_-' '-' | sed 's/-$//')
[ -n "$branch_name" ] || branch_name=detached
project_parent=$common_repo/work/ghidra/$branch_name
project_dir=$project_parent/$target
output_parent=$repo/analysis/$target
staging_dir=$output_parent/.generated-staging
generated_dir=$output_parent/generated
script_path=$script_dir/ghidra_scripts

assert_child() {
    child=$1
    parent=$2
    case "$child" in
        "$parent"/*) ;;
        *) echo "run-analysis.sh: unsafe path rejected: $child" >&2; exit 1 ;;
    esac
}
assert_child "$project_dir" "$project_parent"
assert_child "$staging_dir" "$output_parent"
assert_child "$generated_dir" "$output_parent"

set -- "$analyze_headless" "$project_dir" "$target" \
    -import "$source_path" \
    -overwrite \
    -loader BinaryLoader \
    -processor ARM:LE:32:Cortex \
    -loader-baseAddr "$image_base" \
    -scriptPath "$script_path" \
    -postScript ExportProgramMetadata.java "$staging_dir" "$target" \
        "$source_relative" "$source_sha256" "$image_base" "$reset_handler" \
    -postScript ExportFunctions.java "$staging_dir" \
    -postScript ExportFunctionFingerprints.java "$staging_dir" \
    -postScript ExportStrings.java "$staging_dir" \
    -postScript ExportPeripheralReferences.java "$staging_dir" \
        "$script_dir/nrf52840_peripherals.json" \
    -postScript ExportSelectedDecompilation.java "$staging_dir" "$target" \
        "$script_dir/decompile_targets.json"

if [ "$dry_run" -eq 1 ]; then
    printf '%s' "$1"
    shift
    for argument in "$@"; do
        printf ' %s' "$argument"
    done
    printf '\n'
    exit 0
fi

mkdir -p "$project_parent" "$output_parent" "$script_path"
if [ "$clean" -eq 1 ]; then
    rm -rf -- "$project_dir" "$staging_dir"
fi
rm -rf -- "$staging_dir"
mkdir -p "$project_dir" "$staging_dir"

if ! "$@"; then
    rm -rf -- "$staging_dir"
    exit 1
fi

for expected_export in program.json functions.tsv function_fingerprints.tsv call_edges.tsv strings.tsv string_xrefs.tsv peripheral_refs.tsv; do
    if [ ! -f "$staging_dir/$expected_export" ]; then
        echo "run-analysis.sh: missing expected export: $expected_export" >&2
        rm -rf -- "$staging_dir"
        exit 1
    fi
done
if [ ! -f "$staging_dir/decompilation/index.tsv" ]; then
    echo "run-analysis.sh: missing expected export: decompilation/index.tsv" >&2
    rm -rf -- "$staging_dir"
    exit 1
fi

rm -rf -- "$generated_dir"
mv -- "$staging_dir" "$generated_dir"
