"""Surface enum and per-agent capability matrix for compiled policy outputs.

How strong a control on one of these surfaces is -- the level vocabulary, its ordering, and
the derivation -- lives in `levels.py`; this module owns which surfaces exist where.
"""

from __future__ import annotations

from enum import Enum

from chock.compile.levels import MATRIX_AGENT, _matrix_can_block, in_agent_level


class Surface(str, Enum):
    AMBIENT_RULE = "ambient-rule"
    GIT_HOOK = "git-hook"
    CI_GATE = "ci-gate"
    PRE_TOOL_USE = "pre-tool-use"
    MANAGED_SETTING = "managed-setting"
    GATEWAY = "gateway"
    # MCP tool-call interception (chock#32). Distinct from GATEWAY, which stays reserved
    # for budget/egress backstop controls. Deliberately absent from every SURFACE_AGENTS
    # set: coverage_level can only credit surfaces an agent's set contains, so nothing is
    # credited until P3c ships per-agent config witnesses -- emitted, not yet claimed.
    MCP_GATEWAY = "mcp-gateway"
    # Native pre-tool-use hooks for the GitHub-ecosystem agents (Copilot CLI, VS Code
    # agent mode), read from `.github/hooks/*.json`. A distinct mechanism from PRE_TOOL_USE
    # (which is Claude Code's settings.json + Cursor's .cursor/hooks.json), witnessed
    # blocking on both clients 2026-08-23.
    AGENT_HOOKS = "agent-hooks"


# Surfaces each agent supports. Gateway is modeled now but emitted in P3.
SURFACE_AGENTS: dict[str, set[Surface]] = {
    "claude": {
        Surface.AMBIENT_RULE,
        Surface.GIT_HOOK,
        Surface.CI_GATE,
        Surface.MANAGED_SETTING,
    },
    # Cursor Agent Hooks (GA 2026): beforeShellExecution honours exit 2 as deny and sets
    # CLAUDE_PROJECT_DIR, so the vendored adapter enforces there natively. Caveat carried
    # in docs/enforcement-surfaces.md: Cursor fails OPEN on other non-zero exits.
    "cursor": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "copilot": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "windsurf": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "devin": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "codex": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "grok": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "kimi-code": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "aider": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "gemini": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "replit": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "tabnine": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "vscode": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
    "antigravity": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE},
}


# PRE_TOOL_USE (claude, cursor) and AGENT_HOOKS (copilot, vscode) membership is verified
# against agentseam's capability matrix rather than hand-duplicated a second time -- see
# _matrix_can_block. A mismatch here is loud on purpose: silently losing (or silently
# gaining) one of these claims is exactly the overclaim/underclaim class this module
# exists to prevent, so it is a hard failure rather than a quiet fallback.
for _agent, _surface in (
    ("claude", Surface.PRE_TOOL_USE),
    ("cursor", Surface.PRE_TOOL_USE),
    ("copilot", Surface.AGENT_HOOKS),
    ("vscode", Surface.AGENT_HOOKS),
):
    if not _matrix_can_block(_agent):
        raise AssertionError(
            f"agentseam's matrix no longer confirms {_agent!r} can block a pre-tool call; "
            f"{_surface.value} membership here must be re-reviewed, not silently kept or dropped"
        )
    SURFACE_AGENTS[_agent].add(_surface)
del _agent, _surface


# Surfaces that something actually installs, and therefore actually enforce.
#
# `pre-tool-use` and `managed-setting` are compiled into .chock/compiled/ and then
# read by nothing: no code writes them into .claude/settings.json or a managed-settings
# location. A fragment that never reaches the agent enforces nothing, so it must not raise
# a coverage claim. Add a surface here only once an installer exists for it.
INSTALLED_SURFACES: set[Surface] = {Surface.GIT_HOOK, Surface.CI_GATE, Surface.AMBIENT_RULE}


