- **`chock install --selection` builds a chock.sh selection into one Claude Code plugin.** It takes a
  `chock.selection.yaml`, a URL whose `#s=` fragment carries the selection, or the bare code, checks it against
  the new `selection.schema.json` (schema 1, `client: claude-code` only), fetches the catalog at the pinned
  40-hex commit with `chock add`'s fetch code, and refuses a policy whose id is missing, whose version differs
  from `registry.yaml`, or whose sha256 differs (the `chock add --verify-sha` hash). The policies are merged into
  one plugin, `chock-guardrails`, in a local marketplace (`~/.chock/marketplace`, or `--dest`). It prints each
  policy's Claude Code grade, the plugin's (the weakest), the selection warnings (twins, duplicates,
  allowlist-first policies, observe and advisory policies; data in `chock/install/data/warnings.json`) and the
  two `claude plugin` commands; `--apply` runs them. A re-run rebuilds beside the old directory and swaps it in.
