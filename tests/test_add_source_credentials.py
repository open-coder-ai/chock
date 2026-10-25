"""A catalog URL's credentials never reach chock.lock, the console, or an error message."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chock.lock import write_lock
from chock.scaffold import pin
from chock.scaffold.add import Added, record_provenance

TOKEN = "s3cr3t-token"
WITH_CREDENTIALS = f"https://x-access-token:{TOKEN}@github.com/org/catalog"
CLEAN = "https://github.com/org/catalog"


def test_the_lock_records_the_url_without_userinfo(tmp_path: Path) -> None:
    write_lock({"lockfile_version": 1, "engine": "x", "packs": [{"id": "p", "source": "local"}]}, tmp_path)

    record_provenance(tmp_path, "p", WITH_CREDENTIALS, None, Added(path=tmp_path, sha256="0" * 64, commit="a" * 40))

    text = (tmp_path / "chock.lock").read_text(encoding="utf-8")
    assert TOKEN not in text
    assert json.loads(text)["packs"][0]["source"] == CLEAN


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        (WITH_CREDENTIALS, CLEAN),
        (f"https://{TOKEN}@github.com:8443/org/catalog", "https://github.com:8443/org/catalog"),
        (CLEAN, CLEAN),
        ("git@github.com:org/catalog.git", "git@github.com:org/catalog.git"),
        ("./local/catalog", "./local/catalog"),
    ],
)
def test_redact_source_drops_only_userinfo(given: str, shown: str) -> None:
    assert pin.redact_source(given) == shown


def test_a_pin_error_does_not_echo_credentials() -> None:
    assert TOKEN not in str(pin._pin_error(WITH_CREDENTIALS, "a" * 40, "not available"))
