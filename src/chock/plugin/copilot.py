"""Emit a GitHub Copilot (Agent Plugins 1.0 + hooks) plugin from a policy directory.

The Claude-format package (claude.py) already enforces on Copilot CLI and VS Code -- both
auto-detect that layout -- so this emitter exists for the marketplaces that validate against
the Agent Plugins 1.0 spec instead. awesome-copilot's intake pipeline (`vally lint`, install
smoke test) requires `plugin.json` at the package root and rejects the Claude layout, whose
manifest lives in `.claude-plugin/`. This format is that spec-shaped package, with the hook
in the location VS Code documents for Agent Plugins bundles: `com.github.copilot/hooks/
hooks.json`, a reverse-domain namespace directory a non-Copilot client MUST ignore (spec
section 8.1) -- so a generic Agent Plugins client sees a valid advisory package and a
Copilot client also gets the enforcing hook.

The hook's matcher shape, adapter, guard and posture text follow claude.py's -- but NOT the
plugin-root token. Agent Plugins 1.0 resolves its own bundle root via `${PLUGIN_ROOT}`;
`${CLAUDE_PLUGIN_ROOT}` is the Legacy Copilot format's spelling (agentseam's
`packaging.PACKAGING["copilot"]`, sourced from microsoft/vscode-docs
docs/agent-customization/agent-plugins.md). Importing claude.py's `_hook_command` verbatim
used to reach for `${CLAUDE_PLUGIN_ROOT}`, a token this bundle format never sets -- a real
bug, not a style choice, fixed by deriving the token from agentseam instead. The adapter and
guard BYTES stay byte-identical to the Claude package's (same source, same file), only the
token differs. VS Code parses the `matcher` field but currently ignores it, which is safe
here: the adapter allows any payload it cannot extract a shell command from, so a hook fired
on a non-shell tool is a no-op, not a denial.

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
    NAMESPACE,
    build_manifest,
    build_skill,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

#: This format's package-layout knowledge comes from agentseam's PACKAGING row for
#: "copilot" -- the Agent Plugins 1.0 marketplace bundle, distinct from vscode_copilot's
#: repo-local hooks. Previously this module imported claude.py's `_hook_command` verbatim,
#: which meant the hook referenced `${CLAUDE_PLUGIN_ROOT}` -- the LEGACY Copilot format's
#: token. agentseam's vendor research (microsoft/vscode-docs
#: docs/agent-customization/agent-plugins.md, read 2026-08-29) establishes that Agent
#: Plugins 1.0 bundles resolve their own root via `${PLUGIN_ROOT}` only; `${CLAUDE_PLUGIN_ROOT}`
#: is the Legacy Copilot format's spelling, alongside `${PLUGIN_ROOT}`, per the same vendor
#: table -- so the old command silently referenced a token this bundle format never sets,
#: which resolves to an empty string and breaks the script path. This is a real fix, not a
#: cosmetic rename: see PACKAGING["copilot"]["notes"] in agentseam.
_LAYOUT = packaging.layout("copilot")
PLUGIN_ROOT = packaging.plugin_root("copilot")
COPILOT_NAMESPACE = "com.github.copilot"
HOOKS_REL = packaging.supports("copilot", packaging.HOOKS)  # "com.github.copilot/hooks/hooks.json"
_SCRIPTS_TEMPLATE = packaging.supports("copilot", packaging.EXECUTABLE)  # "scripts/{name}"

#: The Claude package's POSTURE_ENFORCED is deliberately NOT reused here. This format's
#: defining audience is generic Agent Plugins clients, and the spec REQUIRES them to
#: ignore `com.github.copilot` -- so "session-enforced" unqualified would overclaim to
#: exactly the readers this layout exists for. The scope is stated, and only what has
#: been verified is claimed: VS Code documents this hook location; other clients that
#: choose to read the namespace get the same hook, and everyone else gets advisory text.
POSTURE_ENFORCED_COPILOT = (
    "Session-enforced by the PreToolUse hook under com.github.copilot/ in clients that "
    "read that namespace (documented for VS Code agent mode); a client that ignores it, "
    "as the Agent Plugins spec tells generic clients to, gets the advisory skill only. "
    "The hook needs python3 and a usable bash. Without them, fail-open clients allow "
    "silently; fail-closed clients refuse matched commands. On Windows, disable the "
    "python3 Store alias or install Python."
)

#: Replaces the shared builder's closing note in hook-carrying packages, with the same
#: audience scoping as the posture above: "enforced in this client" (the Claude package's
#: note) presumes the reader's client ran the hook, which a namespace-ignoring client
#: did not.
_COPILOT_ENFORCED_NOTE = (
    "This package ships a PreToolUse hook under com.github.copilot/ that enforces this "
    "policy in clients reading that namespace (documented for VS Code agent mode), subject "
    "to the fail posture stated in the plugin description. A client that ignores the "
    "namespace gets this text only. Repo-wide enforcement across every commit and in CI "
    "still needs `chock sync`. See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies.

    The adapter and guard bytes are still byte-identical to the Claude package's (see
    `test_adapter_and_guard_are_verbatim_copies`) -- only the token that reaches them
    differs, because this format defines its own plugin-root spelling.
    """
    adapter = packaging.executable_ref("copilot", _SCRIPTS_TEMPLATE.format(name="vscode_copilot.py"))
    guard = packaging.executable_ref("copilot", _SCRIPTS_TEMPLATE.format(name=script))
    return f'python3 "{adapter}" --guard "{guard}"'


