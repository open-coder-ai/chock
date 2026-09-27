"""A pack's lockfile hash is its source, not the bytecode Python leaves beside it.

A script gate runs its implementation out of the pack directory, so the first gate run writes
`__pycache__/` there -- per interpreter version, and more of it as more rules are imported. The
hash counted it: the first real agent-kit run on Windows had `chock check` report the
java-security pack as changed after the agent's own tool calls ran the gate, with nobody having
touched a file in it.
"""

from __future__ import annotations

from pathlib import Path

from chock.lock import compute_pack_hash


def _pack(tmp_path: Path) -> Path:
    pack = tmp_path / "java-security"
    (pack / "implementations" / "engine").mkdir(parents=True)
    (pack / "manifest.yaml").write_text("id: java-security\n", encoding="utf-8")
    (pack / "implementations" / "engine" / "rule.py").write_text("RULE = 1\n", encoding="utf-8")
    return pack


def test_bytecode_written_by_a_gate_run_leaves_the_hash_alone(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    before = compute_pack_hash(pack)
    cache = pack / "implementations" / "engine" / "__pycache__"
    cache.mkdir()
    (cache / "rule.cpython-314.pyc").write_bytes(b"\x00bytecode")
    (pack / "implementations" / "stray.pyc").write_bytes(b"\x00legacy layout")
    (pack / "implementations" / "stray.pyo").write_bytes(b"\x00optimised")
    assert compute_pack_hash(pack) == before


def test_a_change_to_the_source_still_changes_the_hash(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    before = compute_pack_hash(pack)
    (pack / "implementations" / "engine" / "rule.py").write_text("RULE = 2\n", encoding="utf-8")
    assert compute_pack_hash(pack) != before
