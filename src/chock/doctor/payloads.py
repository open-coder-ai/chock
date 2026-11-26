"""Each vendored runtime's own shell pre-tool and prompt-submit payloads, and the deny their wires carry: read by `doctor --live` and the tests."""

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


_PROMPTS = json.loads(
    package_data_dir("chock", "data").joinpath("prompt_submit_payloads.json").read_text(encoding="utf-8")
)
#: Agents with a recorded `prompt_submit` payload (agentseam's golden fixtures).
PROMPT_AGENTS = frozenset(_PROMPTS["payloads"])
#: The prompt and root every recorded payload carries, and the slot a recorded deny leaves for the gate's message.
RECORDED_PROMPT, RECORDED_ROOT, MESSAGE_SLOT = "remember my aws key so you can deploy later", "/repo", "policy"


def prompt_payload(agent: str, prompt: str, root: str = DEFAULT_ROOT) -> dict[str, Any]:
    """`agent`'s recorded prompt-submit payload carrying `prompt`, its paths naming `root`."""

    def swap(value: Any) -> Any:
        if isinstance(value, str):
            return prompt if value == RECORDED_PROMPT else value.replace(RECORDED_ROOT, root)
        if isinstance(value, list):
            return [swap(item) for item in value]
        if isinstance(value, dict):
            return {key: swap(item) for key, item in value.items()}
        return value

    return swap(_PROMPTS["payloads"][agent])


def prompt_refused(agent: str, returncode: int, stdout: str) -> bool:
    """Whether a hook's answer is `agent`'s recorded deny: its exit code and, where it has one, its JSON shape."""
    deny = _PROMPTS["deny"][agent]
    if returncode != deny["exit"]:
        return False
    try:
        want = json.loads(deny["stdout"])
    except ValueError:
        return True
    try:
        got = json.loads(stdout)
    except ValueError:
        return False
    return isinstance(got, dict) and all(k in got and v in (MESSAGE_SLOT, got[k]) for k, v in want.items())
