"""Emit a Cursor plugin (`.cursor-plugin/`) from a policy directory.

Cursor reads its own plugin layout: a `.cursor-plugin/plugin.json` manifest that points at
its components explicitly (`"skills": "./skills/"`, `"hooks": "./hooks/hooks.json"`), and a
hooks file in Cursor's own envelope. Cursor ignores Agent Plugins 1.0 hooks entirely, so
neither the Claude nor the Copilot package reaches Cursor's hook engine -- this format
exists because those two cannot enforce anything there.

Three deliberate differences from the other hook formats, each load-bearing:

- The event is `beforeShellExecution`, not `preToolUse`. Cursor ships BOTH as distinct
  APIs (not aliases): `preToolUse` fires for every tool, `beforeShellExecution` only for
  shell commands. A policy guard evaluates a shell command, so the shell-scoped event is
  the honest subscription -- and it is the same event `chock sync` already installs into
  `.cursor/hooks.json`, so a repo install and a plugin install run the identical hook.
- No `matcher` is emitted. Under `beforeShellExecution` the matcher is a regex over the
  COMMAND TEXT, not over a tool name -- the other formats' `MATCHER = "Bash"` would be
  read as a command regex here and match almost nothing, silently disabling the guard.
  Matching every shell command is what a policy guard wants.
- The deny is spoken in Cursor's dialect by the shared adapter, not by this emitter.
  Cursor documents exit 2 as "equivalent to returning permission: deny", and that is
  false for plugin hooks: a hook returning exit 2 with the reason on stderr was
  witnessed NOT blocking on a real install. The adapter emits Cursor's stdout response
  as well, which is what actually blocks.
- No `failClosed: true`. Cursor defaults to fail-open on a hook error, and that default is
  kept deliberately: a plugin resolves `python3` from PATH at run time (there is no install
  step to bake an interpreter, unlike the repo path), so fail-closed on a machine without
  python3 would refuse every shell command in the editor. The posture text states the
  fail-open consequence instead of hiding it.

`manifest.yaml` stays canonical; every file here is derived and never hand-authored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock.compile.emitters.claude_pretooluse import TIMEOUT_SECONDS, _guard_script
from chock.emit import write_generated
from chock.plugin.build import _ADVISORY_NOTE, _author, _keywords, _one_line, build_skill, plugin_name
from chock.plugin.claude import POSTURE_ADVISORY, _adapter_source

#: Cursor's plugin-root variable, used verbatim by Cursor's own published plugins.
PLUGIN_ROOT = "${CURSOR_PLUGIN_ROOT}"
HOOKS_REL = "hooks/hooks.json"
SKILLS_REL = "./skills/"
EVENT = "beforeShellExecution"

#: Cursor's manifest schema is `additionalProperties: false`, so this is a fresh dict and
#: never `build_manifest()` output: that function emits `$schema` and `extensions`, which
#: Cursor's schema does not declare and therefore REJECTS. Chock's enforcement metadata
#: has nowhere to ride in this manifest, so it rides where every marketplace UI shows it
#: instead -- the description -- exactly as the Claude package does.
MANIFEST_KEYS = (
    "name",
    "displayName",
    "description",
    "version",
    "author",
    "repository",
    "license",
    "keywords",
    "category",
    "skills",
    "hooks",
)

#: Cursor blocks on exit 2 and treats EVERY other non-zero exit as "proceed" -- so a
#: missing python3 here is silently permissive rather than loudly broken. That is stated
#: plainly: a posture that reads better than the mechanism behaves is the overclaim this
#: project refuses.
POSTURE_ENFORCED_CURSOR = (
    "Session-enforced in Cursor by a beforeShellExecution hook: a matched command is "
    "denied before it runs (witnessed blocking on a real install). The hook needs python3 "
    "and a usable bash resolved from PATH; without them Cursor allows the command "
    "silently, so this fails OPEN. On Windows, disable the python3 Store alias or install "
    "Python. Repo-wide enforcement at commit time and in CI still needs `chock sync`."
)

_ENFORCED_NOTE_CURSOR = (
    "This policy is enforced in Cursor by the beforeShellExecution hook shipped with this "
    "plugin, subject to the fail-open condition stated in the plugin description. "
    "Repo-wide enforcement across every commit and in CI still needs `chock sync`. "
    "See https://github.com/open-coder-ai/chock"
)


def _hook_command(script: str) -> str:
    """One interpreter invocation against the plugin's own bundled copies.

    Deliberately without a fallback chain, for the reason measured in claude.py: `||`
    fires on ANY non-zero exit, so a real denial (exit 2) would cascade into the next
    leg's exit code and be read as allow.
    """
    adapter = f"{PLUGIN_ROOT}/scripts/pretooluse.py"
    guard = f"{PLUGIN_ROOT}/scripts/{script}"
    return f'python3 "{adapter}" --guard "{guard}"'


def build_cursor_manifest(manifest: dict[str, Any], policy_dir: Path, enforced: bool) -> dict[str, Any]:
    """Derive `.cursor-plugin/plugin.json` from a policy manifest."""
    policy_id = str(manifest.get("id") or Path(policy_dir).name)
    provenance = manifest.get("provenance") or {}
    posture = POSTURE_ENFORCED_CURSOR if enforced else POSTURE_ADVISORY

    data: dict[str, Any] = {
        "name": plugin_name(policy_id),
        "displayName": _one_line(manifest.get("name")) or policy_id,
        "description": f"{_one_line(manifest.get('description'))} [{posture}]".strip(),
        "keywords": _keywords(manifest),
        # Cursor's own plugins use this kebab-case category; deliberately NOT shared with
        # the Codex emitter, whose directory uses title-case categories.
        "category": "developer-tools",
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
        # Declared rather than left to convention discovery: Cursor's own template
        # validator checks that a declared path exists, which turns a broken emitter
        # into a loud failure instead of a silently hookless package.
        data["hooks"] = f"./{HOOKS_REL}"
    return {key: data[key] for key in MANIFEST_KEYS if key in data}


def cursor_plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """The Cursor plugin's files as {relative path: content}, writing nothing."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    script = _guard_script(policy_dir, policy_id)

    # Frontmatter claim and closing note are posture-dependent: a package shipping a hook
    # must not carry a file saying it is advisory without chock.
    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=HOOKS_REL if script else None)
    if script:
        skill = skill.replace(_ADVISORY_NOTE, _ENFORCED_NOTE_CURSOR)

    files: dict[Path, str] = {
        Path(".cursor-plugin/plugin.json"): json.dumps(
            build_cursor_manifest(manifest, policy_dir, enforced=script is not None), indent=2
        )
        + "\n",
        Path("skills") / name / "SKILL.md": skill,
    }
    if script:
        # Cursor's envelope: a version stamp and FLAT entries -- no per-entry `hooks`
        # array and no `type`, unlike the Claude/Codex shape. Identical to what
        # `chock sync` writes into .cursor/hooks.json, so the two installs agree.
        hooks = {
            "version": 1,
            "hooks": {EVENT: [{"command": _hook_command(script), "timeout": TIMEOUT_SECONDS}]},
        }
        files[Path(HOOKS_REL)] = json.dumps(hooks, indent=2) + "\n"
        files[Path("scripts/pretooluse.py")] = _adapter_source()
        files[Path("scripts") / script] = (policy_dir / "implementations" / script).read_text(encoding="utf-8")
    return files


