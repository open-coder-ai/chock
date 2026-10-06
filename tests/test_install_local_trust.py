"""`chock install` with `from: local` entries: show and confirm, --trust-local, and trust on first use."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import local_fixtures
import pytest
from local_fixtures import MY, ORIGIN, REL, guard, install, needs_git, only_local, plugin, sha, trust

from chock.install import local, package, place
from chock.install import selection as sel

pytestmark = needs_git
#: The shared fixtures, by the names the tests ask for.
catalog, home, mine = local_fixtures.catalog, local_fixtures.home, local_fixtures.mine


# --- show and confirm ----------------------------------------------------------------------------


def test_every_file_is_shown_with_its_id_hash_and_label(mine: Path, home, capsys) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    out = capsys.readouterr().out
    assert f"Custom policy {MY} -- {ORIGIN} -- from {(mine / REL).resolve()}" in out
    assert f"sha256 {sha(mine)}" in out
    for rel in ("manifest.yaml", "evals/suite.yaml", f"implementations/{MY}.py"):
        assert f"----- {MY}/{rel} (" in out
    assert guard(mine).read_text(encoding="utf-8") in out
    assert out.index(f"----- end of {MY} -----") < out.index("Built mine")


def test_control_characters_are_shown_escaped(mine: Path, home, capsys) -> None:
    guard(mine).write_text(guard(mine).read_text(encoding="utf-8") + "# \x1b[2J \x07\n", encoding="utf-8")
    assert install(mine, only_local(), trust(mine)) == 0
    out = capsys.readouterr().out
    assert "# \\u001b[2J \\u0007" in out
    assert "\x1b" not in out
    assert "\x07" not in out


def test_without_a_terminal_or_trust_local_it_refuses_and_names_the_hash(mine: Path, home, capsys) -> None:
    assert install(mine, only_local()) == 1
    captured = capsys.readouterr()
    assert f"--trust-local {MY}={sha(mine)}" in captured.err
    assert f"----- {MY}/implementations/{MY}.py" in captured.out
    assert not place.default_dest("claude-code").exists()


@pytest.mark.parametrize(("answer", "code"), [("yes\n", 0), ("YES\n", 0), ("no\n", 1), ("y\n", 1), ("", 1)])
def test_the_interactive_confirmation_reads_stdin(
    mine: Path, home, monkeypatch, capsys, answer: str, code: int
) -> None:
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO(answer))
    assert install(mine, only_local()) == code
    captured = capsys.readouterr()
    assert f"Trust and build {MY} (sha256 {sha(mine)[:12]}...)? Type yes to accept: " in captured.out
    if code:
        assert f"{MY}: not accepted. Nothing was installed." in captured.err
        assert not place.default_dest("claude-code").exists()


def test_piped_yes_is_not_a_confirmation(mine: Path, home, monkeypatch, capsys) -> None:
    """D6: only a person at a terminal, or --trust-local, accepts local code; there is no --yes."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert install(mine, only_local()) == 1
    assert "custom code needs your confirmation" in capsys.readouterr().err


def test_a_pipe_is_not_a_terminal(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert local.interactive() is False


def test_trust_local_with_the_right_hash_installs(mine: Path, home, capsys) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    assert f"Accepted {MY} by --trust-local {MY}={sha(mine)}" in capsys.readouterr().out


def test_trust_local_with_the_wrong_hash_refuses_even_at_a_terminal(mine: Path, home, monkeypatch, capsys) -> None:
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert install(mine, only_local(), f"--trust-local={MY}={'a' * 64}") == 1
    assert f"--trust-local gives sha256 {'a' * 64}, the folder hashes to {sha(mine)}" in capsys.readouterr().err
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
    assert install(mine, only_local(), f"--trust-local={value}") == 1
    assert says in capsys.readouterr().err


def test_one_id_given_two_hashes_refuses(mine: Path, home, capsys) -> None:
    assert install(mine, only_local(), trust(mine), f"--trust-local={MY}={'b' * 64}") == 1
    assert f"gives {MY} two different hashes" in capsys.readouterr().err


# --- trust on first use --------------------------------------------------------------------------


def test_the_marker_records_the_engine_and_the_accepted_hash(mine: Path, home) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    block = package.read_marker(plugin("claude-code"))[package.MARKER_KEY]
    assert block["version"] == package.MARKER_VERSION
    assert set(block["engine"]) == {"version", "commit"}
    assert block["accepted_local"] == {MY: sha(mine)}


def test_a_reinstall_with_the_same_hash_shows_one_line_and_does_not_ask(mine: Path, home, capsys) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    capsys.readouterr()
    assert install(mine, only_local()) == 0
    out = capsys.readouterr().out
    assert f"Custom policy {MY} -- {ORIGIN} -- sha256 {sha(mine)}, 3 files, unchanged since accepted" in out
    assert f"----- {MY}/" not in out


def test_a_changed_hash_asks_again(mine: Path, home, monkeypatch, capsys) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    first = sha(mine)
    guard(mine).write_text(guard(mine).read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    capsys.readouterr()
    assert install(mine, only_local()) == 1
    assert f"--trust-local {MY}={sha(mine)}" in capsys.readouterr().err
    assert package.accepted(package.read_marker(plugin("claude-code"))) == {MY: first}, "a refusal keeps the old"
    monkeypatch.setattr(local, "interactive", lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))
    assert install(mine, only_local()) == 0
    assert "# changed" in capsys.readouterr().out
    assert package.accepted(package.read_marker(plugin("claude-code"))) == {MY: sha(mine)}


def test_a_hash_accepted_for_another_bundle_or_client_does_not_carry_over(mine: Path, home) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    assert install(mine, only_local(client="cursor")) == 1
    assert install(mine, only_local(name="other")) == 1


def test_the_plugin_version_changes_with_the_local_hash(mine: Path, home) -> None:
    assert install(mine, only_local(), trust(mine)) == 0
    manifest = plugin("claude-code") / ".claude-plugin" / "plugin.json"
    before = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    assert before == f"0.1.0+{sel.digest(only_local(), {MY: sha(mine)})[:12]}"
    (mine / REL / "evals" / "notes.txt").write_text("more\n", encoding="utf-8")
    assert install(mine, only_local(), trust(mine)) == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] != before
