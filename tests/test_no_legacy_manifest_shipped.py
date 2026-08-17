"""Regression guard: no `policy.yaml` files ship under .agents/ or src/chock/packs/."""

from __future__ import annotations

from pathlib import Path


def test_no_legacy_manifest_files_in_shipped_dirs() -> None:
    """Policy manifests ship as manifest.yaml, not policy.yaml."""
    repo_root = Path(__file__).resolve().parents[1]
    shipped = {repo_root / ".agents", repo_root / "src" / "chock" / "packs"}
    legacy: list[str] = []
    for root in shipped:
        if not root.exists():
            continue
        for path in root.rglob("policy.yaml"):
            rel = path.relative_to(repo_root).as_posix()
            legacy.append(rel)
    assert not legacy, f"Shipped policy.yaml files found (must be manifest.yaml): {legacy}"
