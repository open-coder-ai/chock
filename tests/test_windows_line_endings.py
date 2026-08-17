"""Generated executables and the lockfile must be LF on every platform.

`write_text` without `newline=` emits CRLF on Windows. For a shell script that git runs
from the working tree that means `bad interpreter: /bin/sh^M`; for the lockfile it means a
no-op sync shows as modified. The repo pins these to LF via .gitattributes AND writes them
LF via emit.write_generated -- both halves are required, and these guard the writer half.
"""

from __future__ import annotations

from pathlib import Path

from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.hooks.installers import install_dispatcher
from chock.lock import write_lock


def _no_crlf(path: Path) -> bool:
    return b"\r\n" not in path.read_bytes()


def test_installed_dispatcher_is_lf(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    install_dispatcher(hooks, "pre-commit")
    dispatcher = hooks / "pre-commit"
    assert dispatcher.exists()
    assert _no_crlf(dispatcher), "the dispatcher is executed from the working tree; CRLF breaks /bin/sh"


def test_lockfile_is_lf(tmp_path: Path) -> None:
    write_lock({"version": 1, "packs": []}, tmp_path)
    assert _no_crlf(tmp_path / "chock.lock")


def test_shim_probe_requires_tomllib(tmp_path: Path) -> None:
    # The vendored runner imports tomllib at module scope (3.11+). A probe of `python -c ''`
    # accepted a 3.10 interpreter, which then ImportError'd on every commit. The probe must
    # select an interpreter that can actually import tomllib.
    policy = baseline_policy("protect-main-branch")
    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy, targets=[Surface.GIT_HOOK.value], output_root=out, agents=["claude"])
    shim = (out / "protect-main-branch" / "git-hook" / "git-pre-commit.sh").read_text(encoding="utf-8")
    assert "import tomllib" in shim
    assert "-c ''" not in shim
