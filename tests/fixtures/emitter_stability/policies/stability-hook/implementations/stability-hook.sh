#!/usr/bin/env bash
# Frozen fixture guard: its only job is to be emitted identically by every patch
# release. Do not improve it. See test_emitter_stability.py.
set -eu
full="$*"
case "$full" in
    *frozen-forbidden-token*)
        echo "BLOCKED: frozen fixture token matched." >&2
        exit 1
        ;;
esac
exit 0