def build_copilot_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive the root `plugin.json` from a policy manifest.

    Starts from the conformant Agent Plugins manifest and adds the two statements this
    package needs: the fail posture in the description (the one field every marketplace
    listing renders), and -- for a package that ships a hook -- where the hook lives, in
    our own extensions namespace.

    `coverage_without_chock: advisory` is build_manifest's claim that a client ignoring our
    namespace gets advisory text and nothing else. That is false of this package when it
    carries a hook: the hook enforces in any client that honours `com.github.copilot`
    without chock being involved. The key is replaced rather than left to underclaim,
    because a claim that does not match its own directory is the failure this project
    refuses in either direction.

    build_manifest's `manifest: manifest.yaml` pointer is dropped for the same reason:
    it resolves in the agent-plugins format's in-place mode where manifest.yaml sits
    beside plugin.json, but this format always builds out-of-place and ships no
    manifest.yaml -- the pointer would name a file the package does not contain.
    """
    data = build_manifest(manifest, policy_dir)
    posture = POSTURE_ENFORCED_COPILOT if enforced else POSTURE_ADVISORY
    data["description"] = f"{data['description']} [{posture}]".strip()
    extension = data["extensions"][NAMESPACE]
    del extension["manifest"]
    if enforced:
        del extension["coverage_without_chock"]
        extension["hooks"] = HOOKS_REL
    return data


def copilot_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Copilot plugin's files as {relative path: content}, writing nothing.

    Same pure-render/impure-write split as the other formats, for the same reason: `--check`
    must be able to judge a tree without touching it.
    """
    policy_dir = Path(policy_dir)
    policy_id = manifest.get("id") or policy_dir.name
    name = plugin_name(str(policy_id))
    script = _guard_script(policy_dir, str(policy_id))

    # Frontmatter claim and closing note are both posture-dependent, and both scoped to
    # this format's audience: `build_skill` swaps the advisory coverage claim for the
    # hook's path, and the closing note names where the hook enforces and that a
    # namespace-ignoring client gets text only. Leaving either advisory line in a
    # hook-carrying package would make the file contradict its own directory.
    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE_RULE, _COPILOT_ENFORCED_NOTE).replace(
            _ADVISORY_NOTE_HOOK, _COPILOT_ENFORCED_NOTE
        )

    files: dict[Path, str] = {
        Path(_LAYOUT["manifest"]): json.dumps(
            build_copilot_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("copilot", packaging.SKILL).format(name=name)): skill,
    }
    if script:
        # Claude's matcher shape, verbatim from VS Code's own Agent Plugins hook example.
        # Scripts sit at the package root -- also the documented layout -- but the command
        # references its own ${PLUGIN_ROOT} token, not Claude's ${CLAUDE_PLUGIN_ROOT} --
        # see _hook_command.
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
        files[Path(HOOKS_REL)] = json.dumps(hooks, indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py"))] = _adapter_source("vscode_copilot")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
    return files


#: Everything hook-related this emitter may write. Same reconciliation contract as
#: claude.py's OWNED_SUBTREES: a policy that loses its guard must lose its hook and
#: scripts on the next build, or the package keeps denying commands its own manifest
#: and skill now say are merely advised against.
OWNED_SUBTREES = (COPILOT_NAMESPACE, "scripts")


def stale_copilot_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_copilot_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Copilot-format package for one policy into a distribution directory.

    Always into `out_dir`, never in place: a `com.github.copilot/` hook dropped inside a
    policy folder would be discovered by any client pointed at the repo and read as a
    plugin the catalog never published.
    """
    written: list[Path] = []
    for rel, content in copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)

    # A guard removed upstream must take its hook with it. Writing only current files would
    # leave a package enforcing what its manifest no longer claims.
    for stale in stale_copilot_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def copilot_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Copilot plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in copilot_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_copilot_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
