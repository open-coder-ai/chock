"""Reading packaged templates, and writing them without destroying adopter edits.

Shared by `init` and by the per-agent adapter writer, so it lives apart from both rather
than being imported across them.
"""

from __future__ import annotations

from pathlib import Path

from chock.emit import write_generated


def packaged_template(rel_path: str) -> str:
    """Read a file from the packaged chock-init template tree.

    Single source of truth: the same files the onboarding skill hands to an agent. An
    inline copy here is a second definition free to drift -- `DOCS_README` did exactly
    that, shrinking to a three-line stub while the packaged guide grew to fifteen lines,
    so `init` and the skill produced different repos.

    Reading the packaged file also makes its absence *loud*. The 42 dot-directory
    templates were missing from every built wheel for a long time precisely because
    nothing read them; the gap only surfaced once `init` started to.
    """
    import chock

    base = Path(chock.__file__).parent / "packs" / "_skills" / "chock-init"
    return (base / "assets" / "templates" / rel_path).read_text(encoding="utf-8")


def _dependency_allowlist_template() -> str:
    return packaged_template(".chock/dependency-allowlist.txt")


#: Directory-scoped guardrails dropped next to vendored content in adopter repos. An agent
#: that starts editing a file loads the nearest AGENTS.md / CLAUDE.md up the tree, so the
#: provenance-and-editing contract arrives at exactly the editing moment -- an edit-time
#: guardrail, not a discovery surface. They sit at the PARENT level, never inside a policy
#: pack: `compute_pack_hash` covers every file in a pack, so a file injected into
#: `.agents/policies/<id>/` would break `--verify-sha` and every published-hash comparison.
#: AGENTS.md and CLAUDE.md are two identical generated files, not a symlink -- symlinks
#: need Developer Mode on Windows, and a broken link guards nothing.
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
    """Write the guardrail pair into .agents/policies/ and .agents/skills/.

    Returns the relative paths left alone because the adopter edited them.
    """
    preserved: list[str] = []
    for rel_dir, content in ((".agents/policies", POLICIES_GUARDRAIL), (".agents/skills", SKILLS_GUARDRAIL)):
        for name in ("AGENTS.md", "CLAUDE.md"):
            rel = f"{rel_dir}/{name}"
            if _preserve_or_write(repo_root / rel, content, force):
                preserved.append(rel)
    return preserved


def _preserve_or_write(path: Path, content: str, force: bool) -> bool:
    """Write `content` unless the adopter has already edited what is there. True if left alone.

    `init` is re-run routinely -- after adding a policy, after an upgrade -- and it used to
    rewrite every scaffolded file every time, so local edits to the adapter wrappers vanished
    while the command printed "Initialized Chock" and exited 0.
    `.chock/dependency-allowlist.txt` never had the bug because that path checked
    first; this is the same check, applied everywhere it was missing. Byte-comparing against
    what would be written keeps a re-run idempotent for untouched files, with no state to
    go stale.
    """
    if path.exists() and not force and path.read_text(encoding="utf-8") != content:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    write_generated(path, content)
    return False
