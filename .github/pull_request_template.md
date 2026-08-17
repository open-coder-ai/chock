## What

<!-- One-paragraph summary of the change and which finding/requirement it addresses. -->

## Definition of done

- [ ] `chock check` → 0 errors, 0 warnings, 0 infos
- [ ] `chock check --only matrix` passes; matrix updated in this PR if behavior changed
- [ ] `chock sync --repo . --check` clean (compiled artifacts match their manifests)
- [ ] `chock check --only verify` clean (lockfile matches packs and compiled artifacts)
- [ ] Registry rescanned; no stale entries
- [ ] `pytest -q` green; new checks have attack + ordinary-data tests
- [ ] `pytest acceptance/ -c acceptance/pytest.ini --rootdir=acceptance` green if packaging,
      `init`, `add` or hook installation changed
- [ ] Existing artifacts migrated in this PR if a check was added/extended
- [ ] Touched manifests: version bump + changelog entry
- [ ] `ruff check .` and `ruff format --check .` clean

## Claims

- [ ] No surface is described as enforcing more than it installs. If this PR changes what is
      emitted or installed, `INSTALLED_SURFACES`, the coverage table, and
      `docs/enforcement-surfaces.md` all agree.
