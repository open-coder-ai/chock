#!/usr/bin/env bash
# Generated from README.md's Quick start block by tools/quickstart_block.py.
# Edit the README, not this file -- .github/workflows/quickstart.yml regenerates
# and diffs this file against the README on every push and pull request.
set -euo pipefail

pip install chock==1.2.0

git init -q demo && cd demo
chock init .                       # wiring only, no policies
chock add scan-secrets --skip-compile
chock sync --repo . --ci           # compile, install hooks, add the CI gate
