"""Register `chock mcp` in each wired client's project MCP config: opt-in, merge-only, removable."""

from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

from chock.hooks.launch import launcher_argv, write_launcher
from chock.resources import package_data_dir

SERVER = "chock"
TOML_BEGIN = "# chock:mcp:begin -- managed by `chock sync`; remove with `guidance_mcp: false` in .chock/config.yaml"
TOML_END = "# chock:mcp:end"
_TOML_BLOCK = re.compile(rf"(\n)?{re.escape(TOML_BEGIN)}\n.*?{re.escape(TOML_END)}\n", re.DOTALL)
MAX_BYTES = 1 << 20
_BOM = "﻿"
_NOT_OURS = "a `chock` server that chock did not write (or that was edited) is already there; rename or remove it"


class McpConfigError(ValueError):
    """A client's MCP config cannot be merged into safely; nothing was written."""


class Client(NamedTuple):
    path: str
    format: str
    key: str
    extra: dict[str, Any]


class _File(NamedTuple):
    text: str
    doc: Any
    bom: bool
    crlf: bool
    mode: int


class _Skip(Exception):  # noqa: N818 -- control flow: nothing of ours can be in this file
    """A file chock must not open or touch, with no opt-in to complain about."""


def clients() -> dict[str, Client]:
    """Per-client project MCP config facts (chock's data file; agentseam records none)."""
    raw = json.loads(package_data_dir("chock", "data").joinpath("mcp_clients.json").read_text(encoding="utf-8"))
    return {vendor: Client(**facts) for vendor, facts in raw.items()}


def server_entry(client: Client) -> dict[str, Any]:
    """The committed entry: git's alias runs the repo's launcher, which picks the interpreter at run time."""
    return {"command": "git", "args": launcher_argv("-m", "chock", "mcp", "--repo", ".")[1:], **client.extra}


def _lstat_checked(root: Path, rel: str) -> os.stat_result | None:
    """lstat of `rel` under `root`: None when absent; refuses a symlink anywhere on the way or a non-regular file."""
    cur = root
    parts = Path(rel).parts
    for i, part in enumerate(parts):
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return None
        except OSError as exc:
            msg = f"{rel}: cannot be inspected ({exc.strerror}); chock will not touch it"
            raise McpConfigError(msg) from exc
        if stat.S_ISLNK(st.st_mode):
            msg = f"{rel}: {part} is a symlink; chock will not write through it"
            raise McpConfigError(msg)
        wanted = stat.S_ISREG if i == len(parts) - 1 else stat.S_ISDIR
        if not wanted(st.st_mode):
            msg = f"{rel}: {part} is not a {'regular file' if i == len(parts) - 1 else 'directory'}; chock will not touch it"
            raise McpConfigError(msg)
    return st


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        msg = "duplicate keys"
        raise ValueError(msg)
    return dict(pairs)


