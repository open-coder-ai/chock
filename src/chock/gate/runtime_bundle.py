"""Per-agent runtime entry: agentseam's bundle() plus chock's handler, which loads the shared runtime (runtime_shared)."""

from __future__ import annotations

import functools

from agentseam import bundler, contract

from chock.gate.plugin_manifests import plugin_manifests
from chock.gate.wire_shapes import EVENT_KEYS as _EVENT_KEYS
from chock.gate.wire_shapes import wire_raw as _wire_raw
from chock.hooks.launch import MIN_PYTHON
from chock.resources import package_data_dir
from chock.vendors import entry, in_agent_vendors

from . import sessionstart, write_gate
from .runtime_shared import SHARED_FILE, SHARED_NAME, _extract, _needed_imports, _shared_body, render_shared, shared_pin

BEGIN = "# >>> agentseam handler >>>"
END = "# <<< agentseam handler <<<"

_SESSION_START_AGENTS = frozenset({"claude_code"})

RUNTIME_AGENTS = in_agent_vendors()

_DATA_DIR = package_data_dir("chock.gate", "data")

_DISPATCH = _DATA_DIR.joinpath("dispatch.py.tmpl").read_text(encoding="utf-8")
_DISPATCH_BRANCH_TOKEN = "# __SESSION_START_BRANCH__\n"  # noqa: S105 -- a template marker, not a credential
_WIRE_NAME_OF = {"cursor": "cursor_wire(raw)"}  # a family that infers the wire name from shape: the same way here

_UNREADABLE = _DATA_DIR.joinpath("unreadable_payload.py.tmpl").read_text(encoding="utf-8")
_WIRE_RAW_TOKENS = {"__PRE_TOOL_RAW__": contract.PRE_TOOL, "__STOP_RAW__": contract.STOP}
#: The flags the runtime fault reads the event from, with no shared runtime to read them through.
_FLAG_TOKENS = {
    "__GATE_FLAG__": repr(write_gate.GATE_FLAG),
    "__STOP_FLAG__": repr(write_gate.STOP_FLAG),
    "__STOP_DIR__": repr(write_gate._EVENT_ARG[contract.STOP]),
}


def _warn_answer(agent: str) -> str:
    """The respond function that carries a warning's words in `agent`'s client, as the dispatch routes it."""
    if agent in _COPILOT_RESPOND_AGENTS:
        return "_chock_copilot_respond"
    if agent in _WARN_RESPOND_AGENTS:
        return "_chock_warn_respond"
    return "_chock_stop_warn_respond" if agent in _STOP_WARN_RESPOND_AGENTS else "respond"


def _unreadable_source(agent: str) -> str:
    """The unreadable-payload refusal, in `agent`'s own pre-tool and stop event names and answer."""
    answer = "_chock_copilot_respond" if agent in _COPILOT_RESPOND_AGENTS else "respond"
    source = _UNREADABLE.replace("__WARN_RESPOND__", _warn_answer(agent)).replace("__RESPOND__", answer)
    for token, canonical in _WIRE_RAW_TOKENS.items():
        source = source.replace(token, repr(_wire_raw(agent, canonical)))
    for token, value in _FLAG_TOKENS.items():
        source = source.replace(token, value)
    return source


#: agentseam's `main` allows a payload it cannot read; the replacement refuses in the client's dialect.
_UNREADABLE_BRANCH = """    except json.JSONDecodeError:
        # Malformed input is not the agent's fault to pay for: allow, stay silent.
        if exit:
            sys.exit(0)
        return 0
    except (ValueError, RecursionError, MemoryError):
        # Valid JSON this file cannot decode: nothing to judge, so the blocking exit code.
        _report(traceback.format_exc())
        if exit:
            sys.exit(2)
        return 2
    except Exception:
        if exit:
            sys.exit(0)
        return 0
"""
_UNREADABLE_REFUSAL = """    except Exception:
        raw = None
    if not isinstance(raw, dict):
        text, code = _chock_unreadable()
        if text:
            _emit(out, text)
        if exit:
            sys.exit(code)
        return code
"""

_SESSION_START_BRANCH = _DATA_DIR.joinpath("session_start_branch.py.tmpl").read_text(encoding="utf-8")

