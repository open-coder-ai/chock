"""`chock emit --managed claude_code`: a valid drop-in, honest labels, docs and wording, and nothing outside --out."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from managed_emit_helpers import (
    DEPLOY_ROOT,
    DOCS,
    DROP_IN,
    FAIL_CLOSED,
    FIXTURES,
    OVERRIDE_CLAIM,
    PERMISSION_RULE,
    POLICIES,
    PYTHON,
    ROOT,
    drop_in,
    emit,
    handlers,
    linux,
    make_repo,
    tree,
)

from chock import cli
from chock.compile.emitters import managed
from chock.compile.emitters.in_agent_hooks import TIMEOUT_SECONDS
from chock.compile.emitters.managed import claude_code
from chock.compile.levels import cap_for, level_rank


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def test_nothing_outside_out_changes(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 1: HOME and cwd in tmp; every file there but --out is byte-identical after the run."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    before = tree(tmp_path, out)
    assert linux(repo, out) == 0
    assert tree(tmp_path, out) == before
    assert sorted(p.name for p in out.iterdir()) == ["claude_code"]


def _system_out() -> Path:
    return Path(managed.CHANNELS["system_roots"][managed.host_platform()][1]) / "chock-emit-test"


def test_out_under_a_system_path_is_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance 2: no file is written and the exit is non-zero."""
    out = _system_out()
    assert emit(repo, out) == 1
    assert "resolves to or inside the system path" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege on Windows")
def test_out_through_a_symlink_into_a_system_path_is_refused(repo: Path, tmp_path: Path) -> None:
    link = tmp_path / "innocent"
    link.symlink_to(_system_out().parent)
    assert emit(repo, link) == 1
    assert not (_system_out().parent / "claude_code").exists()


def test_an_existing_vendor_folder_is_never_written_into(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "claude_code").mkdir(parents=True)
    (out / "claude_code" / "mine.txt").write_text("keep", encoding="utf-8")
    assert linux(repo, out) == 1
    assert [p.name for p in (out / "claude_code").iterdir()] == ["mine.txt"]


@pytest.mark.parametrize("root", ["relative/dir", "/has\nnewline", "/"])
def test_a_deploy_root_that_is_not_an_absolute_folder_is_refused(repo: Path, tmp_path: Path, root: str) -> None:
    assert emit(repo, tmp_path / "out", "--platform", "linux", "--deploy-root", root) == 1
    assert not (tmp_path / "out" / "claude_code").exists()


def test_a_deploy_root_with_shell_characters_is_one_argument(repo: Path, tmp_path: Path) -> None:
    """Finding 8: exec form, no shell, so quote, $ and backquote reach the client as written."""
    root = '/srv/a"b$c`d e'
    assert emit(repo, tmp_path / "out", "--platform", "linux", "--deploy-root", root) == 0
    args = [arg for _, hook in handlers(drop_in(tmp_path / "out")) for arg in hook["args"]]
    assert f"{root}/block-no-verify/scripts/claude_code.py" in args


def test_a_deploy_root_is_normalised() -> None:
    """Finding 9: deploy.json never shows a `..` target."""
    assert managed.deploy_root("/etc/claude-code/../../srv/x/", "linux") == "/srv/x"


def test_a_windows_deploy_root_is_written_with_forward_slashes() -> None:
    assert (
        managed.deploy_root("C:\\Program Files\\ClaudeCode\\chock\\", "windows") == "C:/Program Files/ClaudeCode/chock"
    )


def test_the_drop_in_follows_the_documented_schema(repo: Path, tmp_path: Path) -> None:
    """Acceptance 3: JSON object; PreToolUse handlers block on failure with chock's timeout; Stop takes no onFailure."""
    out = tmp_path / "out"
    assert linux(repo, out) == 0
    doc = drop_in(out)
    assert all(PERMISSION_RULE.match(rule) for rule in doc.get("permissions", {}).get("deny", []))
    found = handlers(doc)
    assert {event for event, _ in found} == {"PreToolUse", "Stop"}
    for event, hook in found:
        assert hook["type"] == "command"
        assert hook["timeout"] == TIMEOUT_SECONDS == 45
        assert hook.get("onFailure") == ("block" if event == "PreToolUse" else None)


