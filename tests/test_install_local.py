"""`chock install` with `from: local` entries: containment, hash, checks, show and confirm, trust on first use, labels."""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
from pathlib import Path

import pytest
from bundle_fixtures import GATE_ID, GUARD_ID, denies, hook_commands, project, run_command
from install_fixtures import _git, make_catalog, write_selection
from test_install_clients import CLIENTS, TREE, v2

from chock.guardrails import cli as bundle_cli
from chock.install import cli, local, package, place
from chock.install import selection as sel
from chock.lock import compute_pack_hash
from chock.scaffold import new

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
MY = "my-tf"
REL = f".agents/policies/{MY}"
ORIGIN = "custom, not reviewed"
DESTROY = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "terraform destroy"}}
PLAN = {**DESTROY, "tool_input": {"command": "terraform plan"}}


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


def _local(path: str = REL, **extra: str) -> dict:
    return {"from": "local", "id": MY, "path": path, **extra}


def _only_local(client: str = "claude-code", name: str = "mine", **entry: str) -> dict:
    return {"schema": 2, "client": client, "bundle": {"name": name, "version": "0.1.0"}, "policies": [_local(**entry)]}


def _install(folder: Path, data: dict, *extra: str) -> int:
    path = write_selection(folder / "chock.selection.yaml", data)
    allow = ["--allow-source", data["catalog"]["source"]] if "catalog" in data else []
    return cli.main(["--selection", str(path), *allow, *extra])


def _sha(folder: Path) -> str:
    return compute_pack_hash(folder / REL)


def _trust(folder: Path) -> str:
    return f"--trust-local={MY}={_sha(folder)}"


def _plugin(client: str, name: str = "mine") -> Path:
    return place.plugin_dir(client, place.default_dest(client), name)


def _guard(folder: Path) -> Path:
    return folder / REL / "implementations" / f"{MY}.py"


# --- containment ---------------------------------------------------------------------------------


def test_a_path_with_dotdot_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    shutil.copytree(mine / REL, tmp_path / MY)
    assert _install(mine, _only_local(path=f"../{MY}")) == 1
    assert "invalid selection" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_a_folder_that_links_out_of_the_selection_folder_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    outside = tmp_path / "elsewhere"
    shutil.move(str(mine / REL), outside)
    (mine / REL).symlink_to(outside, target_is_directory=True)
    assert _install(mine, _only_local(), f"--trust-local={MY}={compute_pack_hash(outside)}") == 1
    assert f"{mine / REL} is a symbolic link" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_a_parent_folder_that_is_a_link_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    shutil.move(str(mine / ".agents"), tmp_path / "real")
    (mine / ".agents").symlink_to(tmp_path / "real", target_is_directory=True)
    assert _install(mine, _only_local()) == 1
    assert f"{mine / '.agents'} is a symbolic link" in capsys.readouterr().err


def test_a_link_inside_the_policy_folder_is_refused(mine: Path, tmp_path: Path, home, capsys) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("not yours\n", encoding="utf-8")
    (mine / REL / "implementations" / "data.txt").symlink_to(secret)
    assert _install(mine, _only_local()) == 1
    assert "implementations/data.txt is a symbolic link" in capsys.readouterr().err


def test_a_binary_file_is_refused_because_it_cannot_be_shown(mine: Path, home, capsys) -> None:
    (mine / REL / "implementations" / "blob.bin").write_bytes(b"\xff\xfe\x00")
    assert _install(mine, _only_local()) == 1
    assert "is not UTF-8 text" in capsys.readouterr().err


def test_a_local_entry_from_a_link_or_code_is_refused(home, capsys) -> None:
    code = base64.urlsafe_b64encode(json.dumps(_only_local()).encode("utf-8")).decode("ascii").rstrip("=")
    assert cli.main(["--selection", f"https://chock.sh/#s={code}"]) == 1
    assert "needs a selection file beside its folder" in capsys.readouterr().err


