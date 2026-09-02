"""The CLI command table is data (chock W48): every entry must resolve, and moving it
off a Python literal must not change what `chock --help` prints."""

from __future__ import annotations

import subprocess
import sys
from importlib import import_module
from pathlib import Path

from chock.cli import _COMMANDS_JSON

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_every_command_module_path_imports_and_exposes_its_entry_point() -> None:
    for group in _COMMANDS_JSON.values():
        for name, spec in group.items():
            module = import_module(spec["module"])
            fn_name = spec.get("fn", "main")
            assert hasattr(module, fn_name), f"{name}: {spec['module']} has no {fn_name!r}"


def test_help_output_is_byte_identical_to_the_golden() -> None:
    golden = (FIXTURES / "cli_help_golden.txt").read_text(encoding="utf-8")
    out = subprocess.run([sys.executable, "-m", "chock", "--help"], capture_output=True, text=True, check=True)
    assert out.stdout == golden, "chock --help changed; update tests/fixtures/cli_help_golden.txt if intentional"
