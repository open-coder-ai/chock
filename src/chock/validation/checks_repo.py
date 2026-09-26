"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from chock import vendors
from chock.hooks.in_agent_install import WIRED_VENDORS, agent_hooks_rel
from chock.index.builder import max_tokens_for
from chock.index.cli import is_stale
from chock.scaffold.agents_md import POINTER_BLOCK, POINTER_END, POINTER_START
from chock.validation.loading import discover_artifacts
from chock.validation.report import Finding, Report

#: `.chock/bin/<vendor>.py`, wherever it turns up inside a hook command: chock is the only
#: writer of that directory, so naming a path under it identifies an entry as chock's own,
#: independent of the vendor-specific shapes `in_agent_merged.py`/`in_agent_generic.py` merge
#: it through.
#: A file an agent hook command runs or hands the gate: the runtime, and the compiled gate it reads.
_BIN_TARGET_RE = re.compile(r"\.chock/(?:bin/[\w.-]+\.py|compiled/[\w./-]+\.json)")

_POINTER_RE = re.compile(
    re.escape(POINTER_START) + r"(.*?)" + re.escape(POINTER_END),
    re.DOTALL,
)


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
    """Check that AGENTS.md contains the constant pointer and that INDEX.md is fresh."""
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
    """Does an installed artifact answer to this id?"""
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
        return
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


def check_gate_log_untracked(root: Path, report: Report) -> None:
    """The gate outcome log is per machine and grows on every commit; committed, it is churn."""
    tracked = _tracked_under(root, ".chock/log")
    if not tracked:
        return
    report.add(
        Finding(
            str(root / ".chock" / "log"),
            "gate_log_tracked",
            "warning",
            f"{len(tracked)} gate log file(s) are committed ({', '.join(tracked[:3])}). The log records "
            "this machine's verdicts and changes on every commit. Run `git rm --cached -r .chock/log` "
            "and add `.chock/log/` to .gitignore; `chock init` writes that rule.",
        )
    )


def _tracked_under(root: Path, rel: str) -> list[str]:
    """Paths git tracks under `rel`, or [] outside a repository or when git is absent."""
    git = shutil.which("git")
    if git is None:
        return []
    result = subprocess.run(  # noqa: S603 -- asking git what it tracks is this check's whole job
        [git, "-C", str(root), "ls-files", "--", rel],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split() if result.returncode == 0 else []


def _ignore_rule(root: Path, rel: str) -> str | None:
    """The rule git would ignore `rel` by (`source:line:pattern`), or None; None outside a repo.

    A tracked file is never ignored, so this names only a file a clone would not have. Whether
    it is ignored is asked plainly: `check-ignore -v` also reports a path a `!` negation
    re-includes, and exits 0 for it, so it only names the rule once the answer is yes.
    """
    git = shutil.which("git")
    if git is None:
        return None
    base = [git, "-C", str(root), "check-ignore"]
    ignored = subprocess.run([*base, "-q", "--", rel], capture_output=True, check=False)  # noqa: S603 -- asking git
    if ignored.returncode != 0:
        return None
    named = subprocess.run([*base, "-v", "--", rel], capture_output=True, text=True, check=False)  # noqa: S603
    return named.stdout.strip().split("\t", 1)[0] or "a gitignore rule"


def _dangling_reason(root: Path, target: str) -> str | None:
    """Why a hook naming `target` fails -- here, or in every clone -- or None when it does not."""
    rule = _ignore_rule(root, target)
    if rule is not None:
        return (
            f"is ignored by git ({rule}), so a clone, a teammate's checkout or CI has no such file "
            "and the hook fails there. A global `bin/` rule is the usual cause: `chock sync` adds "
            "`!.chock/bin/` and `!.chock/compiled/` to .gitignore; commit them and the files."
        )
    if not (root / target).exists():
        return "does not exist. Run `chock sync` to reinstall or uninstall this vendor's hooks."
    return None


def check_dangling_hook_targets(root: Path, report: Report) -> None:
    """A chock-written hook entry naming a file that is missing, or that git would not keep.

    `sync` wires in-agent hooks only for the vendors `supported_agents` names and prunes a
    vendored runtime once its vendor falls out of that list (`recompile.py`); a hook config
    still naming the deleted runtime is a client-side failure on every tool call, silent to
    both `chock sync --check` and `chock check` unless something reads the config back. A
    runtime that exists here but is git-ignored fails the same way in every other checkout:
    there, no hook can start the gate at all.
    """
    paths = [root / vendors.config_path(vendor) for vendor in WIRED_VENDORS]
    paths.append(root / agent_hooks_rel())

    seen: set[tuple[str, str]] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in _BIN_TARGET_RE.findall(text):
            key = (str(path), target)
            if key in seen:
                continue
            seen.add(key)
            reason = _dangling_reason(root, target)
            if reason is not None:
                report.add(Finding(str(path), "dangling_hook_target", "error", f"{path} runs {target}, which {reason}"))


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
