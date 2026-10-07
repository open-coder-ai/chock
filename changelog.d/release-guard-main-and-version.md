- **Release: the tag workflow refuses a tag that is off `main` or not `v` + the version.**
  `release.yml`'s guard now also checks that the tagged commit is on `main`. The PyPI job refuses
  unless the build produced exactly that version's sdist and wheel. Each job now declares only
  the permissions it needs (workflow default `{}`). PyPI publishing stays in `release.yml`
  (trusted publisher: workflow `release.yml`, environment `pypi`) with its build-provenance
  attestation.
