"""Gate runner: event, environment, rollout, log and action vocabulary; imports nothing of the runner."""

from __future__ import annotations

import re

#: The vocabulary its sibling modules import (header only: gate.py, one module, needs no `__all__`).
__all__ = [
    "ACTION_ASK",
    "ACTION_BLOCK",
    "ACTION_WARN",
    "AGENT_COMMIT_ENV",
    "AGENT_COMMIT_EVENT",
    "AGENT_EVENTS",
    "AI_AGENT_ENV",
    "ALLOW_ENV",
    "CLAUDECODE_ENV",
    "COMPILED_PREFIX",
    "CONFIG_AGENT_ENV_KEY",
    "EXIT_ASK",
    "EXIT_WARN",
    "GATE_LOG_ENV",
    "HEAD_WAIVER_EVENTS",
    "POLICIES_PREFIX",
    "ROLLOUT_ASK",
    "ROLLOUT_ENFORCE",
    "ROLLOUT_ENV",
    "ROLLOUT_OBSERVE",
    "ROLLOUT_RANK",
    "SCRIPT_BASE_GATE",
    "STOP_EVENT",
    "TOOL_USE_EVENT",
    "VERDICT_ERROR",
    "WAIVABLE_EVENTS",
    "WRITE_PATH_KINDS",
    "_ACTION_RANK",
    "_AGENT_COMMIT_NOTE",
    "_CONFIG_ITEM_RE",
    "_CONFIG_KEY_RE",
    "_CONFIG_PATH",
    "_CONFIG_ROLLOUT_RE",
    "_DEPENDENCY_KIND",
    "_ENV_NAME_RE",
    "_EVENT_NAME",
    "_GIT_EVENTS",
    "_HUMAN_ENV",
    "_LOG_MATCH_CAP",
    "_LOG_MAX_BYTES",
    "_MIN_COMPILED_PATH_DEPTH",
    "_OBSERVE_NOTE",
    "_PUSH_LINE_MIN_PARTS",
    "_ROLLOUT_CEILING",
]

# >>> gate.py 02
#: Kinds whose question a write can answer. A branch name is not in a tool call, so
#: forbidden_ref has nothing to read here; saying so beats passing it empty and calling
#: that an allow.
_DEPENDENCY_KIND = "dependency_allowlist"
WRITE_PATH_KINDS = frozenset({"content_regex", "script", _DEPENDENCY_KIND, "test_integrity"})


#: Events at which a line-level waiver is honoured: the ones where a human staged the text. At
#: tool use the scanned text is a live tool argument, and at the turn's end it is a file the
#: same agent just wrote, so a pragma there is the refused party waiving itself -- the gateway
#: evaluator never read it for that reason, and the published policy message says so.
WAIVABLE_EVENTS = frozenset({"commit", "push", "ci"})

#: The event of both agent surfaces (pre-tool-use and stop), by the name policies declare.
TOOL_USE_EVENT = "tool_use"

#: Env var a person or agent sets to say who is committing: truthy marks an agent, and a value in
#: `_HUMAN_ENV` marks a person and wins over every detected marker.
AGENT_COMMIT_ENV = "CHOCK_AGENT_COMMIT"

#: Markers Claude Code's Bash tool sets in every command it runs (witnessed; a git hook inherits
#: the environment of the git process). `AI_AGENT` is `claude-code_<version>_agent` there.
CLAUDECODE_ENV = "CLAUDECODE"
AI_AGENT_ENV = "AI_AGENT"

#: Top-level key of `.chock/config.yaml` naming further variables whose presence marks an agent.
CONFIG_AGENT_ENV_KEY = "agent_commit_env"
_CONFIG_PATH = (".chock", "config.yaml")
_CONFIG_KEY_RE = re.compile(rf"^{CONFIG_AGENT_ENV_KEY}:[ \t]*(?P<rest>[^#\n]*)")
_CONFIG_ITEM_RE = re.compile(r"^[ \t]+-[ \t]*(?P<name>[^\s#]+)")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Env var naming, comma separated, the policies whose `ask` a person has answered "go ahead".
ALLOW_ENV = "CHOCK_ALLOW"

