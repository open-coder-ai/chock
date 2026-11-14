"""Fixture repositories for `chock check --floor`: a base commit on `main`, a pull request on `pr`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chock.validation.checks_floor import main as floor_main

TOKEN_PATTERN = "FLOOR-TOKEN-[0-9]+"
TEST_PRAGMA = "chock: test-removal-reviewed"
CHECKOUT = "actions/checkout@" + "0" * 40
INDEX_PIN = "ab" * 32

TEST_INTEGRITY = {
    "kind": "test_integrity",
    "on": ["commit"],
    "action": "block",
    "message": "Tests were weakened, not fixed.",
    "params": {
        "test_path_regex": "(^|/)tests?/",
        "assertion_pattern": "\\bassert\\b",
        "allowlist_pragma": TEST_PRAGMA,
    },
}
FLOOR_TOKEN = {
    "kind": "content_regex",
    "on": ["commit", "tool_use"],
    "action": "block",
    "message": "No floor tokens.",
    "params": {"content_pattern": TOKEN_PATTERN},
}
PROBE = {
    "kind": "script",
    "on": ["commit"],
    "action": "block",
    "message": "probe",
    "params": {"script": ".agents/policies/probe/implementations/probe.py"},
}
PROBE_SCRIPT = """import json, os, sys
payload = json.load(sys.stdin)
if os.environ.get("FLOOR_PROBE_SECRET"):
    sys.stderr.write("probe: the environment reached the script\\n")
    sys.exit(1)
if payload.get("deleted"):
    sys.stderr.write("probe: deleted " + ",".join(payload["deleted"]) + "\\n")
    sys.exit(1)
sys.exit(0)
"""
MARKER_SCRIPT = """import pathlib, sys
pathlib.Path("MARKER").write_text("ran", encoding="utf-8")
sys.exit(0)
"""
CLAUDE = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"sh .chock/bin/launch.sh claude.py --multi x.json --index-sha256 {INDEX_PIN}",
                    }
                ],
            },
            {
                "matcher": "Write|Edit",
                "hooks": [{"type": "command", "command": "sh .chock/bin/launch.sh claude.py --write"}],
            },
        ]
    }
}
CURSOR = {"version": 1, "hooks": {"beforeShellExecution": [{"command": "sh .chock/bin/launch.sh cursor.py"}]}}
LOCK = {"lockfile_version": "2", "engine": ">=1.2,<2", "packs": [{"id": "test-integrity"}, {"id": "floor-token"}]}
WORKFLOW = f"""name: chock-floor
on:
  pull_request_target:
  merge_group:
jobs:
  floor:
    runs-on: ubuntu-latest
    steps:
      - uses: {CHECKOUT}
      - name: Floor
        run: chock check --floor --base "$BASE_SHA" --head "$HEAD_SHA"
"""
TEST_FILE = "def test_a():\n    assert 1 + 1 == 2\n    assert 2 * 2 == 4\n"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def write(repo: Path, rel: str, content: object) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def gate(repo: Path, policy: str, spec: dict, *, surfaces: tuple[str, ...] = ("ci-gate", "git-hook")) -> None:
    for surface in surfaces:
        write(repo, f".chock/compiled/{policy}/{surface}/gate.json", spec)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-gpg-sign", "-m", message)
    return git(repo, "rev-parse", "HEAD")


CONTROL_PLANE = "floor/control-plane-changed"


def base_repo(tmp_path: Path, mode: str = "refuse") -> Path:
    """`main` carries two gates, a probe script gate, hook files, a lock, a runtime, a workflow and a test; `pr` is
    checked out. `mode` is the base's floor.control_plane (refuse is the default and writes no config)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    gate(repo, "test-integrity", TEST_INTEGRITY)
    gate(repo, "floor-token", FLOOR_TOKEN)
    gate(repo, "probe", PROBE, surfaces=("ci-gate",))
    write(repo, PROBE["params"]["script"], PROBE_SCRIPT)
    write(repo, ".claude/settings.json", CLAUDE)
    write(repo, ".cursor/hooks.json", CURSOR)
    write(repo, "chock.lock", LOCK)
    write(repo, ".chock/bin/gate.py", "print('runner')\n")
    write(repo, ".chock/bin/index/claude-PreToolUse-3a2134a7.json", "{}\n")
    write(repo, ".github/workflows/chock.yml", WORKFLOW)
    write(repo, "tests/test_core.py", TEST_FILE)
    write(repo, "src/app.py", "VALUE = 1\n")
    if mode != "refuse":
        write(repo, ".chock/config.yaml", f"floor:\n  control_plane: {mode}\n")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "pr")
    return repo


def run_floor(repo: Path, capsys, *extra: str) -> tuple[int, str]:
    """The floor's exit code and everything it printed."""
    code = floor_main(["--repo", str(repo), "--base", "main", *extra])
    out = capsys.readouterr()
    return code, out.out + out.err


def control_plane_change(tmp_path: Path, capsys, change, *paths: str, extra: tuple[str, ...] = ()) -> None:
    """`change(repo)` as the pull request: exit 1 under `refuse`, exit 0 under `listed`, each listing every path."""
    for mode, owed in (("refuse", 1), ("listed", 0)):
        repo = base_repo(tmp_path / mode, mode)
        change(repo)
        code, out = run_floor(repo, capsys, *extra)
        assert code == owed, f"{mode}: {out}"
        assert f"{CONTROL_PLANE} ({mode})" in out, out
        assert out.index(CONTROL_PLANE) < out.index("floor (preview): a floor only"), out
        for path in paths:
            assert f"\n  {path}\n" in out, f"{mode}: {path} not listed\n{out}"
