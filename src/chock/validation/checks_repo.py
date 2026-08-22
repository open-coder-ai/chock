"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from chock.index.builder import max_tokens_for
from chock.index.cli import is_stale
from chock.scaffold.agents_md import POINTER_BLOCK, POINTER_END, POINTER_START
from chock.validation.report import Finding, Report

_POINTER_RE = re.compile(
    re.escape(POINTER_START) + r"(.*?)" + re.escape(POINTER_END),
    re.DOTALL,
)


# Legacy adapter files that must delegate to AGENTS.md.
_ADAPTER_FILES = [
    ".claude/CLAUDE.md",
    ".cursor/rules/chock.mdc",
    ".cursorrules",
    ".windsurf/rules/chock.md",
    ".windsurfrules",
    ".devin/README.md",
    "codex.md",
    ".grok/GROK.md",
    ".kimi-code/AGENTS.md",
    ".github/copilot-instructions.md",
    ".gemini/GEMINI.md",
    "CONVENTIONS.md",
    ".github/agents/chock.agent.md",
    "replit.md",
    "guidelines.md",
]


def _adapter_file_exists(root: Path, rel: str) -> bool:
    return (root / rel.replace("/", os.sep)).exists()


def check_ambient_rule_blocks(root: Path, report: Report) -> None:
    """Check that AGENTS.md contains the constant pointer and that INDEX.md is fresh.

    Replaces the legacy SEC-7 rule-block comparison. The pointer sends agents to
    `.agents/policies/INDEX.md`, so validation now guards that the pointer is present,
    constant, and that the index it references is up to date.
    """
    agents_md = root / "AGENTS.md"
    if not agents_md.exists():
        return

    text = agents_md.read_text(encoding="utf-8")
    match = _POINTER_RE.search(text)
    if not match:
        report.add(
            Finding(
                str(agents_md),
                "ambient_pointer",
                "warning",
                "AGENTS.md is missing the managed pointer block; run `chock sync`.",
            )
        )
        return

    if match.group(0).rstrip() != POINTER_BLOCK.rstrip():
        report.add(
            Finding(
                str(agents_md),
                "ambient_pointer",
                "warning",
                "AGENTS.md pointer block does not match the canonical text; run `chock sync`.",
            )
        )

    index_path = root / ".agents" / "policies" / "INDEX.md"
    if not index_path.exists():
        report.add(
            Finding(
                str(index_path),
                "index_freshness",
                "warning",
                "INDEX.md is missing; run `chock sync`.",
            )
        )
        return

    stale, reason = is_stale(root)
    if stale:
        report.add(
            Finding(
                str(index_path),
                "index_freshness",
                "warning",
                f"{reason}. Run `chock sync`.",
            )
        )

    # Verify that every id referenced in the index resolves to a real policy folder.
    for line in index_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^-\s+\*\*([^*]+)\*\*", line)
        if not m:
            continue
        pid = m.group(1).strip()
        if not _resolve_id(root, pid):
            report.add(
                Finding(
                    str(index_path),
                    "index_resolution",
                    "warning",
                    f"INDEX.md references '{pid}' but no policy folder resolves to it.",
                )
            )


def _resolve_id(root: Path, policy_id: str) -> bool:
    """Does an installed artifact answer to this id?

    Uses the canonical discovery rather than walking the tree here. A second implementation
    of discovery is a second thing to keep in step, and this one had already fallen out of
    it: it once missed a whole class of installed policy and reported eleven of them
    unresolvable on a clean install.
    """
    from chock.validation.loading import discover_artifacts

    for _artifact_type, artifact_dir in discover_artifacts(root):
        if artifact_dir.name == policy_id:
            return True
        for manifest_name in ("manifest.yaml", "SKILL.md"):
            manifest = artifact_dir / manifest_name
            if not manifest.exists():
                continue
            try:
                data = yaml.safe_load(_frontmatter(manifest)) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("id") == policy_id:
                return True
    return False


def _frontmatter(path: Path) -> str:
    """Manifest body, or the YAML frontmatter block when the manifest is a SKILL.md."""
    text = path.read_text(encoding="utf-8")
    if path.name != "SKILL.md" or not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def check_adapter_integrity(root: Path, report: Report) -> None:
    """5.4: verify that every generated adapter file delegates to AGENTS.md."""
    for rel in _ADAPTER_FILES:
        path = root / rel.replace("/", os.sep)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "AGENTS.md" not in text and "AGENTS" not in text:
            report.add(
                Finding(
                    str(path),
                    "adapter_integrity",
                    "warning",
                    f"Adapter {rel} does not reference AGENTS.md; generated wrappers must delegate to AGENTS.md.",
                )
            )


def check_release_consistency(root: Path, report: Report) -> None:
    """Version is single-sourced in pyproject.toml; CHANGELOG and VERSION must match it."""
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return  # consumer repos have no release metadata
    match = re.search(r"^version\s*=\s*\"([^\"]+)\"", pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        return
    version = match.group(1)

    version_file = root / "VERSION"
    if version_file.exists() and version_file.read_text(encoding="utf-8").strip() != version:
        report.add(
            Finding(
                str(version_file),
                "release_consistency",
                "error",
                f"VERSION {version_file.read_text(encoding='utf-8').strip()} != pyproject version {version}.",
            )
        )

    changelog = root / "CHANGELOG.md"
    if changelog.exists():
        # `\d+\.\d+\.\d+` truncated any PEP 440 suffix instead of capturing it, and the failure
        # was not symmetric. Against `## 0.0.1a0` it captured `0.0.1`, so a correctly matched
        # pre-release reported a mismatch -- noisy but safe. The reverse is the real defect: a
        # CHANGELOG topped by `0.0.1a0` against a pyproject on `0.0.1` also captured `0.0.1`,
        # compared equal, and PASSED. A release-gating check that fails open on the version it
        # exists to compare is worse than no check.
        # Bracketed Keep-a-Changelog headings (## [1.2.3]) never matched the bare
        # pattern, so the check silently passed -- the same fail-open shape as above.
        match = re.search(r"^##\s+\[?(\d[^\s\]]*)\]?", changelog.read_text(encoding="utf-8"), re.MULTILINE)
        if match and match.group(1) != version:
            report.add(
                Finding(
                    str(changelog),
                    "release_consistency",
                    "error",
                    f"Top CHANGELOG entry {match.group(1)} != pyproject version {version}.",
                )
            )


def check_ambient_token_budget(root: Path, report: Report) -> None:
    """Spec F2: the attention surface in INDEX.md must fit index.max_tokens (default 2000)."""
    index_path = root / ".agents" / "policies" / "INDEX.md"
    if not index_path.exists():
        return
    text = index_path.read_text(encoding="utf-8")
    tokens = len(text) // 4
    max_tokens = max_tokens_for(root)
    if tokens > max_tokens:
        report.add(
            Finding(
                str(index_path),
                "token_budget",
                "warning",
                f"INDEX.md is ~{tokens} tokens; attention budget is {max_tokens}.",
            )
        )
