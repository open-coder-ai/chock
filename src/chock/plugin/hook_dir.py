"""Hook-folder plugins (goose, grok, antigravity, openhands, kimi, droid): one builder, the layout from data.

The hook documents are agentseam's own rendering for the vendor (`vendors.*_hook_config`), so the
event spelling, matcher, wrapper, hook group and entry extras (goose's `on_failure`) are never
typed here. The folder layout and the plugin-root token are agentseam's packaging record where it
has one, else chock's store data, each with the vendor page it was read from
(data/stores/<store>.json). A layout with `hooks_key` (kimi) ships the hooks document inside
its manifest: it is built at `hooks` like every other, then folded in when the package is written.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Callable

from agentseam import packaging

from chock import vendors
from chock.compile.emitters import in_agent_hooks
from chock.compile.emitters.in_agent_hooks import generic_pre_tool_config, generic_stop_config
from chock.gate.write_gate import STOP_FLAG
from chock.hooks import launch, stop_check
from chock.plugin import gate_package, guard_gate, multi_plugin, store
from chock.plugin.build import (
    LICENSE_REL,
    advisory_note,
    build_skill,
    license_text,
    plugin_name,
    skill_assets,
)
from chock.plugin.claude import _runtime_files
from chock.plugin.store import SCRIPTS_TEMPLATE

#: Stands for the plugin folder where the vendor documents no plugin-root variable (antigravity):
#: replaced by the folder's absolute path when the package is written, never shipped as is.
ROOT_TOKEN = "__CHOCK_PLUGIN_ROOT__"  # noqa: S105 -- a path placeholder, not a credential

#: How every hook-folder posture ends: what the hook needs, and what it does not cover.
POSTURE_TAIL = (
    "The hook needs git and a Python 3.11+ on PATH. Repo-wide git-hook and CI coverage still needs `chock sync`."
)

ManifestFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Spec:
    """One store: its format name, agentseam agent, enforcement notes and (where it has one) manifest builder."""

    store: str
    agent: str
    guard_note: str
    manifest: ManifestFn | None = None


def layout(store_name: str, agent: str | None = None) -> dict[str, Any]:
    """The recorded layout: manifest (or None), hooks, skill template, plugin-root token (or None).

    chock's store data wins; otherwise agentseam's packaging record for `agent`.
    """
    found = store.layout(store_name)
    if found is None and agent is not None and agent in packaging.agents():
        roots = packaging.layout(agent)["plugin_root"]
        found = {
            "manifest": packaging.layout(agent)["manifest"],
            "hooks": packaging.supports(agent, packaging.HOOKS),
            "skill": packaging.supports(agent, packaging.SKILL),
            "plugin_root": roots[0] if roots else None,
        }
    if found is None:
        msg = f"no layout recorded for {store_name!r} in chock's store data"
        raise KeyError(msg)
    return found


def _ref(spec: Spec, rel: str) -> str:
    return f"{layout(spec.store, spec.agent)['plugin_root'] or ROOT_TOKEN}/{rel}"


#: The store-data value naming a Windows hook runner (cmd.exe, `"` passed on as `\"`) no quoting survives.
QUOTE_FREE = "quote_free"


def build_windows() -> bool:
    """Whether this build runs on Windows, where the package it writes is installed."""
    return os.name == "nt"


def quote_free(store_name: str | None) -> bool:
    """Whether this build's hook commands carry no quote or space: on Windows, for a store whose data says so."""
    return build_windows() and store_name is not None and store.windows_hook_command(store_name) == QUOTE_FREE


def hook_command(spec: Spec, flag: str, target: str) -> str:
    """One interpreter invocation of the agent's runtime, handed `--guard <script>` or `--gate <gate.json>`."""
    adapter = _ref(spec, SCRIPTS_TEMPLATE.format(name=f"{spec.agent}.py"))
    launcher_ref = _ref(spec, SCRIPTS_TEMPLATE.format(name=launch.PLUGIN_LAUNCHER))
    target_ref = _ref(spec, SCRIPTS_TEMPLATE.format(name=target))
    if quote_free(spec.store):
        return f"{launch.plugin_interpreter_quote_free(launcher_ref)} {adapter} {flag} {target_ref}"
    return f'{launch.plugin_interpreter(launcher_ref)} "{adapter}" {flag} "{target_ref}"'


def guard_doc(agent: str, command: str) -> Any:
    """agentseam's pre-tool document for the guard, on the vendor's recorded shell tools (all tools if none)."""
    return generic_pre_tool_config(agent, command, vendors.shell_matcher(agent))


def gate_doc(agent: str, command: str) -> Any:
    """agentseam's documents for every surface the gate reaches in `agent`: the write, the turn's end, or both."""
    matcher, stop = gate_package.gate_reach(agent)
    doc = generic_pre_tool_config(agent, command, matcher) if matcher is not None else None
    if stop:
        doc = guard_gate.merge_hooks(doc, generic_stop_config(agent, f"{command} {STOP_FLAG}"))
    return doc


def store_timeout(store_name: str, doc: Any) -> Any:
    """`doc` with the store's own timeout field, where agentseam's rendering writes none and chock sync has no row (kimi)."""
    field = store.hook_timeout_field(store_name)
    if field is not None:
        in_agent_hooks._stamp(doc, field, in_agent_hooks.TIMEOUT_SECONDS)
    return doc


