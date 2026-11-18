"""Each vendored runtime's own shell pre-tool payload, and the deny its wire carries: read by `doctor --live` and the tests."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from chock.resources import package_data_dir

COMMAND, ROOT = "__COMMAND__", "__ROOT__"
#: The root a payload names when the caller gives none: what the tests swap for their own repository.
DEFAULT_ROOT = "/x"
#: The wordless deny: the client reads exit code 2 as the refusal.
EXIT_2 = "exit-2"

_DATA = json.loads(package_data_dir("chock", "data").joinpath("runtime_payloads.json").read_text(encoding="utf-8"))


def _fill(value: Any, command: str, root: str) -> Any:
    if isinstance(value, str):
        return command if value == COMMAND else value.replace(ROOT, root)
    if isinstance(value, list):
        return [_fill(item, command, root) for item in value]
    if isinstance(value, dict):
        return {key: _fill(item, command, root) for key, item in value.items()}
    return value


def payload(agent: str, command: str, root: str = DEFAULT_ROOT) -> dict[str, Any]:
    """`agent`'s pre-tool payload for one shell `command`, its paths naming `root`."""
    return _fill(_DATA["payloads"][agent], command, root)


PAYLOADS = {agent: partial(payload, agent) for agent in _DATA["payloads"]}
DENY_ON_THE_WIRE: dict[str, str] = dict(_DATA["deny_on_the_wire"])
