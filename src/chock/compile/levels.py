"""The enforcement-level vocabulary, its strength order, and how a level is derived.

Split out of `surfaces.py` because it answers a different question. That module says which
SURFACES exist for which agent; this one says how strong a control on one of them actually is
-- and the two drifted apart the moment the grade stopped being a single word per surface.

Everything here is derived from a mechanism. Nothing in this module knows who ships a control,
which is the property that lets it grade a control chock does not ship at all.
"""

from __future__ import annotations

from agentseam import contract as _contract
from agentseam import matrix as _matrix

#: chock agent id -> the agentseam agent whose capability matrix governs whether that
#: agent even HAS the surface (PRE_TOOL_USE / AGENT_HOOKS), replacing what used to be a
#: second, hand-maintained copy of the same fact. Deliberately narrow: this settles
#: membership (does the surface exist for this agent at all), not enforcement TIER --
#: `coverage_level`'s four-value vocabulary is a contract `chock-catalog` (out of scope
#: for this migration, not touched) renders, so it is not touched here. Per agentseam's
#: own finding (recorded in its "for the next worker" notes): "copilot" has no live
#: dispatch adapter of its own -- a Copilot CLI/VS Code payload always arrives as
#: "vscode_copilot", the one wire dialect both chock ids share.
MATRIX_AGENT = {
    "claude": "claude_code",
    "cursor": "cursor",
    "copilot": "vscode_copilot",
    "vscode": "vscode_copilot",
}


def _matrix_can_block(chock_agent: str) -> bool:
    """Whether agentseam's verified matrix confirms `chock_agent` can block a pre-tool call.

    Used only to REPLACE a hardcoded True chock already asserted for claude/cursor
    (PRE_TOOL_USE) and copilot/vscode (AGENT_HOOKS) with a live check against agentseam's
    matrix, so the two projects cannot silently drift apart on whether the surface exists
    at all. It is not consulted for any agent chock does not already claim this for, so it
    can only confirm or -- were agentseam's verified data ever to disagree -- refuse an
    existing claim, never manufacture a new one.
    """
    mapped = MATRIX_AGENT.get(chock_agent)
    return bool(mapped) and _matrix.can_block(mapped, _contract.PRE_TOOL)


DISABLED = "disabled"


# --------------------------------------------------------------------- degradation modes
#
# What OUR control emits when it RUNS but cannot reach a verdict -- the guard crashed, its
# interpreter is missing, it timed out, the command would not tokenize.
#
# This is a different axis from agentseam's `fail_mode`, and conflating the two is what
# made the vocabulary below unable to describe a competitor. agentseam's `fail_mode` is the
# OUTER boundary: what the HOST does when our hook never runs or dies outright. This is the
# INNER one: what the hook itself says when it ran and does not know. A control can be
# fail-open at the outer boundary (the host's choice, not ours) while still refusing to
# silently allow at the inner one, and the two together are the mechanism a grade is derived
# from.
DEGRADES_TO_ALLOW = "allow"
DEGRADES_TO_ASK = "ask"
#: Accepted, and graded identically to `DEGRADES_TO_ASK`. Not because a deny is an ask --
#: it is strictly stronger -- but because the only property this ladder can honestly rank on
#: is whether the action proceeds UNATTENDED, and both answer no. A control mixing the two
#: (deny on one failure, ask on another) must be declared at its weakest path: a control is
#: only as strong as its worst degradation, and grading it by its best is the overclaim this
#: module exists to prevent.
DEGRADES_TO_DENY = "deny"
DEGRADATION_MODES = (DEGRADES_TO_ALLOW, DEGRADES_TO_ASK, DEGRADES_TO_DENY)


#: How chock's own installed in-agent control degrades. `gate.guard_runner.evaluate` answers
#: its "could not decide" paths in two different ways, and this constant is the WEAKER of
#: them, per the rule stated on DEGRADES_TO_DENY above:
#:
#:   ask    the guard ran and did not deliver a verdict -- it crashed, exited a code that is
#:          neither 0 nor 1, or hit its timeout. `Decision.ask` reaches the client as a
#:          confirmation prompt on three of the four vendored runtimes and as a deny on Codex
#:          CLI, whose parser rejects `ask`; no client turns it into an allow.
#:   allow  a PRECONDITION failed, so the guard never started -- no usable bash, a command
#:          POSIX shlex will not tokenize, nothing to tokenize. These are common or uniform
#:          rather than anomalous, and prompting on them would spend the oversight budget the
#:          ask above depends on. `docs/enforcement-surfaces.md` carries the per-path
#:          reasoning and the per-client evidence.
#:
#: So the control is **not** fail-to-ask: it is a mixed control, and a mixed one is declared
#: at its weakest path. chock still fails open at both boundaries on those three paths, and
#: the grade must keep saying so. The value moves only when the WEAKEST path stops allowing.
#:
#: It is a constant here rather than a per-agent entry because it is a property of one
#: mechanism, not of an agent: all four in-agent surfaces run the same `guard_runner` through
#: the same vendored adapter, so there is one fact to state and no table to get wrong.
#: `test_coverage_grades.py` derives this value by running the mechanism down every one of
#: those paths and taking the weakest, rather than trusting the constant -- and separately
#: asserts that at least one path still asks, so the constant cannot go on reading `allow`
#: because the ask was quietly dropped.
CONTROL_DEGRADES_TO = DEGRADES_TO_ALLOW


