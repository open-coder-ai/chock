"""`from: local` entries: contain, snapshot, hash, validate, show, confirm and evaluate a person's own policy folders.

Everything after the snapshot reads the copy, so the code shown is the code checked, evaluated and built.
"""

from __future__ import annotations

import contextlib
import io
import re
import stat
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from chock import yamlio
from chock.install import package
from chock.install.resolve import REFUSED
from chock.install.selection import LOCAL
from chock.lifecycle import check_main
from chock.lock import compute_pack_hash
from chock.scaffold.add import IntegrityError
from chock.scaffold.pin import INERT, _run

#: Where each snapshot sits inside the throwaway repository `chock check` reads.
POLICIES = Path(".agents") / "policies"
MANIFEST = "manifest.yaml"
#: Shown escaped, never sent to the terminal raw: control, format (bidi, zero-width) and private-use characters.
_HIDDEN = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})
_SHOWN_RAW = frozenset("\n\t")
_BYTECODE = ("__pycache__",)
_BYTECODE_SUFFIXES = (".pyc", ".pyo")
YES = "yes"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Local:
    """One local entry after its checks: the folder it came from, its snapshot, and the snapshot's pack hash."""

    id: str
    source: Path
    snapshot: Path
    sha256: str

    def files(self) -> list[Path]:
        return sorted(p.relative_to(self.snapshot) for p in self.snapshot.rglob("*") if p.is_file())


def _refuse(policy_id: str, why: str) -> IntegrityError:
    return IntegrityError(f"{policy_id}: {why}. {REFUSED}")


def origin() -> str:
    """The origin label every local policy carries on every surface."""
    return str(package.settings()["origin"]["custom"])


def visible(text: str) -> str:
    """`text` with every character that could hide or rewrite what the terminal shows written as an escape."""
    return "".join(
        f"\\u{ord(c):04x}" if c not in _SHOWN_RAW and unicodedata.category(c) in _HIDDEN else c for c in text
    )


def _contained(policy_id: str, base: Path, rel: str) -> Path:
    """`base/rel`, refused when any part of it is a link or it resolves outside `base`."""
    root = base.resolve()
    here = base
    for part in Path(rel).parts:
        here = here / part
        if here.is_symlink():
            raise _refuse(policy_id, f"{here} is a symbolic link; a local policy must be a plain folder")
    folder = here.resolve()
    if folder == root or not folder.is_relative_to(root):
        raise _refuse(policy_id, f"path {rel!r} is outside the selection file's folder {root}")
    if not folder.is_dir():
        raise _refuse(policy_id, f"folder {folder} is missing")
    return folder


def _skipped(rel: Path) -> bool:
    return any(part in _BYTECODE for part in rel.parts) or rel.suffix in _BYTECODE_SUFFIXES


def _copy(policy_id: str, folder: Path, into: Path) -> None:
    """Copy the folder's regular text files into `into`; a link, a special file or a binary file refuses."""
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if _skipped(rel):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise _refuse(policy_id, f"{rel.as_posix()} is a symbolic link; a local policy holds plain files only")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise _refuse(policy_id, f"{rel.as_posix()} is not a regular file")
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _refuse(
                policy_id, f"{rel.as_posix()} is not UTF-8 text, so it cannot be shown before install"
            ) from exc
        target = into / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if mode & stat.S_IXUSR:
            target.chmod(0o755)


