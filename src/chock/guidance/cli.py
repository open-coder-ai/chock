"""`chock mcp`: serve the read-only chock_guidance tool over stdio."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.guidance.server import main as serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock mcp",
        description=(
            "Serve one read-only MCP tool, chock_guidance(plan, paths), over stdio: the installed "
            "rules a plan touches, filtered to the repo's deny/ask selection. No network, no writes."
        ),
    )
    parser.add_argument("--repo", default=".", help="Repo root holding .agents/policies (default: .)")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not (repo / ".agents" / "policies").is_dir():
        print(f"mcp: no .agents/policies at {repo}; pass --repo <repo root>", file=sys.stderr)
        return 2
    return serve(repo)


if __name__ == "__main__":
    raise SystemExit(main())
