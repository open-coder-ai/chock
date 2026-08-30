#!/usr/bin/env bash
# Adds the DCO `Signed-off-by` trailer to a commit message when it is missing,
# mirroring what `git commit -s` does. Wired as a pre-commit `commit-msg` hook
# (see CONTRIBUTING.md) so a first-time contributor never discovers the DCO
# requirement via a CI rejection and a rebase.
set -euo pipefail

msg_file="$1"
name="$(git config user.name || true)"
email="$(git config user.email || true)"

if [ -z "$name" ] || [ -z "$email" ]; then
  echo "dco-signoff: set 'git config user.name' and 'user.email' first" >&2
  exit 1
fi

trailer="Signed-off-by: $name <$email>"

if grep -qF "$trailer" "$msg_file"; then
  exit 0
fi

if grep -q "^Signed-off-by: .\+<.\+@.\+>" "$msg_file"; then
  # A trailer already exists (different identity, e.g. a co-author amend) -- don't duplicate.
  exit 0
fi

printf '\n%s\n' "$trailer" >> "$msg_file"
