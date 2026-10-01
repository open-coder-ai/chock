"""Register `chock mcp` in each wired client's project MCP config: opt-in, merge-only, removable."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

from chock.emit import write_generated
from chock.hooks.launch import ALIAS, launcher_argv, write_launcher
from chock.resources import package_data_dir

SERVER = "chock"
TOML_BEGIN = "# chock:mcp:begin -- managed by `chock sync`; remove with `guidance_mcp: false` in .chock/config.yaml"
TOML_END = "# chock:mcp:end"
_TOML_BLOCK = re.compile(rf"(\n)?{re.escape(TOML_BEGIN)}\n.*?{re.escape(TOML_END)}\n", re.DOTALL)


class McpConfigError(ValueError):
    """A client's MCP config cannot be merged into safely; nothing was written."""


class Client(NamedTuple):
    path: str
    format: str
    key: str
    extra: dict[str, Any]


def clients() -> dict[str, Client]:
    """Per-client project MCP config facts (chock's data file; agentseam records none)."""
    raw = json.loads(package_data_dir("chock", "data").joinpath("mcp_clients.json").read_text(encoding="utf-8"))
    return {vendor: Client(**facts) for vendor, facts in raw.items()}


def server_entry(client: Client) -> dict[str, Any]:
    """The committed entry: git's alias runs the repo's launcher, which picks the interpreter at run time."""
    return {"command": "git", "args": launcher_argv("-m", "chock", "mcp", "--repo", ".")[1:], **client.extra}


def _ours(entry: object) -> bool:
    args = entry.get("args") if isinstance(entry, dict) else None
    return isinstance(args, list) and ALIAS in args and "mcp" in args and entry.get("command") == "git"


def _toml_text(client: Client) -> str:
    entry = server_entry(client)
    return (
        f"{TOML_BEGIN}\n[{client.key}.{SERVER}]\ncommand = {json.dumps(entry['command'])}\n"
        f"args = {json.dumps(entry['args'])}\n{TOML_END}\n"
    )


def _read(path: Path, *, removing: bool) -> tuple[str, Any] | None:
    """(text, parsed) of an existing config; None when absent, or unreadable but holding none of ours."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        doc = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        if removing and ALIAS not in text:
            return None
        msg = f"{path.name}: not valid {path.suffix[1:].upper()} ({exc}); fix it by hand, chock will not overwrite it"
        raise McpConfigError(msg) from exc
    if not isinstance(doc, dict):
        msg = f"{path.name}: expected an object at the top level; chock will not overwrite it"
        raise McpConfigError(msg)
    return text, doc


def _servers(doc: dict, client: Client, rel: str) -> dict:
    servers = doc.get(client.key, {})
    if not isinstance(servers, dict):
        msg = f"{rel}: `{client.key}` is not a table/object; chock will not overwrite it"
        raise McpConfigError(msg)
    return servers


def _refuse_foreign(servers: dict, rel: str) -> None:
    if SERVER in servers and not _ours(servers[SERVER]):
        msg = f"{rel}: a `{SERVER}` server that chock did not write is already there; rename or remove it"
        raise McpConfigError(msg)


def _plan_json(client: Client, existing: tuple[str, Any] | None, *, enabled: bool) -> str | None:
    """The file's new text, "" to delete it, None when nothing changes."""
    rel = client.path
    doc = {} if existing is None else existing[1]
    servers = _servers(doc, client, rel)
    if not enabled and SERVER in servers and not _ours(servers[SERVER]):
        return None
    _refuse_foreign(servers, rel)
    if enabled:
        want = server_entry(client)
        if servers.get(SERVER) == want:
            return None
        doc[client.key] = {**servers, SERVER: want}
    else:
        if SERVER not in servers:
            return None
        servers = {k: v for k, v in servers.items() if k != SERVER}
        doc.pop(client.key)
        if servers:
            doc[client.key] = servers
        elif not doc:
            return ""
    return json.dumps(doc, indent=2) + "\n"


def _plan_toml(client: Client, existing: tuple[str, Any] | None, *, enabled: bool) -> str | None:
    rel = client.path
    text, doc = existing if existing else ("", {})
    block = _TOML_BLOCK.search(text)
    if block is None and SERVER in _servers(doc, client, rel):
        if not enabled:
            return None
        msg = f"{rel}: a `{SERVER}` server that chock did not write is already there; rename or remove it"
        raise McpConfigError(msg)
    if not enabled:
        return None if block is None else _TOML_BLOCK.sub("", text, count=1)
    new = _toml_text(client)
    if block is None:
        return (text.rstrip("\n") + "\n\n" if text.strip() else "") + new
    lead = "\n" if block.group(1) else ""
    return None if block.group(0) == lead + new else _TOML_BLOCK.sub(lambda _: lead + new, text, count=1)


def _plan(root: Path, client: Client, *, enabled: bool) -> str | None:
    """The client file's new text, "" to delete it, None when it already matches. Raises on a file we must not touch."""
    existing = _read(root / client.path, removing=not enabled)
    return (_plan_toml if client.format == "toml" else _plan_json)(client, existing, enabled=enabled)


def _selected(wired: tuple[str, ...], *, enabled: bool) -> dict[str, Client]:
    """Clients to act on: wired ones when enabled; every one when removing (a dropped agent keeps nothing of ours)."""
    every = clients()
    return {v: c for v, c in every.items() if v in wired} if enabled else every


def register(repo_root: Path | str, wired: tuple[str, ...], *, enabled: bool) -> list[str]:
    """Bring every client's MCP config in line with the opt-in. A file we must not touch refuses before any write."""
    root = Path(repo_root)
    plans = [(c, _plan(root, c, enabled=enabled)) for c in _selected(wired, enabled=enabled).values()]
    done: list[str] = []
    for client, new in plans:
        if new is None:
            continue
        path = root / client.path
        if not new.strip():
            path.unlink()
        else:
            if enabled:
                write_launcher(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_generated(path, new)
        done.append(
            f"{'Registered the chock MCP server in' if enabled else 'Removed the chock MCP server from'} {client.path}"
        )
    return done


def mcp_differences(repo_root: Path | str, wired: tuple[str, ...], *, enabled: bool) -> list[str]:
    """Where a client's MCP config differs from what `register` would leave; an unreadable one is reported too."""
    diffs: list[str] = []
    for client in _selected(wired, enabled=enabled).values():
        try:
            pending = _plan(Path(repo_root), client, enabled=enabled)
        except McpConfigError as exc:
            diffs.append(f"unreadable: {exc}")
            continue
        if pending is not None:
            diffs.append(f"{'missing' if enabled else 'stale'}: {client.path} (chock MCP server)")
    return diffs
