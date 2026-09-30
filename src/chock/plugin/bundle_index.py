"""The built record of which plugins are bundles, read by the marketplace index and the catalog page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Written beside the packages by `chock plugin build`, so every reader agrees on the order and the members.
BUNDLES_INDEX = "chock-bundles.json"


def bundles_index(bundle_list: list[dict[str, Any]]) -> str:
    """`chock-bundles.json`: bundle ids with their members, in the order listings show them."""
    return json.dumps({"bundles": [{"id": b["id"], "members": b["members"]} for b in bundle_list]}, indent=2) + "\n"


def read_bundles_index(dist_root: Path) -> list[dict[str, Any]]:
    """The built bundle record, or no bundles when none was built."""
    path = Path(dist_root) / BUNDLES_INDEX
    return json.loads(path.read_text(encoding="utf-8"))["bundles"] if path.is_file() else []


def bundles_first(entries: list[dict[str, Any]], dist_root: Path) -> list[dict[str, Any]]:
    """`entries` with the bundles ahead of the policies, each group in its existing order."""
    order = {b["id"]: i for i, b in enumerate(read_bundles_index(dist_root))}
    return sorted(entries, key=lambda e: (e["name"] not in order, order.get(e["name"], 0)))
