#!/bin/sh
__MARKER__
# Source: __SOURCE_REL__
set -e
repo_root="$(git rev-parse --show-toplevel)"
bash "$repo_root/__SOURCE_REL__" "$@"