def test_the_manifest_id_must_match_the_entry(mine: Path, home, capsys) -> None:
    manifest = mine / REL / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(f"id: {MY}", "id: my-other"), encoding="utf-8")
    assert _install(mine, _only_local()) == 1
    assert "says `id: my-other`" in capsys.readouterr().err


# --- hash, validate, evals -----------------------------------------------------------------------


def test_a_hash_mismatch_is_refused(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local(sha256="0" * 64), _trust(mine)) == 1
    err = capsys.readouterr().err
    assert f"the selection pins sha256 {'0' * 64}, the folder hashes to {_sha(mine)}" in err
    assert not place.default_dest("claude-code").exists()


def test_a_matching_pinned_hash_installs(mine: Path, home) -> None:
    assert _install(mine, _only_local(sha256=_sha(mine)), _trust(mine)) == 0


def test_a_validation_failure_is_refused(mine: Path, home, capsys) -> None:
    manifest = mine / REL / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('  source_repo: "local"\n', ""), encoding="utf-8")
    assert _install(mine, _only_local(), _trust(mine)) == 1
    assert "failed `chock check --only validate`" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_an_eval_failure_is_refused(mine: Path, home, capsys) -> None:
    suite = mine / REL / "evals" / "suite.yaml"
    suite.write_text(suite.read_text(encoding="utf-8").replace("expect: allow", "expect: block"), encoding="utf-8")
    assert _install(mine, _only_local(), _trust(mine)) == 1
    assert "failed `chock check --only evals`" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


def test_the_code_does_not_run_before_it_is_accepted(mine: Path, tmp_path: Path, home) -> None:
    """Evals execute the guard, so they wait for the confirmation; a refused install never runs it."""
    ran = tmp_path / "ran"
    text = _guard(mine).read_text(encoding="utf-8")
    _guard(mine).write_text(text.replace("def main(", f"open({str(ran)!r}, 'w').close()\n\n\ndef main(", 1), "utf-8")
    assert _install(mine, _only_local()) == 1
    assert not ran.exists()
    assert _install(mine, _only_local(), _trust(mine)) == 0
    assert ran.exists()


# --- show and confirm ----------------------------------------------------------------------------


def test_every_file_is_shown_with_its_id_hash_and_label(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    out = capsys.readouterr().out
    assert f"Custom policy {MY} -- {ORIGIN} -- from {(mine / REL).resolve()}" in out
    assert f"sha256 {_sha(mine)}" in out
    for rel in ("manifest.yaml", "evals/suite.yaml", f"implementations/{MY}.py"):
        assert f"----- {MY}/{rel} (" in out
    assert _guard(mine).read_text(encoding="utf-8") in out
    assert out.index(f"----- end of {MY} -----") < out.index("Built mine")


def test_control_characters_are_shown_escaped(mine: Path, home, capsys) -> None:
    _guard(mine).write_text(_guard(mine).read_text(encoding="utf-8") + "# \x1b[2J \x07\n", encoding="utf-8")
    assert _install(mine, _only_local(), _trust(mine)) == 0
    out = capsys.readouterr().out
    assert "# \\u001b[2J \\u0007" in out
    assert "\x1b" not in out
    assert "\x07" not in out


def test_without_a_terminal_or_trust_local_it_refuses_and_names_the_hash(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local()) == 1
    captured = capsys.readouterr()
    assert f"--trust-local {MY}={_sha(mine)}" in captured.err
    assert f"----- {MY}/implementations/{MY}.py" in captured.out
    assert not place.default_dest("claude-code").exists()


@pytest.mark.parametrize(("answer", "code"), [("yes\n", 0), ("YES\n", 0), ("no\n", 1), ("y\n", 1), ("", 1)])
def test_the_interactive_confirmation_reads_stdin(
    mine: Path, home, monkeypatch, capsys, answer: str, code: int
) -> None:
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(answer))
    assert _install(mine, _only_local()) == code
    captured = capsys.readouterr()
    assert f"Trust and build {MY} (sha256 {_sha(mine)[:12]}...)? Type yes to accept: " in captured.out
    if code:
        assert f"{MY}: not accepted. Nothing was installed." in captured.err
        assert not place.default_dest("claude-code").exists()


