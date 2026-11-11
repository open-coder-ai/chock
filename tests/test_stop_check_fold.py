"""PERF-1c: the stop check folded into the catch-all multi entry, checked once before any member; else left standalone."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy, init_repo
from decision_log_support import hook_env
from runtime_support import load_runtime, write_runtime

from chock import stop as chock_stop
from chock import vendors
from chock.hooks import multi_wiring, stop_check
from chock.hooks.in_agent_install import WIRED_VENDORS, install_hooks
from chock.hooks.multi_wiring import INDEX_SHA_FLAG, MULTI_FLAG
from chock.hooks.stop_check import STOP_CHECK_FLAG
from chock.scaffold.recompile import recompile

#: `chock stop` writes its machine registry entry under this test's own home, never the real one.
pytestmark = pytest.mark.usefixtures("private_home")

#: No documented timeout, so nothing folds there and its stop check stays standalone (PERF-1).
UNBOUNDED = ("windsurf",)
FOLDED = tuple(v for v in WIRED_VENDORS if v not in UNBOUNDED)
#: Vendors whose pre-tool entries carry a matcher: a shell-only selection leaves them no catch-all entry.
MATCHING = ("claude_code", "cursor", "codex_cli", "gemini_cli", "factory_droid", "goose", "openhands", "mistral_vibe")
GUARD = (
    "import pathlib, sys\n"
    "pathlib.Path({marker!r}).write_text('ran', encoding='utf-8')\n"
    "if 'danger' in sys.argv[1:]:\n"
    "    print('refused by the member')\n"
    "    sys.exit(1)\n"
)


def _wired(root: Path, policies: tuple[str, ...]) -> Path:
    for policy in policies:
        shutil.copytree(baseline_policy(policy), root / ".agents" / "policies" / policy)
    recompile(root, ["claude"])
    for vendor in WIRED_VENDORS:
        install_hooks(root, vendor)
    return root


@pytest.fixture(scope="module")
def catch_all(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """token-efficiency (no matcher) beside a shell guard: every vendor has a catch-all multi entry."""
    return _wired(tmp_path_factory.mktemp("catch-all"), ("token-efficiency", "block-destructive-commands"))


@pytest.fixture(scope="module")
def shell_only(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One shell guard: where the vendor has matchers, no entry matches every tool."""
    return _wired(tmp_path_factory.mktemp("shell-only"), ("block-destructive-commands",))


def _text(root: Path, vendor: str) -> str:
    path = root / (".github/hooks/chock.json" if vendor == "vscode_copilot" else vendors.config_path(vendor))
    return path.read_text(encoding="utf-8")


def _stop_lines(root: Path, vendor: str) -> list[str]:
    return [line for line in _text(root, vendor).splitlines() if STOP_CHECK_FLAG in line]


@pytest.mark.parametrize("vendor", FOLDED)
def test_the_stop_check_rides_the_catch_all_multi_entry(catch_all: Path, vendor: str) -> None:
    lines = _stop_lines(catch_all, vendor)
    assert lines, f"{vendor}: no stop check at all"
    assert all(MULTI_FLAG in line and INDEX_SHA_FLAG in line for line in lines), (vendor, lines)
    assert stop_check.command(vendor) not in _text(catch_all, vendor).replace('\\"', '"'), "a standalone one is left"


@pytest.mark.parametrize("vendor", UNBOUNDED)
def test_a_vendor_that_folds_nothing_keeps_its_standalone_stop_check(catch_all: Path, vendor: str) -> None:
    lines = _stop_lines(catch_all, vendor)
    assert lines and not any(MULTI_FLAG in line for line in lines), lines


@pytest.mark.parametrize("vendor", MATCHING)
def test_an_event_with_no_catch_all_entry_keeps_its_standalone_stop_check(shell_only: Path, vendor: str) -> None:
    lines = _stop_lines(shell_only, vendor)
    assert lines and not any(MULTI_FLAG in line for line in lines), (vendor, lines)


def test_the_claude_shape_folded_and_unfolded(catch_all: Path, shell_only: Path) -> None:
    def matcherless(root: Path) -> list[str]:
        entries = json.loads(_text(root, "claude_code"))["hooks"]["PreToolUse"]
        return [h["command"] for e in entries if "matcher" not in e for h in e["hooks"]]

    [folded] = matcherless(catch_all)
    assert folded.endswith(f" {STOP_CHECK_FLAG}") and f".chock/bin/claude_code.py {MULTI_FLAG} " in folded
    assert matcherless(shell_only) == [stop_check.command("claude_code")]


def test_a_stop_check_with_another_shape_is_never_folded() -> None:
    carrier = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x/r.py --guard g.py", "timeout": 45}]}
    stop = {"hooks": [{"type": "command", "command": f"x/r.py {STOP_CHECK_FLAG}", "timeout": 45}]}
    group = multi_wiring._Group()
    group.carriers.append(
        multi_wiring.Carrier(carrier, "x/r.py --guard g.py", ["--guard", "g.py"], "x/r.py", False, {})
    )
    assert multi_wiring._fold_stop([group, stop], lambda _e: True) == [group, stop]
    assert not group.stop
    del carrier["matcher"]
    assert multi_wiring._fold_stop([group, stop], lambda _e: True) == [group]
    assert group.stop


