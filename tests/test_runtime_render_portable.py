"""The rendered runtime is the same bytes, and valid on the oldest supported Python, whichever interpreter renders it.

`ast.unparse` on 3.12.0-3.12.x writes PEP 701 same-quote f-strings (`f'{', '.join(x)}'`), a SyntaxError on 3.11; later
3.12 releases quote them portably. The renderer lowers any f-string holding a string literal, so no quoting is left to differ.
"""

from __future__ import annotations

import ast
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from chock.gate import runtime_shared

ROOT = Path(__file__).resolve().parent.parent
OLDEST = (3, 11)
CHECKED = ((3, 11), (3, 12), (3, 13), (3, 14))
_COMPILE = "import sys\ncompile(sys.stdin.read(), 'render', 'exec')\n"
_RENDER = "import hashlib\nfrom chock.gate.runtime_shared import render_shared\nprint(hashlib.sha256(render_shared().encode()).hexdigest())\n"
_SAME_QUOTE = "x = f\"{', '.join(y)}\"\nz = f\"{a!r:>{w}} {b=} {'q'!s:'>5}\"\n"
_SHADOWABLE = {"format", "str", "repr", "ascii"}


def _lowered(source: str) -> str:
    return ast.unparse(runtime_shared._Renamer().visit(ast.parse(source)))


def _oldest_python() -> str | None:
    return None if sys.version_info[:2] == OLDEST else shutil.which("python{}.{}".format(*OLDEST))


def _parses_on_oldest(text: str) -> None:
    if sys.version_info[:2] == OLDEST:
        compile(text, "render", "exec")
        return
    exe = _oldest_python()
    if exe is None:
        pytest.skip("no Python 3.11 on PATH; the 3.11 matrix job runs this check")
    run = subprocess.run([exe, "-c", _COMPILE], input=text, capture_output=True, text=True, check=False)
    assert run.returncode == 0, f"not valid on Python 3.11:\n{run.stderr[-600:]}"


def test_the_render_on_this_interpreter_parses_on_the_oldest_supported_python() -> None:
    _parses_on_oldest(runtime_shared.render_shared())


def test_a_same_quote_fstring_is_lowered_to_source_every_grammar_parses() -> None:
    out = _lowered(_SAME_QUOTE)
    assert "f'" not in out
    assert 'f"' not in out
    _parses_on_oldest(out)


def test_the_lowered_fstring_means_what_the_original_did() -> None:
    scope = {"y": ["a", "b"], "a": "A", "w": 4, "b": 7}
    for src in (_SAME_QUOTE, "x = f\"{'k'}-{y[0]!r:>{w}}\"\n"):
        want: dict = dict(scope)
        got: dict = dict(scope)
        exec(src, want)  # noqa: S102 -- a fixed literal above, compared with its own lowering
        exec(_lowered(src), got)  # noqa: S102
        assert {k: v for k, v in got.items() if k in "xz"} == {k: v for k, v in want.items() if k in "xz"}


def test_a_plain_fstring_is_left_alone() -> None:
    assert _lowered("x = f'{a}-{b:>4}'\n") == ast.unparse(ast.parse("x = f'{a}-{b:>4}'\n"))


def test_the_runtime_does_not_shadow_the_builtins_a_lowered_fstring_calls() -> None:
    tree = ast.parse(runtime_shared.render_shared())
    bound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    bound |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    bound |= {
        a.arg for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in [*n.args, *n.kwonlyargs, *n.posonlyargs]
    }
    assert not bound & _SHADOWABLE


def test_every_installed_supported_interpreter_renders_the_same_bytes() -> None:
    mine = hashlib.sha256(runtime_shared.render_shared().encode()).hexdigest()
    seen = 0
    for major, minor in CHECKED:
        exe = shutil.which(f"python{major}.{minor}")
        if exe is None or (major, minor) == sys.version_info[:2]:
            continue
        run = subprocess.run(
            [exe, "-c", _RENDER],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
        )
        if run.returncode != 0:
            continue
        seen += 1
        assert run.stdout.strip() == mine, f"python{major}.{minor} renders different bytes"
    if not seen:
        pytest.skip("no other supported interpreter with chock's dependencies is installed")
