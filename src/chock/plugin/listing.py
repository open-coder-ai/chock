"""What a marketplace listing needs from a package, beyond the manifest it validates."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def one_line(text: Any) -> str:
    """Collapse a folded YAML block to a single line."""
    return " ".join(str(text or "").split())


ICON_REL = Path("assets") / "icon.svg"

LICENSE_REL = Path("LICENSE")

_DATA = Path(__file__).resolve().parent / "data"


def icon_svg() -> str:
    """Chock's logo, as the bytes a package ships."""
    return (_DATA / "icon.svg").read_text(encoding="utf-8")


_LICENSE_TEXT = {"Apache-2.0": _DATA / "Apache-2.0.txt"}


def license_text(manifest: dict[str, Any]) -> str | None:
    """The `LICENSE` file for one package, or None when it cannot be written honestly."""
    provenance = manifest.get("provenance") or {}
    source = _LICENSE_TEXT.get(str(provenance.get("license") or ""))
    holder = one_line(provenance.get("author"))
    stamped = str(provenance.get("created_at") or provenance.get("updated_at") or "")[:4]
    if not source or not holder or not stamped.isdigit():
        return None
    text = source.read_text(encoding="utf-8")
    return text.replace("{year}", stamped).replace("{holder}", holder)


_SENTENCE_END = (". ", "? ", "! ")


def short_description(description: str) -> str:
    """The description's first sentence, for a field a directory renders in a card."""
    cuts = [description.index(end) + 1 for end in _SENTENCE_END if end in description]
    return description[: min(cuts)] if cuts else description


def interface_block(manifest: dict[str, Any], policy_id: str, description: str) -> dict[str, str]:
    """The directory-listing block, every field derived from the policy's own data."""
    return {
        "displayName": one_line(manifest.get("name")) or policy_id,
        "shortDescription": short_description(description),
        "composerIcon": f"./{ICON_REL.as_posix()}",
    }
