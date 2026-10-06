#!/usr/bin/env python3
"""Write gate: refuse an agent's Edit or Write to a guardrails toggle file, links followed and case ignored."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chock_guardrails_protect import REFUSED, is_toggle_path

#: At the turn's end the worktree holds the person's own uncommitted `chock bundle` change too: never refused there.
STOP = "stop"


def main() -> int:
    material = json.load(sys.stdin)
    if material.get("event") == STOP:
        return 0
    root = Path(material.get("repo_root") or ".")
    hits = sorted(path for path in material.get("writes") or {} if is_toggle_path(path, root))
    if hits:
        sys.stderr.write("\n".join([REFUSED, *(f"  - {p}: guardrails toggle file" for p in hits)]) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
