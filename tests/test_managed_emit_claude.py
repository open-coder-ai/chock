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
from chock.compile.emitters.managed import claude_code
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


PYTHON = "/usr/bin/python3"
ROOT = Path(__file__).resolve().parents[1]
FAIL_CLOSED = re.compile(r"fail(s|ing|ed)?[- ]closed|cannot be (bypassed|disabled)|\benforced\b", re.IGNORECASE)


def _emit(repo: Path, out: Path, *extra: str, python: str = PYTHON, on_failure: str = "block") -> int:
    return cli.main(
        [
            "emit",
            "--managed",
            "claude_code",
            "--out",
            str(out),
            "--repo",
            str(repo),
            "--python",
            python,
            "--on-failure",
            on_failure,
            *extra,
        ]
    )


def _linux(repo: Path, out: Path, *extra: str, on_failure: str = "block") -> int:
    return _emit(repo, out, "--platform", "linux", "--deploy-root", DEPLOY_ROOT, *extra, on_failure=on_failure)


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
    return Path(managed.CHANNELS["system_roots"][managed.host_platform()][1]) / "chock-emit-test"


def test_out_under_a_system_path_is_refused(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance 2: no file is written and the exit is non-zero."""
    out = _system_out()
    assert _emit(repo, out) == 1
    assert "resolves to or inside the system path" in capsys.readouterr().err
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


@pytest.mark.parametrize("root", ["relative/dir", "/has\nnewline", "/"])
def test_a_deploy_root_that_is_not_an_absolute_folder_is_refused(repo: Path, tmp_path: Path, root: str) -> None:
    assert _emit(repo, tmp_path / "out", "--platform", "linux", "--deploy-root", root) == 1
    assert not (tmp_path / "out" / "claude_code").exists()


def test_a_deploy_root_with_shell_characters_is_one_argument(repo: Path, tmp_path: Path) -> None:
    """Finding 8: exec form, no shell, so quote, $ and backquote reach the client as written."""
    root = '/srv/a"b$c`d e'
    assert _emit(repo, tmp_path / "out", "--platform", "linux", "--deploy-root", root) == 0
    args = [arg for _, hook in _handlers(_drop_in(tmp_path / "out")) for arg in hook["args"]]
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
    assert _linux(repo, out) == 0
    doc = _drop_in(out)
    assert all(PERMISSION_RULE.match(rule) for rule in doc.get("permissions", {}).get("deny", []))
    handlers = _handlers(doc)
    assert {event for event, _ in handlers} == {"PreToolUse", "Stop"}
    for event, hook in handlers:
        assert hook["type"] == "command"
        assert hook["timeout"] == TIMEOUT_SECONDS == 45
        assert hook.get("onFailure") == ("block" if event == "PreToolUse" else None)


def test_hooks_are_exec_form_started_by_the_given_python(repo: Path, tmp_path: Path) -> None:
    """Findings 1, 8: the command is --python itself; no git, sh, launcher or PATH lookup stands in between."""
    assert _linux(repo, tmp_path / "out") == 0
    for _, hook in _handlers(_drop_in(tmp_path / "out")):
        assert hook["command"] == PYTHON
        assert hook["args"][:4] == ["-I", "-X", "utf8", "-c"]
        assert not [arg for arg in hook["args"] if "launch.sh" in arg or "chock.python" in arg or "git -c" in arg]
    assert not list((tmp_path / "out").rglob("launch.sh"))


@pytest.mark.parametrize("python", ["python3", "bin/python3", ""])
def test_python_must_be_an_absolute_path(repo: Path, tmp_path: Path, python: str, capsys) -> None:
    """Ruling 1: the interpreter is never taken from PATH."""
    assert _emit(repo, tmp_path / "out", "--platform", "linux", python=python) == 1
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
    assert _linux(repo, tmp_path / "out", on_failure="allow") == 0
    assert not [hook for _, hook in _handlers(_drop_in(tmp_path / "out")) if "onFailure" in hook]


def test_no_matcherless_stop_check_is_emitted(repo: Path, tmp_path: Path) -> None:
    """Finding 2: every pre-tool group names its tools; the repo stop's every-tool entry is left out."""
    assert _linux(repo, tmp_path / "out") == 0
    doc = _drop_in(tmp_path / "out")
    assert all(group.get("matcher") for group in doc["hooks"]["PreToolUse"])
    assert not [hook for _, hook in _handlers(doc) if "--stop-check" in hook["args"]]


@pytest.mark.parametrize("choice", ["block", "allow"])
def test_the_failure_consequence_is_stated_in_deploy_json_and_output(
    repo: Path, tmp_path: Path, choice: str, capsys
) -> None:
    """Ruling 2: one sentence each, naming the interpreter and the matched tools."""
    assert _linux(repo, tmp_path / "out", on_failure=choice) == 0
    plan = json.loads((tmp_path / "out" / "claude_code" / "deploy.json").read_text(encoding="utf-8"))
    sentence = plan["on_failure"]["consequence"]
    assert plan["on_failure"]["choice"] == choice
    assert sentence.startswith(f"--on-failure {choice}:") and PYTHON in sentence
    assert "Bash|PowerShell, Write|Edit|MultiEdit|NotebookEdit" in sentence
    assert ("is refused" if choice == "block" else "goes ahead unchecked") in sentence
    assert sentence in capsys.readouterr().out


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
    """Acceptance 5: no repo-relative path, every path argument under the deploy root and in the bundle."""
    out = tmp_path / "out"
    assert _linux(repo, out) == 0
    for _, hook in _handlers(_drop_in(out)):
        paths = [arg for arg in hook["args"][5:] if not arg.startswith("--")]
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


def _bundle_hook(repo: Path, tmp_path: Path, on_failure: str = "block") -> tuple[Path, dict]:
    """The block-no-verify guard's handler, emitted with this test's Python and rooted at the bundle itself."""
    out = tmp_path / "out"
    bundle = (out / "claude_code" / "bundle").as_posix()
    assert (
        _emit(
            repo,
            out,
            "--policies",
            "block-no-verify",
            "--deploy-root",
            bundle,
            python=sys.executable,
            on_failure=on_failure,
        )
        == 0
    )
    [(_, hook), *_] = _handlers(_drop_in(out))
    return out / "claude_code" / "bundle", hook


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = env["USERPROFILE"] = str(home)
    return {**env, **extra}


def _run(hook: dict, command: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run `hook` the way the client runs exec form: `command` spawned with `args`, no shell."""
    return subprocess.run(
        [hook["command"], *hook["args"]],
        input=json.dumps(payload("claude_code", command, cwd.as_posix())),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
        timeout=60,
    )


def test_the_bundle_runs_on_its_own(repo: Path, tmp_path: Path) -> None:
    """The emitted handler, rooted at the bundle itself, refuses the canary and allows a harmless call."""
    _, hook = _bundle_hook(repo, tmp_path)
    env = _env(tmp_path)
    denied, allowed = _run(hook, "git commit --no-verify -m x", tmp_path, env), _run(hook, "git status", tmp_path, env)
    assert denied.returncode == allowed.returncode == 0, denied.stderr + allowed.stderr
    assert '"permissionDecision": "deny"' in denied.stdout
    assert "deny" not in allowed.stdout


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX stubs and git config")
def test_user_interpreter_settings_do_not_switch_the_hook_off(repo: Path, tmp_path: Path) -> None:
    """Finding 1: chock.python set to a stub (local and global) and stub python3, python, sh, git first on PATH."""
    _, hook = _bundle_hook(repo, tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("python3", "python", "py", "sh", "git"):
        stub = stubs / name
        stub.write_text("#!/bin/sh\nprintf chock-python >&9 2>/dev/null; exit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "chock.python", str(stubs / "python3")], check=True)
    global_config = tmp_path / "gitconfig"
    global_config.write_text(f"[chock]\n\tpython = {stubs / 'python3'}\n", encoding="utf-8")
    env = _env(
        tmp_path,
        PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}",
        GIT_CONFIG_GLOBAL=str(global_config),
        PYTHONPATH=str(stubs),
        PYTHONSTARTUP=str(stubs / "python3"),
    )
    for cwd in (work, tmp_path):
        done = _run(hook, "git commit --no-verify -m x", cwd, env)
        assert done.returncode == 0, done.stderr
        assert '"permissionDecision": "deny"' in done.stdout


@pytest.mark.parametrize(("choice", "code"), [("block", 2), ("allow", 0)])
def test_a_missing_bundle_file_follows_on_failure(repo: Path, tmp_path: Path, choice: str, code: int) -> None:
    """Ruling 2: block refuses (exit 2) and allow lets the call through, each with a note on stderr."""
    bundle, hook = _bundle_hook(repo, tmp_path, on_failure=choice)
    (bundle / "block-no-verify" / "scripts" / "_chock_runtime.py").unlink()
    done = _run(hook, "git status", tmp_path, _env(tmp_path))
    assert done.returncode == code
    assert done.stderr.startswith("chock: missing ") and f"--on-failure {choice}" in done.stderr
    assert done.stdout == ""


@pytest.mark.parametrize(("choice", "code"), [("block", 2), ("allow", 0)])
def test_too_old_a_python_follows_on_failure(choice: str, code: int) -> None:
    """Ruling 2: the version check runs before any runtime code; here the minimum is raised past this Python."""
    program = claude_code.bootstrap(choice).replace("(3, 11,)", "(99,)")
    done = subprocess.run(
        [sys.executable, "-I", "-c", program, __file__], capture_output=True, text=True, check=False, timeout=60
    )
    assert done.returncode == code
    assert "this hook needs Python" in done.stderr and f"--on-failure {choice}" in done.stderr


def test_the_stop_gate_never_refuses_for_a_missing_runtime(repo: Path, tmp_path: Path) -> None:
    """onFailure has no effect on Stop, and exit 2 there sends Claude back to work: the turn-end gate notes and exits 0."""
    assert _linux(repo, tmp_path / "out", "--policies", "scan-secrets") == 0
    stop = [hook for event, hook in _handlers(_drop_in(tmp_path / "out")) if event == "Stop"]
    assert stop and all("sys.exit(0)" in hook["args"][4] for hook in stop)


@pytest.mark.parametrize(
    ("path", "platform"),
    [
        ("/", "linux"),
        ("//etc/x", "linux"),
        ("/var/lib/x", "linux"),
        ("/srv/x", "linux"),
        ("/root/x", "linux"),
        ("/run/x", "linux"),
        ("/sys/x", "linux"),
        ("/proc/x", "linux"),
        ("/", "macos"),
        ("/LIBRARY/Application Support/ClaudeCode/x", "macos"),
        ("/system/x", "macos"),
        ("/private/etc/x", "macos"),
        ("C:/", "windows"),
        ("D:\\", "windows"),
        ("c:\\program files\\ClaudeCode", "windows"),
        ("\\\\?\\C:\\Program Files\\x", "windows"),
        ("\\\\.\\C:\\Windows\\x", "windows"),
        ("\\\\localhost\\C$\\Program Files\\x", "windows"),
        ("\\\\?\\UNC\\server\\c$\\Windows", "windows"),
    ],
)
def test_every_system_spelling_is_refused(path: str, platform: str) -> None:
    """Finding 4: filesystem roots, the listed trees, case-insensitive spellings, device and admin-share prefixes."""
    assert managed.root_named(path, platform) is not None


@pytest.mark.parametrize(
    ("path", "platform"),
    [("/home/me/out", "linux"), ("/tmp/out", "linux"), ("/Users/me/out", "macos"), ("C:/Users/me/out", "windows")],
)
def test_ordinary_folders_are_allowed(path: str, platform: str) -> None:
    assert managed.root_named(path, platform) is None


def _one_line_refusal(capsys: pytest.CaptureFixture[str]) -> str:
    err = capsys.readouterr().err
    assert "Traceback" not in err and len(err.strip().splitlines()) == 1, err
    return err


def test_out_naming_a_file_is_refused_cleanly(repo: Path, tmp_path: Path, capsys) -> None:
    """Finding 5."""
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert _linux(repo, afile) == 1
    assert "is not a folder" in _one_line_refusal(capsys)
    assert afile.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("name", ["manifest.yaml", "block-no-verify.py"])
def test_a_non_utf8_policy_file_is_refused_cleanly(repo: Path, tmp_path: Path, name: str, capsys) -> None:
    """Finding 5: a non-UTF-8 manifest or guard."""
    [target] = list((repo / ".agents" / "policies" / "block-no-verify").rglob(name))
    target.write_bytes(target.read_bytes() + b"\xe9\n")
    assert _linux(repo, tmp_path / "out", "--policies", "block-no-verify") == 1
    assert "is not UTF-8 text" in _one_line_refusal(capsys)
    assert not (tmp_path / "out").exists()


def test_a_missing_repo_is_refused_cleanly(tmp_path: Path, capsys) -> None:
    """Findings 5, 9: says the folder is missing, not that no policy has a guard."""
    assert _linux(tmp_path / "does-not-exist", tmp_path / "out") == 1
    assert "is not a folder" in _one_line_refusal(capsys)


def _plan(out: Path) -> dict:
    return json.loads((out / "claude_code" / "deploy.json").read_text(encoding="utf-8"))


def test_deploy_json_states_ownership_stop_file_and_lock_effects(repo: Path, tmp_path: Path) -> None:
    """Ruling 6 (findings 7, 9): admin-owned bundle with the vendor's words, the repo stop, every --lock side effect."""
    assert _linux(repo, tmp_path / "out", "--lock") == 0
    plan = _plan(tmp_path / "out")
    text = json.dumps(plan)
    assert any("owned by an administrator and not writable by users" in line for line in plan["requirements"])
    assert "can edit the managed source itself" in text
    assert any(".chock/stop.json" in line and "refuse every tool call" in line for line in plan["caveats"])
    lock = plan["notes"][-1]
    for effect in (
        "user, project and local hooks",
        "hooks in agent frontmatter",
        "monitors of other plugins",
        "command source are disabled",
        "headersHelper",
        "status line and file suggestion",
        "/goal",
        "force-enable",
    ):
        assert effect in lock, effect


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX paths, a git repository")
def test_a_repo_stop_file_refuses_matched_calls_as_deploy_json_says(repo: Path, tmp_path: Path) -> None:
    """Finding 7: the behaviour the caveat states, proven."""
    _, hook = _bundle_hook(repo, tmp_path)
    work = tmp_path / "stopped"
    (work / ".chock").mkdir(parents=True)
    (work / ".chock" / "stop.json").write_text("not json", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    done = _run(hook, "ls", work, _env(tmp_path))
    assert done.returncode == 0 and '"permissionDecision": "deny"' in done.stdout


def test_no_wording_stronger_than_the_label(repo: Path, tmp_path: Path, capsys) -> None:
    """Ruling 7 (finding 6): no fail-closed, enforced or cannot-override claim in output, help, data, docstrings or changelog."""
    assert _linux(repo, tmp_path / "out", "--lock") == 0
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


DOCS = ROOT / "docs"


def test_docs_say_what_the_code_does() -> None:
    """Ruling 3 (finding 3): no compiled managed-settings file, `chock emit` documented, no cannot-override claim."""
    pages = {p.name: p.read_text(encoding="utf-8") for p in DOCS.rglob("*.md")}
    assert not [name for name, text in pages.items() if "managed-setting/managed-settings.json" in text]
    assert "chock emit --managed" in pages["cli-reference.md"]
    assert not OVERRIDE_CLAIM.search(pages["compare.md"])
    assert "a user cannot override" not in pages["compare.md"].lower()
