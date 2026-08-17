"""Surface enum and per-agent capability matrix for compiled policy outputs."""

from __future__ import annotations

from enum import Enum


class Surface(str, Enum):
    AMBIENT_RULE = "ambient-rule"
    GIT_HOOK = "git-hook"
    CI_GATE = "ci-gate"
    PRE_TOOL_USE = "pre-tool-use"
    MANAGED_SETTING = "managed-setting"
    GATEWAY = "gateway"


# Surfaces each agent supports. Gateway is modeled now but emitted in P3.
SURFACE_AGENTS: dict[str, set[Surface]] = {
    "claude": {
        Surface.AMBIENT_RULE,
        Surface.GIT_HOOK,
        Surface.CI_GATE,
        Surface.PRE_TOOL_USE,
        Surface.MANAGED_SETTING,
    },
    # Cursor Agent Hooks (GA 2026): beforeShellExecution honours exit 2 as deny and sets
    # CLAUDE_PROJECT_DIR, so the vendored adapter enforces there natively. Caveat carried
    # in docs/enforcement-surfaces.md: Cursor fails OPEN on other non-zero exits.
    "cursor": {Surface.AMBIENT_RULE, Surface.GIT_HOOK, Surface.CI_GATE, Surface.PRE_TOOL_USE},
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
}


DISABLED = "disabled"


# Surfaces that something actually installs, and therefore actually enforce.
#
# `pre-tool-use` and `managed-setting` are compiled into .chock/compiled/ and then
# read by nothing: no code writes them into .claude/settings.json or a managed-settings
# location. A fragment that never reaches the agent enforces nothing, so it must not raise
# a coverage claim. Add a surface here only once an installer exists for it.
INSTALLED_SURFACES: set[Surface] = {Surface.GIT_HOOK, Surface.CI_GATE, Surface.AMBIENT_RULE}


def coverage_level(
    emitted: set[Surface], agent: str, *, pre_tool_use_installed: bool = False, ci_gate_installed: bool = False
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
    """
    supported = SURFACE_AGENTS.get(agent, set())
    if not supported:
        return "unsupported"

    active = emitted & supported
    if not active:
        return "unsupported"

    # `enforced` means a hard control that runs BEFORE the action, in-agent. Emitting a
    # PreToolUse fragment does not achieve that while nothing installs it.
    if pre_tool_use_installed and Surface.PRE_TOOL_USE in active:
        return "enforced"
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
    return "unsupported"


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
