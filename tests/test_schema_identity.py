"""Schema `$id`s must live under a URI we control, and actually resolve there.

Every schema previously carried an `$id` under `https://chock.dev/…` -- a domain the
project does not own. It is registered by a third party and currently publishes no DNS at
all, which had two consequences once the repo went public:

  A reader or schema-aware editor that dereferenced an `$id` got NXDOMAIN.

  If that registrant ever pointed DNS somewhere, the `$id`s in a *governance* tool's schemas
  would resolve to content the project does not control. Low probability, bad failure mode,
  and exactly the kind of thing this project is supposed to notice about itself.

JSON Schema does not require an `$id` to be dereferenceable, and `validation.loading` builds
its store from the `$id` values in the files themselves, so nothing was broken. "Nothing is
broken" is a weaker claim than "the URI is honest", which is the bar here.

`$id`s are identifiers people pin, so moving them is a breaking change. These tests exist to
make the base a single reviewed decision rather than something a find-and-replace erodes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock.validation.loading import SCHEMA_STORE

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "src" / "chock" / "validation" / "schemas"

#: GitHub Pages for this repo. Chosen over buying a domain because it is provably ours --
#: anyone can verify the org owns it -- and because it costs nothing to keep correct.
CANONICAL_BASE = "https://open-coder-ai.github.io/chock/schemas/v0/"

#: Vendored third-party schemas keep their upstream `$id`. Re-`$id`ing a copy of someone
#: else's schema would claim authorship of it, and `$schema` in the Agent Plugins manifest is
#: a `const` that must match the canonical URL exactly.
FOREIGN = {"agent-plugins-1.0.0.plugin.schema.json"}


def _ours() -> list[Path]:
    return sorted(p for p in SCHEMA_DIR.glob("*.json") if p.name not in FOREIGN)


def test_every_schema_is_identified_under_a_uri_we_control() -> None:
    for path in _ours():
        schema_id = json.loads(path.read_text(encoding="utf-8")).get("$id")
        assert schema_id, f"{path.name} has no $id"
        assert schema_id.startswith(CANONICAL_BASE), f"{path.name}: {schema_id}"


def test_no_schema_references_a_domain_we_do_not_own() -> None:
    """A half-migrated tree resolves locally and is still wrong.

    `$ref`s are resolved from the local store, so a stale `chock.dev` reference next to
    a migrated `$id` would keep every test green while publishing a mixed, misleading set.
    """
    for path in _ours():
        assert "chock.dev" not in path.read_text(encoding="utf-8"), path.name


def test_the_id_matches_the_filename() -> None:
    """The published path is derived from the filename, so the two cannot disagree."""
    for path in _ours():
        schema_id = json.loads(path.read_text(encoding="utf-8"))["$id"]
        assert schema_id == CANONICAL_BASE + path.name, path.name


def test_every_ref_resolves_within_the_store() -> None:
    """The reason a wrong `$id` is survivable, asserted rather than assumed.

    Resolution is offline: `loading._build_schema_store` keys documents by their own `$id`.
    This test is what makes that a guarantee, so publishing can fail without validation
    failing with it.
    """
    refs: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("http"):
                refs.add(ref.split("#", 1)[0])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in _ours():
        walk(json.loads(path.read_text(encoding="utf-8")))

    missing = sorted(r for r in refs if r not in SCHEMA_STORE)
    assert not missing, f"$refs with no document in the store: {missing}"


def test_the_workflow_publishes_at_the_path_the_ids_name() -> None:
    """An `$id` is only honest if something serves a document there.

    Every other test here compares schemas against `CANONICAL_BASE`, so moving the constant
    keeps them all green -- while `schemas.yml` goes on copying to `_site/schemas/v0/` and
    every published `$id` 404s. The two halves of that contract live in different files and
    nothing joined them, which is the drift class this repo checks for everywhere else.

    Derived from the constant rather than hardcoded, so it follows a deliberate version bump
    and fails on an accidental one.
    """
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "schemas.yml").read_text(
        encoding="utf-8"
    )
    site_path = CANONICAL_BASE.removeprefix("https://open-coder-ai.github.io/chock/").rstrip("/")
    assert f"_site/{site_path}" in workflow, (
        f"schemas.yml does not stage schemas at _site/{site_path}, so every published $id would 404"
    )


@pytest.mark.parametrize("name", sorted(FOREIGN))
def test_vendored_schemas_keep_their_upstream_identity(name: str) -> None:
    schema_id = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))["$id"]
    assert not schema_id.startswith(CANONICAL_BASE), f"{name} must not be re-identified as ours"