# ------------------------------------------------------------------------ the level ladder
#
# The in-agent levels, weakest first. Everything before `fail-to-ask` is agentseam's own
# vocabulary (`matrix.enforcement_level`), reproduced here only so the order can be stated;
# `fail-to-ask` is chock's addition and is justified where it is derived, in `in_agent_level`.
#
# The ordering axis is: HOW LITTLE THE GUARANTEE DEPENDS ON SOMEONE BEING THERE.
#
#   none         no surface at all
#   detect       the action proceeds; we find out afterwards
#   best-effort  the action proceeds silently when the control cannot decide
#   fail-to-ask  the action does not proceed unattended -- but a person must answer, and can
#                say yes; in a headless run there is nobody to ask
#   enforceable  can be configured to block with nobody present, though not by default
#   enforced     blocks with nobody present, by default
#
# `fail-to-ask` sits below `enforceable` deliberately, and it is the one placement worth
# arguing with: by DEFAULT posture a fail-to-ask control is stronger than an unconfigured
# `enforceable` one. It is ranked lower because the ladder ranks the strongest guarantee a
# surface can be made to give, and `enforceable`'s ceiling holds in an unattended CI run
# while `fail-to-ask`'s never does.
IN_AGENT_LEVELS = ("none", "detect", "best-effort", "fail-to-ask", "enforceable", "enforced")

#: chock's own words for surfaces outside agentseam's per-agent-hook model, plus the toggle
#: state. Deliberately NOT ranked against the ladder: `coverage_level`'s docstring refuses to
#: force a translation between an agent lifecycle hook and a commit-time gate, and silently
#: ordering them here would make that refusal a lie by another route.
UNRANKED_LEVELS = ("enforced-at-commit", "advisory", DISABLED)

#: On the ladder for ranking, but NOT a verdict chock's own compiler can ever report.
#: `SURFACE_AGENTS` carries an in-agent surface only for an agent agentseam confirms can
#: BLOCK there -- the assertion loop above makes a non-blocking row a hard import failure
#: rather than a quiet downgrade -- so no chock cell can land on the observe-only tier. It
#: stays on the ladder because ranking a control chock does NOT ship (a competitor's, a
#: vendor's) is the ladder's other job, and that is the job it was extended for.
UNREPORTABLE_LEVELS = ("detect",)

#: Every level chock can report. The published level table is checked against this.
COVERAGE_LEVELS = (
    *(level for level in IN_AGENT_LEVELS if level not in UNREPORTABLE_LEVELS),
    *UNRANKED_LEVELS,
)


def level_rank(level: str) -> int:
    """Position of `level` in the in-agent strength ladder; higher is stronger.

    The comparison a caller actually needs -- "is this control stronger than that one" --
    which the flat five-word vocabulary could not answer at all. Raises for chock's own
    commit-time and ambient words rather than placing them somewhere plausible: there is no
    honest rank for a git hook against an in-agent hook, and a number would invent one.
    """
    try:
        return IN_AGENT_LEVELS.index(level)
    except ValueError:
        raise ValueError(
            f"{level!r} has no rank on the in-agent ladder {IN_AGENT_LEVELS}; "
            f"{UNRANKED_LEVELS} describe different mechanisms and are deliberately unranked"
        ) from None


def in_agent_level(agent: str, *, degrades_to: str = CONTROL_DEGRADES_TO) -> str:
    """The honest word for an INSTALLED in-agent pre-execution control on `agent`.

    Derived from the mechanism, never asserted per agent. Two inputs, both facts about how
    the control behaves rather than about who ships it:

      the HOST's block behaviour and fail mode, from agentseam's verified matrix -- what the
      agent does with our verdict, and what it does when our hook never runs;

      the CONTROL's own degradation (`degrades_to`) -- what our hook says when it ran and
      could not decide.

    agentseam's five words read only the first, which is why two materially different
    controls collapsed onto `best-effort`: one that degrades to silently allowing, and one
    that degrades to putting the action to a human. The second is strictly stronger and the
    vocabulary had no way to say so -- a defect in the grading layer, since a grading layer
    that cannot rank a competitor above us is not measuring anything.

    `fail-to-ask` is the word for it, over `fail-safe` and `fail-closed`: both round up. The
    action is not closed and nothing is safe -- a person is asked, and a person can say yes.
    Naming the observable behaviour is the only spelling that cannot be quoted as a stronger
    claim than the mechanism makes, which is the same test `FAIL_CONFIGURABLE` was named by.

    Note what is NOT overridden: the host's fail mode dominates. A `fail-to-ask` control on a
    host that fails closed is still `enforced`, and on a host that can be told to fail closed
    it is still `enforceable`, because in both cases the host backstops the case where our
    hook never runs at all -- which asking cannot, since a process that did not start asks
    nobody. The upgrade applies exactly where the host fails open, which is where the two
    controls were indistinguishable before.
    """
    if degrades_to not in DEGRADATION_MODES:
        raise ValueError(f"unknown degradation mode {degrades_to!r}; expected one of {DEGRADATION_MODES}")
    mapped = MATRIX_AGENT.get(agent)
    if not mapped:
        return "none"
    host = _matrix.enforcement_level(mapped, _contract.PRE_TOOL)
    if host != "best-effort" or degrades_to == DEGRADES_TO_ALLOW:
        return host
    return "fail-to-ask"
