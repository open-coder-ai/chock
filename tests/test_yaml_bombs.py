"""A repo's YAML cannot hang or crash chock: alias expansion and compact nesting are bounded."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time

import pytest

from chock.config import policy_status

CAP = 512 * 1024


def _bomb(levels: int = 40) -> str:
    lines = ["policies:", "  disabled:", "    - &a0 [x, x]"]
    lines += [f"    - &a{i} [*a{i - 1}, *a{i - 1}]" for i in range(1, levels)]
    return "\n".join(lines) + "\n"


def test_an_alias_bomb_in_disabled_does_not_expand() -> None:
    from chock import yamlio

    config = yamlio.safe_load(_bomb())
    started = time.monotonic()

    status = policy_status(config, "some-policy")

    assert status["state"] != "disabled"
    assert time.monotonic() - started < 2


def test_only_string_ids_count_as_disabled() -> None:
    config = {"policies": {"disabled": ["a-policy", 7, ["nested"], {"k": "v"}, None]}}

    assert policy_status(config, "a-policy")["state"] == "disabled"
    assert policy_status(config, "7")["state"] != "disabled"


_CHILD = textwrap.dedent(
    """
    import sys
    from chock.guidance import advise
    text = sys.stdin.read()
    try:
        advise._parsed(text, 512 * 1024)
    except advise.GuidanceError as exc:
        print("refused:", exc)
    """
)


@pytest.mark.parametrize(
    "text",
    [
        "- " * 100_000 + "x\n",
        "? " * 100_000 + "x\n",
    ],
    ids=["compact-sequence", "compact-key"],
)
def test_compact_nesting_is_refused_without_crashing_the_process(text: str) -> None:
    done = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD], input=text, capture_output=True, text=True, timeout=60, check=False
    )

    assert done.returncode == 0, done.stderr[-300:]
    assert "refused:" in done.stdout


def test_ordinary_nesting_still_parses() -> None:
    from chock.guidance import advise

    assert advise._parsed("policies:\n  disabled:\n    - a\n", CAP) == {"policies": {"disabled": ["a"]}}
