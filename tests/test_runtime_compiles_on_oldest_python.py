"""Every rendered runtime file compiles on the oldest supported Python (3.11).

`ast.unparse` writes nested-quote f-strings that only parse on 3.12+. A runtime built that way
raises SyntaxError on a 3.11 machine, and every hook call is then refused (IR-F13). The 3.11
matrix job runs this on 3.11 itself; on a newer interpreter the files are compiled by a 3.11
interpreter when one is on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDERED = sorted(
    [*(ROOT / ".chock" / "bin").glob("*.py"), *(ROOT / "tests" / "fixtures" / "runtime_goldens").glob("*.py")]
)
OLDEST = (3, 11)
_COMPILE = "import sys\nfor p in sys.argv[1:]:\n    compile(open(p, encoding='utf-8').read(), p, 'exec')\n"


def test_the_rendered_runtime_files_are_found() -> None:
    kinds = {p.parent.name for p in RENDERED}
    assert kinds == {"bin", "runtime_goldens"}, kinds
    assert len(RENDERED) >= 20


def test_every_rendered_runtime_file_compiles_on_the_oldest_supported_python() -> None:
    if sys.version_info[:2] == OLDEST:
        for path in RENDERED:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return
    exe = shutil.which(f"python{OLDEST[0]}.{OLDEST[1]}")
    if exe is None:
        pytest.skip("no Python 3.11 on PATH; the 3.11 matrix job runs this check")
    run = subprocess.run([exe, "-c", _COMPILE, *map(str, RENDERED)], capture_output=True, text=True, check=False)
    assert run.returncode == 0, f"not valid on Python 3.11:\n{run.stderr[-600:]}"
