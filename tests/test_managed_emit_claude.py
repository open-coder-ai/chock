"""`chock emit --managed claude_code`: a valid drop-in, a self-contained bundle, honest labels, and nothing outside --out."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock import cli
from chock.compile.emitters import managed
from chock.compile.emitters.in_agent_hooks import TIMEOUT_SECONDS
from chock.compile.levels import cap_for, level_rank
from chock.doctor.payloads import payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "managed_emit"
POLICIES = ("block-no-verify", "scan-secrets")
DEPLOY_ROOT = "/srv/chock-managed"
DROP_IN = Path("managed-settings.d") / "50-chock.json"
PERMISSION_RULE = re.compile(r"^[A-Za-z]+\(.*\)$")
OVERRIDE_CLAIM = re.compile(r"(cannot|can't|can not|unable to) (be )?overrid", re.IGNORECASE)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository holding the two golden policies and one advisory policy with nothing to run."""
    root = tmp_path / "repo"
    for policy_id in (*POLICIES, "yagni"):
        shutil.copytree(baseline_policy(policy_id), root / ".agents" / "policies" / policy_id)
    return root


def _emit(repo: Path, out: Path, *extra: str) -> int:
    return cli.main(["emit", "--managed", "claude_code", "--out", str(out), "--repo", str(repo), *extra])


def _linux(repo: Path, out: Path, *extra: str) -> int:
    return _emit(repo, out, "--platform", "linux", "--deploy-root", DEPLOY_ROOT, *extra)


def _drop_in(out: Path) -> dict:
    return json.loads((out / "claude_code" / DROP_IN).read_text(encoding="utf-8"))


def _handlers(doc: dict) -> list[tuple[str, dict]]:
    return [(event, hook) for event, groups in doc["hooks"].items() for group in groups for hook in group["hooks"]]


def _tree(root: Path, skip: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and skip not in p.parents and "__pycache__" not in p.parts
    }


