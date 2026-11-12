"""Claude Code's managed drop-in: the plugin route's hooks, rooted at an absolute deploy folder, failing closed."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from agentseam import packaging

from chock.compile.emitters import managed
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.plugin.claude import claude_plugin_files
from chock.plugin.multi_plugin import SCRIPTS_DIR

VENDOR = "claude_code"
AGENT = "claude"
BUNDLE = "bundle"
_HOOKS_REL = Path(packaging.supports(VENDOR, packaging.HOOKS))
#: The plugin-root token the plugin route's commands carry, swapped for the deploy folder.
ROOT_TOKEN = str(packaging.executable_ref(VENDOR, "x")).removesuffix("/x")
_FACTS = managed.facts(VENDOR)
_FAIL = _FACTS["fail_block"]
#: The halves a plugin hook runs, by the flag its command carries.
_HALF_FLAGS = {"guard": " --guard ", "gate": " --gate "}


def _is_stop_check(group: dict[str, Any]) -> bool:
    return all(hook["command"].endswith(f" {STOP_CHECK_FLAG}") for hook in group["hooks"])


def _rooted(group: dict[str, Any], event: str, root: str) -> dict[str, Any]:
    """`group` with its plugin root swapped for `root` and, where the docs say it acts, onFailure set."""
    hooks = []
    for hook in group["hooks"]:
        command = hook["command"].replace(ROOT_TOKEN, root)
        if "${" in command:
            msg = f"{command!r} still names a client token after rooting it at {root}"
            raise managed.EmitRefusedError(msg)
        rooted = {**hook, "command": command}
        if event in _FAIL["events"]:
            rooted[_FAIL["key"]] = _FAIL["value"]
        hooks.append(rooted)
    return {**group, "hooks": hooks}


def _policy_parts(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> tuple[dict[str, Any], dict] | None:
    """The plugin route's hooks and scripts for one policy, or None when it runs nothing."""
    files = claude_plugin_files(policy_dir, manifest, repo_root, folded=False)
    if _HOOKS_REL not in files:
        return None
    scripts = {PurePosixPath(rel.as_posix()): text for rel, text in files.items() if rel.parts[0] == SCRIPTS_DIR}
    return json.loads(files[_HOOKS_REL])["hooks"], scripts


def build(
    policies: list[tuple[str, Path, dict[str, Any]]], repo_root: Path, root: str, *, lock: bool = False
) -> tuple[managed.Files, list[dict[str, Any]], list[str]]:
    """(files under `<out>/claude_code`, one label per emitted policy, the policies with nothing to run)."""
    events: dict[str, list[dict[str, Any]]] = {}
    files: managed.Files = {}
    labels, skipped = [], []
    stop_check_kept = False
    for policy_id, policy_dir, manifest in policies:
        parts = _policy_parts(policy_dir, manifest, repo_root)
        if parts is None:
            skipped.append(policy_id)
            continue
        hooks, scripts = parts
        commands = []
        for event, groups in hooks.items():
            for group in groups:
                if _is_stop_check(group):
                    if stop_check_kept:
                        continue
                    stop_check_kept = True
                events.setdefault(event, []).append(_rooted(group, event, f"{root}/{policy_id}"))
                commands += [hook["command"] for hook in group["hooks"]]
        for rel, text in scripts.items():
            files[PurePosixPath(BUNDLE, policy_id, rel)] = text
        halves = [half for half, flag in _HALF_FLAGS.items() if any(flag in command for command in commands)]
        labels.append(managed.label(policy_id, VENDOR, AGENT, halves))
    document: dict[str, Any] = {"hooks": events}
    if lock:
        document[_FACTS["lock_key"]] = True
    files[PurePosixPath(_FACTS["drop_in"])] = managed.as_json(document)
    return files, labels, skipped


def deploy_plan(platform: str, root: str, *, lock: bool) -> dict[str, Any]:
    """Where an admin places each part, what it needs, what it does not promise, and how to take it out."""
    admin = _FACTS["admin_dir"][platform]
    place = [
        {"from": _FACTS["drop_in"], "to": f"{admin}/{_FACTS['drop_in']}"},
        {"from": f"{BUNDLE}/", "to": f"{root}/"},
    ]
    plan: dict[str, Any] = {
        "vendor": VENDOR,
        "platform": platform,
        "deployed": False,
        "basis": managed.BASIS,
        "place": place,
        "undo": [f"delete {step['to']}" for step in place],
        "requirements": _FACTS["requirements"],
        "caveats": _FACTS["caveats"],
        "never_emitted": _FACTS["never_emitted"],
        "notes": [_FACTS["never_note"], *([_FACTS["lock_note"]] if lock else [])],
        "sources": _FACTS["sources"],
        "read": _FACTS["read"],
    }
    if lock:
        plan["lock_key"] = _FACTS["lock_key"]
    return plan
