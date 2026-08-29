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

from agentseam import packaging

from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    _author,
    _keywords,
    _one_line,
    build_skill,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

#: This format's package-layout knowledge -- plugin-root token, manifest path, and the
#: hooks/skills path templates -- comes from agentseam's PACKAGING row for codex_cli.
#: `CLAUDE_PLUGIN_ROOT` is a documented compatibility alias agentseam also records, but the
#: native name (the first, preferred token) is what a Codex package should say it depends on.
_LAYOUT = packaging.layout("codex_cli")
PLUGIN_ROOT = packaging.plugin_root("codex_cli")
HOOKS_REL = packaging.supports("codex_cli", packaging.HOOKS)
SKILLS_REL = _LAYOUT["declares"][packaging.SKILL][1]
EVENT = "PreToolUse"

#: agentseam's own EXECUTABLE row for codex_cli is deliberately empty (PART_LIMITS:
#: "RawPluginManifest's field list is exhaustive ... and none names a bundled executable or
#: scripts path; whether an undeclared file elsewhere in the plugin directory survives
#: installation ... was not established here") -- a real, honest gap, not a bug. This plugin
#: has shipped scripts/ here regardless (Codex's loader does not enumerate the manifest's
#: field list to reject unknown files, only to find declared ones), so the convention stays
#: chock's own rather than being force-fit through a template agentseam does not vouch for.
_SCRIPTS_TEMPLATE = "scripts/{name}"

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

#: A witnessed claim with its conditions stated. Probed on a real Codex Desktop install
#: (Windows 11, 2026-08-23/24): with the deny carried in stdout JSON and exit 0, the hook
#: BLOCKED the command; with exit 2 -- both vendors' documented equivalent -- the same
#: command ran three times, because Codex wraps Windows hook commands in
#: `powershell -Command`, which collapses exit 2 into 1, a failed hook that fails open.
#: The adapter therefore speaks the exit-0 JSON dialect to Codex. Conditions that still
#: gate enforcement, all named below: hooks are UNTRUSTED on install until a human
#: completes the per-hook trust review; that trust is bound to a hash of the hook
#: command, so an update that changes it silently voids enforcement until re-trusted;
#: and every hook failure (missing python3, timeout, unexpected exit) fails open.
#: OpenAI's parity tracker (openai/codex#21753) lists PreToolUse coverage as Partial
#: across surfaces, so the claim is pinned to what was witnessed.
POSTURE_ENFORCED_CODEX = (
    "Session-enforced in Codex by a PreToolUse hook: a matched command is denied before "
    "it runs (witnessed blocking on Codex Desktop, Windows, 2026-08-24; the deny is "
    "returned as hook JSON, not an exit code, which Codex's Windows shell wrapper "
    "mangles). Codex requires a one-time trust review per hook -- the plugin is ADVISORY "
    "until you approve its hook, and a plugin update voids that trust until re-approved. "
    "The hook needs python3 on PATH; any hook failure fails OPEN. Repo-wide enforcement "
    "at commit time and in CI still needs `chock sync`."
)

_ENFORCED_NOTE_CODEX = (
    "This policy is enforced in Codex by the PreToolUse hook shipped with this plugin, "
    "once its one-time trust review is approved (until then it is advisory, and a plugin "
    "update voids the trust until re-approved). Subject to the fail-open conditions in "
    "the plugin description. Repo-wide enforcement across every commit and in CI still "
    "needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies.

    No fallback chain, for the reason measured in claude.py: `||` fires on ANY non-zero
    exit, so a real denial (exit 2) would cascade into the next leg and read as allow.
    """
    adapter = packaging.executable_ref("codex_cli", _SCRIPTS_TEMPLATE.format(name="pretooluse.py"))
    guard = packaging.executable_ref("codex_cli", _SCRIPTS_TEMPLATE.format(name=script))
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
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE_CODEX).replace(
            _ADVISORY_NOTE_HOOK, _ENFORCED_NOTE_CODEX
        )

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_codex_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("codex_cli", packaging.SKILL).format(name=name)): skill,
    }
    if script:
        # Claude's nested envelope. NO top-level `description`: Codex < 0.143.0 rejects
        # the whole hooks file over that one key and silently drops every hook in it
        # (openai/codex#30397, fixed by #30229 in 0.143.0) -- a package that looks
        # identical and enforces nothing on the versions most users run. `async` is never
        # emitted: Codex only honours a blocking decision from a synchronous hook.
        hooks = {
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
        files[Path(_SCRIPTS_TEMPLATE.format(name="pretooluse.py"))] = _adapter_source()
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
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
