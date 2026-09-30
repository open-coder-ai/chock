"""A guard's hashes cover what it ships, not the bytecode Python leaves beside it once it has run.

A .py guard that imports a sibling package makes Python write __pycache__ into implementations/.
Hashing that made the lockfile drift the first time anything ran the guard.
"""

from __future__ import annotations

from pathlib import Path

from chock.registry.core import compute_script_hashes
from chock.validation.checks_determinism import _compute_script_hashes

MANIFEST = {"artifact": "rule", "hook": {"script": {"on": ["commit"]}}}


def _policy(tmp_path: Path) -> Path:
    impl = tmp_path / "implementations"
    (impl / "helper").mkdir(parents=True)
    (impl / "guard.py").write_text("import helper\n", encoding="utf-8")
    (impl / "helper" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    return tmp_path


def test_bytecode_beside_a_guard_is_not_hashed(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    before = compute_script_hashes(policy, MANIFEST)
    for cache in (policy / "implementations" / "helper" / "__pycache__", policy / "implementations" / "__pycache__"):
        cache.mkdir()
        (cache / "__init__.cpython-312.pyc").write_bytes(b"\x00bytecode")
    (policy / "implementations" / "stray.pyc").write_bytes(b"\x00bytecode")

    assert compute_script_hashes(policy, MANIFEST) == before
    assert set(before) == {"guard.py", "helper/__init__.py"}


def test_the_determinism_check_hashes_the_same_files_as_the_lock(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    cache = policy / "implementations" / "helper" / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-312.pyc").write_bytes(b"\x00bytecode")

    assert _compute_script_hashes(policy, MANIFEST) == compute_script_hashes(policy, MANIFEST)


def test_a_shipped_file_change_still_changes_the_hash(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    before = compute_script_hashes(policy, MANIFEST)
    (policy / "implementations" / "helper" / "__init__.py").write_text("X = 2\n", encoding="utf-8")
    assert compute_script_hashes(policy, MANIFEST) != before
