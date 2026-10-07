- **Release: PyPI publishing moved to `.github/workflows/publish.yml`.** It runs on `v*` tags in the
  `pypi` environment with only `id-token: write` and `contents: read`, and refuses unless the tag
  equals `v` + the `pyproject.toml` version and the tagged commit is on `main`. It also refuses
  unless the build produced exactly that version's sdist and wheel. `release.yml` no longer
  publishes to PyPI (it builds binaries and the GitHub Release), so one tag publishes once. The
  PyPI trusted publisher must name workflow `publish.yml` and environment `pypi`. New releases
  are verified with their PyPI (PEP 740) attestation; see `SECURITY.md`.
