"""Review 4, item 7: ordinary pull requests touching no control-plane path. Owed exit 0 (V7)."""

from __future__ import annotations

import random
import time

import pytest
from floor_support import TEST_FILE, base_repo, commit, run_floor, write


def _bytes(repo, rel, data):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _rand(n, seed=7):
    return random.Random(seed).randbytes(n)  # noqa: S311 -- incompressible filler, not a secret


CASES = {
    "source-edit": lambda r: write(r, "src/app.py", "VALUE = 2\n"),
    "new-directory": lambda r: write(r, "pkg/sub/mod.py", "X = 1\n"),
    "docs": lambda r: write(r, "docs/guide.md", "# Guide\n"),
    "readme": lambda r: write(r, "README.md", "# Project\n"),
    "package-lock": lambda r: write(r, "package-lock.json", '{"lockfileVersion": 3, "packages": {"": {}}}\n'),
    "uv-lock": lambda r: write(r, "uv.lock", 'version = 1\n[[package]]\nname = "x"\nversion = "1.0"\n'),
    "test-added": lambda r: write(r, "tests/test_new.py", "def test_b():\n    assert True\n"),
    "test-edited-values": lambda r: write(r, "tests/test_core.py", TEST_FILE.replace("== 4", "== 4.0")),
    "test-assert-moved": lambda r: write(
        r, "tests/test_core.py", "def test_a():\n    assert 2 * 2 == 4\n    x = 1\n    assert 1 + 1 == 2\n"
    ),
    "crlf-file": lambda r: _bytes(r, "src/win.py", b"A = 1\r\nB = 2\r\n"),
    "crlf-normalised-test": lambda r: _bytes(r, "tests/test_core.py", TEST_FILE.replace("\n", "\r\n").encode()),
    "utf8-bom": lambda r: _bytes(r, "src/bom.py", b"\xef\xbb\xbfA = 1\n"),
    "utf16-bom-text": lambda r: _bytes(r, "src/u16.txt", "hello\nworld\n".encode("utf-16")),
    "png": lambda r: _bytes(r, "assets/logo.png", b"\x89PNG\r\n\x1a\n" + _rand(200_000)),
    "env-example": lambda r: write(r, ".env.example", "DATABASE_URL=\n"),
    "nested-gitattributes": lambda r: write(r, "assets/.gitattributes", "*.png binary\n"),
    "docs-codeowners-word": lambda r: write(r, "docs/codeowners.md", "Who owns what\n"),
    "agents-md": lambda r: write(r, "AGENTS.md", "Be nice.\n"),
    "exec-bit-script": lambda r: (write(r, "scripts/run.sh", "#!/bin/sh\n"), (r / "scripts/run.sh").chmod(0o755)),
}


@pytest.mark.parametrize("name", list(CASES))
def test_ordinary(tmp_path, capsys, name):
    repo = base_repo(tmp_path)
    CASES[name](repo)
    commit(repo, f"pr: {name}")
    code, out = run_floor(repo, capsys)
    assert code == 0, out


@pytest.mark.parametrize(
    ("name", "size", "binary"),
    [
        ("text-20MiB", 20 * 2**20, False),
        ("binary-8MiB", 8 * 2**20, True),
        ("binary-40MiB", 40 * 2**20, True),
    ],
)
def test_large_file_under_the_limit(tmp_path, capsys, name, size, binary):
    repo = base_repo(tmp_path)
    if binary:
        _bytes(repo, f"assets/{name}.bin", _rand(size))
    else:
        line = b"generated_value_0123456789 = 'abcdefghijklmnopqrstuvwxyz'\n"
        _bytes(repo, f"src/{name}.py", line * (size // len(line)))
    commit(repo, "pr")
    start = time.monotonic()
    code, out = run_floor(repo, capsys)
    took = time.monotonic() - start
    print(f"{name}: exit {code} in {took:.1f}s")
    assert code == 0, (took, out[-1500:])


def test_binary_60mib_under_the_64mib_limit(tmp_path, capsys):
    repo = base_repo(tmp_path)
    _bytes(repo, "assets/model.bin", _rand(60 * 2**20))
    commit(repo, "pr")
    start = time.monotonic()
    code, out = run_floor(repo, capsys)
    print(f"binary-60MiB: exit {code} in {time.monotonic() - start:.1f}s")
    assert code == 0, out[-1500:]
