#!/usr/bin/env python3
"""Shell guard: refuse an agent's command that could write a toggle file, switch a member, or accept custom code."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chock_guardrails_protect import refusal


def main() -> int:
    command = os.environ.get("CHOCK_RAW_COMMAND") or shlex.join(sys.argv[1:])
    message = refusal(command, Path.cwd())
    if message:
        sys.stdout.write(message + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
