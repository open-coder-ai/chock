"""Emit a Claude-format plugin from a policy directory.

Claude Code's plugin layout (`.claude-plugin/plugin.json`, auto-discovered `hooks/` and
`skills/`) is read natively by Claude Code, GitHub Copilot CLI, VS Code, and Grok Build --
one emitter, four clients. Unlike Agent Plugins 1.0 (see build.py), this format carries
hooks, so a packaged guard policy is session-enforced where the host honours PreToolUse.

A plugin installs on the *person*, not the repo: there is no `chock sync` to vendor the
adapter and no install step to bake an interpreter path (the fix settings.json relies on).
So the guard and the stdlib-only adapter ship inside the plugin under `scripts/`, and the
hook command resolves `python3` from PATH at run time. When `python3` is absent the hook
exits 127 and the host allows the call -- the plugin fails OPEN. That posture is written
into the emitted description, where marketplace UIs display it, because a listing that
overclaims enforcement is the exact failure Chock exists to refuse.

`manifest.yaml` stays canonical; every file here is derived and never hand-authored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chock.gate.pretooluse as _adapter_module
from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.plugin.build import _author, _keywords, _one_line, build_skill, plugin_name

#: Stated verbatim in the emitted description. "session-enforced" and "advisory" are the
#: coverage taxonomy's words, used with their taxonomy meaning -- the description is a
#: coverage claim, so it uses the vocabulary the rest of the project is held to.
POSTURE_ENFORCED = "Session-enforced via a PreToolUse hook; fails open if python3 is not on PATH."
POSTURE_ADVISORY = "Advisory skill only; enforcement needs chock installed in the repo."


def _adapter_source() -> str:
    """The PreToolUse adapter, verbatim.

    The adapter's own contract is "SELF-CONTAINED, STDLIB ONLY ... copied verbatim" -- the
    same copy discipline `chock compile` uses for `.chock/bin/pretooluse.py`. Shipping a
    byte-identical copy means a plugin and a repo install can never disagree about how a
    payload is parsed.
    """
    return Path(_adapter_module.__file__).read_text(encoding="utf-8")


def _hook_command(script: str) -> str:
    adapter = "${CLAUDE_PLUGIN_ROOT}/scripts/pretooluse.py"
    guard = f"${{CLAUDE_PLUGIN_ROOT}}/scripts/{script}"
    return f'python3 "{adapter}" --guard "{guard}"'


def build_claude_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive `.claude-plugin/plugin.json` from a policy manifest.

    The fail posture rides in the description rather than a custom key: Claude's manifest
    has no schema `const` to hide metadata behind, and the description is the one field
    every marketplace listing renders -- the honest place for an enforcement claim.
    """
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(str(policy_id)),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]",
        "keywords": _keywords(manifest),
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    author = _author(provenance)
    if author:
        data["author"] = author
    if provenance.get("license"):
        data["license"] = str(provenance["license"])
    if provenance.get("source_repo"):
        data["repository"] = str(provenance["source_repo"])
    return data


def claude_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Claude plugin's files as {relative path: content}, writing nothing.

    Same pure-render/impure-write split as `plugin_files`, for the same reason: `--check`
    must be able to judge a tree without touching it.
    """
    policy_dir = Path(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name
    name = plugin_name(str(policy_id))
    script = _guard_script(policy_dir, str(policy_id))

    files: dict[Path, str] = {
        Path(".claude-plugin/plugin.json"): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path("skills") / name / "SKILL.md": build_skill(policy_dir, manifest, Path(repo_root)),
    }
    if script:
        hooks = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": MATCHER,
                        "hooks": [{"type": "command", "command": _hook_command(script), "timeout": TIMEOUT_SECONDS}],
                    }
                ]
            }
        }
        files[Path("hooks/hooks.json")] = json.dumps(hooks, indent=2) + "\n"
        files[Path("scripts/pretooluse.py")] = _adapter_source()
        files[Path("scripts") / script] = (policy_dir / "implementations" / script).read_text(encoding="utf-8")
    return files


def build_claude_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Claude-format package for one policy into a distribution directory.

    Always into `out_dir`, never in place: `.claude-plugin/` and `hooks/` dropped inside a
    policy folder would be discovered by any client pointed at the repo and read as a
    plugin the catalog never published.
    """
    written: list[Path] = []
    for rel, content in claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    return written


def claude_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Claude plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    return differences
