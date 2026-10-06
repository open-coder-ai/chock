#!/usr/bin/env python3
"""Write gate: refuse an agent's Edit or Write to a toggle file or an install marker, links followed, case ignored."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chock_guardrails_protect import INSTALL_REFUSED, REFUSED, is_marker_path, is_toggle_path

#: At the turn's end the worktree holds the person's own uncommitted `chock bundle` change too: never refused there.
STOP = "stop"


def main() -> int:
    material = json.load(sys.stdin)
    if material.get("event") == STOP:
        return 0
    root = Path(material.get("repo_root") or ".")
    writes = sorted(material.get("writes") or {})
    toggles = [p for p in writes if is_toggle_path(p, root)]
    markers = [p for p in writes if is_marker_path(p, root) and p not in toggles]
    lines = [REFUSED, *(f"  - {p}: guardrails toggle file" for p in toggles)] if toggles else []
    if markers:
        lines += [INSTALL_REFUSED, *(f"  - {p}: install marker" for p in markers)]
    if lines:
        sys.stderr.write("\n".join(lines) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
