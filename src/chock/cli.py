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


def _build_group(group: dict[str, dict[str, str]]) -> dict[str, tuple]:
    """One command name -> (lazy handler, help text), from a data/commands.json group."""
    built = {}
    for name, spec in group.items():
        handler = _module_fn(spec["module"], spec["fn"]) if "fn" in spec else _module_main(spec["module"])
        built[name] = (handler, spec["help"])
    return built


_COMMANDS_JSON = json.loads(package_data_dir("chock", "data").joinpath("commands.json").read_text(encoding="utf-8"))

EVERYDAY = _build_group(_COMMANDS_JSON["everyday"])
AUTHORING = _build_group(_COMMANDS_JSON["authoring"])
ALIASES = _build_group(_COMMANDS_JSON["aliases"])

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
