"""One decision-log line per runtime hook call, on either route. Stdlib only: every vendored runtime carries it.

Sync route (the runtime under `<repo>/.chock/bin/`): `<repo>/.chock/log/gate-events.jsonl`, where gate.py
already writes each compiled gate's own record, so a `--gate` call it judged is left to it. Plugin route
(anywhere else): `~/.chock/log/<agent>/events.jsonl`. Never raises, never changes the decision, never logs
contents: a tool call's `target` is a fingerprint (decision_target.py).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from .decision_target import _dlog_client, dlog_fields, dlog_session
from .guard_runner import GUARD_LAST
from .runner.halt import HALT_HOOK_FLAG, HALT_POLICY, HALT_REASON
from .runner.journal import (
    LOG_DEBUG,
    LOG_SETTINGS_PARTS,
    log_admits,
    log_record_level,
    log_settings,
    log_trace_text,
    log_write,
)

DLOG_ROUTE_SYNC, DLOG_ROUTE_PLUGIN = "sync", "plugin"
#: The runtime's own folder on the sync route: `<repo>/.chock/bin/`.
_DLOG_SYNC_BIN = (".chock", "bin")
_DLOG_SYNC_LOG = ("log", "gate-events.jsonl")
_DLOG_PLUGIN_LOG = ("log", "events.jsonl")
#: The argv flags that name what a hook judges; the first present names the policy.
_DLOG_TARGET_FLAGS = ("--guard", "--gate", "--tool-call", "--record")
_DLOG_GATE_FLAG = "--gate"
_DLOG_COMPILED = "compiled"
#: How far above the runtime a plugin's manifest may sit (`<root>/scripts/<agent>.py`, or deeper).
_DLOG_MANIFEST_DEPTH = 3
#: agentseam's decision outcomes, as the log names them; no decision is an allow.
_DLOG_SPOKEN = {"deny": "block", "escalate": "ask", "warn": "warn"}
_DLOG_EVENT_LOGGED = {"pre_tool": "tool_use"}
_DLOG_SURFACE = {"pre_tool": "pre-tool-use", "stop": "stop"}
_DLOG_NO_RULE = "no rule matched"
_DLOG_DIST_INFO = re.compile(r"^chock-([^-]+)\.dist-info$")
#: The pre-tool exit codes of a gate.py run that wrote its own line (allow, block, ask, warn); 2 wrote none.
_DLOG_GATE_LOGGED_CODES = (0, 1, 3, 4)
#: Set by write_gate when this call ran gate.py: `code` is its exit code.
GATE_LAST = {}


def _dlog_flag_value(argv, flag):
    if flag in argv:
        at = argv.index(flag)
        if at + 1 < len(argv):
            return argv[at + 1]
    return None


def runtime_route(runtime):
    """`sync` for a runtime under `<repo>/.chock/bin/`, `plugin` for one a package carries."""
    folder = Path(runtime).resolve().parent
    return DLOG_ROUTE_SYNC if (folder.parent.name, folder.name) == _DLOG_SYNC_BIN else DLOG_ROUTE_PLUGIN


def dlog_plugin_manifest(runtime, manifests):
    """(name, version) from the nearest plugin manifest above the runtime; empty strings when there is none."""
    folder = Path(runtime).resolve().parent
    for root in [folder, *folder.parents][:_DLOG_MANIFEST_DEPTH]:
        for rel in manifests:
            try:
                doc = json.loads(root.joinpath(rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict):
                return str(doc.get("name") or ""), str(doc.get("version") or "")
    return "", ""


def _dlog_chock_version():
    """The chock installed beside this Python, from its dist-info folder name; empty when it is not installed."""
    for entry in sys.path:
        try:
            names = os.listdir(entry or ".")
        except OSError:
            continue
        found = next((m.group(1) for m in map(_DLOG_DIST_INFO.match, names) if m), None)
        if found:
            return found
    return ""


def _dlog_policy_id(target, route, plugin_name):
    """The policy a hook serves: from `.chock/compiled/<id>/` on the sync route, else the package's own name."""
    if target is None:
        return plugin_name or "unknown"
    parts = Path(target).parts
    if route == DLOG_ROUTE_SYNC and _DLOG_COMPILED in parts and parts.index(_DLOG_COMPILED) + 1 < len(parts):
        return parts[parts.index(_DLOG_COMPILED) + 1]
    if route == DLOG_ROUTE_SYNC and Path(target).parent.name == "implementations":
        return Path(target).parent.parent.name
    return plugin_name or Path(target).stem


def _dlog_repo_root(start):
    """The repository holding `start`: the nearest folder with `.git`, or None."""
    try:
        here = Path(start).resolve()
    except (OSError, ValueError):
        return None
    return next((folder for folder in (here, *here.parents) if (folder / ".git").exists()), None)


def _dlog_trace(event, wire, rule, stages):
    """The debug-only fields: what was detected and matched, and how long each stage took. Never file contents."""
    trace = {"wire_event": wire, "tool": event.tool, "rule": rule or _DLOG_NO_RULE, "stages_ms": stages}
    if event.command:
        trace["command"] = log_trace_text(event.command)
    if event.path:
        trace["path"] = log_trace_text(event.path)
    if "code" in GUARD_LAST:
        trace["exit_code"] = GUARD_LAST["code"]
    return trace