_SESSION_START_ORCHESTRATION = _DATA_DIR.joinpath("session_start_orchestration.py.tmpl").read_text(encoding="utf-8")

#: Vendors whose refusal also carries the top-level answer their runtime was witnessed honouring.
_COPILOT_RESPOND_AGENTS = frozenset({"vscode_copilot"})
#: agentseam's own call, in `_decide`, that the Copilot answer is routed through instead: a rebind of
#: `respond` would shadow its name in the one flat namespace, which test_runtime_goldens forbids.
_RESPOND_CALL = "return respond(degrade(decision, event), event)"
_COPILOT_RESPOND_CALL = "return _chock_copilot_respond(degrade(decision, event), event)"
_COPILOT_RESPOND = _DATA_DIR.joinpath("copilot_respond.py.tmpl").read_text(encoding="utf-8")


#: Vendors whose warn also reaches the agent or the user: only where the reply channel is documented.
_WARN_RESPOND_AGENTS = frozenset({"claude_code"})
_WARN_RESPOND_CALL = "return _chock_warn_respond(degrade(decision, event), event)"
_WARN_RESPOND = _DATA_DIR.joinpath("warn_respond.py.tmpl").read_text(encoding="utf-8")

#: Vendors that document `systemMessage` as a warning shown to the user, at Stop too.
_STOP_WARN_AGENTS = frozenset({"claude_code", "codex_cli", "vscode_copilot"})
_STOP_WARN = _DATA_DIR.joinpath("stop_warn.py.tmpl").read_text(encoding="utf-8")
#: Of those, the ones no other respond wrapper routes: their stop warning is routed on its own.
_STOP_WARN_RESPOND_AGENTS = _STOP_WARN_AGENTS - _COPILOT_RESPOND_AGENTS - _WARN_RESPOND_AGENTS
_STOP_WARN_RESPOND_CALL = "return _chock_stop_warn_respond(degrade(decision, event), event)"


def pre_tool_can_ask(agent: str) -> dict[str, bool]:
    """Per wire event `agent` maps to pre_tool: whether that gate shows an escalate as a prompt."""
    vendor = entry(agent)
    gates = vendor.get("verdicts", {}).get("gates", {})
    pre_tool = [name for name, canonical in vendor.get("events", {}).items() if canonical == contract.PRE_TOOL]
    return {name: bool((gates.get(name) or {}).get("honours_escalate")) for name in pre_tool}


def _can_ask_tokens(agent: str) -> dict[str, str]:
    """The dispatcher's can-ask map, the keys naming a payload's event, and how this bundle reads the name."""
    vendor = entry(agent)
    return {
        "__CAN_ASK__": repr(pre_tool_can_ask(agent)),
        "__EVENT_KEYS__": repr(tuple(dict.fromkeys((*vendor["claims"].get("event_key", ()), *_EVENT_KEYS)))),
        "__WIRE_NAME__": _WIRE_NAME_OF.get(vendor.get("family"), "_chock_wire_name(raw)"),
        "__PLUGIN_MANIFESTS__": repr(plugin_manifests()),
    }


_LOADER = _DATA_DIR.joinpath("runtime_loader.py.tmpl").read_text(encoding="utf-8")


def _loader() -> str:
    return (
        _LOADER.replace("__SHARED_FILE_REPR__", repr(SHARED_FILE))
        .replace("__SHARED_NAME_REPR__", repr(SHARED_NAME))
        .replace("__SHARED_FILE__", SHARED_FILE)
        .replace("__PIN__", repr(shared_pin()))
    )


def _handler_source(agent: str) -> str:
    """Every name `agent`'s entry runs with: the shared guard logic, then the entry's own handler."""
    return _shared_body() + _entry_handler(agent)


def _entry_handler(agent: str) -> str:
    """The handler block `agent`'s entry carries: the pinned loader, then its vendor's own glue."""
    parts = [_loader()]
    if agent in _SESSION_START_AGENTS:
        parts.append(_extract(sessionstart))
        parts.append(_SESSION_START_ORCHESTRATION)
    branch = _SESSION_START_BRANCH if agent in _SESSION_START_AGENTS else ""
    parts.append(_unreadable_source(agent))
    dispatch = _DISPATCH.replace(_DISPATCH_BRANCH_TOKEN, branch)
    for token, value in _can_ask_tokens(agent).items():
        dispatch = dispatch.replace(token, value)
    parts.append(dispatch)
    if agent in _COPILOT_RESPOND_AGENTS:
        parts.append(_COPILOT_RESPOND)
    if agent in _WARN_RESPOND_AGENTS:
        parts.append(_WARN_RESPOND)
    if agent in _STOP_WARN_AGENTS:
        parts.append(_STOP_WARN)
    return "".join(parts)


