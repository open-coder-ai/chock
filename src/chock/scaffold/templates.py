"""Reading packaged templates, and writing them without destroying adopter edits."""

from __future__ import annotations

from pathlib import Path

from chock.emit import write_generated


def packaged_template(rel_path: str) -> str:
    """Read a file from the packaged chock-init template tree."""
    import chock

    base = Path(chock.__file__).parent / "packs" / "_skills" / "chock-init"
    return (base / "assets" / "templates" / rel_path).read_text(encoding="utf-8")


def _dependency_allowlist_template() -> str:
    return packaged_template(".chock/dependency-allowlist.txt")


_GITATTRIBUTES_TEMPLATE = """\
# Written by `chock init`; yours to extend. Chock's pack hashes and compiled artifacts
# are raw bytes, so they must check out identically on every platform -- with
# core.autocrlf=true (common on Windows) an unpinned clone flips them to CRLF and
# `chock check --only verify` fails on every pack nobody touched.
chock.lock text eol=lf
.chock/** text eol=lf
.agents/** text eol=lf
"""

POLICIES_GUARDRAIL = """\
# Installed policies -- provenance and editing

Policy folders here were installed from a catalog and are hash-pinned in `chock.lock`
(source, version, sha256). They are yours to edit -- but an edited copy no longer matches
its pinned hash, and `chock check --only verify` will report the divergence. To take the
upstream version instead of keeping a local variant, fix it in the source catalog and
reinstall: `chock add <id> --force`, then `chock sync --repo .`.

After any edit here, run `chock sync --repo .` so the compiled gates match the source.
"""

SKILLS_GUARDRAIL = """\
# Installed skills -- edit here, not the bridge copy

Skills here are the canonical copies. Some agents (Claude Code) read a bridged copy under
`.claude/skills/`, regenerated from this directory on every `chock sync` -- edits made to
a bridge copy are overwritten. Edit here. The authoring skills Chock ships (eval,
optimize, policy-init, validate) are refreshed only by `chock install-skills .`, which
preserves local edits.
"""


def write_vendored_guardrails(repo_root: Path, force: bool) -> list[str]:
    """Write the guardrail pair into .agents/policies/ and .agents/skills/."""
    preserved: list[str] = []
    for rel_dir, content in ((".agents/policies", POLICIES_GUARDRAIL), (".agents/skills", SKILLS_GUARDRAIL)):
        for name in ("AGENTS.md", "CLAUDE.md"):
            rel = f"{rel_dir}/{name}"
            if _preserve_or_write(repo_root / rel, content, force):
                preserved.append(rel)
    return preserved


def _preserve_or_write(path: Path, content: str, force: bool) -> bool:
    """Write `content` unless the adopter has already edited what is there. True if left alone."""
    if path.exists() and not force and path.read_text(encoding="utf-8") != content:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    write_generated(path, content)
    return False
