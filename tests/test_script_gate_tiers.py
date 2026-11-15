"""A script gate whose findings carry a tier takes its verdict from the findings the change adds.

The toy script computes its exit code over every finding in the files, old ones included, as real
scripts do; the tier on each finding is what lets the engine ignore the old ones.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from findings_support import repo_with

from chock.gate.runner.verdict import judge

#: BLOCKME lines are block-tier findings, ASKME lines ask-tier, WARNME lines warn-tier, ODDME a tier the protocol lacks.
#: TOY_TIERS=off drops the tier field; TOY_TIERS=partial drops it from ASKME findings only.
TOY = textwrap.dedent(
    """\
    import json, os, sys
    payload = json.load(sys.stdin)
    tiers = {"BLOCKME": "block", "ASKME": "ask", "WARNME": "warn", "ODDME": "severe"}
    mode = os.environ.get("TOY_TIERS", "on")
    findings = []
    for path, text in payload["writes"].items():
        for number, line in enumerate(text.splitlines(), 1):
            for word, tier in tiers.items():
                if word in line:
                    item = {"key": word + ":" + line.strip(), "path": path, "line": number, "message": tier + " " + line}
                    if mode == "on" or (mode == "partial" and word != "ASKME"):
                        item["tier"] = tier
                    findings.append(item)
    print(json.dumps({"findings": findings}))
    kinds = {item["message"].split()[0] for item in findings}
    if "block" in kinds or "severe" in kinds:
        sys.exit(1)
    sys.exit(3 if "ask" in kinds else 4 if kinds else 0)
    """
)

OLD = "x = BLOCKME\n"
COMMIT, WRITE = "commit", "pre-tool-use"


def _gate(repo: Path, action: str = "block") -> Path:
    (repo / "toy.py").write_text(TOY, encoding="utf-8")
    gate = repo / "gate.json"
    spec = {"kind": "script", "on": ["commit", "tool_use"], "action": action, "message": "m"}
    gate.write_text(json.dumps({**spec, "params": {"script": "toy.py"}}), encoding="utf-8")
    return gate


def _verdict(gate: Path, repo: Path, event: str, text: str) -> str:
    """The verdict of changing app.py to `text`, as a commit stages it or an agent writes it."""
    if event == COMMIT:
        (repo / "app.py").write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
        return judge(gate, COMMIT, None, repo)[1]
    return judge(gate, event, None, repo, writes={"app.py": text})[1]


@pytest.fixture(params=[COMMIT, WRITE])
def event(request: pytest.FixtureRequest) -> str:
    return request.param


def test_a_new_ask_finding_beside_an_old_block_finding_asks(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, OLD + "y = ASKME\n") == "ask"


def test_a_new_block_finding_beside_an_old_one_blocks(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, OLD + "y = BLOCKME two\n") == "block"


def test_touching_only_old_findings_allows(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, "# top\n" + OLD) == "allow"


def test_the_highest_tier_among_new_findings_decides(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    assert _verdict(_gate(repo), repo, event, "a = WARNME\nb = ASKME\n") == "ask"
    assert _verdict(_gate(repo), repo, event, "a = WARNME\n") == "warn"


def test_the_refusal_text_lists_only_the_new_finding(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    _verdict(_gate(repo), repo, WRITE, OLD + "y = ASKME\n")
    err = capsys.readouterr().err
    assert "app.py:2: ask y = ASKME" in err
    assert "x = BLOCKME" not in err


def test_the_declared_action_still_caps_a_block_tier_finding(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": "x = 1\n"})
    assert _verdict(_gate(repo, "ask"), repo, event, "y = BLOCKME\n") == "ask"


def test_a_script_with_no_tiers_keeps_its_exit_code(
    tmp_path: Path, event: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_TIERS", "off")
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, OLD + "y = ASKME\n") == "block"


def test_one_finding_without_a_tier_hands_the_verdict_back_to_the_exit_code(
    tmp_path: Path, event: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOY_TIERS", "partial")
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, OLD + "y = ASKME\n") == "block"


def test_a_tier_the_protocol_lacks_is_ignored(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"app.py": OLD})
    assert _verdict(_gate(repo), repo, event, OLD + "y = ODDME\nz = ASKME\n") == "block"


def test_a_new_file_with_an_ask_finding_asks(tmp_path: Path, event: str) -> None:
    repo = repo_with(tmp_path, **{"keep.py": OLD})
    assert _verdict(_gate(repo), repo, event, "y = ASKME\n") == "ask"
