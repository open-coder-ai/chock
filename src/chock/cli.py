"""Chock CLI: one entry point, one subcommand per activity.

Usage: chock <command> [args]
"""

from __future__ import annotations

import json
import sys
from importlib import import_module

from chock import __version__
from chock.pipe import guard_stdout, silence_interpreter_flush
from chock.resources import package_data_dir


def _module_main(module_name: str):
    def _main(argv: list[str] | None) -> int:
        return int(import_module(module_name).main(argv) or 0)

    return _main


def _module_fn(module_name: str, fn_name: str):
    """Lazy handler for a named function: keeps the dispatcher import-light and the"""

    def _main(argv: list[str] | None) -> int:
        return int(getattr(import_module(module_name), fn_name)(argv) or 0)

    return _main


def _load_command_groups() -> dict[str, dict[str, tuple]]:
    """The command table from data/commands.json: group -> name -> (lazy handler, help)."""
    spec = json.loads((package_data_dir("chock", "data") / "commands.json").read_text(encoding="utf-8"))
    groups: dict[str, dict[str, tuple]] = {}
    for group, commands in spec.items():
        groups[group] = {}
        for name, entry in commands.items():
            fn = _module_fn(entry["module"], entry["fn"]) if "fn" in entry else _module_main(entry["module"])
            groups[group][name] = (fn, entry.get("help") or f"alias of: {entry['alias_of']}")
    return groups


_GROUPS = _load_command_groups()
EVERYDAY = _GROUPS["everyday"]
AUTHORING = _GROUPS["authoring"]
ALIASES = _GROUPS["aliases"]

COMMANDS = {**EVERYDAY, **AUTHORING, **ALIASES}


def main(argv: list[str] | None = None) -> int:
    writer = guard_stdout()
    try:
        return _dispatch(list(sys.argv[1:] if argv is None else argv))
    finally:
        silence_interpreter_flush(writer)


def _dispatch(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        print("\nEveryday:")
        for name, (_, help_text) in EVERYDAY.items():
            print(f"  {name:10} {help_text}")
        print("\nAuthoring:")
        for name, (_, help_text) in AUTHORING.items():
            print(f"  {name:10} {help_text}")
        return 0
    if argv[0] in ("--version", "-V"):
        print(__version__)
        return 0
    command, rest = argv[0], argv[1:]
    if command not in COMMANDS:
        print(f"Unknown command: {command!r}. Run 'chock --help'.", file=sys.stderr)
        return 2
    fn, _ = COMMANDS[command]
    return int(fn(rest) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
