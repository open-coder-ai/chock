"""A catalog URL is a URL: a directory of the same shape under the working directory never replaces it."""

from __future__ import annotations

from pathlib import Path

import pytest

from chock.install import trust
from chock.scaffold import pin

URL = "https://github.com/open-coder-ai/chock-catalog"
SCP = "git@github.com:open-coder-ai/chock-catalog.git"


def _plant(root: Path, source: str) -> None:
    planted = root / Path(source)
    planted.mkdir(parents=True)
    (planted / "registry.yaml").write_text("planted: true\n", encoding="utf-8")


@pytest.mark.parametrize("source", [URL, SCP])
def test_fetch_catalog_clones_the_remote_not_a_lookalike_directory(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, source)
    monkeypatch.chdir(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(pin, "_clone_ref", lambda _s, remote, _r, _i: seen.append(remote))
    monkeypatch.setattr(pin, "_snapshot_local", lambda *_a: pytest.fail("a lookalike directory was snapshotted"))

    pin.fetch_catalog(source, None, tmp_path / "into")

    assert seen == [source]


@pytest.mark.parametrize("source", [URL, SCP])
def test_a_pinned_remote_is_still_checked_as_published(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, source)
    monkeypatch.chdir(tmp_path)
    sha = "a" * 40
    checked: list[str] = []
    monkeypatch.setattr(pin, "_fetch_commit", lambda _s, _r, s, _i: s)
    monkeypatch.setattr(pin, "_require_published", lambda _s, remote, *_a: checked.append(remote))

    pin.fetch_catalog(source, sha, tmp_path / "into")

    assert checked == [source]


@pytest.mark.parametrize("source", [URL, SCP])
def test_require_on_branch_reads_the_remote_not_a_lookalike_directory(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, source)
    monkeypatch.chdir(tmp_path)
    cloned: list[list[str]] = []

    class Done:
        returncode = 1
        stderr = "unreachable"

    monkeypatch.setattr(trust, "_run", lambda cmd, *_a: cloned.append(cmd) or Done())

    with pytest.raises(trust.IntegrityError):
        trust.require_on_branch(source, "b" * 40, tmp_path / "bare")

    assert cloned[0][-2] == source


def test_an_explicit_local_path_is_still_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "cat").mkdir()
    (tmp_path / "cat" / "registry.yaml").write_text("x: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pin, "_snapshot_local", lambda source, _l, _i: (Path(source), None))

    root, _ = pin.fetch_catalog("./cat", None, tmp_path / "into")

    assert root == Path("./cat")
