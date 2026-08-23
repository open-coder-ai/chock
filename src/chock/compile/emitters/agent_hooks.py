"""Emit the agent-hooks surface: a `.github/hooks` preToolUse entry per guard policy.

Copilot CLI and VS Code agent mode both read `.github/hooks/*.json` and both honour exit
code 2 as deny (witnessed 2026-08-23). They disagree only on the command-field NAMES --
Copilot reads `bash`/`powershell`, VS Code reads `command` plus OS overrides
`windows`/`linux`/`osx` -- so a single entry carries all four; each client uses the fields
it knows and ignores the rest.

Portable and sound, deliberately:
- Repo root is found at RUN time with `git rev-parse --show-toplevel` (like the git-hook
  shim), so the committed file needs no machine-specific path baked in.
- The interpreter is RESOLVED first, then the guard runs exactly once. The rejected
  `python3 ... || python ...` chain was unsound (it re-ran the guard in the fallback leg,
  and the first leg had already consumed stdin). On Windows the resolver skips the
  Microsoft Store `python3` alias stub, the exact thing that made the plugin hook error
  and fail-closed clients brick every command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chock.compile.emitters.claude_pretooluse import TIMEOUT_SECONDS, _guard_script, _relative_to_repo
from chock.emit import write_generated_json

# Anchored full-match (`^(?:PATTERN)$`) against the tool name. The witnessed shell tool
# names are `bash` (Copilot/unix) and `powershell` (Windows); include common variants.
# Non-shell tools (`view`, `glob`, read/edit) are deliberately NOT matched -- these guards
# inspect shell commands, and matching a read tool would run the guard on input it cannot
# evaluate.
SHELL_MATCHER = "bash|powershell|pwsh|sh|shell"


def _bash_command(adapter: str, guard: str) -> str:
    return (
        'repo="$(git rev-parse --show-toplevel)"; '
        'PY="$(command -v python3 || command -v python)"; '
        '[ -n "$PY" ] || { echo "chock: no python interpreter found" >&2; exit 1; }; '
        f'exec "$PY" "$repo/{adapter}" --guard "$repo/{guard}"'
    )


def _powershell_command(adapter: str, guard: str) -> str:
    return (
        "$repo = (git rev-parse --show-toplevel); "
        "$py = (Get-Command python3, python, py -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Source -and $_.Source -notlike '*WindowsApps*' } | "
        "Select-Object -First 1).Source; "
        "if (-not $py) { [Console]::Error.WriteLine('chock: no python interpreter found'); exit 1 }; "
        f'$input | & $py "$repo/{adapter}" --guard "$repo/{guard}"; exit $LASTEXITCODE'
    )


def build_entry(policy_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """The single preToolUse entry for one policy, or None when it has no guard script."""
    policy_id = manifest.get("id", policy_dir.name)
    script = _guard_script(policy_dir, policy_id)
    if not script:
        return None
    rel = _relative_to_repo(policy_dir)
    adapter = ".chock/bin/pretooluse.py"
    guard = f"{rel}/implementations/{script}"
    bash = _bash_command(adapter, guard)
    powershell = _powershell_command(adapter, guard)
    return {
        "type": "command",
        "matcher": SHELL_MATCHER,
        "timeout": TIMEOUT_SECONDS,
        "timeoutSec": TIMEOUT_SECONDS,
        # Copilot CLI reads bash/powershell; VS Code reads command + windows override.
        "bash": bash,
        "command": bash,
        "powershell": powershell,
        "windows": powershell,
    }


def emit(policy_dir: Path, output_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Write the per-policy entry; the installer aggregates them into .github/hooks/chock.json."""
    entry = build_entry(policy_dir, manifest)
    if entry is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / "agent-hooks.json"
    write_generated_json(dest, entry)
    return [dest]