def plugin_files(
    spec: Spec, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, *, folded: bool = True
) -> dict[Path, str]:
    """The plugin's files as {relative path: content}, writing nothing; `ROOT_TOKEN` left unresolved."""
    policy_dir = Path(policy_dir)
    policy_id = str(manifest.get("id") or policy_dir.name)
    name = plugin_name(policy_id)
    shape = layout(spec.store, spec.agent)
    parts = guard_gate.halves(spec.agent, policy_dir, policy_id, Path(repo_root))
    script, gate = parts.script, parts.gate

    shipped = shape["manifest"] if shape.get("hooks_key") else shape["hooks"]
    skill = build_skill(policy_dir, manifest, Path(repo_root), hooks=shipped if parts.enforced else None)
    note = guard_gate.skill_note(
        spec.guard_note if script else None,
        gate_package.gate_skill_note(spec.agent, gate.get("action")) if gate else None,
    )
    if note:
        skill = skill.replace(advisory_note(policy_dir, manifest), note)
    skill_rel = Path(shape["skill"].format(name=name))
    files: dict[Path, str] = {skill_rel: skill}
    if shape["manifest"] and spec.manifest is not None:
        data = spec.manifest(manifest, policy_dir, enforced=parts.enforced, gate=gate is not None, guard=bool(script))
        files[Path(shape["manifest"])] = json.dumps(data, indent=2) + "\n"
    for rel, content in skill_assets(policy_dir).items():
        files[skill_rel.parent / rel] = content
    licence = license_text(manifest)
    if licence:
        files[LICENSE_REL] = licence
    hooks = guard_gate.merge_hooks(
        guard_doc(spec.agent, hook_command(spec, "--guard", script)) if script else None,
        gate_doc(spec.agent, hook_command(spec, "--gate", "gate.json")) if gate else None,
    )
    if hooks is not None:
        hooks = guard_gate.merge_hooks(hooks, stop_check.plugin_doc(spec.agent, hooks, generic=True))
        files[Path(shape["hooks"])] = json.dumps(store_timeout(spec.store, hooks), indent=2) + "\n"
        files.update(_runtime_files(spec.agent))
    if script:
        guard_gate.place(files, store.guard_files(policy_dir, script))
    if gate:
        guard_gate.place(files, gate_package.packaged_gate_files(policy_dir, gate, SCRIPTS_TEMPLATE))
    return multi_plugin.fold_files(files, shape["hooks"], spec.agent) if folded else files


def root_path(folder: PurePath) -> str:
    """How a hook command names the plugin folder: absolute, forward slashes (git's sh reads `C:/x` on Windows)."""
    path = folder if isinstance(folder, PurePath) else Path(folder)
    return (path if path.is_absolute() else Path(path).absolute()).as_posix()


def resolve_root(files: dict[Path, str], folder: PurePath, store_name: str | None = None) -> dict[Path, str]:
    """`files` with every `ROOT_TOKEN` naming `folder`; a folder whose path a hook command cannot carry is refused."""
    root = root_path(folder)
    carried = any(ROOT_TOKEN in content for content in files.values())
    if carried and quote_free(store_name) and launch.QUOTE_FREE_UNSAFE.search(root):
        msg = (
            f"{root}: this client runs hook commands through cmd.exe on Windows, where no quoting reaches git, so "
            "the plugin folder's path may not hold spaces or other whitespace, quotes, any of | & < > ^ % ( ) ! $ "
            "backquote backslash * ? [; choose another --dest"
        )
        raise ValueError(msg)
    # A plain space is literal inside the command's double quotes; every other whitespace is refused.
    if carried and re.search(r'[^\S ]|["$`\\]', root):
        msg = (
            f"{root}: this client names the plugin folder by absolute path inside a quoted hook command, "
            "so the path may not hold tabs, line breaks or other non-space whitespace, quotes, `$`, backquotes "
            "or backslashes; choose another --dest"
        )
        raise ValueError(msg)
    return {rel: content.replace(ROOT_TOKEN, root) for rel, content in files.items()}


def fold(files: dict[Path, str], store_name: str) -> dict[Path, str]:
    """`files` as written to disk: a store whose layout names a `hooks_key` carries its hooks inside the manifest."""
    shape = store.layout(store_name) or {}
    key, hooks_rel = shape.get("hooks_key"), Path(shape.get("hooks") or "")
    if not key or hooks_rel not in files:
        return files
    out = dict(files)
    doc = json.loads(out.pop(hooks_rel))
    manifest_rel = Path(shape["manifest"])
    out[manifest_rel] = json.dumps({**json.loads(out[manifest_rel]), key: doc}, indent=2) + "\n"
    return out


def bind(spec: Spec, out_dir: Path | None = None) -> store.FilesFn:
    """`plugin_files` for `spec` in the packagers' (policy_dir, manifest, repo_root) shape, as written to `out_dir`."""

    def files_fn(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
        files = plugin_files(spec, policy_dir, manifest, repo_root)
        return fold(resolve_root(files, out_dir, spec.store) if out_dir is not None else files, spec.store)

    return files_fn


def build(spec: Spec, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[Path]:
    """Write `spec`'s package for one policy into `out_dir`."""
    return store.build_store_plugin(spec.store, bind(spec, out_dir), policy_dir, manifest, repo_root, out_dir)


def differences(spec: Spec, policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path) -> list[str]:
    """Where the on-disk package disagrees with what the manifest would produce."""
    return store.store_plugin_differences(spec.store, bind(spec, out_dir), policy_dir, manifest, repo_root, out_dir)
