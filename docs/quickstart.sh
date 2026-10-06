#!/usr/bin/env bash
# Generated from README.md's Quick start block by tools/quickstart_block.py.
# Edit the README, not this file -- .github/workflows/quickstart.yml regenerates
# and diffs this file against the README on every push and pull request.
set -euo pipefail

pip install "chock @ git+https://github.com/open-coder-ai/chock@992711af4cf8d4fd9c4c861f10ef6e53374d75d7"

git init -q demo && cd demo
chock init .                       # wiring only, no policies
chock add scan-secrets --ref 9a64623e30769c49d7011ec3f559592d84e3f657 --verify-sha 47ff46faf00e86089e79b868077ac2443e75bb879af7224190477d0c65e3360f --skip-compile
chock sync --repo . --ci           # compile, install hooks, add the CI gate