def _check_manifest(policy_id: str, snapshot: Path) -> None:
    try:
        manifest = yamlio.safe_load((snapshot / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _refuse(policy_id, f"no readable {MANIFEST} ({exc})") from exc
    declared = manifest.get("id") if isinstance(manifest, dict) else None
    if declared != policy_id:
        raise _refuse(policy_id, f"its {MANIFEST} says `id: {declared}`; the selection and the folder must agree")


def snapshot(chosen: dict[str, Any], base: Path | None, into: Path) -> list[Local]:
    """Each local entry contained in `base`, copied to `into/.agents/policies/<id>`, and hashed there."""
    entries = [p for p in chosen["policies"] if p["from"] == LOCAL]
    if entries and base is None:
        ids = ", ".join(p["id"] for p in entries)
        msg = f"{ids}: a local policy needs a selection file beside its folder, not a link or code. {REFUSED}"
        raise IntegrityError(msg)
    found = []
    for entry in entries:
        policy_id = entry["id"]
        folder = _contained(policy_id, base, entry["path"])
        copy = into / POLICIES / policy_id
        copy.mkdir(parents=True)
        _copy(policy_id, folder, copy)
        _check_manifest(policy_id, copy)
        digest = compute_pack_hash(copy)
        if "sha256" in entry and entry["sha256"] != digest:
            raise _refuse(policy_id, f"the selection pins sha256 {entry['sha256']}, the folder hashes to {digest}")
        found.append(Local(policy_id, folder, copy, digest))
    return found


def _git_init(root: Path) -> None:
    """A repository around the snapshots, so `chock check` reads them as it reads any repository."""
    with contextlib.suppress(OSError):
        _run(["git", *INERT, "init", "--quiet", str(root)])


def check(root: Path, only: str) -> None:
    """`chock check --repo <root> --only <only>` on the snapshots; any failure refuses."""
    _git_init(root)
    if check_main(["--repo", str(root), "--only", only]) != 0:
        msg = f"the local policies failed `chock check --only {only}` (above). {REFUSED}"
        raise IntegrityError(msg)


def show(local: Local, out: TextIO) -> None:
    """Every file of the snapshot in full, with the policy's id, hash and origin label."""
    print(f"Custom policy {local.id} -- {origin()} -- from {local.source}", file=out)
    print(f"  sha256 {local.sha256}", file=out)
    for rel in local.files():
        text = (local.snapshot / rel).read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        print(f"----- {local.id}/{rel.as_posix()} ({size} bytes) -----", file=out)
        print(visible(text), end="" if text.endswith("\n") or not text else "\n", file=out)
    print(f"----- end of {local.id} -----", file=out)


def _summary(local: Local) -> str:
    count = len(local.files())
    return f"Custom policy {local.id} -- {origin()} -- sha256 {local.sha256}, {count} files, unchanged since accepted"


def _ask(local: Local, read: Callable[[str], str]) -> bool:
    try:
        answer = read(f"Trust and build {local.id} (sha256 {local.sha256[:12]}...)? Type {YES} to accept: ")
    except EOFError:
        return False
    return answer.strip().lower() == YES


@dataclass(frozen=True)
class Trust:
    """What may accept a local policy: hashes accepted before (the marker), `--trust-local`, and the person."""

    accepted: dict[str, str]
    given: dict[str, str]
    interactive: bool
    read: Callable[[str], str] = input


def _check_given(found: list[Local], given: dict[str, str]) -> None:
    unknown = sorted(set(given) - {item.id for item in found})
    if unknown:
        msg = f"--trust-local names {', '.join(unknown)}, which is not a local policy of this selection. {REFUSED}"
        raise IntegrityError(msg)
    for item in found:
        if item.id in given and given[item.id] != item.sha256:
            raise _refuse(item.id, f"--trust-local gives sha256 {given[item.id]}, the folder hashes to {item.sha256}")


def confirm(found: list[Local], trust: Trust, out: TextIO | None = None) -> dict[str, str]:
    """Show and accept every local policy, or refuse; returns {id: accepted sha256} for the marker.

    A hash accepted before prints one line; any other is shown in full and needs `--trust-local id=sha256`
    or a person typing yes at a terminal. Nothing else accepts local code.
    """
    out = out or sys.stdout
    _check_given(found, trust.given)
    for item in found:
        if trust.accepted.get(item.id) == item.sha256 and item.id not in trust.given:
            print(_summary(item), file=out)
            continue
        show(item, out)
        if item.id in trust.given:
            print(f"Accepted {item.id} by --trust-local {item.id}={item.sha256}", file=out)
            continue
        out.flush()
        if not trust.interactive:
            msg = (
                f"{item.id}: custom code needs your confirmation. Read it above, then run this in a terminal, or pass "
                f"--trust-local {item.id}={item.sha256}. {REFUSED}"
            )
            raise IntegrityError(msg)
        if not _ask(item, trust.read):
            raise _refuse(item.id, "not accepted")
    return {item.id: item.sha256 for item in found}


def interactive() -> bool:
    """Whether a person can answer: stdin and stdout are both a terminal."""
    with contextlib.suppress(ValueError, io.UnsupportedOperation, AttributeError):
        return sys.stdin.isatty() and sys.stdout.isatty()
    return False


def parse_trust(value: str) -> tuple[str, str]:
    """`<id>=<sha256>` from `--trust-local`."""
    policy_id, sep, digest = value.partition("=")
    if not (sep and policy_id and _SHA256.fullmatch(digest)):
        msg = f"--trust-local takes <id>=<64 lowercase hex sha256>, not {value!r}"
        raise ValueError(msg)
    return policy_id, digest


def given(values: list[str]) -> dict[str, str]:
    """The `--trust-local` values as {id: sha256}; one id given two hashes is refused."""
    found: dict[str, str] = {}
    for value in values:
        policy_id, digest = parse_trust(value)
        if found.setdefault(policy_id, digest) != digest:
            msg = f"--trust-local gives {policy_id} two different hashes"
            raise ValueError(msg)
    return found
