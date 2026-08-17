"""`chock sync` CLI implementation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.emit import write_generated
from chock.index.builder import build_entries, emit_warnings, max_tokens_for
from chock.index.render import render_index
from chock.scaffold.agents_md import is_stale as agents_md_is_stale
from chock.scaffold.agents_md import update_agents_md
from chock.scaffold.skills_bridge import update_skill_bridges

INDEX_PATH = ".agents/policies/INDEX.md"
EXTENDED_PATH = ".agents/policies/INDEX-extended.md"


def _disk_state(root: Path) -> tuple[str | None, str | None]:
    index_path = root / INDEX_PATH
    ext_path = root / EXTENDED_PATH
    main = index_path.read_text(encoding="utf-8") if index_path.exists() else None
    ext = ext_path.read_text(encoding="utf-8") if ext_path.exists() else None
    return main, ext


def _generate(root: Path):
    entries, warnings = build_entries(root)
    emit_warnings(warnings)
    max_tokens = max_tokens_for(root)
    return render_index(entries, max_tokens)


def _write(root: Path, output) -> None:
    index_path = root / INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if not index_path.exists() or index_path.read_text(encoding="utf-8") != output.main:
        write_generated(index_path, output.main)

    ext_path = root / EXTENDED_PATH
    if output.extended is not None:
        if not ext_path.exists() or ext_path.read_text(encoding="utf-8") != output.extended:
            write_generated(ext_path, output.extended)
    elif ext_path.exists():
        ext_path.unlink()
    update_agents_md(root / "AGENTS.md")
    update_skill_bridges(root)


def _report_cost(output) -> None:
    print(f"INDEX.md: ~{output.main_tokens} tokens (chars/4, max {output.max_tokens})")
    if output.extended is not None:
        print(f"INDEX-extended.md: ~{output.extended_tokens} tokens (demoted advise entries)")
    if output.warning:
        print(f"[WARN] {output.warning}", file=sys.stderr)


def is_stale(root: Path) -> tuple[bool, str | None]:
    """Return (stale, reason) without writing files."""
    output = _generate(root)
    main, ext = _disk_state(root)
    if main is None:
        return True, "INDEX.md is missing"
    if main != output.main:
        return True, "INDEX.md is stale"
    if ext != output.extended:
        return True, "INDEX-extended.md is stale"
    # AGENTS.md's managed form was rewritten by refresh but never checked, so a hand-inlined
    # per-policy block survived until someone happened to run refresh -- serving text
    # INDEX.md had already resolved differently.
    if agents_md_is_stale(root / "AGENTS.md"):
        return True, "AGENTS.md has drifted from its managed form"
    return False, None


def cmd_refresh(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate .agents/policies/INDEX.md and the AGENTS.md pointer")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the on-disk files differ from generated; do not write",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()

    try:
        output = _generate(root)
    except OSError as exc:
        print(f"[ERROR] Failed to read repository files: {exc}", file=sys.stderr)
        return 2

    if args.check:
        # Defer to is_stale() rather than repeating the comparison: `validate` reports
        # freshness through the same helper, and two copies of the rule could disagree
        # about whether the index is current.
        stale, reason = is_stale(root)
        if output.warning:
            print(f"[WARN] {output.warning}", file=sys.stderr)
        if stale:
            print(reason, file=sys.stderr)
            return 1
        return 0

    _write(root, output)
    _report_cost(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_refresh(argv)