def test_nothing_outside_out_changes(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 1: HOME and cwd in tmp; every file there but --out is byte-identical after the run."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    before = _tree(tmp_path, out)
    assert _linux(repo, out) == 0
    assert _tree(tmp_path, out) == before
    assert sorted(p.name for p in out.iterdir()) == ["claude_code"]


def _system_out() -> Path:
    return Path(managed.CHANNELS["system_roots"][managed.host_platform()][0]) / "chock-emit-test"


def test_out_under_a_system_path_is_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance 2: no file is written and the exit is non-zero."""
    out = _system_out()
    assert _emit(repo, out) == 1
    assert "resolves inside the system path" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege on Windows")
def test_out_through_a_symlink_into_a_system_path_is_refused(repo: Path, tmp_path: Path) -> None:
    link = tmp_path / "innocent"
    link.symlink_to(_system_out().parent)
    assert _emit(repo, link) == 1
    assert not (_system_out().parent / "claude_code").exists()


def test_an_existing_vendor_folder_is_never_written_into(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "claude_code").mkdir(parents=True)
    (out / "claude_code" / "mine.txt").write_text("keep", encoding="utf-8")
    assert _linux(repo, out) == 1
    assert [p.name for p in (out / "claude_code").iterdir()] == ["mine.txt"]


@pytest.mark.parametrize("root", ["relative/dir", '/has"quote', "/has$dollar", "/has`tick"])
def test_a_deploy_root_a_shell_would_read_is_refused(repo: Path, tmp_path: Path, root: str) -> None:
    assert _emit(repo, tmp_path / "out", "--platform", "linux", "--deploy-root", root) == 1
    assert not (tmp_path / "out" / "claude_code").exists()


def test_a_windows_deploy_root_is_written_with_forward_slashes() -> None:
    assert (
        managed.deploy_root("C:\\Program Files\\ClaudeCode\\chock\\", "windows") == "C:/Program Files/ClaudeCode/chock"
    )


def test_the_drop_in_follows_the_documented_schema(repo: Path, tmp_path: Path) -> None:
    """Acceptance 3: JSON object; PreToolUse handlers block on failure with chock's timeout; Stop takes no onFailure."""
    out = tmp_path / "out"
    assert _linux(repo, out) == 0
    doc = _drop_in(out)
    assert all(PERMISSION_RULE.match(rule) for rule in doc.get("permissions", {}).get("deny", []))
    handlers = _handlers(doc)
    assert {event for event, _ in handlers} == {"PreToolUse", "Stop"}
    for event, hook in handlers:
        assert hook["type"] == "command"
        assert hook["timeout"] == TIMEOUT_SECONDS == 45
        assert hook.get("onFailure") == ("block" if event == "PreToolUse" else None)
    assert sum(" --stop-check" in hook["command"] for _, hook in handlers) == 1


def test_no_managed_only_key_without_lock(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance 4: no allowManaged* key by default; --lock adds the hooks key alone, never the permission-rules one."""
    assert _linux(repo, tmp_path / "plain") == 0
    assert not [key for key in _drop_in(tmp_path / "plain") if key.startswith("allowManaged")]
    assert _linux(repo, tmp_path / "locked", "--lock") == 0
    assert [key for key in _drop_in(tmp_path / "locked") if key.startswith("allowManaged")] == ["allowManagedHooksOnly"]
    text = capsys.readouterr().out
    assert "allowManagedPermissionRulesOnly is never emitted" in text
    assert "chock's own project hooks and plugins included" in text


def test_hook_commands_name_only_the_deploy_root(repo: Path, tmp_path: Path) -> None:
    """Acceptance 5: no repo-relative path, no project launcher prefix, every path under the deploy root."""
    out = tmp_path / "out"
    assert _linux(repo, out) == 0
    for _, hook in _handlers(_drop_in(out)):
        command = hook["command"]
        assert ".chock/bin" not in command and "launch.sh ||" not in command
        paths = re.findall(r'"([^"]+)"', command)
        assert paths and all(path.startswith(f"{DEPLOY_ROOT}/") for path in paths)
        for path in paths:
            assert (out / "claude_code" / "bundle" / path.removeprefix(f"{DEPLOY_ROOT}/")).is_file(), path


@pytest.mark.parametrize("policy_id", POLICIES)
def test_drop_in_golden(repo: Path, tmp_path: Path, policy_id: str) -> None:
    """Acceptance 6: the file for one policy, byte for byte."""
    out = tmp_path / "out"
    assert _linux(repo, out, "--policies", policy_id) == 0
    actual = (out / "claude_code" / DROP_IN).read_text(encoding="utf-8")
    golden = FIXTURES / f"{policy_id}.json"
    if os.environ.get("CHOCK_REGEN_GOLDENS") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")
    assert actual == golden.read_text(encoding="utf-8")


def test_labels_are_vendor_docs_unwitnessed_and_capped(repo: Path, tmp_path: Path) -> None:
    """Acceptance 7: every emitted cell rests on vendor docs, is unwitnessed, and is at most best-effort."""
    out = tmp_path / "out"
    assert _linux(repo, out) == 0
    labels = json.loads((out / "claude_code" / "labels.json").read_text(encoding="utf-8"))
    assert [row["policy"] for row in labels] == list(POLICIES)
    for row in labels:
        assert row["basis"] == "vendor-docs" and row["witnessed"] is False
        assert level_rank(row["level"]) <= level_rank(cap_for("vendor-docs")) == level_rank("best-effort")
        assert row["label"] == f"{row['level']} (vendor-docs)"
    assert {row["policy"]: row["halves"] for row in labels} == {"block-no-verify": ["guard"], "scan-secrets": ["gate"]}


def test_nothing_written_or_printed_claims_users_cannot_override(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert _linux(repo, out, "--lock") == 0
    texts = [capsys.readouterr().out, *(p.read_text(encoding="utf-8") for p in (out / "claude_code").glob("*.json"))]
    texts.append((out / "claude_code" / DROP_IN).read_text(encoding="utf-8"))
    texts.append(json.dumps(managed.CHANNELS))
    assert not [text for text in texts if OVERRIDE_CLAIM.search(text)]
    plan = json.loads((out / "claude_code" / "deploy.json").read_text(encoding="utf-8"))
    assert plan["deployed"] is False and plan["basis"] == "vendor-docs"
    assert any("local administrator can edit or delete" in caveat for caveat in plan["caveats"])
    assert plan["place"][0]["to"] == "/etc/claude-code/managed-settings.d/50-chock.json"
    assert plan["undo"] == [f"delete {step['to']}" for step in plan["place"]]


def test_a_selection_with_nothing_to_run_writes_nothing(repo: Path, tmp_path: Path) -> None:
    assert _linux(repo, tmp_path / "out", "--policies", "yagni") == 1
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(
    not (shutil.which("git") and shutil.which("sh")), reason="the hook needs git and sh, as on a client"
)
def test_the_bundle_runs_on_its_own(repo: Path, tmp_path: Path) -> None:
    """The emitted command, rooted at the bundle itself, refuses the canary and allows a harmless call."""
    out = tmp_path / "out"
    bundle = (out / "claude_code" / "bundle").as_posix()
    assert _emit(repo, out, "--policies", "block-no-verify", "--deploy-root", bundle) == 0
    [(_, hook), *_] = _handlers(_drop_in(out))
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT")}
    (tmp_path / "home").mkdir()
    env["HOME"] = env["USERPROFILE"] = str(tmp_path / "home")

    def answer(command: str) -> str:
        done = subprocess.run(
            hook["command"],
            shell=True,
            input=json.dumps(payload("claude_code", command, tmp_path.as_posix())),
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            check=False,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    assert '"permissionDecision": "deny"' in answer("git commit --no-verify -m x")
    assert "deny" not in answer("git status")
