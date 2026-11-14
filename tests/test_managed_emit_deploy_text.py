"""Rulings 10-13: deploy.json names every stop file and client version, says what happens, and odd paths still run."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from managed_emit_helpers import bundle_hook, drop_in, emit, env_for, handlers, linux, make_repo, plan_of, run_hook

from chock.compile.emitters import managed

CANARY = "git commit --no-verify -m x"
DENY = '"permissionDecision": "deny"'
HOOKS_DOC = "https://code.claude.com/docs/en/hooks"
POSIX_GIT = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("git"), reason="POSIX paths, git")

#: Every deploy.json sentence that states a behaviour (by its opening words), and the test that proves it. A
#: sentence about the vendor's own behaviour is proven by its quote: "vendor docs".
SENTENCE_PROOF = {
    "--on-failure block:": "test_a_missing_bundle_file_follows_on_failure, test_a_missing_guard_or_parser_follows_on_failure",
    "--on-failure allow:": "test_a_missing_bundle_file_follows_on_failure, test_a_missing_guard_or_parser_follows_on_failure",
    "Every machine needs Python 3.11": "test_too_old_a_python_follows_on_failure, test_user_interpreter_settings_do_not_switch_the_hook_off",
    "onFailure needs Claude Code 2.1.295": "test_client_versions_are_quoted_with_the_date_read",
    "Monitor commands are checked only": "test_client_versions_are_quoted_with_the_date_read",
    "The bundle must sit at deploy_root": "test_odd_deploy_root_and_python_paths_still_start_the_bundle",
    "The bundle folder and __PYTHON__": "vendor docs",
    "Managed settings bind Claude Code only.": "vendor docs",
    "On WSL,": "vendor docs",
    "By default (managedSourcesBehavior": "vendor docs",
    "onFailure has no effect on Stop hooks": "test_the_stop_gate_never_refuses_for_a_missing_runtime",
    "A repository holding .chock/stop.json": "test_a_repo_stop_file_refuses_matched_calls_as_deploy_json_says",
    "Files under the user's home folder": "test_each_user_stop_file_refuses_as_deploy_json_says",
    "The bundled runtime runs git from PATH": "test_user_interpreter_settings_do_not_switch_the_hook_off",
    "Hooks write their decision log": "test_the_decision_log_lands_under_the_users_home",
    "A file in managed-settings.d": "vendor docs",
    "The labels are vendor-docs evidence": "test_labels_are_vendor_docs_unwitnessed_and_capped",
}
SUITE = Path(__file__).parent


def stated(plan: dict) -> list[str]:
    return [plan["on_failure"]["consequence"], *plan["requirements"], *plan["caveats"]]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


@pytest.mark.parametrize("choice", ["block", "allow"])
def test_every_behaviour_sentence_has_a_proof(repo: Path, tmp_path: Path, choice: str) -> None:
    """Ruling 12: a new sentence fails here until it names its test, and each named test exists."""
    assert linux(repo, tmp_path / "out", on_failure=choice) == 0
    sources = "".join(path.read_text(encoding="utf-8") for path in SUITE.glob("test_managed_emit_*.py"))
    for sentence in stated(plan_of(tmp_path / "out")):
        [proof] = [proof for opening, proof in SENTENCE_PROOF.items() if sentence.startswith(opening.split("__")[0])]
        for name in (part.strip() for part in proof.split(",") if proof != "vendor docs"):
            assert f"def {name}(" in sources, (sentence, name)


@pytest.mark.parametrize(("choice", "code"), [("block", 2), ("allow", 0)])
@pytest.mark.parametrize("missing", ["block-no-verify.py", "chock_shellparse"])
def test_a_missing_guard_or_parser_follows_on_failure(repo, tmp_path, choice, code, missing) -> None:
    """Ruling 12: allow lets the call through with a note, block refuses (exit 2), never an ask or a guard deny."""
    bundle, hook = bundle_hook(repo, tmp_path, on_failure=choice)
    target = bundle / "block-no-verify" / "scripts" / missing
    shutil.rmtree(target) if target.is_dir() else target.unlink()
    for command in (CANARY, "git status"):
        done = run_hook(hook, command, tmp_path, env_for(tmp_path))
        assert done.returncode == code and "permissionDecision" not in done.stdout, done.stdout + done.stderr
        assert f"missing {target.as_posix()}" in done.stderr.replace("\\", "/") or missing in done.stderr
        assert f"(--on-failure {choice})" in done.stderr


def test_deploy_json_names_every_stop_file_with_its_effect(repo: Path, tmp_path: Path) -> None:
    """Ruling 10: the repository's stop, the machine-wide stop, each registry entry, the unreadable registry."""
    assert linux(repo, tmp_path / "out") == 0
    stops = plan_of(tmp_path / "out")["stop_files"]
    by_writer = {entry["path"].split(" ")[0]: entry for entry in stops}
    assert set(by_writer) == {
        ".chock/stop.json",
        "~/.chock/stops/_everywhere.json",
        "~/.chock/stops/<repository>.json",
        "~/.chock/stops",
    }
    assert by_writer["~/.chock/stops/_everywhere.json"]["written_by"] == "chock stop --everywhere"
    assert all(entry["effect"] and "refused" in entry["effect"] for entry in stops)