def _read_raw(root: Path, rel: str) -> tuple[bytes, os.stat_result] | None:
    """The bytes of a small regular file reached without a link; None when absent."""
    st = _lstat_checked(root, rel)
    if st is None:
        return None
    if st.st_size > MAX_BYTES:
        msg = f"{rel}: larger than {MAX_BYTES} bytes; chock will not read it"
        raise McpConfigError(msg)
    fd = os.open(root / rel, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        return handle.read(MAX_BYTES + 1), st


def _inspect(root: Path, client: Client, *, removing: bool) -> _File | None:
    """The parsed config, None when absent. A file of no use to us is refused, or skipped when removing."""
    rel = client.path
    try:
        got = _read_raw(root, rel)
    except (McpConfigError, OSError) as exc:
        if removing:
            raise _Skip from exc
        if isinstance(exc, McpConfigError):
            raise
        msg = f"{rel}: cannot be read ({exc}); chock will not touch it"
        raise McpConfigError(msg) from exc
    if got is None:
        return None
    raw, st = got
    try:
        text = raw.decode("utf-8")
        bom = text.startswith(_BOM)
        text = text.removeprefix(_BOM)
        crlf = "\r\n" in text
        text = text.replace("\r\n", "\n")
        doc = tomllib.loads(text) if client.format == "toml" else json.loads(text, object_pairs_hook=_no_duplicates)
    except ValueError as exc:
        if removing:
            raise _Skip from exc
        kind = "TOML" if client.format == "toml" else "JSON (comments are not accepted)"
        msg = f"{rel}: not valid {kind}: {exc}; fix it by hand, chock will not overwrite it"
        raise McpConfigError(msg) from exc
    if not isinstance(doc, dict):
        msg = f"{rel}: expected an object at the top level; chock will not overwrite it"
        raise McpConfigError(msg)
    return _File(text, doc, bom, crlf, st.st_mode & 0o777)


def _servers(doc: dict, client: Client) -> dict:
    servers = doc.get(client.key, {})
    if not isinstance(servers, dict):
        msg = f"{client.path}: `{client.key}` is not a table/object; chock will not overwrite it"
        raise McpConfigError(msg)
    return servers


def _plan_json(client: Client, existing: _File | None, *, enabled: bool) -> str | None:
    """The file's new text, "" to delete it, None when nothing changes."""
    doc = {} if existing is None else existing.doc
    servers = _servers(doc, client)
    want = server_entry(client)
    if SERVER in servers and servers[SERVER] != want:
        if enabled:
            msg = f"{client.path}: {_NOT_OURS}"
            raise McpConfigError(msg)
        return None
    if enabled:
        if SERVER in servers:
            return None
        doc.setdefault(client.key, servers)[SERVER] = want
    else:
        if SERVER not in servers:
            return None
        del servers[SERVER]
        if not servers:
            del doc[client.key]
        if not doc:
            return ""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _toml_text(client: Client) -> str:
    entry = server_entry(client)
    return (
        f"{TOML_BEGIN}\n[{client.key}.{SERVER}]\ncommand = {json.dumps(entry['command'])}\n"
        f"args = {json.dumps(entry['args'])}\n{TOML_END}\n"
    )


def _plan_toml(client: Client, existing: _File | None, *, enabled: bool) -> str | None:
    text, doc = (existing.text, existing.doc) if existing else ("", {})
    blocks = list(_TOML_BLOCK.finditer(text))
    markers = text.count(TOML_BEGIN) + text.count(TOML_END)
    new = _toml_text(client)
    genuine = len(blocks) == 1 and markers == 2 and blocks[0].group(0).lstrip("\n") == new  # noqa: PLR2004
    if not genuine and (blocks or markers or SERVER in _servers(doc, client)):
        if enabled:
            msg = f"{client.path}: {_NOT_OURS}"
            raise McpConfigError(msg)
        return None
    if not enabled:
        return _TOML_BLOCK.sub("", text, count=1) if genuine else None
    if genuine:
        return None
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + new


def _plan(root: Path, client: Client, *, enabled: bool) -> tuple[str | None, _File | None]:
    """(new text, "" to delete, None when it already matches; the file it came from). Raises on a file we must not touch."""
    try:
        existing = _inspect(root, client, removing=not enabled)
        return (_plan_toml if client.format == "toml" else _plan_json)(client, existing, enabled=enabled), existing
    except _Skip:
        return None, None


def _write(root: Path, client: Client, text: str, existing: _File | None) -> None:
    """Replace the file through a same-directory temp file, after re-checking the path is still safe."""
    _lstat_checked(root, client.path)
    path = root / client.path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if existing and existing.crlf else text
    payload = ((_BOM if existing and existing.bom else "") + data).encode("utf-8")
    tmp = path.with_name(f".{path.name}.chock-{os.urandom(6).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, existing.mode if existing else 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _selected(wired: tuple[str, ...], *, enabled: bool) -> dict[str, Client]:
    """Clients to act on: wired ones when enabled; every one when removing (a dropped agent keeps nothing of ours)."""
    every = clients()
    return {v: c for v, c in every.items() if v in wired} if enabled else every


def register(repo_root: Path | str, wired: tuple[str, ...], *, enabled: bool) -> list[str]:
    """Bring every client's MCP config in line with the opt-in. A file we must not touch refuses before any write."""
    root = Path(repo_root)
    plans = [(c, *_plan(root, c, enabled=enabled)) for c in _selected(wired, enabled=enabled).values()]
    done: list[str] = []
    for client, new, existing in plans:
        if new is None:
            continue
        if new.strip():
            if enabled:
                write_launcher(root)
            _write(root, client, new, existing)
        else:
            _lstat_checked(root, client.path)
            (root / client.path).unlink()
        verb = "Registered the chock MCP server in" if enabled else "Removed the chock MCP server from"
        done.append(f"{verb} {client.path}")
    return done


def mcp_differences(repo_root: Path | str, wired: tuple[str, ...], *, enabled: bool) -> list[str]:
    """Where a client's MCP config differs from what `register` would leave; an unreadable one is reported too."""
    diffs: list[str] = []
    for client in _selected(wired, enabled=enabled).values():
        try:
            pending, _ = _plan(Path(repo_root), client, enabled=enabled)
        except McpConfigError as exc:
            diffs.append(f"unreadable: {exc}")
            continue
        if pending is not None:
            diffs.append(f"{'missing' if enabled else 'stale'}: {client.path} (chock MCP server)")
    return diffs
