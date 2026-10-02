# Changelog fragments

One file per change: `changelog.d/<short-slug>.md`. Content is the bullet(s) exactly as they
would appear under `## Unreleased` in `CHANGELOG.md` (`- ` bullets, indented continuation lines).

- Do not edit `CHANGELOG.md` in a PR: every PR editing the same top lines conflicts with every other.
- `python tools/changelog.py --check` validates fragments (run by `tests/test_changelog_fragments.py`).
  `--check --base origin/main` also fails if the branch touched `CHANGELOG.md`.
- Release time (owner): `python tools/changelog.py --assemble` prints `CHANGELOG.md` with the
  fragments folded into `## Unreleased`, sorted by filename; `--write` rewrites the file. Then
  rename the heading to the version and delete the folded fragments.
