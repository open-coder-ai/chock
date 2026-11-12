"""Claude Code's managed drop-in: the plugin route's hooks in exec form, run by the admin's interpreter from an absolute deploy folder."""

from __future__ import annotations

import json
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from agentseam import packaging

from chock.compile.emitters import managed
from chock.hooks import launch
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.plugin.claude import claude_plugin_files
from chock.plugin.multi_plugin import SCRIPTS_DIR
from chock.resources import package_data_dir

VENDOR = "claude_code"
AGENT = "claude"
BUNDLE = "bundle"
_HOOKS_REL = Path(packaging.supports(VENDOR, packaging.HOOKS))
#: The plugin-root token the plugin route's commands carry, swapped for the deploy folder.
ROOT_TOKEN = str(packaging.executable_ref(VENDOR, "x")).removesuffix("/x")
#: What every plugin-route command starts with: its sh launcher, which the managed file never runs.
_PLUGIN_PREFIX = launch.plugin_interpreter(f"{ROOT_TOKEN}/{SCRIPTS_DIR}/{launch.PLUGIN_LAUNCHER}") + " "
_FACTS = managed.facts(VENDOR)
_FAIL = _FACTS["fail_block"]
#: --on-failure choices; `block` refuses what cannot be checked, `allow` lets it through with a note.
BLOCK, ALLOW = "block", "allow"
ON_FAILURE = (BLOCK, ALLOW)
_OUTCOME = {
    BLOCK: ("refusing this call (--on-failure block)", 2),
    ALLOW: ("this call goes ahead unchecked (--on-failure allow)", 0),
}
_BOOTSTRAP = (
    package_data_dir("chock", "compile", "emitters", "data")
    .joinpath("managed_bootstrap.txt")
    .read_text(encoding="utf-8")
    .strip()
    .replace("__MIN_PYTHON_TEXT__", ".".join(map(str, launch.MIN_PYTHON)))
    .replace("__MIN_PYTHON__", ", ".join(map(str, launch.MIN_PYTHON)))
)
#: The halves a plugin hook runs, by the flag its argv carries.
_HALF_FLAGS = {"guard": "--guard", "gate": "--gate"}


def bootstrap(on_failure: str) -> str:
    """The `-c` program that starts a bundled runtime, or, when it or Python 3.11+ is missing, says so and exits per `on_failure`."""
    outcome, code = _OUTCOME[on_failure]
    return _BOOTSTRAP.replace("__OUTCOME__", outcome).replace("__EXIT__", str(code))


def _argv(command: str) -> list[str]:
    """The runtime path and flags of a plugin-route command, its sh launcher prefix dropped."""
    if not command.startswith(_PLUGIN_PREFIX):
        msg = f"{command!r} does not start with the plugin launcher this emitter replaces"
        raise managed.EmitRefusedError(msg)
    return shlex.split(command.removeprefix(_PLUGIN_PREFIX))


def _exec_hook(hook: dict[str, Any], event: str, root: str, python: str, on_failure: str) -> dict[str, Any]:
    """`hook` in exec form: `python` runs the bootstrap on the runtime rooted at `root`; onFailure only where it acts."""
    argv = [arg.replace(ROOT_TOKEN, root) for arg in _argv(hook["command"])]
    if any("${" in arg for arg in argv):
        msg = f"{argv!r} still names a client token after rooting it at {root}"
        raise managed.EmitRefusedError(msg)
    blocks = on_failure == BLOCK and event in _FAIL["events"]
    entry = {
        "type": hook["type"],
        "command": python,
        "args": [*_FACTS["python_flags"], bootstrap(on_failure if blocks else ALLOW), *argv],
    }
    entry.update({key: value for key, value in hook.items() if key not in {"type", "command"}})
    if blocks:
        entry[_FAIL["key"]] = _FAIL["value"]
    return entry


def _is_stop_check(group: dict[str, Any]) -> bool:
    return all(hook["command"].endswith(f" {STOP_CHECK_FLAG}") for hook in group["hooks"])


