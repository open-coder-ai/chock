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
from chock.plugin.build import _ADVISORY_NOTE, _author, _keywords, _one_line, build_skill, plugin_name

#: Stated verbatim in the emitted description. "session-enforced" and "advisory" are the
#: coverage taxonomy's words, used with their taxonomy meaning -- the description is a
#: coverage claim, so it uses the vocabulary the rest of the project is held to.
#:
#: Both fail-open conditions are named, not just the interpreter. The guards are bash
#: scripts and the adapter probes for a bash that can resolve the guard path; when it finds
#: none it reports "not checked" and ALLOWS. On a Windows machine without Git Bash that is
#: the common case, not an edge case -- so a posture line naming only python3 would describe
#: one of the two ways this plugin silently stops enforcing.
POSTURE_ENFORCED = (
    "Session-enforced via a PreToolUse hook; fails open (allows) if Python or a usable bash is unavailable."
)
POSTURE_ADVISORY = "Advisory skill only; enforcement needs chock installed in the repo."

#: Replaces the packaged skill's closing note when the package carries a working hook.
#: `build_skill` ends every skill with "this skill is advisory: the client reading it has no
#: mechanism to enforce it" -- true of the Agent Plugins package, which has no hooks, and
#: false inside a Claude package that ships one. Shipping a file that says nothing enforces
#: this next to a hook that does is a claim that does not match its own directory, even
#: though it errs toward under-claiming.
_ENFORCED_NOTE = (
    "This policy is enforced in this client by a PreToolUse hook installed with the plugin, "
    "subject to the fail-open condition stated in the plugin description. Repo-wide "
    "enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _adapter_source() -> str:
    """The PreToolUse adapter, verbatim.

    The adapter's own contract is "SELF-CONTAINED, STDLIB ONLY ... copied verbatim" -- the
    same copy discipline `chock compile` uses for `.chock/bin/pretooluse.py`. Shipping a
    byte-identical copy means a plugin and a repo install can never disagree about how a
    payload is parsed.
    """
    return Path(_adapter_module.__file__).read_text(encoding="utf-8")


def _hook_command(script: str) -> str:
    """The hook invocation, with an interpreter fallback that is not decoration.

    On Windows, `python3` is routinely the Microsoft Store alias stub, which prints an
    install prompt and exits non-zero without running anything. A client that treats a
    hook error as deny (VS Code does) then refuses EVERY shell command the moment this
    plugin is installed -- observed in the field on 2026-08-22, safe probes and all. The
    `||` fallback to `python` is valid in sh, bash and cmd alike, and the guards are
    read-only and deterministic, so the one redundant case -- a real deny (exit 2)
    triggering the fallback and reaching the same verdict twice -- is harmless.
    """
    adapter = "${CLAUDE_PLUGIN_ROOT}/scripts/pretooluse.py"
    guard = f"${{CLAUDE_PLUGIN_ROOT}}/scripts/{script}"
    return f'python3 "{adapter}" --guard "{guard}" || python "{adapter}" --guard "{guard}"'


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

    skill = build_skill(policy_dir, manifest, Path(repo_root))
    if script:
        # The shared builder's closing note is written for a format with no hooks. This
        # package has one, so the note is replaced rather than appended: leaving both would
        # make the file contradict itself inside the reader's own directory.
        skill = skill.replace(_ADVISORY_NOTE, _ENFORCED_NOTE)

    files: dict[Path, str] = {
        Path(".claude-plugin/plugin.json"): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path("skills") / name / "SKILL.md": skill,
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


#: Everything the Claude emitter may write. Reconciliation needs this list because the set
#: of files a policy produces CHANGES: a policy that loses its guard script stops emitting
#: hooks.json and scripts/, and a build that only writes current files would leave the old
#: hook in place -- a package that still denies commands while its own manifest and skill
#: now say it is advisory. That is the overclaim this project exists to refuse, arriving by
#: omission rather than by assertion.
OWNED_SUBTREES = ("hooks", "scripts")


def stale_claude_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(claude_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


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

    # A guard removed upstream must take its hook with it. Writing only current files would
    # leave a package enforcing what its manifest no longer claims.
    for stale in stale_claude_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
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
    for stale in stale_claude_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
