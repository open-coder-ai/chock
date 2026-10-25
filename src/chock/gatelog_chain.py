"""`chock status --verify-log`: walk each decision log's hash chain and report its first break."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from chock.display import inert
from chock.gate.runner import chain as log_chain
from chock.gatelog_read import LOG_DIR, LOG_NAME, PLUGIN_LOG_NAME, ROUTES

#: A kept head: `<seq>:<sha256>`, optionally `@<log label>` to confirm it only in that log.
_HEAD_SEP = ":"
_LABEL_SEP = "@"
_ANCHOR_NOTE = "a writer of the log can recompute its whole chain: keep a head outside anything it can write"
_HASH_LEN = 64
#: Why a line after the chain began carries no link; the writer's own reason follows in brackets.
_UNCHAINED_WHY = "unchained line (a runtime without chaining wrote it — run the regen) or lock timeout"


@dataclass
class Chain:
    """One log's chain, oldest file first: where it starts, its head, and its first break (None when intact)."""

    label: str
    files: list[Path]
    records: int = 0
    legacy: int = 0
    start: str | None = None
    head: dict[str, Any] | None = None
    breaks: dict[str, Any] | None = None
    seqs: dict[int, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "log": self.label,
            "records": self.records,
            "unchained_before_start": self.legacy,
            "starts_at": self.start,
            "head": self.head,
            "intact": self.breaks is None,
            "first_break": self.breaks,
        }


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _label(path: Path, repo_root: Path, home: Path) -> str:
    for base, shown in ((repo_root, ""), (home, "~/")):
        try:
            return shown + path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def chains(repo_root: Path, route: str | None = None, home: Path | None = None, agents: list[str] | None = None):
    """Every log's (label, [rotated, current]) on the routes asked for; `agents` limits the plugin route's folders."""
    home = home or _home()
    folders = [(Path(repo_root) / ".chock" / LOG_DIR, LOG_NAME)] if route in (None, "sync") else []
    if route in (None, "plugin"):
        base = home / ".chock" / LOG_DIR
        folders.append((base, LOG_NAME))
        found = sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []
        folders += [(p, PLUGIN_LOG_NAME) for p in found if agents is None or p.name in agents]
    found = []
    for folder, name in folders:
        current = folder / name
        files = [f for f in (log_chain.log_rotated(current), current) if f.exists()]
        if files:
            found.append((_label(current, Path(repo_root), home), files))
    return found


def _break(where: tuple[str, int], kind: str, expected: object, found: object) -> dict[str, Any]:
    return {"file": where[0], "line": where[1], "kind": kind, "expected": expected, "found": found}


def _link(record: dict[str, Any], before: bytes | None, before_seq: int) -> tuple[str, object, object] | None:
    """What is wrong with `record`'s link to the line `before` it (kind, expected, found); None when it holds."""
    prev, seq = record.get(log_chain.LOG_CHAIN_PREV), record.get(log_chain.LOG_CHAIN_SEQ)
    if before is not None and prev != log_chain.log_line_hash(before):
        return "prev", log_chain.log_line_hash(before), prev
    if before_seq >= 0 and seq != before_seq + 1:
        return "seq", before_seq + 1, seq
    return None


def _chained(record: object) -> bool:
    keys = (log_chain.LOG_CHAIN_PREV, log_chain.LOG_CHAIN_SEQ)
    return isinstance(record, dict) and all(k in record for k in keys) and log_chain.LOG_CHAIN_UNCHAINED not in record


def _step(chain: Chain, where: tuple[str, int], line: bytes, before: bytes | None) -> dict[str, Any] | None:
    """Check one line against the one before it; the break it shows, or None."""
    try:
        record = json.loads(line)
    except ValueError:
        return _break(where, "not-json", "a JSON record", "unreadable bytes")
    if not _chained(record):
        if chain.start is None:
            chain.legacy += 1  # written before chaining (or by a writer that does not chain): the chain starts later
            return None
        why = record.get(log_chain.LOG_CHAIN_UNCHAINED, "no prev/seq") if isinstance(record, dict) else "not an object"
        return _break(where, "unchained", "prev and seq", f"{_UNCHAINED_WHY} [{why}]")
    if chain.start is None:
        prev, seq = record[log_chain.LOG_CHAIN_PREV], record[log_chain.LOG_CHAIN_SEQ]
        chain.start = "genesis" if (prev, seq) == (log_chain.LOG_CHAIN_GENESIS, 0) else f"{prev} (seq {seq})"
        if before is None:
            return None  # what came before is missing or rotated away: not a break
    wrong = _link(record, before, log_chain.log_line_seq(before) if before is not None and chain.records else -1)
    return _break(where, *wrong) if wrong else None


