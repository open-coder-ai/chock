#!/usr/bin/env bash
# Generated from README.md's Quick start block by tools/quickstart_block.py.
# Edit the README, not this file -- .github/workflows/quickstart.yml regenerates
# and diffs this file against the README on every push and pull request.
set -euo pipefail

pip install chock==1.1.0

git init -q demo && cd demo
chock init .                       # wiring only, no policies
chock add scan-secrets --ref 1e60d211c1bb767152c6ab0167932da06ab3a10f --verify-sha c7cf363c6eb8a8ed47287beef9c06fe76dfd2d9c0ccc203fe74e32fba0e92a94 --skip-compile
chock sync --repo . --ci           # compile, install hooks, add the CI gate