def test_hooks_are_exec_form_started_by_the_given_python(repo: Path, tmp_path: Path) -> None:
    """Findings 1, 8: the command is --python itself; no git, sh, launcher or PATH lookup stands in between."""
    assert linux(repo, tmp_path / "out") == 0
    for _, hook in handlers(drop_in(tmp_path / "out")):
        assert hook["command"] == PYTHON
        assert hook["args"][:4] == ["-I", "-X", "utf8", "-c"]
        assert not [arg for arg in hook["args"] if "launch.sh" in arg or "chock.python" in arg or "git -c" in arg]
    assert not list((tmp_path / "out").rglob("launch.sh"))


@pytest.mark.parametrize("python", ["python3", "bin/python3", ""])
def test_python_must_be_an_absolute_path(repo: Path, tmp_path: Path, python: str, capsys) -> None:
    """Ruling 1: the interpreter is never taken from PATH."""
    assert emit(repo, tmp_path / "out", "--platform", "linux", python=python) == 1
    assert "must be the absolute path of the Python 3.11+ interpreter" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("missing", ["--python", "--on-failure"])
def test_python_and_on_failure_have_no_default(repo: Path, tmp_path: Path, missing: str, capsys) -> None:
    """Rulings 1, 2: the admin names both; without either the command fails and says which."""
    argv = ["emit", "--managed", "claude_code", "--out", str(tmp_path / "out"), "--repo", str(repo)]
    argv += [flag for pair in (("--python", PYTHON), ("--on-failure", "block")) if pair[0] != missing for flag in pair]
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert missing in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_on_failure_allow_emits_no_failure_key(repo: Path, tmp_path: Path) -> None:
    """Ruling 2: `allow` emits no onFailure anywhere."""
    assert linux(repo, tmp_path / "out", on_failure="allow") == 0
    assert not [hook for _, hook in handlers(drop_in(tmp_path / "out")) if "onFailure" in hook]


def test_no_matcherless_stop_check_is_emitted(repo: Path, tmp_path: Path) -> None:
    """Finding 2: every pre-tool group names its tools; the repo stop's every-tool entry is left out."""
    assert linux(repo, tmp_path / "out") == 0
    doc = drop_in(tmp_path / "out")
    assert all(group.get("matcher") for group in doc["hooks"]["PreToolUse"])
    assert not [hook for _, hook in handlers(doc) if "--stop-check" in hook["args"]]


@pytest.mark.parametrize("choice", ["block", "allow"])
def test_the_failure_consequence_is_stated_in_deploy_json_and_output(
    repo: Path, tmp_path: Path, choice: str, capsys
) -> None:
    """Ruling 2: one sentence each, naming the interpreter and the matched tools."""
    assert linux(repo, tmp_path / "out", on_failure=choice) == 0
    plan = json.loads((tmp_path / "out" / "claude_code" / "deploy.json").read_text(encoding="utf-8"))
    sentence = plan["on_failure"]["consequence"]
    assert plan["on_failure"]["choice"] == choice
    assert sentence.startswith(f"--on-failure {choice}:") and PYTHON in sentence
    assert "Bash|PowerShell, Write|Edit|MultiEdit|NotebookEdit" in sentence
    assert ("is refused" if choice == "block" else "goes ahead unchecked") in sentence
    assert sentence in capsys.readouterr().out


