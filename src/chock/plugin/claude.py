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

from agentseam import packaging

from chock.compile.emitters.claude_pretooluse import MATCHER, TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.gate import runtime_bundle
from chock.plugin.build import (
    _ADVISORY_NOTE_HOOK,
    _ADVISORY_NOTE_RULE,
    LICENSE_REL,
    _author,
    _keywords,
    _one_line,
    build_skill,
    license_text,
    plugin_name,
)

#: This format's package-layout knowledge -- manifest path, plugin-root token, and the
#: skills/hooks/scripts path templates -- comes from agentseam's PACKAGING row for
#: claude_code rather than being hand-maintained here a second time. Only the CONTENT of
#: each file (the manifest fields, the skill body, the hooks fragment) stays chock's own.
_MANIFEST_REL = packaging.layout("claude_code")["manifest"]  # ".claude-plugin/plugin.json"
_SCRIPTS_TEMPLATE = packaging.supports("claude_code", packaging.EXECUTABLE)  # "scripts/{name}"

#: Stated verbatim in the emitted description. "session-enforced" and "advisory" are the
#: coverage taxonomy's words, used with their taxonomy meaning -- the description is a
#: coverage claim, so it uses the vocabulary the rest of the project is held to.
#:
#: Both fail-open conditions are named, not just the interpreter. The guards are bash
#: scripts and the adapter probes for a bash that can resolve the guard path; when it finds
#: none it reports "not checked" and ALLOWS. On a Windows machine without Git Bash that is
#: the common case, not an edge case -- so a posture line naming only python3 would describe
#: one of the two ways this plugin silently stops enforcing.
#: Both failure directions are named because clients disagree about them: Claude Code
#: allows on a hook error (silently unenforced), VS Code denies on one (matched commands
#: refuse until Python exists). Promising "fails open" unconditionally was true for one
#: client and false for the other; a posture line that is wrong for somebody is worse
#: than one that is longer.
POSTURE_ENFORCED = (
    "Session-enforced via a PreToolUse hook; needs python3 and a usable bash. Without them, "
    "fail-open clients allow silently; fail-closed clients refuse matched commands. On Windows, "
    "disable the python3 Store alias or install Python."
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


def _adapter_source(agent: str = "claude_code") -> str:
    """`agent`'s self-contained runtime, verbatim -- agentseam's bundle plus chock's own
    handler (see `gate/runtime_bundle.py`).

    Byte-identical to what `chock compile`/`chock sync` vendors into `.chock/bin/` for the
    same agent, so a plugin install and a repo install can never disagree about how a
    payload is parsed.
    """
    return runtime_bundle.render(agent)


def _hook_command(script: str) -> str:
    """One interpreter invocation, deliberately without a fallback chain.

    A `python3 ... || python ...` chain was tried and is unsound in both directions,
    each verified empirically before this docstring was written:

    - `||` fires on ANY non-zero exit. On a machine where python3 is real but the
      fallback names are absent (Debian-family Linux, the majority install), a real
      denial (exit 2) cascades into the missing leg's 127 -- which Claude Code treats
      as allow. The chain silently disabled enforcement on the most common platform.
    - Fallbacks cannot re-adjudicate anyway: the first leg that actually runs consumes
      the stdin payload, so any later leg sees an empty one.

    The residual limitation is Windows machines where `python3` is the Microsoft Store
    alias stub: the hook errors there, and the client's own error posture applies
    (Claude Code allows silently; VS Code refuses matched commands until Python is
    installed or the stub alias is disabled). That is stated in POSTURE_ENFORCED
    rather than papered over -- a loud failure beats silently lost enforcement, and the
    real fix is a per-client emitter that knows each client's hook shell, not a shell
    trick that trades one platform's correctness for another's.
    """
    adapter = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name="claude_code.py"))
    guard = packaging.executable_ref("claude_code", _SCRIPTS_TEMPLATE.format(name=script))
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

    # The frontmatter coverage claim and the closing note are both posture-dependent: a
    # package that ships hooks/hooks.json must not carry a file stating it is advisory
    # without chock. `build_skill` swaps the frontmatter claim for the hook's path; the
    # closing note is replaced here for the same reason -- leaving either would make the
    # file contradict itself inside the reader's own directory.
    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks="hooks/hooks.json" if script else None)
    if script:
        # A guard-script policy is rule-tier in its manifest, so build_skill emits the rule
        # note; replace whichever advisory note is present, since the Claude plugin enforces
        # this policy via its PreToolUse hook.
        skill = skill.replace(_ADVISORY_NOTE_RULE, _ENFORCED_NOTE).replace(_ADVISORY_NOTE_HOOK, _ENFORCED_NOTE)

    files: dict[Path, str] = {
        Path(_MANIFEST_REL): json.dumps(
            build_claude_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path(packaging.supports("claude_code", packaging.SKILL).format(name=name)): skill,
    }
    # Same reason as every other format: these packages are published on their own, and the
    # distribution repos carry a licence at the root only. `license_text` writes nothing when
    # the policy's own provenance cannot supply the notice.
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    if script:
        hooks_rel = packaging.supports("claude_code", packaging.HOOKS)
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
        files[Path(hooks_rel)] = json.dumps(hooks, indent=2) + "\n"
        files[Path(_SCRIPTS_TEMPLATE.format(name="claude_code.py"))] = _adapter_source("claude_code")
        files[Path(_SCRIPTS_TEMPLATE.format(name=script))] = (policy_dir / "implementations" / script).read_text(
            encoding="utf-8"
        )
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
