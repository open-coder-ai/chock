"""Reading packaged templates, and writing them without destroying adopter edits."""

from __future__ import annotations

from pathlib import Path

from chock.emit import write_generated
from chock.resources import template_text


def packaged_template(rel_path: str) -> str:
    """Read a file from the packaged chock-init template tree."""
    import chock

    base = Path(chock.__file__).parent / "packs" / "_skills" / "chock-init"
    return (base / "assets" / "templates" / rel_path).read_text(encoding="utf-8")


def _dependency_allowlist_template() -> str:
    return packaged_template(".chock/dependency-allowlist.txt")


GITATTRIBUTES_TEMPLATE = template_text("scaffold/gitattributes")

POLICIES_GUARDRAIL = template_text("scaffold/policies-guardrail.md")

SKILLS_GUARDRAIL = template_text("scaffold/skills-guardrail.md")


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