def test_no_managed_only_key_without_lock(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance 4: no allowManaged* key by default; --lock adds the hooks key alone, never the permission-rules one."""
    assert linux(repo, tmp_path / "plain") == 0
    assert not [key for key in drop_in(tmp_path / "plain") if key.startswith("allowManaged")]
    assert linux(repo, tmp_path / "locked", "--lock") == 0
    assert [key for key in drop_in(tmp_path / "locked") if key.startswith("allowManaged")] == ["allowManagedHooksOnly"]
    text = capsys.readouterr().out
    assert "allowManagedPermissionRulesOnly is never emitted" in text
    assert "chock's own project hooks and plugins included" in text


def test_hook_commands_name_only_the_deploy_root(repo: Path, tmp_path: Path) -> None:
    """Acceptance 5: no repo-relative path, every path argument under the deploy root and in the bundle."""
    out = tmp_path / "out"
    assert linux(repo, out) == 0
    for _, hook in handlers(drop_in(out)):
        paths = [arg for arg in hook["args"][5:] if not arg.startswith("--")]
        assert paths and all(path.startswith(f"{DEPLOY_ROOT}/") for path in paths)
        for path in paths:
            assert (out / "claude_code" / "bundle" / path.removeprefix(f"{DEPLOY_ROOT}/")).is_file(), path


@pytest.mark.parametrize("policy_id", POLICIES)
def test_drop_in_golden(repo: Path, tmp_path: Path, policy_id: str) -> None:
    """Acceptance 6: the file for one policy, byte for byte."""
    out = tmp_path / "out"
    assert linux(repo, out, "--policies", policy_id) == 0
    actual = (out / "claude_code" / DROP_IN).read_text(encoding="utf-8")
    golden = FIXTURES / f"{policy_id}.json"
    if os.environ.get("CHOCK_REGEN_GOLDENS") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")
    assert actual == golden.read_text(encoding="utf-8")


def test_labels_are_vendor_docs_unwitnessed_and_capped(repo: Path, tmp_path: Path) -> None:
    """Acceptance 7: every emitted cell rests on vendor docs, is unwitnessed, and is at most best-effort."""
    out = tmp_path / "out"
    assert linux(repo, out) == 0
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
    assert linux(repo, out, "--lock") == 0
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
    assert linux(repo, tmp_path / "out", "--policies", "yagni") == 1
    assert not (tmp_path / "out").exists()


def test_no_wording_stronger_than_the_label(repo: Path, tmp_path: Path, capsys) -> None:
    """Ruling 7 (finding 6): no fail-closed, enforced or cannot-override claim in output, help, data, docstrings or changelog."""
    assert linux(repo, tmp_path / "out", "--lock") == 0
    with pytest.raises(SystemExit):
        cli.main(["emit", "--help"])
    texts = [
        capsys.readouterr().out,
        *(p.read_text(encoding="utf-8") for p in (tmp_path / "out" / "claude_code").rglob("*.json")),
    ]
    texts += [json.dumps(managed.CHANNELS), managed.__doc__ or "", claude_code.__doc__ or ""]
    texts += [p.read_text(encoding="utf-8") for p in (ROOT / "changelog.d").glob("w2b1*.md")]
    texts += [
        p.read_text(encoding="utf-8")
        for p in (ROOT / "src" / "chock" / "compile" / "emitters" / "managed").glob("*.py")
    ]
    assert not [text for text in texts if FAIL_CLOSED.search(text) or OVERRIDE_CLAIM.search(text)]
    assert "writes no system path" not in "".join(texts)


def test_docs_say_what_the_code_does() -> None:
    """Ruling 3 (finding 3): no compiled managed-settings file, `chock emit` documented, no cannot-override claim."""
    pages = {p.name: p.read_text(encoding="utf-8") for p in DOCS.rglob("*.md")}
    assert not [name for name, text in pages.items() if "managed-setting/managed-settings.json" in text]
    assert "chock emit --managed" in pages["cli-reference.md"]
    assert not OVERRIDE_CLAIM.search(pages["compare.md"])
    assert "a user cannot override" not in pages["compare.md"].lower()