@POSIX_GIT
@pytest.mark.parametrize("which", ["everywhere", "registry", "unreadable"])
def test_each_user_stop_file_refuses_as_deploy_json_says(repo: Path, tmp_path: Path, which: str) -> None:
    """Ruling 10 / finding 3: each file under ~/.chock/stops refuses a harmless call; nothing there allows it."""
    _, hook = bundle_hook(repo, tmp_path)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    env = env_for(tmp_path)
    stops = Path(env["HOME"]) / ".chock" / "stops"
    stops.parent.mkdir(parents=True, exist_ok=True)
    if which == "unreadable":
        stops.write_text("a file where the folder should be", encoding="utf-8")
    else:
        stops.mkdir()
        key = hashlib.sha256(os.path.realpath(work).encode("utf-8")).hexdigest()
        name = "_everywhere.json" if which == "everywhere" else f"{key}.json"
        (stops / name).write_text("{}" if which == "everywhere" else '{"scope": "all"}', encoding="utf-8")
    assert run_hook(hook, "git status", work, {**env, "CLAUDE_PROJECT_DIR": str(work)}).stdout.count(DENY) == 1


@POSIX_GIT
def test_the_decision_log_lands_under_the_users_home(repo: Path, tmp_path: Path) -> None:
    _, hook = bundle_hook(repo, tmp_path)
    env = {k: v for k, v in env_for(tmp_path).items() if not k.startswith("CHOCK_")}  # the suite turns logging off
    assert DENY in run_hook(hook, CANARY, tmp_path, env).stdout
    assert any((Path(env["HOME"]) / ".chock" / "log").rglob("*")), "no decision record under ~/.chock/log"


def test_client_versions_are_quoted_with_the_date_read(repo: Path, tmp_path: Path) -> None:
    """Ruling 11: the failure key's and the Monitor matcher's client versions, quoted and dated; what is not covered."""
    assert linux(repo, tmp_path / "out") == 0
    plan = plan_of(tmp_path / "out")
    versions = {entry["min_client"]: entry for entry in plan["client_versions"]}
    assert set(versions) == {"2.1.295", "2.1.314"}
    for version, entry in versions.items():
        assert f"Claude Code v{version} or later" in entry["quote"] and entry["source"] == HOOKS_DOC
        assert entry["read"] == "2026-11-13"
    assert "Monitor" in versions["2.1.314"]["quote"]
    text = " ".join(plan["not_covered"])
    for gap in ("older than 2.1.314", "WebSocket watches", "MCP tools"):
        assert gap in text, gap
    matchers = "|".join(group["matcher"] for group in drop_in(tmp_path / "out")["hooks"]["PreToolUse"])
    assert "Bash|PowerShell" in matchers and "mcp__" not in matchers and "Monitor" not in matchers


ODD = "odd dir 'q' \"dq\" $HOME `tick` ünï"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink and file names")
def test_odd_deploy_root_and_python_paths_still_start_the_bundle(repo: Path, tmp_path: Path) -> None:
    """Ruling 13: spaces, quotes, `$`, a backquote and non-ASCII in both paths; the emitted argv still runs."""
    base = tmp_path / ODD
    base.mkdir()
    python = base / f"py {ODD}"
    python.symlink_to(sys.executable)
    out = base / "out"
    root = (out / "claude_code" / "bundle").as_posix()
    assert emit(repo, out, "--policies", "block-no-verify", "--deploy-root", root, python=str(python)) == 0
    [(_, hook), *_] = handlers(drop_in(out))
    assert hook["command"] == str(python) and any(arg.startswith(root) for arg in hook["args"])
    env = env_for(tmp_path)
    assert DENY in run_hook(hook, CANARY, tmp_path, env).stdout
    allowed = run_hook(hook, "git status", tmp_path, env)
    assert allowed.returncode == 0 and "permissionDecision" not in allowed.stdout, allowed.stderr


#: (path as given, platform, its comparable spelling, the system root it names or None for an ordinary folder).
SPELLINGS = [
    ("//etc//x", "linux", "/etc//x", "/etc"),
    ("/Etc/x", "linux", "/Etc/x", None),
    ("/etcetera/x", "linux", "/etcetera/x", None),
    ("/home/me/etc", "linux", "/home/me/etc", None),
    ("/srv-data/x", "linux", "/srv-data/x", None),
    ("/LIBRARY/x", "macos", "/library/x", "/Library"),
    ("/Users/me/Library/x", "macos", "/users/me/library/x", None),
    ("/Volumes/Data/out", "macos", "/volumes/data/out", None),
    ("C:\\Program Files\\x", "windows", "c:/program files/x", "C:/Program Files"),
    ("\\\\?\\C:\\Windows\\x", "windows", "c:/windows/x", "C:/Windows"),
    ("\\\\host\\D$\\x", "windows", "d:/x", None),
    ("\\\\?\\UNC\\host\\c$\\ProgramData", "windows", "c:/programdata", "C:/ProgramData"),
    ("C:/Users//Me/out", "windows", "c:/users/me/out", None),
    ("C:/Users/me/Program Files/x", "windows", "c:/users/me/program files/x", None),
    ("C:/ProgramDataX/x", "windows", "c:/programdatax/x", None),
    ("D:/out", "windows", "d:/out", None),
]


@pytest.mark.parametrize(("given", "platform", "spelling", "root"), SPELLINGS)
def test_output_guard_normalisation_table(given: str, platform: str, spelling: str, root: str | None) -> None:
    """Ruling 13: each spelling the guard compares, and whether it is refused; ordinary folders stay allowed."""
    assert managed.spelled(given, platform) == spelling
    assert managed.root_named(given, platform) == root
