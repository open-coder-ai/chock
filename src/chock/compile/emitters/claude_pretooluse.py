"""Emit a Claude PreToolUse hook fragment for a policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.emit import write_generated_json

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


MATCHER = "Bash"
TIMEOUT_SECONDS = 30


def _relative_to_repo(policy_dir: Path) -> str:
    """The policy's path relative to the repo root, derived from the policy, not the output."""
    path = Path(policy_dir).resolve()
    for parent in path.parents:
        if (parent / ".agents").is_dir() or (parent / ".chock").is_dir():
            try:
                return path.relative_to(parent).as_posix()
            except ValueError:  # pragma: no cover - relative_to cannot fail on a parent
                break
    return path.name


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write a PreToolUse fragment in Claude Code's settings schema."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return []

    rel = _relative_to_repo(policy_dir)
    guard = f"${{CLAUDE_PROJECT_DIR}}/{rel}/implementations/{script}"

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

    cursor_adapter = "${CLAUDE_PROJECT_DIR}/.chock/bin/cursor.py"
    cursor_command = f'@CHOCK_PYTHON@ "{cursor_adapter}" --guard "{guard}"'
    cursor_dest = output_dir / "cursor-hooks.json"
    write_generated_json(
        cursor_dest,
        {"beforeShellExecution": [{"command": cursor_command, "timeout": TIMEOUT_SECONDS}]},
    )
    return [dest, cursor_dest]