def _dlog_reason(source, outcome):
    """A short code for why: `stopped`, `guard-blocked`, `guard-errored`, `gate-block`, `fault`, or `no-rule` (allow)."""
    if source is None:
        return "no-rule"
    if source == HALT_REASON:
        return HALT_REASON
    if source == "guard" and "outcome" in GUARD_LAST:
        guarded = GUARD_LAST["outcome"]
        return f"guard-{guarded}"
    if source == "fault":
        return source
    spoken = _DLOG_SPOKEN.get(outcome, "allow")
    return f"{source}-{spoken}"


def _dlog_paths(route, runtime, agent, event):
    """(log file, repository whose settings apply) for this call."""
    if route == DLOG_ROUTE_SYNC:
        chock_root = Path(runtime).resolve().parent.parent
        return chock_root.joinpath(*_DLOG_SYNC_LOG), chock_root.parent
    home = Path(os.path.expanduser("~")).joinpath(LOG_SETTINGS_PARTS[0])
    return home.joinpath(_DLOG_PLUGIN_LOG[0], agent, _DLOG_PLUGIN_LOG[1]), _dlog_repo_root(event.cwd or ".")


def log_decision(argv, event, decision, judged, context):
    """Write this call's one line, if the level in force admits it.

    `judged` is (source, rule, started, stages); `context` may carry `wire`, `can_ask` and the plugin `manifests`.
    """
    try:
        runtime = globals().get("__file__") or sys.argv[0]
        route = runtime_route(runtime)
        source, rule, started, stages = judged
        gate_wrote = event.event != "pre_tool" or GATE_LAST.get("code") in _DLOG_GATE_LOGGED_CODES
        if route == DLOG_ROUTE_SYNC and _DLOG_GATE_FLAG in argv and source in (None, "gate") and gate_wrote:
            return  # gate.py and the stop re-entry ledger write this call's line on the sync route
        agent = str(getattr(event, "agent", None) or "unknown")
        log_path, repo = _dlog_paths(route, runtime, agent, event)
        outcome = getattr(decision, "outcome", None) if decision is not None else None
        level = log_settings(repo)[0]
        fields = dlog_fields(event, repo)
        if not log_admits(level, log_record_level({"verdict": _DLOG_SPOKEN.get(outcome, "allow"), **fields})):
            return  # nothing to write: skip the manifest and version lookups on the hot path
        plugin_name, plugin_version = (
            dlog_plugin_manifest(runtime, context.get("manifests", ())) if route == DLOG_ROUTE_PLUGIN else ("", "")
        )
        target = next((v for v in (_dlog_flag_value(argv, f) for f in _DLOG_TARGET_FLAGS) if v), None)
        record = {
            "route": route,
            "agent": agent,
            "event": _DLOG_EVENT_LOGGED.get(event.event, event.event),
            "policy_id": HALT_POLICY if HALT_HOOK_FLAG in argv else _dlog_policy_id(target, route, plugin_name),
            "surface": _DLOG_SURFACE.get(event.event, str(event.event)),
            "verdict": _DLOG_SPOKEN.get(outcome, "allow"),
            "reason": _dlog_reason(source, outcome),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "can_ask": context.get("can_ask"),
        }
        version = _dlog_chock_version() if route == DLOG_ROUTE_SYNC else ""  # a plugin runs no chock: never named
        if version:  # unknown is left out, never written empty
            record["chock_version"] = version
        record.update(fields)
        client = _dlog_client(event.raw)
        if client:
            record["client"] = client
        if route == DLOG_ROUTE_PLUGIN:  # one file per client, shared by every plugin in it: each line names its own
            record.update(plugin=plugin_name, plugin_version=plugin_version)
        if level == LOG_DEBUG:
            record["trace"] = _dlog_trace(event, context.get("wire"), rule, stages)
        log_write(log_path, record, repo)
    except Exception:  # noqa: BLE001 -- a log line must never change the decision or raise
        return


def log_heartbeat(event, manifests):
    """The `session_start` line a session-start hook writes at info: which route, agent and package ran. Never raises."""
    try:
        runtime = globals().get("__file__") or sys.argv[0]
        route = runtime_route(runtime)
        agent = str(getattr(event, "agent", None) or "unknown")
        log_path, repo = _dlog_paths(route, runtime, agent, event)
        record = dlog_session(event, {"event": "session_start", "route": route, "agent": agent})
        if route == DLOG_ROUTE_PLUGIN:
            plugin_name, plugin_version = dlog_plugin_manifest(runtime, manifests)
            record.update(plugin=plugin_name, plugin_version=plugin_version)
        version = _dlog_chock_version() if route == DLOG_ROUTE_SYNC else ""
        if version:
            record["chock_version"] = version
        log_write(log_path, record, repo)
    except Exception:  # noqa: BLE001 -- a heartbeat must never block a session or raise
        return
