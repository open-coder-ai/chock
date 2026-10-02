"""gate.py is assembled from the runner package: every module's fragments, in number order, after the prelude."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from chock.gate import assemble
from chock.gate.assemble import runner_source

PACKAGE = Path(assemble.__file__).resolve().parent / "runner"
PRELUDE = Path(assemble.__file__).resolve().parent / "data" / "gate_prelude.py.tmpl"
MARKER = re.compile(r"^# >>> gate\.py (\d+)$", re.MULTILINE)
ENTRY_POINTS = {"__init__.py", "__main__.py"}


def _modules() -> list[Path]:
    return sorted(path for path in PACKAGE.glob("*.py") if path.name not in ENTRY_POINTS)


def _header(path: Path) -> str:
    return MARKER.split(path.read_text(encoding="utf-8"), maxsplit=1)[0]


def _bound(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom) and not getattr(node, "level", 0):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def test_every_module_contributes_and_the_entry_points_do_not() -> None:
    for path in _modules():
        assert MARKER.search(path.read_text(encoding="utf-8")), f"{path.name} has no gate.py fragment"
    for name in ENTRY_POINTS:
        assert not MARKER.search((PACKAGE / name).read_text(encoding="utf-8")), f"{name} must stay out of gate.py"


def test_a_header_holds_only_its_docstring_and_imports() -> None:
    """Code above the first marker would run in the package but never in gate.py."""
    for path in _modules():
        for node in ast.parse(_header(path)).body:
            docstring = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            assert docstring or isinstance(node, ast.Import | ast.ImportFrom), f"{path.name}:{node.lineno}"


def test_a_header_imports_only_the_stdlib_and_its_siblings() -> None:
    for path in _modules():
        for node in ast.parse(_header(path)).body:
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert not node.module.startswith("chock"), f"{path.name} imports {node.module}"


def test_the_prelude_binds_every_stdlib_name_a_header_imports() -> None:
    """A module may import what it reads; gate.py has only the prelude's imports to read it from."""
    prelude = _bound(ast.parse(PRELUDE.read_text(encoding="utf-8")))
    for path in _modules():
        missing = _bound(ast.parse(_header(path))) - prelude
        assert not missing, f"{path.name} imports {sorted(missing)}; add them to {PRELUDE.name}"


def test_the_assembled_runner_is_one_compilable_file() -> None:
    source = runner_source()
    compile(source, "gate.py", "exec")
    assert source.startswith(PRELUDE.read_text(encoding="utf-8"))
    assert "# >>> gate.py" not in source


def _package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modules: dict[str, str]) -> None:
    pkg = tmp_path / "runner"
    pkg.mkdir()
    for name, text in modules.items():
        (pkg / name).write_text(text, encoding="utf-8")
    real = assemble.package_data_dir
    monkeypatch.setattr(assemble, "package_data_dir", lambda package, *sub: pkg if not sub else real(package, *sub))


def test_fragments_join_in_number_order_whatever_module_holds_them(tmp_path: Path, monkeypatch) -> None:
    _package(
        tmp_path, monkeypatch, {"a.py": "import os\n# >>> gate.py 2\nB = 2\n", "b.py": "# >>> gate.py 1\nA = 1\n\n"}
    )
    assert runner_source() == PRELUDE.read_text(encoding="utf-8") + "A = 1\n\n\nB = 2\n"


@pytest.mark.parametrize(
    ("modules", "error"),
    [
        ({"a.py": "# >>> gate.py 1\nA = 1\n", "b.py": "# >>> gate.py 1\nB = 1\n"}, ValueError),
        ({"a.py": "# >>> gate.py 1\nA = 1\n# >>> gate.py 3\nC = 1\n"}, ValueError),
        ({"a.py": "# >>> gate.py 2\nB = 1\n"}, ValueError),
        ({"a.py": "A = 1\n"}, FileNotFoundError),
        ({}, FileNotFoundError),
    ],
    ids=["repeat", "gap", "no-first", "no-marker", "no-module"],
)
def test_a_fragment_set_that_cannot_be_ordered_refuses(tmp_path, monkeypatch, modules, error) -> None:
    _package(tmp_path, monkeypatch, modules)
    with pytest.raises(error):
        runner_source()