def coverage_level(
    emitted: set[Surface],
    agent: str,
    *,
    pre_tool_use_installed: bool = False,
    ci_gate_installed: bool = False,
    agent_hooks_installed: bool = False,
) -> str:
    """Return the enforcement level a policy actually achieves on an agent.

    This reports what is enforced, not what the agent is capable of. The previous version
    asked only whether the policy's target surfaces were a subset of the agent's supported
    ones, which had two consequences:

      Surfaces that emitted zero files still counted, because the compiler records a key
      per surface whether or not the emitter produced anything.

      A policy with no gate of any kind therefore reported `enforced` -- code-safety, an
      advise-only rule, claimed a "hard, pre-execution control" on claude.

    14 of 15 policies claimed `enforced` before this change. For a governance tool,
    overstating its own enforcement is the failure that discredits every other claim.

    `active & {GIT_HOOK, CI_GATE}` used to be spelled out here with no reference to
    `INSTALLED_SURFACES` at all, so that constant was documentation rather than a control:
    removing a surface from it changed no verdict. Every branch below now intersects with it,
    which makes membership *necessary* -- a surface absent from the constant can raise no
    claim at all.

    It is not *sufficient*, and the difference is worth stating rather than glossing. Which
    level a surface maps to, and whether it needs an install witness, are still literals here,
    because the two commit-time surfaces do not behave alike: `recompile` wires up a git hook
    by itself, while a CI workflow exists only because someone ran `install-ci`. Folding that
    into the set would mean dropping the witness -- the exact overclaim this function exists
    to prevent.

    Vocabulary (owner decision #9): PRE_TOOL_USE and AGENT_HOOKS, once installed, no longer
    read flatly `enforced` -- they read whatever `in_agent_level` derives from the mapped
    agent's PRE_TOOL row and the way chock's own guard degrades. claude_code's PreToolUse is
    FAIL_OPEN (a crashed hook silently allows), so it reads `best-effort`, never `enforced` --
    the honest downgrade this decision exists to make; cursor's is FAIL_CONFIGURABLE, so it
    reads `enforceable`. `fail-to-ask` joins that ladder for a control that blocks and, when
    it cannot decide, puts the action to a human instead of letting it through; chock does not
    earn it today, and `CONTROL_DEGRADES_TO` says so rather than the ladder flattering us.
    `enforced-at-commit` and `advisory` stay chock's own words: agentseam's tiers describe an
    AGENT lifecycle hook, and chock's git-hook/CI-gate and ambient-rule surfaces are not that
    -- there is no lossless translation, so this function does not force one. `unsupported`
    becomes `none`, agentseam's own word for "no surface at all", a direct match either way.
    """
    supported = SURFACE_AGENTS.get(agent, set())
    if not supported:
        return "none"

    active = emitted & supported
    if not active:
        return "none"

    # A hard control that runs BEFORE the action, in-agent. Emitting a PreToolUse fragment
    # does not achieve that while nothing installs it; once installed, the honest word for
    # what it achieves comes from `in_agent_level` -- the mapped agent's own PRE_TOOL row
    # combined with how chock's own guard degrades, not a flat `enforced`.
    if pre_tool_use_installed and Surface.PRE_TOOL_USE in active:
        if MATRIX_AGENT.get(agent):
            return in_agent_level(agent)
    # Copilot CLI / VS Code native hooks: same hard pre-execution tier, gated on the same
    # kind of witness -- `.github/hooks/chock.json` must actually carry this policy's entry.
    # Emitting the entry is not enough; without the installed file the client runs nothing.
    # Same derivation: these run the identical vendored guard, so the degradation is identical.
    if agent_hooks_installed and Surface.AGENT_HOOKS in active:
        if MATRIX_AGENT.get(agent):
            return in_agent_level(agent)
    # Unlike git-hook (wired up automatically by every `recompile`), nothing runs `install-ci`
    # on a policy's behalf -- crediting CI_GATE the moment it is merely compiled would repeat
    # the exact overclaim `pre_tool_use_installed` exists to prevent for PreToolUse.
    commit_time = active & INSTALLED_SURFACES & {Surface.GIT_HOOK}
    if ci_gate_installed:
        commit_time |= active & INSTALLED_SURFACES & {Surface.CI_GATE}
    if commit_time:
        return "enforced-at-commit"
    if Surface.AMBIENT_RULE in active & INSTALLED_SURFACES:
        return "advisory"
    # Only uninstalled surfaces remain: the agent supports them, but nothing wires them up,
    # so the policy has no effect here.
    return "none"


def parse_agent_selection(groups: list[str], valid: dict[str, object] | None = None) -> list[str]:
    """Split comma- or space-separated --agents values; reject names not in `valid`.

    One funnel for every agent selection, wherever it enters: `init --agents
    claude,cursor <path>` once swallowed the path into the agent list (nargs="*"),
    silently filtered every unknown entry, and handed the deselect pass an empty
    selection. A selection mistake must stop the run, not redirect it. Duplicates are
    dropped (order preserved) so `--agents claude claude,cursor` selects two agents,
    not three.
    """
    valid = SURFACE_AGENTS if valid is None else valid
    agents: list[str] = []
    for group in groups:
        for name in group.split(","):
            name = name.strip()
            if name and name not in agents:
                agents.append(name)
    unknown = [a for a in agents if a not in valid]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)} -- valid: {', '.join(sorted(valid))}")
    return agents