def test_a_folded_multi_entry_is_never_stripped_as_a_stop_check() -> None:
    folded = {
        "hooks": [{"type": "command", "command": f"r.py {MULTI_FLAG} i.json {INDEX_SHA_FLAG} 00 {STOP_CHECK_FLAG}"}]
    }
    alone = {"hooks": [{"type": "command", "command": f"r.py {STOP_CHECK_FLAG}"}]}
    assert stop_check.without({"PreToolUse": [folded, alone]}) == {"PreToolUse": [folded]}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def folded(tmp_path: Path) -> tuple[Path, list[str], Path]:
    """(repo, the folded command's argv, the file its one member writes when it runs)."""
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    write_runtime(repo / ".chock" / "bin" / "claude_code.py", "claude_code")
    marker = tmp_path / "member-ran"
    guard = repo / "guards" / "g.py"
    guard.parent.mkdir()
    guard.write_text(GUARD.format(marker=str(marker)), encoding="utf-8")
    index = repo / "index.json"
    members = [{"argv": ["--guard", "guards/g.py"], "timeout": 30, "files": {"guards/g.py": _sha(guard)}}]
    index.write_text(json.dumps({"members": members}), encoding="utf-8")
    argv = [".chock/bin/claude_code.py", MULTI_FLAG, "index.json", INDEX_SHA_FLAG, _sha(index), STOP_CHECK_FLAG]
    return repo, argv, marker


def _run(repo: Path, argv: list[str], command: str) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    payload.update(cwd=str(repo), session_id="s", tool_use_id="t")
    return subprocess.run(
        [sys.executable, *argv],
        cwd=repo,
        env=hook_env(repo.parent),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_with_a_stop_the_folded_entry_denies_before_any_member_runs(folded) -> None:
    repo, argv, marker = folded
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "fold test"]) == 0
    done = _run(repo, argv, "echo danger")
    alone = _run(repo, [argv[0], STOP_CHECK_FLAG], "echo danger")
    assert '"permissionDecision": "deny"' in done.stdout and "fold test" in done.stdout, done
    assert (done.returncode, done.stdout) == (alone.returncode, alone.stdout), "not what the standalone check says"
    assert not marker.exists(), "a member ran while stopped"
    (repo / "guards" / "g.py").write_text("tampered\n", encoding="utf-8")
    assert _run(repo, argv, "echo hi").stdout == done.stdout, "the stop is checked before the index is even read"


def test_with_no_stop_the_members_run_as_before(folded) -> None:
    repo, argv, marker = folded
    clean = _run(repo, argv, "echo hi")
    assert clean.returncode == 0 and "deny" not in clean.stdout, clean
    assert marker.exists(), "the member never ran"
    refused = _run(repo, argv, "echo danger")
    assert "refused by the member" in refused.stdout, refused
    assert refused.stdout == _run(repo, argv[:-1], "echo danger").stdout, "the fold changed a member's verdict"


@pytest.mark.parametrize("fault", ["stop_check", "runtime"])
def test_a_fault_in_the_stop_check_refuses(folded, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    repo, argv, marker = folded
    namespace = load_runtime(repo / ".chock" / "bin", "claude_code")

    def broken(_event: object) -> None:
        raise RuntimeError("stop check broke")

    if fault == "stop_check":
        namespace["repo_stop_refusal"] = broken
    else:
        namespace["_CHOCK_RUNTIME_FAULT"] = "the shared runtime does not match its pin"
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", argv)
    event = namespace["Event"]("claude_code", "pre_tool", tool="Bash", command="echo hi", cwd=str(repo), raw={})
    decision = namespace["handle"](event)
    assert decision is not None and decision.outcome == "deny", decision
    assert ("stop check broke" if fault == "stop_check" else "does not match its pin") in decision.reason
    assert not marker.exists(), "a member ran after the stop check failed"


def test_a_stopped_unreadable_call_is_refused_even_when_no_member_would_refuse_it(folded) -> None:
    repo, argv, _marker = folded
    advisory = repo / "tc.json"
    advisory.write_text(json.dumps({"action": "warn"}), encoding="utf-8")
    index = repo / "warn-index.json"
    index.write_text(
        json.dumps(
            {"members": [{"argv": ["--tool-call", "tc.json"], "timeout": 30, "files": {"tc.json": _sha(advisory)}}]}
        ),
        encoding="utf-8",
    )
    warn_argv = [argv[0], MULTI_FLAG, "warn-index.json", INDEX_SHA_FLAG, _sha(index), STOP_CHECK_FLAG]

    def unreadable() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *warn_argv],
            cwd=repo,
            env=hook_env(repo.parent),
            input="not json",
            capture_output=True,
            text=True,
            check=False,
        )

    allowed = unreadable()
    assert allowed.returncode == 0 and "deny" not in allowed.stdout, "an advisory member alone lets it through"
    assert chock_stop.stop_main(["--repo", str(repo), "--reason", "fold test"]) == 0
    refused = unreadable()
    assert refused.returncode == 2 or '"permissionDecision": "deny"' in refused.stdout, refused
