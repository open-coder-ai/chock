"""Build the selection into one merged Claude Code plugin inside a local marketplace, and swap it into place."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentseam import packaging

from chock.emit import write_generated
from chock.plugin import bundle_build, bundle_grade, marketplace_core
from chock.plugin.bundle_build import Member
from chock.plugin.store import build_store_plugin
from chock.resources import package_data_dir

CLIENT = "claude"
#: Written into every build: the selection it came from, and proof the directory is chock's to replace.
MARKER = "chock.selection.json"


def settings() -> dict[str, Any]:
    """Plugin, marketplace and command data from data/install.json."""
    return json.loads(package_data_dir("chock.install", "data").joinpath("install.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Grade:
    """One member's Claude Code grade: the manifest keyword and what its hooks do."""

    policy_id: str
    keyword: str
    says: str
    level: int


def grades(members: list[Member], catalog: Path) -> list[Grade]:
    """Each member's grade from the hooks its own Claude package ships (`bundle_grade`)."""
    client = bundle_build.CLIENTS[CLIENT]
    hooks_rel = packaging.supports(client.package_agent, packaging.HOOKS)
    return [
        Grade(m.id, bundle_grade.enforcement_keyword(level), says, level)
        for m, _files, level, says in bundle_build._member_packages(client, members, catalog, hooks_rel)
    ]


def bundle(members: list[Member], version: str) -> dict[str, Any]:
    """The bundle record the packager reads, named and described from data."""
    data = settings()
    return {
        "id": data["plugin"],
        "version": version,
        "description": data["description"],
        "members": [m.id for m in members],
    }


def stage(members: list[Member], catalog: Path, selection: dict[str, Any], into: Path, version: str) -> None:
    """Write the marketplace into `into`: the merged plugin, the index over it, and the selection marker."""
    record = bundle(members, version)
    target = into / CLIENT / record["id"]

    def files_fn(_dir: Path, _manifest: dict[str, Any], root: Path) -> dict[Path, str]:
        return bundle_build.merged_files(CLIENT, record, members, root)

    build_store_plugin(CLIENT, files_fn, Path(record["id"]), {"id": record["id"]}, catalog, target)
    index = json.dumps(marketplace_core.build_index(into, settings()["marketplace"]), indent=2) + "\n"
    index_path = into / marketplace_core.INDEX_PATHS[0]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated(index_path, index)
    write_generated(into / MARKER, json.dumps(selection, indent=2, sort_keys=True) + "\n")


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
