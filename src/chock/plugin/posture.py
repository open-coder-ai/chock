"""Package posture prose whose witness clause is rendered from the ledger, never hand-asserted."""

from __future__ import annotations

from agentseam import contract as _contract
from agentseam import matrix as _matrix

from chock import evidence

UNWITNESSED = "documented by the vendor; not witnessed by chock"


def witness_clause(agent: str, surface: str = evidence.PLUGIN_HOOK, *, ledger=None) -> str:
    """What chock may say about seeing `agent` block: the ledger row, or that there is none."""
    row = evidence.witness(agent, surface, ledger=ledger)
    if row is None or not _matrix.can_block(agent, _contract.PRE_TOOL):
        return UNWITNESSED
    return f"witnessed blocking on {row.client}, {row.date}"


def enforced_codex(*, ledger=None) -> str:
    """Codex's enforced posture: its trust review, its fail-open hook, its deny-on-guard-failure."""
    return (
        "Session-enforced in Codex by a PreToolUse hook: a matched command is denied before "
        f"it runs ({witness_clause('codex_cli', ledger=ledger)}; the deny is "
        "returned as hook JSON, not an exit code, which Codex's Windows shell wrapper "
        "mangles). Codex requires a one-time trust review per hook -- the plugin is ADVISORY "
        "until you approve its hook, and a plugin update voids that trust until re-approved. "
        "The hook needs git and a Python 3.11+ (python3, python or py) on PATH; with no working "
        "Python it exits 2 rather than allowing, and any other failure of the HOOK (missing git, a "
        "timeout, an unexpected exit) fails OPEN. A failure of the GUARD it runs is a DENY here, because "
        "Codex rejects the confirmation prompt the other clients get. Repo-wide enforcement "
        "at commit time and in CI still needs `chock sync`."
    )


def enforced_devin(*, ledger=None) -> str:
    """Devin's best-effort posture: the vendor's own fail-open caveat, session-scoped and unwitnessed."""
    return (
        "Best-effort in Devin by a PreToolUse hook shipped with the plugin's hooks.json "
        f"({witness_clause('devin', ledger=ledger)}). In the vendor's own words, plugin hooks "
        "are 'currently best effort and fail open -- if a hook fails to load or run, the "
        "session continues without it -- so don't rely on them for crucial guardrails yet', "
        "documented for local Devin sessions (the CLI and Devin Desktop) only. The hook "
        "command expands $DEVIN_PLUGIN_ROOT, an environment variable the vendor documents "
        "hook commands receive; whether that expansion happens inside a hooks.json command "
        "string is documented, not witnessed here. The hook needs git and a Python 3.11+ on PATH. Repo-wide "
        "git-hook and CI coverage still needs `chock sync`."
    )


def enforced_cursor(*, ledger=None) -> str:
    """Cursor's enforced posture: the interpreters it needs, and what it does without them."""
    return (
        "Session-enforced in Cursor by a beforeShellExecution hook: a matched command is "
        f"denied before it runs ({witness_clause('cursor', ledger=ledger)}). The hook needs git, "
        "a Python 3.11+ (python3, python or py; the Windows Store stub is skipped) and a usable "
        "bash resolved from PATH. The hook entry sets `failClosed`, so Cursor refuses the command "
        "when the hook cannot start (live trial, Cursor 3.17.8, recorded by agentseam). If the guard itself crashes or times out, the hook returns "
        '`permission: "ask"`, which beforeShellExecution honours. Repo-wide enforcement at '
        "commit time and in CI still needs `chock sync`."
    )
