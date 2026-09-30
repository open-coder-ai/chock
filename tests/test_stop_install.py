"""The stop fragments reach the vendor's config and the installed hook actually refuses.

Split from test_stop_surface.py, which asks what is emitted and what it is worth. This asks
the two questions a fragment on disk cannot answer for itself: does the installer find it,
and does the thing it installs block a turn that left something the policy forbids.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from chock import vendors
from chock.compile.compiler import compile_policy
from chock.gate.stop_reentry import REENTRY_CAP
from chock.hooks.in_agent_generic import FRAGMENT_SURFACES
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks, installed_policy_ids
from chock.hooks.in_agent_merged import MERGED

SECRET = "AKIA" + "1234567890ABCDEF"  # pragma: allowlist secret
POLICY_ID = "leaky"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    policy = repo / ".agents" / "policies" / POLICY_ID
    policy.mkdir(parents=True)
    manifest = {
        "id": POLICY_ID,
        "name": "Leaky",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {
                "kind": "content_regex",
                "on": ["commit", "tool_use"],
                "action": "block",
                "message": "secret-shaped string in what this turn wrote",
                "params": {"scan": "added_lines", "content_pattern": r"AKIA[0-9A-Z]{16}"},
            }
        },
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    compile_policy(policy, output_root=repo / ".chock" / "compiled", repo_root=repo)
    return repo


def _fire(repo: Path, payload: dict) -> subprocess.CompletedProcess:
    gate = repo / ".chock" / "compiled" / POLICY_ID / "stop" / "gate.json"
    return subprocess.run(
        [shutil.which("python3") or "python3", str(repo / ".chock" / "bin" / "claude_code.py"), "--gate", str(gate)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )


# --- the installer finds what the emitter wrote --------------------------------------------------


def test_every_emitted_stop_fragment_is_one_some_installer_looks_for(tmp_path: Path) -> None:
    """A fragment nothing installs is machinery that never runs. Asserted over the real globs."""
    repo = _repo(tmp_path)
    emitted = sorted(p.name for p in (repo / ".chock" / "compiled" / POLICY_ID / "stop").iterdir())
    globs = [w.fragment_glob for wiring in MERGED.values() for w in wiring.wirings]
    globs += [f"*/{surface}/{vendor}-hooks.json" for surface in FRAGMENT_SURFACES for vendor in vendors.stop_vendors()]

    unclaimed = [
        name
        for name in emitted
        if name != "gate.json" and not any(Path(f"{POLICY_ID}/stop/{name}").match(glob) for glob in globs)
    ]
    assert not unclaimed, f"emitted but never installed: {unclaimed}"


def test_installing_reports_every_stop_vendor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    installed = {vendor for vendor in WIRED_VENDORS if install_hooks(repo, vendor)}
    assert set(vendors.stop_vendors()) <= installed


def test_the_policy_reads_back_as_installed_on_every_stop_vendor(tmp_path: Path) -> None:
    """Coverage asks this question, so a fragment that writes but does not read back is a lie."""
    repo = _repo(tmp_path)
    for vendor in WIRED_VENDORS:
        install_hooks(repo, vendor)
    for vendor in vendors.stop_vendors():
        assert POLICY_ID in installed_policy_ids(repo, vendor), vendor


def test_claude_keeps_the_two_events_apart(tmp_path: Path) -> None:
    """One settings file, two keys. A turn-end hook installed as a pre-tool one would fire wrong."""
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    hooks = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]

    stop_key = vendors.stop_event("claude_code")
    pre_key = vendors.shell_gate_event("claude_code")
    assert "/stop/gate.json" in json.dumps(hooks[stop_key])
    assert "/stop/gate.json" not in json.dumps(hooks[pre_key])
    assert all("matcher" not in entry for entry in hooks[stop_key])


def test_an_entry_the_adopter_put_there_survives(tmp_path: Path) -> None:
    """chock replaces its own entries under both keys and leaves everything else as found."""
    repo = _repo(tmp_path)
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"hooks": [{"type": "command", "command": "their-own-turn-end-script"}]}
    settings.write_text(json.dumps({"hooks": {vendors.stop_event("claude_code"): [theirs]}}), encoding="utf-8")

    install_hooks(repo, "claude_code")
    install_hooks(repo, "claude_code")  # twice: the second must not stack chock's entry
    entries = json.loads(settings.read_text(encoding="utf-8"))["hooks"][vendors.stop_event("claude_code")]
    assert theirs in entries
    assert len(entries) == 2


# --- and the installed hook refuses ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["clean.py", "nested/dir/clean.py"])
def test_a_clean_turn_is_not_touched(tmp_path: Path, name: str) -> None:
    """The mandate: a control that fires on a correct change has failed, however sound the reasoning."""
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")

    result = _fire(repo, {"hook_event_name": "Stop"})
    assert result.returncode == 0
    assert "block" not in (result.stdout or "")


def test_a_turn_that_wrote_a_secret_by_any_means_is_blocked(tmp_path: Path) -> None:
    """No tool call is named here, and that is the point: the worktree is what gets read."""
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")

    decision = json.loads(_fire(repo, {"hook_event_name": "Stop"}).stdout)
    assert decision["decision"] == "block"
    assert "leak.py" in decision["reason"]


def test_a_stop_hook_that_already_fired_refuses_until_the_cap_then_warns(tmp_path: Path) -> None:
    """Refusing a turn re-enters this hook. The secret is still on disk, so the re-entry is refused
    again; the cap ends the turn with a warning rather than a loop (tests/test_stop_reentry_wire.py)."""
    repo = _repo(tmp_path)
    install_hooks(repo, "claude_code")
    (repo / "leak.py").write_text(f'aws = "{SECRET}"\n', encoding="utf-8")
    assert json.loads(_fire(repo, {"hook_event_name": "Stop"}).stdout)["decision"] == "block"
    for _ in range(REENTRY_CAP):
        assert (
            json.loads(_fire(repo, {"hook_event_name": "Stop", "stop_hook_active": True}).stdout)["decision"] == "block"
        )

    result = _fire(repo, {"hook_event_name": "Stop", "stop_hook_active": True})
    assert result.returncode == 0
    assert "still on disk" in json.loads(result.stdout)["systemMessage"]