#: The end of agentseam's `main`: a multi-policy hook leaves through `_chock_leave`, which ends what a hung member left behind.
_MAIN_EXIT = "        _emit(out, text)\n    if exit:\n        sys.exit(code)\n    return code\n"
_MAIN_LEAVE = "        _emit(out, text)\n    if exit:\n        _chock_leave(code)\n    return code\n"

_FUTURE = "from __future__ import annotations\n\n"

#: Run first in every entry: a Python below the minimum exits silently, and the launcher's marker fd is written to.
_START_MARKER = (
    _DATA_DIR.joinpath("start_marker.py.tmpl").read_text(encoding="utf-8").replace("__MIN_PYTHON__", repr(MIN_PYTHON))
)

#: chock's imports go right after this line of agentseam's hoisted block. Anchored on the one
#: line, not the whole block: agentseam 0.3.4 hoists contextlib/io/os around json and sys, and
#: an exact-block anchor then matched nothing -- every runtime failed to render and sync wired
#: no hooks at all. Where the block is unchanged the output is byte-identical to before.
_SYS_IMPORT = "import sys\n"


def _hoist_point(source: str) -> int:
    """Offset just past `import sys` in the import block after `from __future__`, or -1."""
    start = source.find(_FUTURE)
    if start < 0:
        return -1
    block_start = start + len(_FUTURE)
    block_end = source.find("\n\n", block_start)
    block = source[block_start : block_end + 1 if block_end >= 0 else len(source)]
    at = ("\n" + block).find("\n" + _SYS_IMPORT)
    return -1 if at < 0 else block_start + at + len(_SYS_IMPORT)


def runtime_files(agent: str) -> dict[str, str]:
    """{file name: text} for `agent`'s runtime: the entry and the shared runtime it loads, placed side by side."""
    return {f"{agent}.py": render(agent), SHARED_FILE: render_shared()}


@functools.cache
def render(agent: str) -> str:
    """Render `agent`'s runtime entry: agentseam's bundle, chock's imports and its handler, which loads `render_shared()`."""
    source = bundler.bundle(agent)
    at = _hoist_point(source)
    if at < 0:
        raise ValueError("%s: bundle() output has no top-imports anchor to hoist onto" % agent)
    handler = _entry_handler(agent)
    source = source[:at] + "\n" + _needed_imports(handler) + source[at:]
    future = source.find(_FUTURE) + len(_FUTURE)
    source = source[:future] + _START_MARKER + source[future:]
    head, sep, rest = source.partition(BEGIN)
    if not sep:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, BEGIN))
    _, sep2, tail = rest.partition(END)
    if not sep2:
        raise ValueError("%s: bundle() output has no %r marker" % (agent, END))
    routes = (
        (_COPILOT_RESPOND_AGENTS, _COPILOT_RESPOND_CALL),
        (_WARN_RESPOND_AGENTS, _WARN_RESPOND_CALL),
        (_STOP_WARN_RESPOND_AGENTS, _STOP_WARN_RESPOND_CALL),
    )
    for agents, call in routes:
        if agent in agents:
            if _RESPOND_CALL not in tail:
                raise ValueError("%s: bundle() output has no %r call to route" % (agent, _RESPOND_CALL))
            tail = tail.replace(_RESPOND_CALL, call)
    if _UNREADABLE_BRANCH not in tail:
        raise ValueError("%s: bundle() output has no unreadable-payload branch to refuse on" % agent)
    tail = tail.replace(_UNREADABLE_BRANCH, _UNREADABLE_REFUSAL)
    if tail.count(_MAIN_EXIT) != 1:
        raise ValueError("%s: bundle() output has no single exit of main to route through _chock_leave" % agent)
    tail = tail.replace(_MAIN_EXIT, _MAIN_LEAVE)
    return "%s%s\n%s%s%s" % (head, BEGIN, handler, END, tail)
