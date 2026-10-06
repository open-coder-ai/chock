"""`chock install` with `from: local` entries: containment, hash, checks, and a mixed bundle for every client."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest
from bundle_fixtures import GATE_ID, GUARD_ID, denies, hook_commands, project, run_command
from install_fixtures import _git, make_catalog
from local_fixtures import (
    MY,
    ORIGIN,
    REL,
    guard,
    install,
    local_entry,
    make_home,
    make_mine,
    needs_git,
    only_local,
    plugin,
    sha,
    trust,
)
from test_install_clients import CLIENTS, TREE, v2

from chock.guardrails import cli as bundle_cli
from chock.install import cli, package, place
from chock.lock import compute_pack_hash

pytestmark = needs_git


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_home(tmp_path, monkeypatch)


@pytest.fixture
def mine(tmp_path: Path) -> Path:
    return make_mine(tmp_path)


DESTROY = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "terraform destroy"}}
PLAN = {**DESTROY, "tool_input": {"command": "terraform plan"}}


# --- containment ---------------------------------------------------------------------------------


def test_a_path_with_dotdot_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    shutil.copytree(mine / REL, tmp_path / MY)
    assert install(mine, only_local(path=f"../{MY}")) == 1
    assert "invalid selection" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_a_folder_that_links_out_of_the_selection_folder_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    outside = tmp_path / "elsewhere"
    shutil.move(str(mine / REL), outside)
    (mine / REL).symlink_to(outside, target_is_directory=True)
    assert install(mine, only_local(), f"--trust-local={MY}={compute_pack_hash(outside)}") == 1
    assert f"{mine / REL} is a symbolic link" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_a_parent_folder_that_is_a_link_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    shutil.move(str(mine / ".agents"), tmp_path / "real")
    (mine / ".agents").symlink_to(tmp_path / "real", target_is_directory=True)
    assert install(mine, only_local()) == 1
    assert f"{mine / '.agents'} is a symbolic link" in capsys.readouterr().err


def test_a_link_inside_the_policy_folder_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours\n", encoding="utf-8")
    (mine / REL / "implementations" / "data.txt").symlink_to(secret)
    assert install(mine, only_local()) == 1
    assert "implementations/data.txt is a symbolic link" in capsys.readouterr().err


def test_a_binary_file_is_refused_because_it_cannot_be_shown(mine: Path, home, capsys) -> None:
    (mine / REL / "implementations" / "blob.bin").write_bytes(b"\xff\xfe\x00")
    assert install(mine, only_local()) == 1
    assert "is not UTF-8 text" in capsys.readouterr().err


def test_a_local_entry_from_a_link_or_code_is_refused(home, capsys) -> None:
    code = base64.urlsafe_b64encode(json.dumps(only_local()).encode("utf-8")).decode("ascii").rstrip("=")
    assert cli.main(["--selection", f"https://chock.sh/#s={code}"]) == 1
    assert "needs a selection file beside its folder" in capsys.readouterr().err


def test_the_manifest_id_must_match_the_entry(mine: Path, home, capsys) -> None:
    manifest = mine / REL / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(f"id: {MY}", "id: my-other"), encoding="utf-8")
    assert install(mine, only_local()) == 1
    assert "says `id: my-other`" in capsys.readouterr().err


# --- hash, validate, evals -----------------------------------------------------------------------


def test_a_hash_mismatch_is_refused(mine: Path, home, capsys) -> None:
    assert install(mine, only_local(sha256="0" * 64), trust(mine)) == 1
    err = capsys.readouterr().err
    assert f"the selection pins sha256 {'0' * 64}, the folder hashes to {sha(mine)}" in err
    assert not place.default_dest("claude-code").exists()


def test_a_matching_pinned_hash_installs(mine: Path, home) -> None:
    assert install(mine, only_local(sha256=sha(mine)), trust(mine)) == 0


def test_a_validation_failure_is_refused(mine: Path, home, capsys) -> None:
    manifest = mine / REL / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('  source_repo: "local"\n', ""), encoding="utf-8")
    assert install(mine, only_local(), trust(mine)) == 1
    assert "failed `chock check --only validate`" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_an_eval_failure_is_refused(mine: Path, home, capsys) -> None:
    suite = mine / REL / "evals" / "suite.yaml"
    suite.write_text(suite.read_text(encoding="utf-8").replace("expect: allow", "expect: block"), encoding="utf-8")
    assert install(mine, only_local(), trust(mine)) == 1
    assert "failed `chock check --only evals`" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_the_code_does_not_run_before_it_is_accepted(mine: Path, tmp_path: Path, home) -> None:
    """Evals execute the guard, so they wait for the confirmation; a refused install never runs it."""
    ran = tmp_path / "ran"
    text = guard(mine).read_text(encoding="utf-8")
    guard(mine).write_text(text.replace("def main(", f"open({str(ran)!r}, 'w').close()\n\n\ndef main(", 1), "utf-8")
    assert install(mine, only_local()) == 1
    assert not ran.exists()
    assert install(mine, only_local(), trust(mine)) == 0
    assert ran.exists()


# --- a mixed catalog and custom bundle, every client ---------------------------------------------


def _mixed(root: Path, ref: str, client: str) -> dict:
    data = v2(root, ref, client, (GUARD_ID, GATE_ID), name="mine")
    data["policies"].insert(1, local_entry())
    return data


@pytest.mark.parametrize("client", CLIENTS)
def test_a_mixed_bundle_builds_for_every_client(catalog, mine: Path, home, capsys, client: str) -> None:
    assert install(mine, _mixed(*catalog, client), trust(mine)) == 0
    out = capsys.readouterr().out
    built = plugin(client)
    assert built == place.default_dest(client) / TREE[client][0].replace("chock-guardrails", "mine")
    assert (built / "scripts" / MY / f"{MY}.py").is_file(), "the custom guard ships under its own namespace"
    members = json.loads((built / "scripts" / "chock_bundle.json").read_text(encoding="utf-8"))["members"]
    labels = {m["id"]: m["label"] for m in members}
    assert [m["id"] for m in members] == [GUARD_ID, MY, GATE_ID]
    assert labels[MY].startswith(f"{ORIGIN}; ")
    assert not labels[GUARD_ID].startswith(ORIGIN)
    assert not labels[GATE_ID].startswith(ORIGIN)
    skill = next(built.rglob("customize-guardrails/SKILL.md")).read_text(encoding="utf-8")
    assert f"| `{MY}` | {ORIGIN}; " in skill
    printed = [line for line in out.splitlines() if line.startswith(f"  {MY} ")]
    assert len(printed) == 1
    assert ORIGIN in printed[0]
    marker = package.read_marker(built)
    assert marker["client"] == client
    assert package.accepted(marker) == {MY: sha(mine)}


def test_bundle_status_labels_the_custom_member(catalog, mine: Path, home, capsys) -> None:
    assert install(mine, _mixed(*catalog, "claude-code"), trust(mine)) == 0
    capsys.readouterr()
    assert bundle_cli.main(["status"]) == 0
    rows = [line.split(None, 2) for line in capsys.readouterr().out.splitlines() if line.strip().startswith(MY)]
    assert len(rows) == 1
    assert rows[0][2].startswith(ORIGIN)


def test_the_built_custom_guard_refuses_in_the_agent(catalog, mine: Path, tmp_path: Path, home) -> None:
    assert install(mine, _mixed(*catalog, "claude-code"), trust(mine)) == 0
    built = plugin("claude-code")
    commands = hook_commands(json.loads((built / "hooks" / "hooks.json").read_text(encoding="utf-8")))
    repo = project(tmp_path)
    assert any(denies(run_command(c, built, repo, DESTROY)) for c in commands)
    assert not any(denies(run_command(c, built, repo, PLAN)) for c in commands)


def test_a_local_id_that_the_catalog_also_lists_is_refused(catalog, mine: Path, home, capsys) -> None:
    root, _ref = catalog
    registry = root / "registry.yaml"
    registry.write_text(registry.read_text(encoding="utf-8") + f"- id: {MY}\n  path: base/{MY}\n  version: 0.0.1\n")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "--quiet", "-am", "clash")
    assert install(mine, _mixed(root, _git(root, "rev-parse", "HEAD"), "claude-code"), trust(mine)) == 1
    assert f"{MY}: a local policy may not reuse a catalog id" in capsys.readouterr().err
