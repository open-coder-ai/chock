"""Drift between a committed agent-hook config and what sync would install over it."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from chock import vendors
from chock.hooks.in_agent_install import agent_hooks_rel, install_hooks


def _wired_config_rel(vendor: str) -> Path:
    """The file `install_hooks` writes for `vendor`: chock's own file, or the vendor's config."""
    if vendor in vendors.AGENT_HOOKS_VENDORS:
        return agent_hooks_rel(vendor)
    return Path(vendors.config_path(vendor))


def _canonical(path: Path) -> object:
    """The JSON at `path` with list order ignored: sync appends its entries after a vendor's own."""

    def norm(node: object) -> object:
        if isinstance(node, dict):
            return {key: norm(value) for key, value in node.items()}
        if isinstance(node, list):
            return sorted((norm(item) for item in node), key=lambda item: json.dumps(item, sort_keys=True))
        return node

    try:
        return norm(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return path.read_bytes()


def wiring_differences(repo_root: Path | str, wired: tuple[str, ...]) -> list[str]:
    """Where a committed config of a `wired` vendor differs from what sync would install over it.

    Runs the real installers on a scratch copy of the committed configs, so entries that are
    not chock's survive on both sides and only chock's own entries can differ. A config that
    was never written (skip-hooks, not yet synced) has nothing committed to be stale.
    """
    repo_root = Path(repo_root)
    rels = {vendor: _wired_config_rel(vendor) for vendor in wired}
    diffs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="chock-wiringcheck-") as tmp:
        shadow = Path(tmp)
        if (repo_root / ".chock" / "compiled").exists():
            shutil.copytree(repo_root / ".chock" / "compiled", shadow / ".chock" / "compiled")
        for rel in rels.values():
            if (repo_root / rel).is_file():
                (shadow / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo_root / rel, shadow / rel)
        try:
            for vendor in wired:
                install_hooks(shadow, vendor)
        except ValueError:
            return diffs  # an unreadable config is reported by its own check, not as drift

        for rel in sorted(set(rels.values())):
            expected, actual = shadow / rel, repo_root / rel
            if not actual.is_file():
                continue
            if not expected.is_file():
                diffs.append(f"stale: {rel.as_posix()}")
            elif _canonical(expected) != _canonical(actual):
                diffs.append(f"differs: {rel.as_posix()}")
    return diffs
