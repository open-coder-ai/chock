"""Inputs for install.tape: chock's version from pyproject, and a chock.sh preset's builder share code."""

from __future__ import annotations

import argparse
import base64
import json
import tomllib
import urllib.request
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
SITE_JSON = "https://chock.sh/data/site.json"
TIMEOUT = 30
#: A named client: the site's CDN may refuse urllib's default User-Agent.
HEADERS = {"User-Agent": "chock-install-clip", "Accept": "application/json"}


def version() -> str:
    """The version pyproject.toml declares."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def site() -> dict:
    """The data the chock.sh builder reads (static/js/builder.js fetches the same file)."""
    request = urllib.request.Request(SITE_JSON, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 -- SITE_JSON, a fixed https URL
        return json.load(response)


def selection(data: dict, preset_id: str, client: str) -> dict:
    """The selection chock-site's static/js/common.js::buildSelection makes for a preset's members, key order kept."""
    preset = next(p for p in data["presets"] if p["id"] == preset_id)
    ids = sorted(preset["members"])
    policies = {p["id"]: p for p in data["policies"]}
    catalog = {"source": data["catalog"]["source"], "ref": data["catalog"]["ref"]}
    if data["catalog"].get("release"):
        catalog["release"] = data["catalog"]["release"]
    chosen = {
        "schema": 2,
        "client": client,
        "bundle": {"version": data["builder_clients"]["bundle_version"]},
        "catalog": catalog,
        "preset": preset_id,
    }
    chosen["policies"] = [
        {"from": "catalog", "id": i, "version": policies[i]["version"], "sha256": policies[i]["sha256"]} for i in ids
    ]
    return chosen


def code(chosen: dict) -> str:
    """common.js::encodeSelection: base64url of the compact UTF-8 JSON, unpadded."""
    raw = json.dumps(chosen, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="what", required=True)
    sub.add_parser("version")
    share = sub.add_parser("code")
    share.add_argument("--preset", default="git-hygiene")
    share.add_argument("--client", default="claude-code")
    args = parser.parse_args()
    print(version() if args.what == "version" else code(selection(site(), args.preset, args.client)))


if __name__ == "__main__":
    main()
