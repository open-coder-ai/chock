"""Read the pinned index a folded plugin hook command runs: its root, its members, and that its pin holds."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

FOLDED = re.compile(
    r'--multi "?(?P<root>[^"\s]*)/(?P<rel>scripts/chock_index/[^"\s]+\.json)"? '
    r'--index-sha256 (?P<pin>[0-9a-f]{64}) --root "?(?P<named>[^"\s]*)"?(?P<stop> --stop-check)?$'
)


def folded_members(command: str, head: str, read: Callable[[str], str]) -> list[dict[str, Any]]:
    """The members of the index `command` runs, after checking it is `head` plus a pinned index named by its root."""
    found = FOLDED.search(command)
    assert found, command
    assert command == f"{head} {found.group(0)}", command
    assert found["root"] == found["named"], "the index and the root are named in the same form"
    body = read(found["rel"])
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == found["pin"]
    return json.loads(body)["members"]


def argvs(members: list[dict[str, Any]]) -> list[list[str]]:
    return [member["argv"] for member in members]


def seen_through(command: str, package: Path) -> str:
    """`command` followed by what each member of its pinned index runs, so a search for `--gate` or `--stop` still finds it."""
    found = FOLDED.search(command)
    if not found:
        return command
    members = json.loads((package / found["rel"]).read_text(encoding="utf-8"))["members"]
    return " ".join([command, *(" ".join(member["argv"]) for member in members)])


def stops(command: str, package: Path) -> bool:
    """Whether `command` (or a member of its index) runs a Stop gate: `--stop` as a flag, never `--stop-check`."""
    return re.search(r" --stop(?![\w-])", seen_through(command, package)) is not None


def reader(package: Path) -> Callable[[str], str]:
    """A reader of files inside the package written at `package`, for `folded_members`."""
    return lambda rel: (package / rel).read_text(encoding="utf-8")
