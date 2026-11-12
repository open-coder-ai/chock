"""chock.lock's `engine` field is derived from the running engine and enforced by `check --only verify` (IR-F71)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import chock
from chock import lock
from chock.lifecycle import check_main
from chock.lock import (
    LEGACY_ENGINE_CONSTRAINT,
    build_lock,
    check_engine,
    engine_constraint,
    verify_lock,
    write_lock,
)


def _locked(repo: Path, constraint: object) -> Path:
    (repo / ".agents" / "policies").mkdir(parents=True)
    write_lock({"lockfile_version": "2", "engine": constraint, "packs": []}, repo)
    return repo


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1.2.0", ">=1.2,<2"), ("1.2.7", ">=1.2,<2"), ("2.0.0rc1", ">=2.0,<3"), ("0.0.1", ">=0.0,<1")],
)
def test_constraint_is_derived_from_the_engine_version(version: str, expected: str) -> None:
    assert engine_constraint(version) == expected


def test_written_lock_carries_the_running_engines_constraint(tmp_path: Path) -> None:
    (tmp_path / ".agents" / "policies").mkdir(parents=True)
    assert build_lock(tmp_path)["engine"] == engine_constraint(chock.__version__)
    assert engine_constraint(chock.__version__) != LEGACY_ENGINE_CONSTRAINT


@pytest.mark.parametrize("version", ["1.2.0", "1.2.9", "1.9.0"])
def test_engine_inside_the_constraint_passes(version: str) -> None:
    assert check_engine(">=1.2,<2", version) == (None, None)


@pytest.mark.parametrize(("version", "side"), [("1.1.9", "below"), ("2.0.0", "above"), ("3.1.0", "above")])
def test_engine_outside_the_constraint_fails_naming_engine_lock_and_fix(version: str, side: str) -> None:
    failure, note = check_engine(">=1.2,<2", version)
    assert note is None, side
    assert failure is not None
    assert "\n" not in failure
    assert f"engine {version}" in failure
    assert "'>=1.2,<2'" in failure
    assert 'pip install "chock>=1.2,<2"' in failure
    assert "chock sync --repo ." in failure


def test_legacy_constraint_passes_with_a_note_to_resync() -> None:
    failure, note = check_engine(LEGACY_ENGINE_CONSTRAINT, "1.2.0")
    assert failure is None
    assert note is not None
    assert "chock sync --repo ." in note


@pytest.mark.parametrize("constraint", ["x", "", "^1.2", ">=1.2", "<2,>=1.2", None, 12, ["1.2"]])
def test_unparseable_constraint_fails(constraint: object) -> None:
    failure, note = check_engine(constraint, "1.2.0")
    assert note is None
    assert failure is not None
    assert "cannot be read" in failure


def test_verify_fails_when_the_running_engine_is_outside_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _locked(tmp_path, ">=9.0,<10")
    ok, failures = verify_lock(repo)
    assert not ok
    assert len(failures) == 1
    assert "outside chock.lock's constraint '>=9.0,<10'" in failures[0]
    monkeypatch.chdir(repo)
    assert check_main(["--only", "verify", "--repo", str(repo)]) == 1
    err = capsys.readouterr().err
    assert err.count("verify FAIL:") == 1
    assert f"engine {chock.__version__} is outside" in err


def test_verify_passes_inside_the_lock(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _locked(tmp_path, engine_constraint(chock.__version__))
    assert verify_lock(repo) == (True, [])
    assert lock.main(["verify", "--repo", str(repo)]) == 0
    assert "note:" not in capsys.readouterr().out


def test_verify_passes_a_legacy_lock_with_one_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _locked(tmp_path, LEGACY_ENGINE_CONSTRAINT)
    notes: list[str] = []
    assert verify_lock(repo, notes) == (True, [])
    assert len(notes) == 1
    assert lock.main(["verify", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.count("note:") == 1


def test_verify_fails_an_unparseable_constraint(tmp_path: Path) -> None:
    repo = _locked(tmp_path, ">=one,<two")
    ok, failures = verify_lock(repo)
    assert not ok
    assert "cannot be read" in failures[0]


def test_verify_fails_a_lock_without_an_engine_field(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / ".agents" / "policies").mkdir(parents=True)
    (repo / "chock.lock").write_text(json.dumps({"lockfile_version": "2", "packs": []}), encoding="utf-8")
    ok, failures = verify_lock(repo)
    assert not ok
    assert "cannot be read" in failures[0]
