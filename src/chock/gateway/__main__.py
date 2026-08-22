"""CLI for the mcp-gateway proxy: `chock gateway run --repo . -- <downstream command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chock.gateway.proxy import Gateway


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock gateway",
        description=(
            "Run the MCP gateway proxy: wraps ONE downstream MCP server and refuses "
            "tools/call requests that match the repo's compiled gateway gates. "
            "Configure your MCP client to launch this command instead of the server; "
            "put the real server command after `--`."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="serve stdio between the MCP client and the wrapped server")
    run.add_argument("--repo", default=".", help="Repo root holding .chock/compiled (default: .)")
    run.add_argument(
        "downstream",
        nargs=argparse.REMAINDER,
        help="the real MCP server command, after `--` (e.g. -- npx some-mcp-server)",
    )
    args = parser.parse_args(argv)

    if args.command != "run":
        parser.print_help()
        return 0 if args.command is None else 2

    # Drop only the leading `--` separator, not every occurrence: a downstream command
    # can legitimately contain `--` (e.g. `-- npx server -- --inner-flag`), and stripping
    # them all would rewrite the server's own arguments.
    downstream = args.downstream[1:] if args.downstream and args.downstream[0] == "--" else list(args.downstream)
    if not downstream:
        print("gateway: no downstream command given; put the real MCP server after `--`", file=sys.stderr)
        return 2

    repo = Path(args.repo).resolve()
    compiled = repo / ".chock" / "compiled"
    if not compiled.is_dir():
        # Fail closed on the likeliest silent-disable: the client spawns the proxy from
        # its own cwd, so a wrong --repo or an unsynced repo would otherwise forward every
        # call with zero gates and no warning. Refuse to serve instead.
        print(
            f"gateway: no compiled gates at {compiled} -- run `chock sync` there, or pass "
            f"--repo <repo root>. Refusing to serve unguarded (fail closed).",
            file=sys.stderr,
        )
        return 2

    gateway = Gateway(repo, downstream)
    print(f"chock gateway: {len(gateway.gates)} gate(s) loaded from {compiled}", file=sys.stderr)
    return gateway.serve()


if __name__ == "__main__":
    raise SystemExit(main())