#: The event an agent-made commit is judged at: outside WAIVABLE_EVENTS, so a waiver the commit
#: adds is not honoured. Coverage (`on: [commit]`) is still decided by the name `commit`.
AGENT_COMMIT_EVENT = "agent-commit"

#: Events where the actor may be the refused agent: a waiver counts only when HEAD already has that line.
HEAD_WAIVER_EVENTS = frozenset({AGENT_COMMIT_EVENT, TOOL_USE_EVENT})

_HUMAN_ENV = frozenset({"0", "false", "no", "off"})

_OBSERVE_NOTE = (
    "gate: {policy} found a violation that enforce would have stopped ({held}); "
    "this repo's rollout level lets it through and records it in .chock/log/gate-events.jsonl."
)

_AGENT_COMMIT_NOTE = (
    "gate: this commit is treated as an agent's ({signal}), so a waiver it adds "
    "was not honoured; only waivers already in HEAD count. A person reviews and waives it, then "
    f"commits from their own shell with {AGENT_COMMIT_ENV}=0."
)


# >>> gate.py 04
#: How far a gate may escalate in this repo: `rollout:` in `.chock/config.yaml`, else enforce.
ROLLOUT_ENV = "CHOCK_ROLLOUT"
ROLLOUT_OBSERVE, ROLLOUT_ASK, ROLLOUT_ENFORCE = "observe", "ask", "enforce"
ROLLOUT_RANK = {ROLLOUT_OBSERVE: 0, ROLLOUT_ASK: 1, ROLLOUT_ENFORCE: 2}
_CONFIG_ROLLOUT_RE = re.compile(r"^rollout:[ \t]*(?P<rest>[^#\n]*)")


# >>> gate.py 09
GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576
_LOG_MATCH_CAP = 20

#: A pre-push stdin line is `<local ref> <local sha> <remote ref> <remote sha>`;
#: at least 3 whitespace-separated parts to reach the remote ref at index 2.
_PUSH_LINE_MIN_PARTS = 3

#: `<repo>/.chock/compiled/<policy>/git-hook/<script>`.resolve().parents needs at
#: least 4 entries to reach the `compiled` directory at index 2 and its parent
#: (the `.chock` root) at index 3.
_MIN_COMPILED_PATH_DEPTH = 4


# >>> gate.py 11
#: Both agent surfaces answer to the vocabulary policies already declare. A policy saying
#: `on: [commit, tool_use]` has been asking for both of these all along; nothing in a manifest
#: has to change for it to get them.
_EVENT_NAME = {
    "pre-commit": "commit",
    "commit-msg": "commit",
    "pre-push": "push",
    "pre-tool-use": "tool_use",
    "stop": "tool_use",
}

STOP_EVENT = "stop"

AGENT_EVENTS = ("pre-tool-use", STOP_EVENT)

#: `script_base` value naming the gate file's own directory as where `params.script` lives.
SCRIPT_BASE_GATE = "gate"

#: A gate skips only its own policy's folders, so a policy's evals (which carry the very
#: content its gate refuses) never trip it. The rest of `.chock/`, including other policies'
#: compiled output and the vendored runtimes, stays in scope: a file planted there is judged.
COMPILED_PREFIX = ".chock/compiled/"
POLICIES_PREFIX = ".agents/policies/"


# >>> gate.py 13
#: What a gate does with a violation. The declared action is the ceiling: a script may choose a
#: gentler verdict at run time, never a harsher one.
ACTION_BLOCK, ACTION_ASK, ACTION_WARN = "block", "ask", "warn"
_ACTION_RANK = {ACTION_WARN: 0, ACTION_ASK: 1, ACTION_BLOCK: 2}
_ROLLOUT_CEILING = {ROLLOUT_OBSERVE: ACTION_WARN, ROLLOUT_ASK: ACTION_ASK, ROLLOUT_ENFORCE: ACTION_BLOCK}

#: Exit codes an agent-event run reports beyond 0 (allow), 1 (block) and 2 (cannot judge): the
#: command-guard contract's own, so the vendored runtimes read a gate as they read a guard.
EXIT_ASK, EXIT_WARN = 3, 4

#: The verdict of a run that could not judge, beside the actions a gate can take.
VERDICT_ERROR = "error"

_GIT_EVENTS = ("pre-commit", "pre-push", "commit-msg")
