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

The hook's matcher shape, adapter and guard follow claude.py's -- but NOT how the command
reaches them. This format sets NO plugin-root token and NO plugin-root environment variable
(VS Code's `AGENT_PLUGIN_FORMAT`: `pluginRootTokens: []`, `pluginRootEnvVars: []`), so a
hook here cannot be told where it lives. An earlier pass moved this command from
`${CLAUDE_PLUGIN_ROOT}` to `${PLUGIN_ROOT}` and recorded that as a real fix; both tokens are
equally unset here, so it fixed nothing and the command kept resolving to a bare `/scripts/...`
path. `python3` then exited 2 on the missing file, which is this client's BLOCKING code --
so the package denied every tool call rather than the destructive ones. See `_hook_command`
for the correction and why it is safe under every format at once. The adapter and guard
BYTES stay byte-identical to the Claude package's (same source, same file). VS Code parses the `matcher` field but currently ignores it, which is safe
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
    LICENSE_REL,
    NAMESPACE,
    build_manifest,
    build_skill,
    license_text,
    plugin_name,
)
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

#: This format's package-layout knowledge comes from agentseam's PACKAGING row for
#: "copilot" -- the Agent Plugins 1.0 marketplace bundle, distinct from vscode_copilot's
#: repo-local hooks. PLUGIN_ROOT below is kept because the three sibling formats
#: (CLAUDE, OPEN_PLUGIN, legacy COPILOT) do export it as an environment variable, and a
#: package can be read as any of them; it is NOT relied on for this format, which exports
#: nothing. That distinction was previously taken from the vendor's documentation table --
#: which is ambiguous on it -- rather than from the parser source, which is not. Derive
#: from the mechanism, not the doc row.
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
    "python3 Store alias or install Python. If the guard itself crashes or times out, the "
    "hook asks for confirmation rather than allowing silently -- VS Code agent mode honours "
    "that ask and it overrides the client's own auto-approve."
)

#: Replaces the shared builder's closing note in hook-carrying packages, with the same
#: audience scoping as the posture above: "enforced in this client" (the Claude package's
#: note) presumes the reader's client ran the hook, which a namespace-ignoring client
#: did not.
_COPILOT_ENFORCED_NOTE = (
    "This package ships a PreToolUse hook under com.github.copilot/. It enforces only in a "
    "client that both reads that namespace AND tells the hook where the package lives; a "
    "client that exports no plugin-root variable runs the hook, which then allows -- so "
    "treat this package as advisory unless a deny has been witnessed in your own client. "
    "A client that ignores the namespace gets this text only. Repo-wide enforcement across "
    "every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation, guarded so an unresolved plugin root ALLOWS.

    This format gives a hook no way to find itself, and the naive command turned that into
    a deny-all. VS Code's `AGENT_PLUGIN_FORMAT` declares `pluginRootTokens: []` and
    `pluginRootEnvVars: []` (`src/vs/platform/agentPlugins/common/pluginParsers.ts`), where
    `CLAUDE_FORMAT`, `OPEN_PLUGIN_FORMAT` and the legacy `COPILOT_FORMAT` all declare both
    tokens and both environment variables. So `${PLUGIN_ROOT}` reaches the shell verbatim,
    `sh -c` expands the unset variable to nothing, `python3` exits 2 on the missing file --
    and 2 is precisely VS Code's *blocking* code. Matchers are ignored, so every tool call
    in the session was denied, not merely every Bash call.

    An earlier pass changed this token from `${CLAUDE_PLUGIN_ROOT}` to `${PLUGIN_ROOT}` and
    recorded it as a real fix. It was not: it moved between two tokens this format sets
    equally never. That reading came from the vendor's documentation table, which is
    ambiguous here; the source is not. Derive from the mechanism, not the doc row.

    So the root is read as an ENVIRONMENT VARIABLE rather than a token, and the command
    allows when it cannot resolve. That is correct under every format at once: the three
    formats that interpolate also export `PLUGIN_ROOT`, so the guard runs and enforces
    there; the Agent Plugins format exports nothing, so `$r` is empty and the hook exits 0
    -- advisory, which is what the skill text already claims for namespace-ignoring
    clients. It also stays correct by construction if this format later gains the variable.

    The `-f` test is not belt-and-braces: a client could export a root that does not
    contain our scripts, and the failure mode of guessing wrong here is denying the
    session, so the command proves the adapter exists before it will run anything.
    """
    # PLUGIN_ROOT is derived from agentseam's token rather than hardcoded, so the two stay
    # in step; `${X}` -> `${X:-}` makes it a defaulted shell expansion instead of a bare one.
    assert PLUGIN_ROOT.startswith("${") and PLUGIN_ROOT.endswith("}"), PLUGIN_ROOT
    root = f"{PLUGIN_ROOT[:-1]}:-}}"
    adapter = f'"$r/{_SCRIPTS_TEMPLATE.format(name="vscode_copilot.py")}"'
    guard = f'"$r/{_SCRIPTS_TEMPLATE.format(name=script)}"'
    return f'r="{root}"; [ -n "$r" ] && [ -f {adapter} ] || exit 0; exec python3 {adapter} --guard {guard}'


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
    # Same reason as every other format: these packages are published on their own, and the
    # distribution repos carry a licence at the root only. `license_text` writes nothing when
    # the policy's own provenance cannot supply the notice.
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
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
