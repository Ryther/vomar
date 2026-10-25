#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
INPUTS="${ROOT}/inputs"
OUTPUT="${ROOT}/analysis/input-inventory.tsv"

printf 'sha256\tsize_bytes\tpath\n' > "$OUTPUT"
while IFS= read -r -d '' file; do
  hash="$(sha256sum "$file" | awk '{print $1}')"
  size="$(stat -c '%s' "$file")"
  relative="${file#${ROOT}/}"
  printf '%s\t%s\t%s\n' "$hash" "$size" "$relative" >> "$OUTPUT"
done < <(find "$INPUTS" -type f ! -name README.md -print0 | sort -z)

printf 'Wrote %s\n' "$OUTPUT"
