"""`sync` wires in-agent hooks for the agents the repo names, not for every vendor chock knows."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import baseline_policy, init_repo

from chock.hooks.in_agent_install import WIRED_VENDORS
from chock.hooks.launch import LAUNCHER_REL
from chock.scaffold.recompile import recompile, wired_vendors
from chock.vendors import CHOCK_AGENT


def _repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    shutil.copytree(
        baseline_policy("block-destructive-commands"), repo / ".agents" / "policies" / "block-destructive-commands"
    )
    return repo


def test_every_wired_vendor_is_chosen_when_every_agent_is() -> None:
    assert wired_vendors(sorted(CHOCK_AGENT)) == WIRED_VENDORS


def test_one_agent_chooses_one_vendor() -> None:
    assert wired_vendors(["claude"]) == ("claude_code",)
    assert wired_vendors(["cursor", "claude"]) == tuple(v for v in WIRED_VENDORS if v in {"claude_code", "cursor"})


def test_a_claude_only_repo_gets_no_other_vendors_config(tmp_path: Path) -> None:
    """`chock init --agents claude` followed by `sync` used to write ten vendors' hook files."""
    repo = _repo(tmp_path)
    recompile(repo, ["claude"], skip_hooks=False)

    assert (repo / ".claude" / "settings.json").exists()
    assert (repo / ".chock" / "bin" / "claude_code.py").exists()
    for stray in (".cursor", ".codex", ".windsurf", ".devin", ".gemini", ".github/hooks", ".agents/hooks.json"):
        assert not (repo / stray).exists(), stray
    runtimes = sorted(p.name for p in (repo / ".chock" / "bin").iterdir() if p.name not in {"gate.py", "launch.sh"})
    assert runtimes == ["claude_code.py"], "no other vendor's runtime is vendored either"
    assert (repo / LAUNCHER_REL).is_file(), "the launcher every hook command runs"


def test_a_cursor_only_repo_gets_no_claude_settings(tmp_path: Path) -> None:
    """The SessionStart arm hook lives in .claude/settings.json; it is only wired for a repo that names claude."""
    repo = _repo(tmp_path)
    recompile(repo, ["cursor"], skip_hooks=False)

    assert (repo / ".cursor" / "hooks.json").exists()
    assert not (repo / ".claude" / "settings.json").exists()


def test_a_vendor_dropped_from_supported_agents_has_its_runtime_pruned(tmp_path: Path) -> None:
    """A vendor's `.chock/bin/<vendor>.py` outlives it leaving `supported_agents` otherwise:

    nothing rewrites it once it is unwired, so it drifts against every future render forever.
    """
    repo = _repo(tmp_path)
    recompile(repo, ["claude", "cursor"], skip_hooks=False)
    assert (repo / ".chock" / "bin" / "cursor.py").exists()

    recompile(repo, ["claude"], skip_hooks=False)

    assert not (repo / ".chock" / "bin" / "cursor.py").exists()
    assert (repo / ".chock" / "bin" / "claude_code.py").exists()


def test_dropping_a_vendor_removes_its_hook_config_entries_too(tmp_path: Path) -> None:
    """#151: 0.9.1 pruned `.chock/bin/cursor.py` but left `.cursor/hooks.json` naming it.

    A repo synced on 0.9.0 wired every vendor chock knew; narrowing `supported_agents` on
    0.9.1 deleted the runtime but never touched the vendor's own hook config, so every tool
    call in that client ran a hook whose command failed before the gate ran.
    """
    repo = _repo(tmp_path)
    recompile(repo, sorted(CHOCK_AGENT), skip_hooks=False)
    cursor_hooks = repo / ".cursor" / "hooks.json"
    assert cursor_hooks.exists()
    assert ".chock/bin/cursor.py" in cursor_hooks.read_text(encoding="utf-8")

    recompile(repo, ["claude"], skip_hooks=False)

    assert not (repo / ".chock" / "bin" / "cursor.py").exists()
    assert not cursor_hooks.exists() or ".chock/bin/cursor.py" not in cursor_hooks.read_text(encoding="utf-8")


def test_a_repo_already_broken_by_0_9_1_self_heals_on_the_next_sync(tmp_path: Path) -> None:
    """A repo that hit #151 under 0.9.1 already lost the runtime -- only the stale config
    entry is left to find it by. The next `sync` must still clean it up, not just repos that
    still have the runtime lying around when they narrow `supported_agents`.
    """
    repo = _repo(tmp_path)
    recompile(repo, sorted(CHOCK_AGENT), skip_hooks=False)
    cursor_hooks = repo / ".cursor" / "hooks.json"
    assert cursor_hooks.exists()

    (repo / ".chock" / "bin" / "cursor.py").unlink()  # simulate 0.9.1's buggy prune

    recompile(repo, ["claude"], skip_hooks=False)

    assert not cursor_hooks.exists() or ".chock/bin/cursor.py" not in cursor_hooks.read_text(encoding="utf-8")


def test_a_vendor_that_cannot_be_wired_fails_sync_after_wiring_the_rest(tmp_path: Path) -> None:
    """A warning scrolled past was the only sign a vendor's gate was not installed at all."""
    import json

    import pytest

    from chock.scaffold.recompile import HookWiringError

    repo = _repo(tmp_path)
    (repo / ".cursor").mkdir()
    (repo / ".cursor" / "hooks.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(HookWiringError, match="cursor"):
        recompile(repo, ["claude", "cursor"], skip_hooks=False)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"], "the vendor that could be wired still was"
    assert (repo / ".cursor" / "hooks.json").read_text(encoding="utf-8") == "{ not json", (
        "a foreign file is never clobbered"
    )
