- Hardening: release and CI builds use the hash-pinned `setuptools` from `requirements/` with
  `--no-build-isolation`; a test fails if a workflow builds or editable-installs with isolation.
