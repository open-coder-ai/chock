"""`chock witness export`: one client's decision-log records, redacted, in a local file for agentseam. Never uploads."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentseam import matrix as _matrix

from chock import __version__, vendors
from chock.display import inert
from chock.gate.runner import journal
from chock.gatelog import SINCE_HELP, positive_days
from chock.gatelog_chain import heads
from chock.gatelog_read import read_events, record_route
from chock.resources import package_data_dir

DATA: dict[str, Any] = json.loads(
    package_data_dir("chock", "data").joinpath("evidence_export.json").read_text(encoding="utf-8")
)
#: A plugin name a log line gives is only ever a folder name; anything else is not looked up.
_PLUGIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_UNKNOWN = "unknown"
#: A person's git email (an override's approver, a stop's author): kept in the local 0o600 log, never exported.
LOCAL_ONLY = ("approver", "who")
#: The only file type an export writes: it never replaces a config, a script or anything else.
EXPORT_SUFFIX = ".json"


def exported(record: dict[str, Any], agent: str) -> bool:
    """Whether an export for `agent` carries `record`: the agent's own, or a person's override at a git hook."""
    return record.get("agent") == agent or ("override" in record and not record.get("agent"))


def install_agents() -> dict[str, str]:
    """{`chock install` client id: the agent its runtime is built for}."""
    from chock.install import package  # noqa: PLC0415 -- install data loads only for an export
    from chock.plugin.bundle_build import CLIENTS  # noqa: PLC0415

    return {cid: CLIENTS[data["format"]].agent for cid, data in package.settings()["clients"].items()}


def resolve_agent(name: str) -> str | None:
    """agentseam's id for `name`: an agentseam id, a `chock install` client id, or a `chock sync` agent name."""
    if name in _matrix.MATRIX:
        return name
    return install_agents().get(name) or vendors.CHOCK_AGENT.get(name)


def _issue_in(text: str) -> str | None:
    """The agentseam issue URL that follows the "Evidence wanted" marker in `text`, else None."""
    at = text.find(DATA["evidence_marker"])
    found = re.search(DATA["issue_url_pattern"], text[at:]) if at >= 0 else None
    return found.group(0) if found else None


def issue_url(agent: str) -> str:
    """The agentseam "evidence wanted" issue for `agent`: agentseam's matrix row, then chock's install
    warnings; otherwise a new evidence report."""
    from chock.install import warnings  # noqa: PLC0415 -- install data loads only for an export

    found = _issue_in(str((_matrix.MATRIX.get(agent) or {}).get("notes") or ""))
    clients = {cid for cid, runs in install_agents().items() if runs == agent}
    for rule in warnings.load_rules():
        if found:
            break
        if clients & set(rule.get("clients") or ()):
            found = _issue_in(str(rule.get("says") or ""))
    return found or str(DATA["new_issue_url"])


def redact(value: Any, home: str) -> Any:
    """`value` with the home folder written `~` and every string passed through the log's own redaction."""
    if isinstance(value, dict):
        return {key: redact(item, home) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, home) for item in value]
    if isinstance(value, str):
        for spelling in {home, home.replace("\\", "/")} if len(home) > 1 else ():
            value = value.replace(spelling, "~")
        return journal.log_trace_text(value)
    return value


def catalog_refs(agent: str, records: list[dict[str, Any]], repo_root: Path) -> list[str]:
    """Catalog refs behind the records: each plugin's install marker (plugin route), chock.lock (sync route)."""
    from chock.install import package, place  # noqa: PLC0415 -- install data loads only for an export
    from chock.lock import LockError, read_lock  # noqa: PLC0415

    refs: set[str] = set()
    names = {str(r.get("plugin")) for r in records if record_route(r) == "plugin" and r.get("plugin")}
    clients = [cid for cid, runs in install_agents().items() if runs == agent]
    for cid in clients:
        for name in sorted(n for n in names if _PLUGIN_NAME.match(n)):
            try:
                path = place.plugin_dir(cid, place.default_dest(cid), name) / package.MARKER
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            catalog = doc.get("catalog") if isinstance(doc, dict) else None
            if isinstance(catalog, dict) and catalog.get("ref"):
                refs.add(f"{catalog.get('source', '')}@{catalog['ref']}")
    if any(record_route(r) == "sync" for r in records):
        try:
            packs = read_lock(repo_root).get("packs", [])
        except (LockError, OSError, ValueError):
            packs = []
        for pack in (p for p in packs if isinstance(p, dict) and p.get("source_commit")):
            refs.add(f"{pack.get('source', '')}@{pack['source_commit']}")
    return sorted(refs)


