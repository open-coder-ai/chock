"""Build the selection into one merged plugin for one client, and swap it into place."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chock.emit import write_generated
from chock.plugin import bundle_build, bundle_grade
from chock.plugin.build import _one_line
from chock.plugin.bundle_build import Member
from chock.plugin.store import build_store_plugin
from chock.resources import package_data_dir

#: Written into every plugin it builds: the selection it came from, and proof the directory is chock's to replace.
MARKER = "chock.selection.json"


def settings() -> dict[str, Any]:
    """Marketplace, client and label data from data/install.json."""
    return json.loads(package_data_dir("chock.install", "data").joinpath("install.json").read_text(encoding="utf-8"))


def client(client_id: str) -> dict[str, Any]:
    """One client's packaging, layout and steps data."""
    return settings()["clients"][client_id]


@dataclass(frozen=True)
class Label:
    """One member's own label on one client: its enforcement, what its hooks do there, and its description."""

    policy_id: str
    keyword: str
    says: str
    description: str


def labels(members: list[Member], catalog: Path, client_id: str) -> list[Label]:
    """Each member's label from the hooks its own package for the client ships (`bundle_grade`); never an aggregate."""
    data = client(client_id)
    graded = bundle_build.member_grades(data["format"], members, catalog, write_judged=not data["gate_turn_end_only"])
    return [
        Label(
            m.id,
            bundle_grade.enforcement_keyword(level),
            says if level == bundle_grade.ADVISORY else f"{data['label_prefix']}{says}",
            _one_line(m.manifest.get("description")),
        )
        for m, level, says in graded
    ]


def bundle(members: list[Member], name: str, version: str) -> dict[str, Any]:
    """The bundle record the packager reads: named by the selection, described from data."""
    return {
        "id": name,
        "version": version,
        "description": settings()["description"],
        "members": [m.id for m in members],
    }


def stage(members: list[Member], catalog: Path, chosen: dict[str, Any], into: Path, version: str) -> None:
    """Write the merged plugin for the selection's client into `into`, with the selection marker."""
    fmt = client(chosen["client"])["format"]
    record = bundle(members, chosen["bundle"]["name"], version)

    def files_fn(_dir: Path, _manifest: dict[str, Any], root: Path) -> dict[Path, str]:
        return bundle_build.merged_files(fmt, record, members, root, aggregate=False)

    build_store_plugin(fmt, files_fn, Path(record["id"]), {"id": record["id"]}, catalog, into)
    write_generated(into / MARKER, json.dumps(chosen, indent=2, sort_keys=True) + "\n")


def read_marker(plugin_dir: Path) -> dict[str, Any] | None:
    """The selection a chock-built plugin was built from, or None for a directory chock did not build."""
    try:
        data = json.loads((plugin_dir / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def owned(dest: Path) -> bool:
    """Whether `dest` may be replaced: absent, empty, or a previous build carrying the marker."""
    return not dest.exists() or (dest.is_dir() and (not any(dest.iterdir()) or (dest / MARKER).is_file()))


def replace(dest: Path, build: Any) -> None:
    """Build into a sibling directory, then swap it in by rename; a failed build leaves `dest` untouched."""
    if not owned(dest):
        msg = f"{dest} exists and is not a chock install directory (no {MARKER}); choose another --dest"
        raise FileExistsError(msg)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.new-", dir=dest.parent))
    try:
        build(staging)
        old = Path(tempfile.mkdtemp(prefix=f".{dest.name}.old-", dir=dest.parent))
        old.rmdir()
        if dest.exists():
            dest.rename(old)
        try:
            staging.rename(dest)
        except OSError:
            if old.exists():
                old.rename(dest)
            raise
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
