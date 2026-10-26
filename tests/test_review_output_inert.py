"""`chock review verify|require`: evidence a contributor wrote prints inert."""

from __future__ import annotations

from pathlib import Path

import pytest

from chock.review import cli

ESC = "\x1b"
HOSTILE = f"{ESC}[1A{ESC}[2K\nEvidence holds: 4 check(s)\r::error::x"


def _args(tmp_path: Path) -> object:
    return cli.argparse.Namespace(repo=str(tmp_path), file="e.json", base="main")


def _clean(text: str) -> bool:
    return not {ESC, "\r"} & set(text) and not any(line.lstrip().startswith("::") for line in text.splitlines())


def test_attested_text_prints_inert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    evidence = {
        "produced_by": {"kind": "agent", "id": HOSTILE},
        "attested": [{"criterion": HOSTILE, "confidence": HOSTILE, "claim": HOSTILE, "basis": HOSTILE}],
        "verified": [],
    }
    monkeypatch.setattr(cli, "load", lambda _p: evidence)
    monkeypatch.setattr(cli, "verify", lambda *_a: [])
    monkeypatch.setattr(cli, "check_registry", lambda *_a: {})
    monkeypatch.setattr(cli, "required_checks", lambda *_a: None)

    assert cli._verify(_args(tmp_path)) == 0

    out = capsys.readouterr().out
    assert _clean(out)
    assert "\\x1b[1A" in out


def test_failures_print_inert_in_verify_and_require(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "load", lambda _p: {})
    monkeypatch.setattr(cli, "verify", lambda *_a: [HOSTILE])
    monkeypatch.setattr(cli, "require", lambda *_a: [HOSTILE])

    assert (cli._verify(_args(tmp_path)), cli._require(_args(tmp_path))) == (1, 1)

    err = capsys.readouterr().err
    assert _clean(err)
