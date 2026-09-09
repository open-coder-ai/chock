#!/usr/bin/env bash
# Generated from README.md's Quick start block by tools/quickstart_block.py.
# Edit the README, not this file -- .github/workflows/quickstart.yml regenerates
# and diffs this file against the README on every push and pull request.
set -euo pipefail

pip install chock

git init -q demo && cd demo
chock init .                       # wiring only — no policies, no opinions
chock add scan-secrets             # pull a policy from the catalog
chock sync --repo .                # compile + install it