def test_piped_yes_is_not_a_confirmation(mine: Path, home, monkeypatch, capsys) -> None:
    """D6: only a person at a terminal, or --trust-local, accepts local code; there is no --yes."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert _install(mine, _only_local()) == 1
    assert "custom code needs your confirmation" in capsys.readouterr().err


def test_a_pipe_is_not_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert local.interactive() is False


def test_trust_local_with_the_right_hash_installs(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    assert f"Accepted {MY} by --trust-local {MY}={_sha(mine)}" in capsys.readouterr().out


def test_trust_local_with_the_wrong_hash_refuses_even_at_a_terminal(mine: Path, home, monkeypatch, capsys) -> None:
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert _install(mine, _only_local(), f"--trust-local={MY}={'a' * 64}") == 1
    assert f"--trust-local gives sha256 {'a' * 64}, the folder hashes to {_sha(mine)}" in capsys.readouterr().err
    assert not place.default_dest("claude-code").exists()


@pytest.mark.parametrize(
    ("value", "says"),
    [
        (f"my-other={'a' * 64}", "my-other, which is not a local policy of this selection"),
        (f"{MY}=abc", "takes <id>=<64 lowercase hex sha256>"),
        (MY, "takes <id>=<64 lowercase hex sha256>"),
    ],
)
def test_a_malformed_or_unknown_trust_local_refuses(mine: Path, home, capsys, value: str, says: str) -> None:
    assert _install(mine, _only_local(), f"--trust-local={value}") == 1
    assert says in capsys.readouterr().err


def test_one_id_given_two_hashes_refuses(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local(), _trust(mine), f"--trust-local={MY}={'b' * 64}") == 1
    assert f"gives {MY} two different hashes" in capsys.readouterr().err


# --- trust on first use --------------------------------------------------------------------------


def test_the_marker_records_the_engine_and_the_accepted_hash(mine: Path, home) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    block = package.read_marker(_plugin("claude-code"))[package.MARKER_KEY]
    assert block["version"] == package.MARKER_VERSION
    assert set(block["engine"]) == {"version", "commit"}
    assert block["accepted_local"] == {MY: _sha(mine)}


def test_a_reinstall_with_the_same_hash_shows_one_line_and_does_not_ask(mine: Path, home, capsys) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    capsys.readouterr()
    assert _install(mine, _only_local()) == 0
    out = capsys.readouterr().out
    assert f"Custom policy {MY} -- {ORIGIN} -- sha256 {_sha(mine)}, 3 files, unchanged since accepted" in out
    assert f"----- {MY}/" not in out


def test_a_changed_hash_asks_again(mine: Path, home, monkeypatch, capsys) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    first = _sha(mine)
    _guard(mine).write_text(_guard(mine).read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    capsys.readouterr()
    assert _install(mine, _only_local()) == 1
    assert f"--trust-local {MY}={_sha(mine)}" in capsys.readouterr().err
    assert package.accepted(package.read_marker(_plugin("claude-code"))) == {MY: first}, "a refusal keeps the old"
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert _install(mine, _only_local()) == 0
    assert "# changed" in capsys.readouterr().out
    assert package.accepted(package.read_marker(_plugin("claude-code"))) == {MY: _sha(mine)}


def test_a_hash_accepted_for_another_bundle_or_client_does_not_carry_over(mine: Path, home) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    assert _install(mine, _only_local(client="cursor")) == 1
    assert _install(mine, _only_local(name="other")) == 1


def test_the_plugin_version_changes_with_the_local_hash(mine: Path, home) -> None:
    assert _install(mine, _only_local(), _trust(mine)) == 0
    manifest = _plugin("claude-code") / ".claude-plugin" / "plugin.json"
    before = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    assert before == f"0.1.0+{sel.digest(_only_local(), {MY: _sha(mine)})[:12]}"
    (mine / REL / "evals" / "notes.txt").write_text("more\n", encoding="utf-8")
    assert _install(mine, _only_local(), _trust(mine)) == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] != before


# --- a mixed catalog and custom bundle, every client ---------------------------------------------


def _mixed(root: Path, ref: str, client: str) -> dict:
    data = v2(root, ref, client, (GUARD_ID, GATE_ID), name="mine")
    data["policies"].insert(1, _local())
    return data


@pytest.mark.parametrize("client", CLIENTS)
def test_a_mixed_bundle_builds_for_every_client(catalog, mine: Path, home, capsys, client: str) -> None:
    assert _install(mine, _mixed(*catalog, client), _trust(mine)) == 0
    out = capsys.readouterr().out
    plugin = _plugin(client)
    assert plugin == place.default_dest(client) / TREE[client][0].replace("chock-guardrails", "mine")
    assert (plugin / "scripts" / MY / f"{MY}.py").is_file(), "the custom guard ships under its own namespace"
    members = json.loads((plugin / "scripts" / "chock_bundle.json").read_text(encoding="utf-8"))["members"]
    labels = {m["id"]: m["label"] for m in members}
    assert [m["id"] for m in members] == [GUARD_ID, MY, GATE_ID]
    assert labels[MY].startswith(f"{ORIGIN}; ")
    assert not labels[GUARD_ID].startswith(ORIGIN)
    assert not labels[GATE_ID].startswith(ORIGIN)
    skill = next(plugin.rglob("customize-guardrails/SKILL.md")).read_text(encoding="utf-8")
    assert f"| `{MY}` | {ORIGIN}; " in skill
    printed = [line for line in out.splitlines() if line.startswith(f"  {MY} ")]
    assert len(printed) == 1
    assert ORIGIN in printed[0]
    marker = package.read_marker(plugin)
    assert marker["client"] == client
    assert package.accepted(marker) == {MY: _sha(mine)}


def test_bundle_status_labels_the_custom_member(catalog, mine: Path, home, capsys) -> None:
    assert _install(mine, _mixed(*catalog, "claude-code"), _trust(mine)) == 0
    capsys.readouterr()
    assert bundle_cli.main(["status"]) == 0
    rows = [line.split(None, 2) for line in capsys.readouterr().out.splitlines() if line.strip().startswith(MY)]
    assert len(rows) == 1
    assert rows[0][2].startswith(ORIGIN)


def test_the_built_custom_guard_refuses_in_the_agent(catalog, mine: Path, tmp_path: Path, home) -> None:
    assert _install(mine, _mixed(*catalog, "claude-code"), _trust(mine)) == 0
    plugin = _plugin("claude-code")
    commands = hook_commands(json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8")))
    repo = project(tmp_path)
    assert any(denies(run_command(c, plugin, repo, DESTROY)) for c in commands)
    assert not any(denies(run_command(c, plugin, repo, PLAN)) for c in commands)


def test_a_local_id_that_the_catalog_also_lists_is_refused(catalog, mine: Path, home, capsys) -> None:
    root, _ref = catalog
    registry = root / "registry.yaml"
    registry.write_text(registry.read_text(encoding="utf-8") + f"- id: {MY}\n  path: base/{MY}\n  version: 0.0.1\n")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "--quiet", "-am", "clash")
    assert _install(mine, _mixed(root, _git(root, "rev-parse", "HEAD"), "claude-code"), _trust(mine)) == 1
    assert f"{MY}: a local policy may not reuse a catalog id" in capsys.readouterr().err
