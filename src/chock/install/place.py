"""Where a client's plugin goes, what chock may replace there, and the client's own index over its plugins.

Layouts (data/install.json `layout`):
- `marketplace`: `dest` is a local marketplace chock owns, one per client; each bundle is `dest/<format>/<name>/`,
  and the client's index lists every plugin in it, so bundles coexist.
- `plugin-dir`: each bundle is `dest/<name>/`, the plugin folder the client loads; there is no index.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chock.emit import write_generated
from chock.install import package, selection
from chock.plugin import marketplace_core

MARKETPLACE, PLUGIN_DIR = "marketplace", "plugin-dir"
#: Written at a marketplace root chock built: which client's marketplace it is.
MARKETPLACE_MARKER = "chock.marketplace.json"


def plugin_dir(client_id: str, dest: Path, name: str) -> Path:
    """The plugin folder a bundle named `name` is built into."""
    data = package.client(client_id)
    return dest / data["format"] / name if data["layout"] == MARKETPLACE else dest / name


def default_dest(client_id: str) -> Path:
    """The client's own default folder: never shared with another client."""
    return Path(package.client(client_id)["dest"]).expanduser()


def _marketplace_client(dest: Path) -> str | None:
    """The client a chock marketplace at `dest` was built for, or None when `dest` is not one.

    A root `chock.selection.json` is a schema-1 install's marketplace, which was always Claude Code's.
    """
    try:
        return str(json.loads((dest / MARKETPLACE_MARKER).read_text(encoding="utf-8"))["client"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return selection.SCHEMA1_CLIENT if (dest / package.MARKER).is_file() else None


def check_owned(client_id: str, dest: Path, name: str) -> None:
    """Refuse a destination chock did not build, or built for another client; never touch either."""
    if package.client(client_id)["layout"] == MARKETPLACE and dest.exists() and any(dest.iterdir()):
        found = _marketplace_client(dest)
        if found is None:
            msg = f"{dest} exists and is not a chock marketplace (no {MARKETPLACE_MARKER}); choose another --dest"
            raise FileExistsError(msg)
        if found != client_id:
            msg = f"{dest} is chock's marketplace for {found}, not {client_id}; choose another --dest"
            raise FileExistsError(msg)
        return
    marker = package.read_marker(plugin_dir(client_id, dest, name))
    if marker is not None and marker.get("client") != client_id:
        msg = f"{plugin_dir(client_id, dest, name)} was built for {marker.get('client')}, not {client_id}"
        raise FileExistsError(msg)


def _legacy(dest: Path) -> tuple[Path, dict[str, Any]] | None:
    """A schema-1 install's (plugin folder, selection): one plugin, its marker at the marketplace root."""
    marker = package.read_marker(dest)
    if marker is None:
        return None
    return dest / package.client(selection.SCHEMA1_CLIENT)["format"] / selection.DEFAULT_BUNDLE, marker


def migrate_legacy(dest: Path) -> None:
    """Move a schema-1 root marker beside the plugin it describes; the root then carries the marketplace marker."""
    legacy = _legacy(dest)
    if legacy is None:
        return
    folder, marker = legacy
    if folder.is_dir() and package.read_marker(folder) is None:
        write_generated(folder / package.MARKER, json.dumps(marker, indent=2, sort_keys=True) + "\n")
    _write_marketplace_marker(dest, selection.SCHEMA1_CLIENT)
    (dest / package.MARKER).unlink()


def _write_marketplace_marker(dest: Path, client_id: str) -> None:
    marker = {"client": client_id, "marketplace": package.settings()["marketplace"]}
    write_generated(dest / MARKETPLACE_MARKER, json.dumps(marker, indent=2, sort_keys=True) + "\n")


def others(client_id: str, dest: Path, name: str) -> list[tuple[str, Path, list[str]]]:
    """(plugin name, folder, policy ids) of every other chock-built plugin for this client under `dest`."""
    parent = plugin_dir(client_id, dest, name).parent
    found = []
    if parent.is_dir():
        for folder in sorted(
            p for p in parent.iterdir() if p.is_dir() and p.name != name and not p.name.startswith(".")
        ):
            marker = package.read_marker(folder)
            if marker is not None and marker.get("client", selection.SCHEMA1_CLIENT) == client_id:
                found.append((folder.name, folder, [str(p.get("id")) for p in marker.get("policies", [])]))
    legacy = _legacy(dest) if package.client(client_id)["layout"] == MARKETPLACE else None
    if legacy is not None and legacy[0].name != name and legacy[0].is_dir():
        found.append((legacy[0].name, legacy[0], [str(p.get("id")) for p in legacy[1].get("policies", [])]))
    return found


def _index(spec: dict[str, Any], dest: Path, fmt: str, marketplace: str) -> dict[str, Any]:
    """One index document over every plugin in the marketplace, in the style the client reads."""
    if spec["style"] != "codex":
        return marketplace_core.build_index(dest, marketplace, fmt)
    plugins = [
        {"name": e["name"], "source": {"source": "local", "path": e["source"]}, **spec["entry"]}
        for e in marketplace_core.collect_entries(dest, fmt)
    ]
    return {"name": marketplace, "plugins": plugins}


def write_marketplace(client_id: str, dest: Path) -> list[Path]:
    """The marketplace marker and the client's index files, rebuilt over every plugin now in `dest`."""
    data = package.client(client_id)
    if data["layout"] != MARKETPLACE:
        return []
    marketplace = package.settings()["marketplace"]
    _write_marketplace_marker(dest, client_id)
    written = []
    for spec in data["index"]:
        path = dest / spec["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_generated(path, json.dumps(_index(spec, dest, data["format"], marketplace), indent=2) + "\n")
        written.append(path)
    return written
