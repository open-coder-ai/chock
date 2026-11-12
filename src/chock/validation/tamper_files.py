"""Tamper rules for files chock writes: compiled gates, the vendored runtimes and the floor's own workflow.

A runtime file or the floor workflow must be byte-equal to the merge-base or to what this engine
renders; anything else is refused by name. No structural diff is attempted, so `if: false`,
`continue-on-error`, a narrowed trigger or an added PATH-shadowing step are refused like any edit.
These files change only through a privileged merge: first a pull request that moves the floor
workflow's engine pin, then the regeneration, which the new engine renders byte-equal.
"""

from __future__ import annotations

import fnmatch
import tempfile
from pathlib import Path

import yaml

from chock import yamlio
from chock.gate.runner.constants import _ACTION_RANK
from chock.validation.floor_git import FloorError, Revision
from chock.validation.tamper import Revs, Tamper, as_json, changed, facts
from chock.validation.tamper_hooks import hook_files

_CONFIG = ".chock/config.yaml"
_PRIVILEGED = "changes only through a privileged merge (first the engine pin, then a regeneration it renders)"


def _gate_paths(rev: Revision) -> list[str]:
    prefix, name = facts()["compiled_prefix"], facts()["gate_file"]
    globs = [f"{prefix}*/{surface}/{name}" for surface in facts()["gate_surfaces"]]
    return [path for path in rev.paths(prefix) if any(fnmatch.fnmatchcase(path, g) for g in globs)]


def _how(was: dict, now: object) -> str:
    if not isinstance(now, dict):
        return "gate is not a JSON object at the head"
    lost = sorted(set(map(str, was.get("on") or [])) - set(map(str, now.get("on") or [])))
    if lost:
        return f"no longer bound to: {', '.join(lost)}"
    was_action, now_action = str(was.get("action", "block")), str(now.get("action", "block"))
    if _ACTION_RANK.get(now_action, -1) < _ACTION_RANK.get(was_action, -1):
        return f"action {was_action} -> {now_action}"
    return "kind, params, paths or message changed"


def gate_rules(revs: Revs, packs: frozenset[str]) -> list[Tamper]:
    """A compiled gate the merge-base has: deleted, or changed with no lock change for its pack."""
    found: list[Tamper] = []
    prefix = facts()["compiled_prefix"]
    for path in _gate_paths(revs.fork):
        if not revs.head.has(path):
            found.append(Tamper("gate-removed", path, "compiled gate present at the merge-base, deleted at the head"))
            continue
        if revs.head.oid(path) == revs.fork.oid(path):
            continue
        pack = path.removeprefix(prefix).partition("/")[0]
        if pack in packs:
            continue  # listed under floor/pack-changed
        was = as_json(revs.fork.text(path))
        detail = _how(was if isinstance(was, dict) else {}, as_json(revs.head.text(path)))
        found.append(Tamper("gate-changed", path, f"{detail}, and chock.lock has no change for {pack!r}"))
    return found


# --- what this engine renders -------------------------------------------------------------------


def _runtime_render(name: str) -> bytes | None:
    from chock.hooks.launch import launcher_text  # noqa: PLC0415 -- heavy imports, only when a runtime changed
    from chock.vendored import VENDORED_RUNTIMES, expected_runtime  # noqa: PLC0415

    if f"{facts()['runtime_prefix']}{name}" == facts()["launcher"]:
        return launcher_text().encode("utf-8")
    if name in VENDORED_RUNTIMES:
        return expected_runtime(*VENDORED_RUNTIMES[name])
    return None


def _vendor(index_path: str) -> str:
    return index_path.removeprefix(facts()["index_prefix"]).split("-", 1)[0]


def rendered_indexes(head: Revision, vendors: set[str]) -> dict[str, bytes] | None:
    """{path: bytes} of the pinned indexes `chock sync` writes for `vendors` from the head's committed policy
    data (read as data; nothing of it runs); None when the engine cannot render them."""
    from chock.hooks.in_agent_install import install_hooks  # noqa: PLC0415 -- only when an index changed

    index = facts()["index_prefix"]
    with tempfile.TemporaryDirectory(prefix="chock-floor-render-") as scratch:
        shadow = Path(scratch)
        prefixes = [facts()["compiled_prefix"], facts()["policies_prefix"], _CONFIG]
        prefixes += [p for _, p in hook_files(head.paths())]
        for prefix in prefixes:
            head.materialise(prefix, shadow)
        try:
            for vendor in sorted(vendors):
                install_hooks(shadow, vendor)
        except Exception:  # noqa: BLE001 -- any failure to render is "not rendered", which refuses
            return None
        folder = shadow / index
        return {
            f"{index}{p.name}": p.read_bytes()
            for p in (folder.glob("*.json") if folder.is_dir() else [])
            if _vendor(f"{index}{p.name}") in vendors
        }


def runtime_rules(revs: Revs) -> list[Tamper]:
    """Every `.chock/bin/` file the pull request changed must be the merge-base's bytes or this engine's render."""
    prefix, index = facts()["runtime_prefix"], facts()["index_prefix"]
    paths = changed(revs, prefix)
    vendors = {_vendor(p) for p in paths if p.startswith(index)}
    rendered = rendered_indexes(revs.head, vendors) if vendors else {}
    found: list[Tamper] = []
    for path in paths:
        now = revs.head.blob(path)
        if path.startswith(index):
            expected = None if rendered is None else rendered.get(path)
        else:
            expected = _runtime_render(path.removeprefix(prefix))
        if now is None and path.startswith(index) and rendered is not None and path not in rendered:
            continue  # a stale index the engine's own sync prunes
        if now is None:
            found.append(Tamper("runtime-removed", path, f"vendored runtime file deleted; it {_PRIVILEGED}"))
        elif now != expected:
            found.append(
                Tamper("runtime-changed", path, f"neither the merge-base's bytes nor this engine's; it {_PRIVILEGED}")
            )
    return found


# --- the floor's own workflow -------------------------------------------------------------------


def workflow_path(base: Revision) -> str:
    """The workflow the floor guards: the base config's `floor_workflow`, else the default."""
    try:
        config = yamlio.safe_load(base.text(_CONFIG) or "")
    except yaml.YAMLError as exc:
        msg = f"{_CONFIG} at the base does not parse; cannot tell which workflow the floor guards"
        raise FloorError(msg) from exc
    named = config.get(facts()["workflow_config_key"]) if isinstance(config, dict) else None
    return named if isinstance(named, str) and named.strip() else facts()["workflow_default"]


def _workflow_renders() -> list[bytes]:
    from chock.scaffold import install_ci  # noqa: PLC0415

    return [install_ci.render().encode("utf-8")]


def floor_workflow(revs: Revs) -> list[Tamper]:
    path = workflow_path(revs.base)
    if revs.head.oid(path) == revs.fork.oid(path):
        return []
    now = revs.head.blob(path)
    if now is None:
        return [Tamper("floor-workflow-changed", path, f"the floor's workflow was deleted; it {_PRIVILEGED}")]
    if now in _workflow_renders():
        return []
    detail = f"neither the merge-base's bytes nor this engine's render; the floor's workflow {_PRIVILEGED}"
    return [Tamper("floor-workflow-changed", path, detail)]
