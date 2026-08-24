"""Emit an OpenAI Codex plugin (`.codex-plugin/`) from a policy directory.

Codex's hook protocol is Claude's: event `PreToolUse`, matcher `Bash`, the payload's shell
command at `tool_input.command`, deny by exiting 2. The adapter and guard are therefore the
same bytes as every other format, and this emitter only changes the envelope.

Why a separate format rather than reusing the Copilot (Agent Plugins 1.0) package, which
Codex can also discover: Codex's loader DISCARDS hooks from an Agent-Plugins-format manifest
outright --

    let (hook_sources, hook_load_warnings) =
        if loaded_manifest.format == PluginManifestFormat::AgentPlugin { (Vec::new(), Vec::new()) }
        else { load_plugin_hooks(...) };
    -- codex-rs/core-plugins/src/loader.rs

so shipping the Copilot package to Codex would install a plugin whose entire purpose is
deleted at load time, while its description still claimed enforcement. The `.codex-plugin/`
(Legacy) manifest is the only shape whose hooks are loaded at all.

A second Codex-specific hazard is handled in the shared adapter rather than here: Codex
records exit 2 with an EMPTY stderr as a failed hook ("PreToolUse hook exited with code 2
but did not write a blocking reason to stderr", codex-rs/hooks/src/events/pre_tool_use.rs)
and lets the command through. `gate.pretooluse` therefore guarantees a reason on every deny,
so a silent guard cannot become a silent allow here.

`manifest.yaml` stays canonical; every file here is derived and never hand-authored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.plugin.build import _ADVISORY_NOTE, _author, _keywords, _one_line, build_skill, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

#: Codex's own plugin-root variable. `CLAUDE_PLUGIN_ROOT` is a documented compatibility
#: alias, but the native name is what a Codex package should say it depends on.
PLUGIN_ROOT = "${PLUGIN_ROOT}"
HOOKS_REL = "hooks/hooks.json"
SKILLS_REL = "./skills/"
EVENT = "PreToolUse"

#: Only `name`, `version` and `description` are required. `interface` (the directory
#: listing block) is deliberately omitted until a package is actually submitted to
#: OpenAI's directory: every field in it is optional, and it carries the most
#: unverified constraints of anything in this schema.
MANIFEST_KEYS = (
    "name",
    "version",
    "description",
    "author",
    "repository",
    "license",
    "keywords",
    "skills",
    "hooks",
)

#: Codex is fail-open on a hook error like Claude, and additionally requires a reason on
#: stderr for a deny to count -- which the adapter guarantees. Both conditions are named
#: because a posture that omits either would describe a way this package silently stops
#: enforcing.
POSTURE_ENFORCED_CODEX = (
    "Session-enforced in Codex by a PreToolUse hook: a matched command is denied before it "
    "runs (exit 2 with the guard's reason). The hook needs python3 and a usable bash "
    "resolved from PATH; without them Codex records a failed hook and allows the command, "
    "so this fails OPEN. On Windows, disable the python3 Store alias or install Python. "
    "Repo-wide enforcement at commit time and in CI still needs `chock sync`."
)

_ENFORCED_NOTE_CODEX = (
    "This policy is enforced in Codex by the PreToolUse hook shipped with this plugin, "
    "subject to the fail-open condition stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies.

    No fallback chain, for the reason measured in claude.py: `||` fires on ANY non-zero
    exit, so a real denial (exit 2) would cascade into the next leg and read as allow.
    """
    adapter = f"{PLUGIN_ROOT}/scripts/pretooluse.py"
    guard = f"{PLUGIN_ROOT}/scripts/{script}"
    return f'python3 "{adapter}" --guard "{guard}"'


def build_codex_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive `.codex-plugin/plugin.json` from a policy manifest."""
    policy_id = str(manifest.get("id") or Path(policy_dir).name)
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED_CODEX if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(policy_id),
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
        "keywords": _keywords(manifest),
        "skills": SKILLS_REL,
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
    if enforced:
        # Declared explicitly rather than relying on the default `hooks/hooks.json`
        # discovery: the declaration is what makes the package's enforcement claim
        # checkable by anything reading the manifest alone.
        data["hooks"] = f"./{HOOKS_REL}"
    return {key: data[key] for key in MANIFEST_KEYS if key in data}


def codex_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Codex plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    script = _guard_script(policy_dir, policy_id)

    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE, _ENFORCED_NOTE_CODEX)

    files: dict[Path, str] = {
        Path(".codex-plugin/plugin.json"): json.dumps(
            build_codex_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path("skills") / name / "SKILL.md": skill,
    }
    if script:
        # Claude's nested envelope, which Codex parses with `deny_unknown_fields` at the
        # top level -- exactly `description` and `hooks`, nothing else. `async` is never
        # emitted: Codex only honours a blocking decision from a synchronous hook.
        hooks = {
            "description": "Chock policy enforcement",
            "hooks": {
                EVENT: [
                    {
                        "matcher": MATCHER,
                        "hooks": [{"type": "command", "command": _hook_command(script), "timeout": TIMEOUT_SECONDS}],
                    }
                ]
            },
        }
        files[Path(HOOKS_REL)] = json.dumps(hooks, indent=2) + "\n"
        files[Path("scripts/pretooluse.py")] = _adapter_source()
        files[Path("scripts") / script] = (policy_dir / "implementations" / script).read_text(encoding="utf-8")
    return files


#: Everything this emitter may write; see cursor.py for why reconciliation needs the list.
OWNED_SUBTREES = ("hooks", "scripts")


def stale_codex_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_codex_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Codex package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    for stale in stale_codex_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def codex_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Codex plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in codex_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_codex_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
