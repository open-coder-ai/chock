"""The gate must decode git output as UTF-8, never as the machine's locale codec.

`subprocess.run(..., text=True)` without `encoding=` decodes using
`locale.getpreferredencoding()` -- cp1252 on a default Windows install. Git emits UTF-8, so
any staged file containing a byte that codec lacks raised UnicodeDecodeError inside
subprocess's reader thread, `proc.stdout` came back None, and the gate died on
`None.splitlines()`.

Found the way it would find an adopter: committing a design doc containing `←`
(U+2190 -> E2 86 90; 0x90 is undefined in cp1252). The hook printed a traceback and blocked
the commit. A crash is not a verdict -- this was a denial of service on valid content, and
on Windows it would have hit any adopter writing an arrow, a dash variant, or CJK text.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import init_repo, stage

from chock.gate.runner import GateContext, run

# Characters whose UTF-8 encoding contains a byte cp1252 cannot decode.
HOSTILE = {
    "left arrow U+2190": "note = 'value'  # ← chosen default\n",
    "CJK": "# 設定ファイル\n",
    "emoji": "# ✅ verified\n",
}


def _gate(tmp_path: Path, pattern: str) -> Path:
    spec = {
        "kind": "content_regex",
        "on": ["commit"],
        "action": "block",
        "message": "blocked",
        "params": {"scan": "added_lines", "content_pattern": pattern},
    }
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_git_output_is_decoded_as_utf8_not_the_locale_codec(tmp_path: Path) -> None:
    """The direct unit: the accessor must return text, never None."""
    repo = init_repo(tmp_path)
    stage(repo, "notes.md", "# ← arrow\n")
    ctx = GateContext(repo_root=repo)

    lines = ctx.added_lines("notes.md")
    assert lines, "added_lines returned nothing for a staged file"
    assert any("arrow" in line for line in lines)


def test_a_hostile_file_does_not_crash_the_gate(tmp_path: Path) -> None:
    """Whatever the verdict, it must be a verdict -- exit 0 or 1, never a traceback."""
    for label, content in HOSTILE.items():
        case_dir = tmp_path / label.replace(" ", "_")
        case_dir.mkdir()
        repo = init_repo(case_dir)
        stage(repo, "notes.md", content)
        code = run(_gate(repo, "NOTHING_MATCHES_THIS"), "pre-commit", None, repo)
        assert code == 0, f"{label}: gate returned {code} for content it should allow"


def test_a_secret_next_to_hostile_bytes_is_still_caught(tmp_path: Path) -> None:
    """Failing open on undecodable bytes would be the worse bug.

    `errors="replace"` keeps scanning rather than refusing the file, so a real match beside
    an odd character must still be found -- otherwise the fix would have turned a crash into
    a silent miss.
    """
    repo = init_repo(tmp_path)
    stage(repo, "config.py", "# ← default\nAWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n")  # pragma: allowlist secret

    code = run(_gate(repo, "AKIA[0-9A-Z]{16}"), "pre-commit", None, repo)
    assert code == 1, "the gate missed a secret sitting beside a non-cp1252 character"
