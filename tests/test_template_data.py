"""Packaged emitted-artifact templates: valid as their own language, tokens round-trip."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from chock.resources import package_data_dir

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "chock"
TEMPLATE_ROOT = package_data_dir("chock", "data", "templates")

TOKEN = re.compile(r"__[A-Z][A-Z0-9_]*__")

RENDER_FUNCTIONS = {"template_text", "render_template", "render_template_line"}


def _template_files() -> dict[str, str]:
    return {
        p.relative_to(TEMPLATE_ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in TEMPLATE_ROOT.rglob("*")
        if p.is_file()
    }


def _renderer_calls() -> dict[str, set[str]]:
    """Every template referenced from src, mapped to the union of token keys supplied."""
    calls: dict[str, set[str]] = {}
    for path in SRC_ROOT.rglob("*.py"):
        if path == SRC_ROOT / "resources.py":  # the loader itself forwards a variable path
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in RENDER_FUNCTIONS or not node.args:
                continue
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"{path}: {node.func.id} must take a literal template path so this test can bind it"
            )
            supplied = calls.setdefault(first.value, set())
            if len(node.args) > 1:
                tokens_arg = node.args[1]
                assert isinstance(tokens_arg, ast.Dict), (
                    f"{path}: {node.func.id}({first.value!r}) must pass a literal token dict"
                )
                for key in tokens_arg.keys:
                    assert isinstance(key, ast.Constant) and isinstance(key.value, str)
                    supplied.add(key.value)
    return calls


def test_every_template_is_rendered_and_every_token_is_supplied() -> None:
    """No orphan template files, no orphan or missing __TOKEN__ placeholders."""
    files = _template_files()
    calls = _renderer_calls()

    unrendered = sorted(files.keys() - calls.keys())
    assert not unrendered, f"template files no renderer reads: {unrendered}"
    dangling = sorted(calls.keys() - files.keys())
    assert not dangling, f"renderers reading template files that do not exist: {dangling}"

    for rel, text in files.items():
        in_file = set(TOKEN.findall(text))
        supplied = calls[rel]
        assert in_file == supplied, (
            f"{rel}: tokens in the file {sorted(in_file)} != tokens its renderer supplies {sorted(supplied)}"
        )


def test_python_templates_parse_as_python() -> None:
    for path in TEMPLATE_ROOT.rglob("*.py.tmpl"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_shell_templates_parse_as_shell() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    for path in TEMPLATE_ROOT.rglob("*.sh"):
        proc = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path.name} is not valid shell as-is:\n{proc.stderr}"


def test_yaml_templates_parse_as_yaml() -> None:
    for pattern in ("*.yaml", "*.yml"):
        for path in TEMPLATE_ROOT.rglob(pattern):
            yaml.safe_load(path.read_text(encoding="utf-8"))


def test_rendered_ci_step_fragment_is_yaml_with_the_tokens_gone() -> None:
    """actionlint needs a complete workflow, so the step fragment is pinned here instead."""
    from chock.resources import render_template

    rendered = render_template("ci/step.yaml", {"__POLICY_ID__": "policy-x", "__GATE_PATH__": "gate.json"})
    assert not TOKEN.search(rendered)
    steps = yaml.safe_load(rendered)
    assert steps[0]["name"] == "chock-ci-gate (policy-x)"
    assert "--gate gate.json" in steps[0]["run"]


def test_hook_templates_carry_the_ownership_marker() -> None:
    """is_ours() only recognises what the templates actually emit."""
    from chock.hooks.ownership import GENERATED_MARKER

    for rel in ("hooks/dispatcher.sh", "hooks/policy-wrapper.sh", "hooks/validate-wrapper-windows.sh"):
        lines = (TEMPLATE_ROOT / rel).read_text(encoding="utf-8").splitlines()
        assert lines[1] == GENERATED_MARKER, f"{rel} line 2 must be the ownership marker verbatim"


def test_dispatch_variants_differ_only_by_the_session_start_branch() -> None:
    base = (TEMPLATE_ROOT / "runtime/dispatch.py.tmpl").read_text(encoding="utf-8")
    ss = (TEMPLATE_ROOT / "runtime/dispatch-session-start.py.tmpl").read_text(encoding="utf-8")
    branch = '    if event.event == "session_start":\n        return _chock_handle_session_start(event)\n'
    tail = "    return None\n"
    assert base.endswith(tail) and ss.endswith(branch + tail)
    assert ss == base.removesuffix(tail) + branch + tail


def test_workflow_template_first_line_is_the_ownership_marker() -> None:
    from chock.scaffold.install_ci import MARKER, WORKFLOW_TEMPLATE

    assert WORKFLOW_TEMPLATE.startswith(MARKER + "\n")
    assert "Auto-generated by chock sync --ci" in MARKER


def test_pointer_template_is_bounded_by_the_pointer_markers() -> None:
    from chock.scaffold.agents_md import POINTER_BLOCK, POINTER_END, POINTER_START

    assert POINTER_BLOCK.startswith(POINTER_START + "\n")
    assert POINTER_BLOCK.endswith(POINTER_END + "\n")
