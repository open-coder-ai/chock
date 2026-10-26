- **Hardening: `chock review` defines checks from the base only.** With a base ref, the built-in checks and
  the checks the base's `.chock/config.yaml` declares are the whole registry. A check a pull request adds
  to its own config, or a built-in it redefines there, is neither run nor part of `command_set_hash`.
  A check a pull request both adds and requires is not required of that pull request: `chock review require`
  prints that it is required from the merge on. Without a base ref the working tree still defines.