def _shown(label: str, path: Path) -> str:
    """`path` as its log's label spells the folder: `.chock/log/gate-events.1.jsonl`, `~/.chock/log/...`."""
    return str(PurePosixPath(label).parent / path.name)


def walk(chain: Chain) -> Iterator[tuple[tuple[str, int], bytes | None, dict[str, Any] | None]]:
    """Every line of `chain.files` (rotated first) as (where, line, its break or None), going on past a break.

    An unreadable file is one item with no line. `chain` counts its records and seqs as the walk goes.
    """
    before: bytes | None = None
    for path in chain.files:
        try:
            text = path.read_bytes()
        except OSError as exc:
            where = (_shown(chain.label, path), 0)
            yield where, None, _break(where, "unreadable", "a readable file", str(exc))
            continue
        for number, line in enumerate(text.split(b"\n"), start=1):
            if not line:
                continue
            where = (_shown(chain.label, path), number)
            found = _step(chain, where, line, before)
            if found is None and chain.start is not None:
                chain.records += 1
                chain.seqs[log_chain.log_line_seq(line)] = log_chain.log_line_hash(line)
            yield where, line, found
            before = line


def verify(label: str, files: list[Path]) -> Chain:
    """Walk `files` (rotated first) as one chain, stopping at its first break."""
    chain = Chain(label, files)
    last: bytes | None = None
    for _where, line, found in walk(chain):
        if found:
            chain.breaks = found
            return chain
        last = line
    if last is not None and chain.start is not None:
        chain.head = {"seq": log_chain.log_line_seq(last), "sha256": log_chain.log_line_hash(last)}
    return chain


def heads(repo_root: Path, agents: list[str] | None = None, home: Path | None = None) -> list[dict[str, Any]]:
    """Each log's head (`seq`, `sha256` of its last line) and whether its chain is intact, for an export to bind."""
    found = [verify(label, files) for label, files in chains(repo_root, home=home, agents=agents)]
    return [{"log": c.label, **(c.head or {"seq": None, "sha256": None}), "intact": c.breaks is None} for c in found]


def _kept(text: str) -> tuple[int, str, str | None]:
    head, _, label = text.partition(_LABEL_SEP)
    seq, _, digest = head.partition(_HEAD_SEP)
    if not seq.isdigit() or len(digest) != _HASH_LEN or any(c not in "0123456789abcdef" for c in digest):
        msg = f"--head must be <seq>:<sha256>[@<log>], not {text!r}"
        raise argparse.ArgumentTypeError(msg)
    return int(seq), digest, label or None


def _head_check(found: list[Chain], kept: tuple[int, str, str | None]) -> str | None:
    """Where the kept head is confirmed (only in the log it names, when it names one), or None."""
    seq, digest, label = kept
    return next(
        (c.label for c in found if c.breaks is None and c.seqs.get(seq) == digest and label in (None, c.label)), None
    )


def _render(chain: Chain) -> str:
    lines = [f"{chain.label}: {chain.records} chained record(s)"]
    if chain.legacy:
        lines.append(f"  {chain.legacy} record(s) before the chain began (written without one)")
    lines.append(f"  chain starts at {chain.start or 'no chained record yet'}")
    if chain.breaks:
        b = chain.breaks
        lines.append(f"  BROKEN at {b['file']}:{b['line']} ({b['kind']}): expected {b['expected']}, found {b['found']}")
    elif chain.head:
        head = f"{chain.head['seq']}{_HEAD_SEP}{chain.head['sha256']}{_LABEL_SEP}{chain.label}"
        lines.append(f"  intact; head {head} ({_ANCHOR_NOTE})")
    return "\n".join(inert(line) for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chock status --verify-log")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--route", choices=ROUTES)
    parser.add_argument("--head", type=_kept, help="A head kept earlier (<seq>:<sha256>): confirm a log still holds it")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    found = [verify(label, files) for label, files in chains(repo_root, args.route)]
    confirmed = _head_check(found, args.head) if args.head else None
    if args.json:
        doc: dict[str, Any] = {"chains": [c.summary() for c in found]}
        if args.head:
            doc["kept_head"] = {
                "seq": args.head[0],
                "sha256": args.head[1],
                "log": args.head[2],
                "confirmed_in": confirmed,
            }
        sys.stdout.write(json.dumps(doc, indent=2) + "\n")
    else:
        sys.stdout.write(("\n".join(_render(c) for c in found) or "no decision log found") + "\n")
        if args.head:
            shown = f"confirmed in {confirmed}" if confirmed else "NOT found with that hash in any intact log"
            sys.stdout.write(f"kept head {inert(shown)}\n")
    broken = any(c.breaks for c in found)
    return 1 if broken or (args.head and confirmed is None) else 0


if __name__ == "__main__":
    sys.exit(main())
