- **Hardening: `chock review` defines checks from the base only.** With a base ref, the built-in checks and
  the checks the base's `.chock/config.yaml` declares are the whole registry. A check a pull request adds
  to its own config, or a built-in it redefines there, is neither run nor part of `command_set_hash`;
  `required_checks` still unions base and head, so a head can add a requirement but not a command. A new
  check must be merged to the base before it can be required. Without a base ref the working tree still defines.
