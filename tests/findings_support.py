"""A toy script gate that emits keyed findings, and the repositories the findings tests run it in."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from conftest import init_repo

from chock.gate.runner import run

NAME = "toy.py"

#: Flags a line carrying BAD, and any `query(` line in a file that never calls `sanitize(`: the
#: second is a finding a deletion can create. Keys carry no line number. Env knobs: TOY_EXIT
#: (exit code when it has findings), TOY_SLEEP (seconds each run takes), TOY_MODE=plain (no findings document), TOY_NEW=1 (`new: true`).
TOY = textwrap.dedent(
    """\
    import json, os, sys, time
    time.sleep(float(os.environ.get("TOY_SLEEP", "0")))
    payload = json.load(sys.stdin)
    if os.environ.get("TOY_LOG"):
        with open(os.environ["TOY_LOG"], "a") as fh:
            fh.write(("baseline" if payload.get("baseline") else "change") + "\\n")
    texts = payload["writes"]
    if payload.get("baseline") and any("BASECRASH" in t for t in texts.values()):
        sys.exit(9)
    if os.environ.get("TOY_MODE") == "plain":
        bad = sorted(p for p, t in texts.items() if "BAD" in t)
        if bad:
            print("plain: bad in " + ", ".join(bad), file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    findings = []
    for path, text in texts.items():
        safe = "sanitize(" in text
        for number, line in enumerate(text.splitlines(), 1):
            stmt = " ".join(line.split())
            for rule, hit in (("bad", "BAD" in stmt), ("unsanitized", "query(" in stmt and not safe)):
                if hit:
                    item = {"key": rule + ":" + stmt, "path": path, "line": number, "message": rule + " " + stmt}
                    findings.append({**item, "new": True} if os.environ.get("TOY_NEW") else item)
    print(json.dumps({"findings": findings}))
    if findings:
        print("RAW-STDERR", file=sys.stderr)
        sys.exit(int(os.environ.get("TOY_EXIT", "1")))
    """
)


def gate_spec(script: str = NAME, on: tuple[str, ...] = ("commit", "tool_use")) -> dict:
    return {"kind": "script", "on": list(on), "action": "block", "message": "m", "params": {"script": script}}


def make_gate(repo: Path, on: tuple[str, ...] = ("commit", "tool_use")) -> Path:
    """The toy script in `repo`, and a gate naming it."""
    (repo / NAME).write_text(TOY, encoding="utf-8")
    gate = repo / "gate.json"
    gate.write_text(json.dumps(gate_spec(on=on)), encoding="utf-8")
    return gate


def commit(repo: Path, **files: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=repo, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def repo_with(tmp_path: Path, **head: str) -> Path:
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    if head:
        commit(repo, **head)
    return repo


def judge_write(gate: Path, repo: Path, text: str, event: str = "pre-tool-use", path: str = "app.py") -> int:
    return run(gate, event, None, repo, writes={path: text})
