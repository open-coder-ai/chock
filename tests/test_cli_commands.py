"""The CLI command table is data: every entry resolves, and --help is frozen."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path

from chock.resources import package_data_dir

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _spec() -> dict:
    return json.loads((package_data_dir("chock", "data") / "commands.json").read_text(encoding="utf-8"))


def test_every_command_module_imports_and_exposes_its_entrypoint() -> None:
    for group, commands in _spec().items():
        for name, entry in commands.items():
            module = import_module(entry["module"])
            target = getattr(module, entry.get("fn", "main"), None)
            assert callable(target), f"{group}/{name}: {entry['module']}.{entry.get('fn', 'main')} is not callable"


def test_every_entry_carries_help_or_alias_of_and_never_both() -> None:
    for group, commands in _spec().items():
        for name, entry in commands.items():
            has_help, has_alias = "help" in entry, "alias_of" in entry
            assert has_help != has_alias, f"{group}/{name}: exactly one of help/alias_of"
            assert has_alias == (group == "aliases"), f"{group}/{name}: alias_of belongs to the aliases group"


def test_help_output_matches_the_golden() -> None:
    """Adopters script against --help; a byte drift here is an interface change."""
    out = subprocess.run([sys.executable, "-m", "chock", "--help"], capture_output=True, text=True).stdout
    golden = (FIXTURES / "cli_help.txt").read_text(encoding="utf-8")
    assert out == golden, "chock --help drifted from tests/fixtures/cli_help.txt; intentional? Update the golden."