_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


def rekey(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`records` with each `target` fingerprint keyed by a random key made for this export and then dropped.

    Equal targets stay equal inside the file; a guessed path or command can no longer be confirmed offline.
    """
    key = secrets.token_bytes(32)

    def keyed(match: re.Match[str]) -> str:
        return "hmac-sha256:" + hmac.new(key, match.group(0).encode(), hashlib.sha256).hexdigest()

    return [
        {**r, "target": _FINGERPRINT.sub(keyed, r["target"])} if isinstance(r.get("target"), str) else r
        for r in records
    ]


def bundle(agent: str, records: list[dict[str, Any]], repo_root: Path, since: int | None) -> dict[str, Any]:
    """The export: the evidence form's fields, then the records; everything read from a log or a marker is redacted."""
    from chock.scaffold.pin import engine_commit  # noqa: PLC0415 -- a git call, made only for an export

    home = os.path.expanduser("~")
    refs = redact(catalog_refs(agent, records, repo_root), home)
    records = rekey(redact([{k: v for k, v in r.items() if k not in LOCAL_ONLY} for r in records], home))
    plugins = sorted({f"{r['plugin']} {r.get('plugin_version') or ''}".strip() for r in records if r.get("plugin")})
    return {
        "format": DATA["format"],
        "issue": issue_url(agent),
        "template": DATA["template"],
        "notice": DATA["notice"],
        "agent": agent,
        "agent_version": DATA["agent_version_unknown"],
        "clients": sorted({str(r["client"]) for r in records if r.get("client")}),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "engine": {"chock_version": __version__, "commit": engine_commit() or _UNKNOWN},
        "plugins": plugins,
        "catalog_refs": refs or [_UNKNOWN],
        "events": sorted({str(r.get("event")) for r in records if r.get("event")}),
        "since_days": since,
        "exported": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": redact(heads(repo_root, [agent]), home),
        "records": records,
    }


def write_new(path: Path, text: str) -> None:
    """Create `path` owner-only and write `text`; an existing file (or link) raises FileExistsError, never overwritten."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))


def default_out(agent: str) -> Path:
    return Path(f"chock-witness-{agent}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chock witness", description="Evidence from your own decision log")
    verbs = parser.add_subparsers(dest="verb", required=True)
    export = verbs.add_parser("export", help="Write one client's redacted log records to a local file; never uploads")
    export.add_argument("--client", required=True, help="The client: an agentseam id, or a chock install/sync name")
    export.add_argument("--since", type=positive_days, metavar="DAYS", help=SINCE_HELP)
    export.add_argument(
        "--out",
        type=Path,
        help="A new .json file to write; an existing file is refused (default: ./chock-witness-<client>-<date>.json)",
    )
    export.add_argument("--repo", default=".", help="Repository root whose sync-route log is read (default: cwd)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out = args.out
    if out is not None and out.suffix.lower() != EXPORT_SUFFIX:
        sys.stderr.write(f"chock witness: --out must name a {EXPORT_SUFFIX} file, not {out}\n")
        return 2
    agent = resolve_agent(args.client)
    if agent is None:
        sys.stderr.write(f"chock witness: unknown client {args.client!r}\n")
        return 2
    repo_root = Path(args.repo).resolve()
    records = [r for r in read_events(repo_root, args.since, heartbeats=True) if exported(r, agent)]
    doc = bundle(agent, records, repo_root, args.since)
    out = out or default_out(agent)
    try:
        write_new(out, json.dumps(doc, indent=2) + "\n")
    except FileExistsError:
        sys.stderr.write(f"chock witness: {out} already exists; move or rename it first, nothing was overwritten\n")
        return 2
    except OSError as exc:
        sys.stderr.write(f"chock witness: cannot write {out}: {exc}\n")
        return 1
    shown = {**doc, "events": ", ".join(doc["events"]) or "none", "records": out.name}
    lines = [
        f"Wrote {len(records)} redacted {agent} record(s) to {out}. Nothing was uploaded.",
        DATA["notice"],
        f"Attach it to: {doc['issue']}",
        "Form fields: " + "; ".join(f"{label} = {shown[key]}" for key, label in DATA["form_fields"].items()),
    ]
    sys.stdout.write("\n".join(map(inert, lines)) + "\n")
    return 0
