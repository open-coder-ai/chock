"""Emit a Claude PreToolUse hook fragment for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.emit import write_generated_json

# Historic filename exceptions only. The rule is `implementations/<policy-id>.sh`; these
# two predate it. A hardcoded-only map silently unwired every newer guard policy: the
# catalog's protect-commit-privacy and protect-agent-config shipped labelled
# "enforced (pre-tool-use, once hooks are installed)" while this emitter, not knowing
# their names, emitted nothing -- coverage stayed honestly `advisory`, but the label and
# the README table overclaimed. Discovery by convention closes the class.
GUARD_SCRIPTS = {
    "block-destructive-commands": "block-destructive.sh",
    "block-no-verify": "block-no-verify.sh",
}


def _guard_script(policy_dir: Path, policy_id: str) -> str | None:
    """The policy's guard script name, by convention first, legacy map second."""
    impl = policy_dir / "implementations"
    if (impl / f"{policy_id}.sh").exists():
        return f"{policy_id}.sh"
    legacy = GUARD_SCRIPTS.get(policy_id)
    if legacy and (impl / legacy).exists():
        return legacy
    return None


# Only Bash carries a shell command. Edit tools deliver file content, which these guards
# cannot tokenize, so matching them would run the guard on input it cannot evaluate --
# the previous version matched both and would have checked neither correctly.
MATCHER = "Bash"
TIMEOUT_SECONDS = 30


def _relative_to_repo(policy_dir: Path) -> str:
    """The policy's path relative to the repo root, derived from the policy, not the output.

    This used to walk up from the *output* directory. `recompile --check` compiles into a
    temporary root, where that walk finds no `.chock` and falls back to
    `git rev-parse` in the caller's cwd -- so the check emitted a different path than the
    real compile and reported a spurious `differs`, unless you happened to be standing in
    the repo being checked. A freshness check whose verdict depends on the caller's working
    directory is not a check.

    `policy_dir` is the real on-disk path in both cases, so deriving from it gives the same
    answer either way.
    """
    path = Path(policy_dir).resolve()
    for parent in path.parents:
        if (parent / ".agents").is_dir() or (parent / ".chock").is_dir():
            try:
                return path.relative_to(parent).as_posix()
            except ValueError:  # pragma: no cover - relative_to cannot fail on a parent
                break
    return path.name


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a PreToolUse fragment in Claude Code's settings schema.

    The previous version emitted an invented shape -- `{name, match: {tool: [...]},
    fail_on_exit_code}` -- that Claude Code would never read. Nothing installed it
    anywhere, so no failure ever surfaced the mismatch while `coverage.json` reported
    these policies as `enforced`.

    Paths use ${CLAUDE_PROJECT_DIR} so the fragment survives the repo being moved or
    cloned elsewhere; an absolute path baked in at compile time would not.
    """
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return []

    # The guard path must be derived, not assumed. `init` installs baseline packs under
    # .agents/policies/_baseline/<id>/, while this repo dogfoods them at
    # .agents/policies/<id>/ -- a hardcoded path produced a hook that ran and reported
    # "guard not found", allowing everything while appearing installed.
    rel = _relative_to_repo(policy_dir)
    guard = f"${{CLAUDE_PROJECT_DIR}}/{rel}/implementations/{script}"

    # `@CHOCK_PYTHON@` is a placeholder, not a literal interpreter: install bakes the real
    # one into settings.json (see hooks/pretooluse_install.INTERPRETER_PLACEHOLDER). A literal
    # `python` was absent on python3-only systems, where the hook exited 127 and Claude Code
    # let the tool call through while coverage still reported `enforced`. The compiled fragment
    # keeps the placeholder so committed compiled output is portable and deterministic.
    #
    # Claude and Cursor each get their own vendored runtime now (agentseam bundles one
    # self-contained file per agent -- see gate/runtime_bundle.py) rather than the one
    # shared, payload-sniffing adapter this used to point both at.
    claude_adapter = "${CLAUDE_PROJECT_DIR}/.chock/bin/claude_code.py"
    claude_command = f'@CHOCK_PYTHON@ "{claude_adapter}" --guard "{guard}"'
    fragment = {
        "matcher": MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": claude_command,
                "timeout": TIMEOUT_SECONDS,
            }
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "pretooluse.json"
    write_generated_json(dest, fragment)

    # Cursor's beforeShellExecution speaks the same protocol -- JSON payload in, a native
    # deny -- through a different config shape (a flat entry in .cursor/hooks.json) and a
    # top-level `command` field. Same guard, same placeholder discipline; only the envelope
    # (and now the vendored runtime file, since each agent's bundle is agent-specific)
    # differs. Cursor sets CLAUDE_PROJECT_DIR itself (documented alias), so the identical
    # path form works.
    cursor_adapter = "${CLAUDE_PROJECT_DIR}/.chock/bin/cursor.py"
    cursor_command = f'@CHOCK_PYTHON@ "{cursor_adapter}" --guard "{guard}"'
    cursor_dest = output_dir / "cursor-hooks.json"
    write_generated_json(
        cursor_dest,
        {"beforeShellExecution": [{"command": cursor_command, "timeout": TIMEOUT_SECONDS}]},
    )
    return [dest, cursor_dest]
