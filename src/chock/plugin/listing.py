"""What a marketplace listing needs from a package, beyond the manifest it validates.

A directory renders a card: a title, one line of text, an icon. A scanner looks for terms. The
manifest emitters answer "is this package valid for its client"; this module answers "is this
package publishable", which is a different question with a different failure mode -- a package
can be perfectly valid and still arrive with no licence and a 900-character subtitle.

Every value here is DERIVED from the policy's own manifest. Nothing is written copy. Where a
field has no honest source it is omitted rather than invented, because a listing is exactly
where an invented claim travels furthest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def one_line(text: Any) -> str:
    """Collapse a folded YAML block to a single line."""
    return " ".join(str(text or "").split())


#: Chock's own logo, 512x512 by its viewBox, shipped as package data rather than read from
#: `docs/` -- docs are not in the wheel, and an emitter that works from a source checkout and
#: not from a `pip install` is worse than one that does not exist. `test_plugin_listing.py`
#: pins it byte-identical to `docs/assets/logo.svg` so the two cannot drift.
ICON_REL = Path("assets") / "icon.svg"

#: Package-root `LICENSE`, no extension -- what every scanner and every human looks for.
LICENSE_REL = Path("LICENSE")

_DATA = Path(__file__).resolve().parent / "data"


def icon_svg() -> str:
    """Chock's logo, as the bytes a package ships."""
    return (_DATA / "icon.svg").read_text(encoding="utf-8")


#: The only licence text chock ships. The manifest schema also permits `MIT`,
#: `BSD-3-Clause` and `proprietary`; `proprietary` has no canonical text to ship at all, and
#: the other two are not what any policy chock packages declares today, so shipping them
#: would be speculative content in a legal file. Adding one is a data file plus a key here.
_LICENSE_TEXT = {"Apache-2.0": _DATA / "Apache-2.0.txt"}


def license_text(manifest: dict[str, Any]) -> str | None:
    """The `LICENSE` file for one package, or None when it cannot be written honestly.

    Distribution repos carry a licence at the root and none inside each published package, so
    a plugin lifted out of the tree arrives with no terms attached. This emits one per package.

    Every part of the notice is derived from the policy's own `provenance` -- the licence from
    `license`, the holder from `author`, the year from `created_at` (or `updated_at`). None of
    it is chock's. That distinction is the reason this is not simply a copy of the repository's
    own `LICENSE`: `chock plugin build` runs on anybody's policies, and stamping this project's
    copyright line into a third party's package would be a false claim in the one file where a
    false claim actually matters.

    Returns None -- and writes nothing -- when the licence is one whose text is not shipped, or
    when the year cannot be derived. A missing `LICENSE` is a gap someone can see and fix; an
    invented copyright notice is not.
    """
    provenance = manifest.get("provenance") or {}
    source = _LICENSE_TEXT.get(str(provenance.get("license") or ""))
    holder = one_line(provenance.get("author"))
    stamped = str(provenance.get("created_at") or provenance.get("updated_at") or "")[:4]
    if not source or not holder or not stamped.isdigit():
        return None
    # Substituted rather than `str.format`ed: the text is a legal document that may one day
    # contain a brace, and a formatter that raises on the licence body is a worse failure than
    # two explicit replacements.
    text = source.read_text(encoding="utf-8")
    return text.replace("{year}", stamped).replace("{holder}", holder)


#: Sentence terminators, in the order a description is scanned for them. `.` alone is not
#: enough: several policy descriptions open on a question or an exclamation, and cutting at
#: the first period would hand the listing the whole paragraph.
_SENTENCE_END = (". ", "? ", "! ")


def short_description(description: str) -> str:
    """The description's first sentence, for a field a directory renders in a card.

    Derived, never rewritten. The policy descriptions run past 900 characters -- whatever a
    listing does with that, it is not a short description -- and their first sentence is
    already the one-line statement of what the policy does, because that is how they are
    written. Taking it is a truncation a reader can verify against the full text; writing a
    new one would be marketing copy the manifest cannot be checked against.

    Falls back to the whole (already single-line) description when it has no sentence break:
    a description that is one sentence IS its own first sentence.
    """
    cuts = [description.index(end) + 1 for end in _SENTENCE_END if end in description]
    return description[: min(cuts)] if cuts else description


def interface_block(manifest: dict[str, Any], policy_id: str, description: str) -> dict[str, str]:
    """The directory-listing block, every field derived from the policy's own data.

    `displayName` is the policy's own `name` -- the human title it already carries, and the
    same field the Cursor emitter has always published as `displayName`. `shortDescription` is
    the first sentence of the description. `composerIcon` points at the icon this emitter
    writes into the package, so the path resolves in the package rather than naming a file
    that only exists in this repository.

    Nothing else from the block is emitted. The schema's other optional fields have no source
    in a policy manifest, and a field invented to fill a listing is exactly the kind of claim
    the rest of this package refuses to make.
    """
    return {
        "displayName": one_line(manifest.get("name")) or policy_id,
        "shortDescription": short_description(description),
        "composerIcon": f"./{ICON_REL.as_posix()}",
    }