def _policy_parts(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> tuple[dict[str, Any], dict] | None:
    """The plugin route's hooks and scripts for one policy, or None when it runs nothing; its sh launcher is left out."""
    files = claude_plugin_files(policy_dir, manifest, repo_root, folded=False)
    if _HOOKS_REL not in files:
        return None
    scripts = {
        PurePosixPath(rel.as_posix()): text
        for rel, text in files.items()
        if rel.parts[0] == SCRIPTS_DIR and rel.name != launch.PLUGIN_LAUNCHER
    }
    return json.loads(files[_HOOKS_REL])["hooks"], scripts


def build(
    policies: list[tuple[str, Path, dict[str, Any]]], repo_root: Path, options: dict[str, Any]
) -> tuple[managed.Files, list[dict[str, Any]], list[str]]:
    """(files under `<out>/claude_code`, one label per emitted policy, the policies with nothing to run).

    `options`: root (deploy folder), python (absolute interpreter), on_failure, lock. The repo stop's matcher-less
    stop check is never emitted: no policy needs it, and it would run on every tool call.
    """
    events: dict[str, list[dict[str, Any]]] = {}
    files: managed.Files = {}
    labels, skipped = [], []
    for policy_id, policy_dir, manifest in policies:
        parts = _policy_parts(policy_dir, manifest, repo_root)
        if parts is None:
            skipped.append(policy_id)
            continue
        hooks, scripts = parts
        flags = set()
        for event, groups in hooks.items():
            for group in (group for group in groups if not _is_stop_check(group)):
                rooted = [
                    _exec_hook(hook, event, f"{options['root']}/{policy_id}", options["python"], options["on_failure"])
                    for hook in group["hooks"]
                ]
                events.setdefault(event, []).append({**group, "hooks": rooted})
                flags.update(arg for hook in rooted for arg in hook["args"])
        for rel, text in scripts.items():
            files[PurePosixPath(BUNDLE, policy_id, rel)] = text
        labels.append(
            managed.label(policy_id, VENDOR, AGENT, [half for half, flag in _HALF_FLAGS.items() if flag in flags])
        )
    document: dict[str, Any] = {"hooks": events}
    if options["lock"]:
        document[_FACTS["lock_key"]] = True
    files[PurePosixPath(_FACTS["drop_in"])] = managed.as_json(document)
    return files, labels, skipped


def matchers(document: dict[str, Any]) -> list[str]:
    """The tool matchers of the emitted pre-tool groups, in order, each once."""
    found = (group.get("matcher") for group in document["hooks"].get("PreToolUse", []))
    return list(dict.fromkeys(matcher for matcher in found if matcher))


def deploy_plan(platform: str, options: dict[str, Any], tools: list[str]) -> dict[str, Any]:
    """Where an admin places each part, what it needs, what the failure choice does, what it does not promise, and the undo."""
    root, python, lock = options["root"], options["python"], options["lock"]
    admin = _FACTS["admin_dir"][platform]
    place = [
        {"from": _FACTS["drop_in"], "to": f"{admin}/{_FACTS['drop_in']}"},
        {"from": f"{BUNDLE}/", "to": f"{root}/"},
    ]
    consequence = (
        _FACTS["on_failure"][options["on_failure"]]
        .replace("__PYTHON__", python)
        .replace("__MATCHERS__", ", ".join(tools))
    )
    plan: dict[str, Any] = {
        "vendor": VENDOR,
        "platform": platform,
        "deployed": False,
        "basis": managed.BASIS,
        "python": python,
        "on_failure": {"choice": options["on_failure"], "consequence": consequence},
        "place": place,
        "undo": [f"delete {step['to']}" for step in place],
        "requirements": [line.replace("__PYTHON__", python) for line in _FACTS["requirements"]],
        "caveats": _FACTS["caveats"],
        "never_emitted": _FACTS["never_emitted"],
        "notes": [_FACTS["never_note"], *([_FACTS["lock_note"]] if lock else [])],
        "sources": _FACTS["sources"],
        "read": _FACTS["read"],
    }
    if lock:
        plan["lock_key"] = _FACTS["lock_key"]
    return plan
