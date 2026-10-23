"""The Claude Code build as an alternative install for agents that load Claude Code plugins (data/claude_plugin.json).

A route is offered only where agentseam's `loads_claude_plugins` records a witnessed refusal: its `deny_reply` is
one `offer_when` allows and its `witnessed` text carries the route's `witness` quote.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from agentseam.vendor_config import loads_claude_plugins

from chock.install import package, place, steps
from chock.resources import package_data_dir

INDENT = "  "


def settings() -> dict[str, Any]:
    """The offer's data: the build client, the rule, each client's agentseam agent, routes and steps."""
    text = package_data_dir("chock.install", "data").joinpath("claude_plugin.json").read_text(encoding="utf-8")
    return json.loads(text)


def routes(client_id: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The client's routes that agentseam's witness backs; empty when it records none."""
    data = data or settings()
    entry = data["clients"].get(client_id)
    row = loads_claude_plugins(entry["agent"]) if entry else None
    if not row or row.get("deny_reply") not in data["offer_when"]["deny_reply"]:
        return []
    witnessed = row.get("witnessed", "")
    return [r for r in entry["routes"] if r["witness"] in witnessed]


def tokens(dest: Path, name: str, selection_arg: str, marketplace: str) -> dict[str, str]:
    """The Claude build's own folder and marketplace, for the steps another agent runs on it."""
    build = settings()["build_client"]
    return {
        "__DEST__": str(dest),
        "__PLUGIN_DIR__": str(place.plugin_dir(build, dest, name)),
        "__PLUGIN__": name,
        "__MARKETPLACE__": marketplace,
        "__MARKETPLACE_FLAG__": "" if marketplace == package.marketplace() else f" --marketplace-name {marketplace}",
        "__SELECTION__": shlex.quote(selection_arg),
        "__BUILD_CLIENT__": build,
    }


def _route(route: dict[str, Any], filled: dict[str, str], *, build_line: str) -> list[str]:
    out = [f"{INDENT}{route['where']}: {route['label']}"]
    if "prefer_native" in route:
        out.append(f"{INDENT * 2}{route['prefer_native']}")
    if build_line:
        out.append(f"{INDENT * 2}{build_line.replace('__WHERE__', route['where'])}")
    for step in steps.render_steps(route["steps"], filled):
        text = shlex.join(step.command) if step.command else step.text
        out.extend(f"{INDENT * 2}{line}" for line in text.splitlines())
    return out


def lines(client_id: str, filled: dict[str, str]) -> list[str]:
    """What `chock install` prints about the Claude build for `client_id`; empty when there is nothing to say."""
    data = settings()
    if client_id == data["build_client"]:
        return _listing(data, filled)
    entry = data["clients"].get(client_id, {})
    offered = routes(client_id, data)
    if not offered:
        return [entry["not_offered"]] if "not_offered" in entry else []
    build_line = steps.render_steps([{"note": data["build"]}], filled)[0].text
    out = [data["heading"]]
    for route in offered:
        out.extend(_route(route, filled, build_line=build_line))
    return out + [f"warning: {w}" for w in data["warnings"]]


def _listing(data: dict[str, Any], filled: dict[str, str]) -> list[str]:
    """For the Claude build itself: every agent it is witnessed in, with that agent's steps."""
    found = {cid: routes(cid, data) for cid in data["clients"]}
    if not any(found.values()):
        return []
    out = [data["listing"]]
    for route in (r for offered in found.values() for r in offered):
        out.extend(_route(route, filled, build_line=""))
    out.extend(e["not_offered"] for cid, e in data["clients"].items() if "not_offered" in e and not found[cid])
    return out + [f"warning: {w}" for w in data["warnings"]]
