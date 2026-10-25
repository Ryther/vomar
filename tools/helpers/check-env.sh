#!/usr/bin/env bash
set -u

printf '%-24s %s\n' "tool" "location/version"
printf '%-24s %s\n' "------------------------" "----------------------------------------"

for cmd in git codex java javac python3 rg jq arm-none-eabi-gcc gdb-multiarch openocd protoc ghidra analyzeHeadless pyghidraRun; do
  if command -v "$cmd" >/dev/null 2>&1; then
    case "$cmd" in
      codex) version="$(codex --version 2>/dev/null | head -n1)" ;;
      java) version="$(java -version 2>&1 | head -n1)" ;;
      javac) version="$(javac -version 2>&1 | head -n1)" ;;
      python3) version="$(python3 --version 2>&1 | head -n1)" ;;
      arm-none-eabi-gcc) version="$(arm-none-eabi-gcc --version 2>&1 | head -n1)" ;;
      gdb-multiarch) version="$(gdb-multiarch --version 2>&1 | head -n1)" ;;
      openocd) version="$(openocd --version 2>&1 | head -n1)" ;;
      protoc) version="$(protoc --version 2>&1 | head -n1)" ;;
      *) version="$(command -v "$cmd")" ;;
    esac
    printf '%-24s %s\n' "$cmd" "$version"
  else
    printf '%-24s MISSING\n' "$cmd"
  fi
done

printf '\nGHIDRA_HOME=%s\n' "${GHIDRA_HOME:-unset}"
printf 'DISPLAY=%s\n' "${DISPLAY:-unset}"
printf 'WORKSPACE=%s\n' "${WORKSPACE:-unset}"
