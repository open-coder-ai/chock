"""Shared by the `from: local` install tests: a catalog, a throwaway HOME, a person's own guard, and helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from install_fixtures import make_catalog, write_selection

from chock.install import cli, local, place
from chock.lock import compute_pack_hash
from chock.scaffold import new

MY = "my-tf"
REL = f".agents/policies/{MY}"
ORIGIN = "custom, not reviewed"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway HOME and no terminal, unless a test says otherwise."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    monkeypatch.setattr(local, "interactive", lambda: False)
    return path


@pytest.fixture
def mine(tmp_path: Path) -> Path:
    """The folder a person keeps their selection and their own guard in."""
    folder = tmp_path / "mine"
    folder.mkdir()
    assert new.cmd_new(["policy", "tf", "--kind", "guard", "--root", str(folder)]) == 0
    return folder


def local_entry(path: str = REL, **extra: str) -> dict:
    return {"from": "local", "id": MY, "path": path, **extra}


def only_local(client: str = "claude-code", name: str = "mine", **entry: str) -> dict:
    return {
        "schema": 2,
        "client": client,
        "bundle": {"name": name, "version": "0.1.0"},
        "policies": [local_entry(**entry)],
    }


def install(folder: Path, data: dict, *extra: str) -> int:
    path = write_selection(folder / "chock.selection.yaml", data)
    allow = ["--allow-source", data["catalog"]["source"]] if "catalog" in data else []
    return cli.main(["--selection", str(path), *allow, *extra])


def sha(folder: Path) -> str:
    return compute_pack_hash(folder / REL)


def trust(folder: Path) -> str:
    return f"--trust-local={MY}={sha(folder)}"


def plugin(client: str, name: str = "mine") -> Path:
    return place.plugin_dir(client, place.default_dest(client), name)


def guard(folder: Path) -> Path:
    return folder / REL / "implementations" / f"{MY}.py"
