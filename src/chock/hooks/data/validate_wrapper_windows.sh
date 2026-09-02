#!/usr/bin/env bash
__MARKER__
hook_dir="$(cd "$(dirname "$0")" && pwd)"
script="$hook_dir/__SCRIPT_NAME__"
if command -v cygpath >/dev/null 2>&1; then script="$(cygpath -w "$script")"; fi
powershell.exe -ExecutionPolicy Bypass -File "$script" "$@"
