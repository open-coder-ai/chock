"""`chock sync`: record a committed `.chock/guardrails.json` only when it is byte-identical to the remote default branch.

That content went through review: the baseline check reports any switch-off in its pull request. A local commit
an agent made is not on the remote, so it is never recorded here: a person adopts it with `chock bundle status --adopt`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from chock.guardrails import toggle
from chock.guardrails.cli import record

#: The remote default branch, as a fresh clone names it.
REMOTE_REFS = ("refs/remotes/origin/HEAD", "refs/remotes/origin/main")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- fixed argv: git reading this clone's own refs
        ["git", "-C", str(root), *args],  # noqa: S607 -- git on PATH is the repo route's premise
        capture_output=True,
        check=False,
        timeout=30,
    )


def remote_copy(root: Path) -> tuple[str | None, bytes | None]:
    """(the remote ref read, the toggle file's bytes there); (None, None) with no remote, (ref, None) when it has none."""
    for ref in REMOTE_REFS:
        if _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0:
            shown = _git(root, "show", f"{ref}:{toggle.FILENAME}")
            return ref, shown.stdout if shown.returncode == 0 else None
    return None, None


def _summary(path: Path) -> str:
    try:
        toggles = toggle.read(path)
    except toggle.ToggleError as exc:
        return f"invalid, so every guardrail stays on ({exc})"
    off = [f"{b}/{i}" for b, members in sorted(toggles.items()) for i, s in sorted(members.items()) if s == toggle.OFF]
    return "off: " + ", ".join(off) if off else "no member is switched off"


def record_reviewed(root: Path) -> None:
    """Record the repo toggle file when it matches the remote default branch, and print its on/off summary."""
    path = Path(root) / toggle.FILENAME
    if not path.exists() and not path.is_symlink():
        return
    if toggle.drift(path) is None:
        print(f"guardrails: {toggle.FILENAME} matches its record; {_summary(path)}")
        return
    ref, reviewed = remote_copy(Path(root))
    if not path.is_symlink() and path.is_file() and reviewed is not None and path.read_bytes() == reviewed:
        record(path)
        print(f"guardrails: {toggle.FILENAME} is identical to {ref}, recorded; {_summary(path)}")
        return
    where = ref or "no remote default branch"
    print(
        f"guardrails: {toggle.FILENAME} is not identical to {where}, so it is not recorded and every guardrail stays "
        "on. A person reviews it and runs `chock bundle status --adopt` to honour it."
    )