#: Everything this emitter may write. Reconciliation needs the list because the file set
#: CHANGES: a policy that loses its guard stops emitting hooks and scripts, and a build
#: that only wrote current files would leave the old hook enforcing while the manifest
#: and skill say advisory.
OWNED_SUBTREES = ("hooks", "scripts")


def stale_cursor_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Files under this package that the current manifest would no longer produce."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    expected = set(cursor_plugin_files(Path(policy_dir), manifest, Path(repo_root)))
    stale: list[Path] = []
    for sub in OWNED_SUBTREES:
        for path in sorted((out_dir / sub).rglob("*")) if (out_dir / sub).is_dir() else []:
            if path.is_file() and path.relative_to(out_dir) not in expected:
                stale.append(path)
    return stale


def build_cursor_plugin(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write the Cursor package for one policy into a distribution directory."""
    written: list[Path] = []
    for rel, content in cursor_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    for stale in stale_cursor_files(policy_dir, manifest, repo_root, out_dir):
        stale.unlink()
        parent = stale.parent
        while parent != Path(out_dir) and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return written


def cursor_plugin_differences(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Report where the on-disk Cursor plugin disagrees with what the manifest would produce."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in cursor_plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(out_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    for stale in stale_cursor_files(policy_dir, manifest, repo_root, out_dir):
        differences.append(f"stale: {policy_id}/{Path(stale).relative_to(Path(out_dir)).as_posix()}")
    return differences
