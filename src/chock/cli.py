"""Chock CLI: one entry point, one subcommand per activity.

Usage: chock <command> [args]
"""

from __future__ import annotations

import sys
from importlib import import_module

from chock import __version__
from chock.pipe import guard_stdout, silence_interpreter_flush


def _module_main(module_name: str):
    def _main(argv: list[str] | None) -> int:
        return int(import_module(module_name).main(argv) or 0)

    return _main


def _module_fn(module_name: str, fn_name: str):
    """Lazy handler for a named function: keeps the dispatcher import-light and the
    import graph one-directional (cli never imports command modules at load time)."""

    def _main(argv: list[str] | None) -> int:
        return int(getattr(import_module(module_name), fn_name)(argv) or 0)

    return _main


# The adopter surface follows the Python toolchain's verbs (uv init/add/sync,
# poetry check, git status) so nothing here needs learning twice.
EVERYDAY = {
    "init": (_module_main("chock.scaffold.init"), "Scaffold a consumer repo (wiring only -- no policies)"),
    "add": (_module_main("chock.scaffold.add"), "Install a policy or skill from a catalog and compile it"),
    "remove": (_module_main("chock.scaffold.remove"), "Remove an installed policy and resync"),
    "sync": (
        _module_fn("chock.lifecycle", "sync_main"),
        "Recompile + rewire so the repo matches its policies (--ci/--skills for extras)",
    ),
    "check": (
        _module_fn("chock.lifecycle", "check_main"),
        "Run every truth check: validate, verify, evals, matrix (--only to narrow)",
    ),
    "status": (
        _module_fn("chock.lifecycle", "status_main"),
        "Policy states and coverage (--only registry,log for more)",
    ),
    "enable": (_module_fn("chock.toggles", "enable_main"), "Enable a policy by id"),
    "disable": (_module_fn("chock.toggles", "disable_main"), "Disable a policy by id"),
}

AUTHORING = {
    "new": (_module_main("chock.scaffold.new"), "Create a deterministic artifact skeleton"),
    "compile": (_module_main("chock.compile.compiler"), "Low-level single-policy compile"),
    "install-skills": (
        _module_main("chock.scaffold.skills"),
        "Install bundled authoring skills into agent skill dirs (write mode; check via CI)",
    ),
    "registry": (_module_main("chock.registry.cli"), "Scan/list/resolve the artifact registry"),
    "plugin": (
        _module_main("chock.plugin.cli"),
        "Package policies as installable plugins (plugin build [--format claude] [--check])",
    ),
    "marketplace": (
        _module_main("chock.plugin.marketplace"),
        "Emit marketplace index files over a built plugin tree (marketplace build --dist <dir>)",
    ),
    "review": (
        _module_main("chock.review.cli"),
        "Produce or check reviewer evidence (review emit | review verify <file>)",
    ),
    "compliance": (
        _module_main("chock.authoring.compliance"),
        "Generate a compliance coverage report (compliance report --framework owasp_asi)",
    ),
}

# Pre-launch aliases: the pre-consolidation names, behaving exactly as before.
# Hidden from --help; deleted at launch so the public CLI is born with 12 commands.
ALIASES = {
    "validate": (_module_main("chock.validation.engine"), "alias of: check --only validate"),
    "verify": (_module_main("chock.lock"), "alias of: check --only verify"),
    "eval": (_module_main("chock.eval.cli"), "alias of: check --only evals"),
    "check-matrix": (_module_main("chock.authoring.matrix"), "alias of: check --only matrix"),
    "recompile": (_module_fn("chock.toggles", "recompile_main"), "alias of: sync"),
    "refresh": (_module_main("chock.index.cli"), "alias of: sync / check --only index"),
    "install-hooks": (_module_main("chock.hooks.install"), "alias of: sync (hooks part)"),
    "install-ci": (_module_main("chock.scaffold.install_ci"), "alias of: sync --ci"),
    "policies": (_module_fn("chock.toggles", "policies_main"), "alias of: status"),
    "gate-log": (_module_main("chock.gatelog"), "alias of: status --only log"),
}

#: Every invocable command. External tooling (the catalog's check_console) reads this
#: as the definition of "a real chock command", so aliases belong in it.
COMMANDS = {**EVERYDAY, **AUTHORING, **ALIASES}


def main(argv: list[str] | None = None) -> int:
    # Before any command runs. `sync | head -2` used to die between installing hooks and
    # refreshing the registry they depend on, leaving the repo failing validation on every
    # commit -- a closed pager must stop the output, never the work. See chock.pipe.
    writer = guard_stdout()
    try:
        return _dispatch(list(sys.argv[1:] if argv is None else argv))
    finally:
        silence_interpreter_flush(writer)


def _dispatch(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        # Generated from the tables, never hand-maintained: a previous hard-coded summary
        # silently omitted `refresh` from the moment that command was added. Aliases are
        # dispatchable but not advertised.
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
