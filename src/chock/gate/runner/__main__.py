"""`python -m chock.gate.runner`: the same command line as the vendored gate.py."""

from .cli import main

raise SystemExit(main())
