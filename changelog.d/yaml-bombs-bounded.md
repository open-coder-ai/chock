- **Hardening: repo YAML cannot hang or crash the guidance server or `chock check`.** Only string entries
  of `policies.disabled` are read (an alias-built nested value is no longer stringified), and
  the guidance config's nesting limit is measured on parser events, so compact block nesting is refused
  like bracket and indent nesting.
