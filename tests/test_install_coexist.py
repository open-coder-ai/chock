"""`chock install`: bundles coexist per client, clients never share a folder, overlaps and schema-1 installs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID
from install_fixtures import make_catalog, selection
from test_install_clients import CLIENTS, _files, _read, _run, v2

from chock.install import package, place

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway HOME, so every default folder lands in the test's own directory."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def test_two_bundles_for_one_client_coexist_and_both_are_indexed(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, "claude-code", (GUARD_ID,), name="set-one")) == 0
    assert _run(tmp_path, v2(root, ref, "claude-code", (GATE_ID,), name="set-two")) == 0
    dest = place.default_dest("claude-code")
    assert (dest / "claude" / "set-one" / "skills" / GUARD_ID).is_dir()
    assert (dest / "claude" / "set-two" / "skills" / GATE_ID).is_dir()
    index = _read(dest / ".claude-plugin" / "marketplace.json")
    assert [p["name"] for p in index["plugins"]] == ["set-one", "set-two"]
    assert _run(tmp_path, v2(root, ref, "claude-code", (ADVISORY_ID,), name="set-one")) == 0
    assert not (dest / "claude" / "set-one" / "skills" / GUARD_ID).exists(), "a rebuild replaces only its own bundle"
    assert (dest / "claude" / "set-two" / "skills" / GATE_ID).is_dir()


@pytest.mark.parametrize("client", ["cursor", "devin"])
def test_two_plugin_dir_bundles_coexist(catalog, tmp_path: Path, home: Path, client: str) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, client, (GUARD_ID,), name="set-one")) == 0
    assert _run(tmp_path, v2(root, ref, client, (GATE_ID,), name="set-two")) == 0
    dest = place.default_dest(client)
    assert {p.name for p in dest.iterdir()} == {"set-one", "set-two"}


def test_a_second_client_never_wipes_the_first(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    before = {}
    for client in CLIENTS:
        assert _run(tmp_path, v2(root, ref, client)) == 0
        before[client] = _files(place.default_dest(client))
    for client in CLIENTS:
        assert _files(place.default_dest(client)) == before[client]


def test_one_folder_is_never_shared_by_two_clients(catalog, tmp_path: Path, home, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "shared"
    assert _run(tmp_path, v2(root, ref, "claude-code"), "--dest", str(dest)) == 0
    before = _files(dest)
    assert _run(tmp_path, v2(root, ref, "copilot"), "--dest", str(dest)) == 1
    assert "chock's marketplace for claude-code, not copilot" in capsys.readouterr().err
    assert _files(dest) == before
    assert _run(tmp_path, v2(root, ref, "devin"), "--dest", str(tmp_path / "dirs")) == 0
    assert _run(tmp_path, v2(root, ref, "cursor"), "--dest", str(tmp_path / "dirs")) == 1
    assert "was built for devin, not cursor" in capsys.readouterr().err


def test_overlap_with_another_chock_plugin_for_the_client_is_warned(catalog, tmp_path: Path, home, capsys) -> None:
    root, ref = catalog
    assert _run(tmp_path, v2(root, ref, "codex", (GUARD_ID, GATE_ID), name="set-one")) == 0
    capsys.readouterr()
    assert _run(tmp_path, v2(root, ref, "codex", (GATE_ID, ADVISORY_ID), name="set-two")) == 0
    folder = place.default_dest("codex").resolve() / "codex" / "set-one"
    out = capsys.readouterr().out
    assert f"warning: {GATE_ID} is also in the chock plugin set-one ({folder}): both copies fire" in out
    assert GUARD_ID not in out.split("warning:", 1)[1].split("\n", 1)[0]
    assert _run(tmp_path, v2(root, ref, "claude-code", (GATE_ID,), name="set-three")) == 0
    assert "is also in the chock plugin" not in capsys.readouterr().out, "another client's plugin never overlaps"


def test_a_schema_1_install_is_kept_and_listed_beside_a_new_bundle(catalog, tmp_path: Path, home, capsys) -> None:
    root, ref = catalog
    dest = tmp_path / "old"
    assert _run(tmp_path, selection(root, ref), "--dest", str(dest)) == 0
    legacy = _read(dest / "claude" / "chock-guardrails" / package.MARKER)
    (dest / package.MARKER).write_text(json.dumps(selection(root, ref)), encoding="utf-8")
    (dest / "claude" / "chock-guardrails" / package.MARKER).unlink()
    (dest / place.MARKETPLACE_MARKER).unlink()
    capsys.readouterr()
    assert _run(tmp_path, v2(root, ref, "claude-code", (GUARD_ID,), name="set-two"), "--dest", str(dest)) == 0
    assert f"warning: {GUARD_ID} is also in the chock plugin chock-guardrails" in capsys.readouterr().out
    assert not (dest / package.MARKER).exists()
    assert (
        _read(dest / "claude" / "chock-guardrails" / package.MARKER)["policies"][0]["id"] == legacy["policies"][0]["id"]
    )
    names = [p["name"] for p in _read(dest / ".claude-plugin" / "marketplace.json")["plugins"]]
    assert names == ["chock-guardrails", "set-two"]


def test_a_local_entry_is_refused_as_not_yet_supported(catalog, tmp_path: Path, home, capsys) -> None:
    root, ref = catalog
    data = v2(root, ref, "claude-code")
    data["policies"].append({"from": "local", "id": "my-guard", "path": "policies/my-guard"})
    assert _run(tmp_path, data) == 1
    err = capsys.readouterr().err
    assert "my-guard: local policies (from: local) are not yet supported" in err
    assert "Nothing was installed." in err
    assert not place.default_dest("claude-code").exists()


def test_migrating_a_schema_1_marketplace_keeps_it_chocks(catalog, tmp_path: Path, home) -> None:
    """If the build fails after the move, the next run must still recognise the folder as chock's."""
    root, ref = catalog
    dest = tmp_path / "old"
    assert _run(tmp_path, selection(root, ref), "--dest", str(dest)) == 0
    (dest / package.MARKER).write_text(json.dumps(selection(root, ref)), encoding="utf-8")
    (dest / place.MARKETPLACE_MARKER).unlink()
    place.migrate_legacy(dest)
    assert not (dest / package.MARKER).exists()
    assert _read(dest / place.MARKETPLACE_MARKER)["client"] == "claude-code"
    place.check_owned("claude-code", dest, "set-two")
