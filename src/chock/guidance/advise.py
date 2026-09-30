"""chock_guidance: the rules of the repo's installed policies a plan touches, and what each one does."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chock import resources
from chock.config import load_config, policy_status
from chock.guidance import match, selection
from chock.guidance.match import Hit
from chock.guidance.source import GuidanceError, load_catalog, read_text

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_VERDICT_ORDER = {selection.DENY: 0, selection.ASK: 1}
_NO_SELECTION = "absent: every rule denies"


def data() -> dict[str, Any]:
    path = resources.package_data_dir("chock.guidance", "data") / "guidance_map.json"
    return json.loads(path.read_text(encoding="utf-8"))


def clean_paths(paths: object, limits: dict[str, int]) -> list[str]:
    """Repo-relative posix paths, or GuidanceError. Paths are only ever matched against globs, never opened."""
    if not isinstance(paths, list) or len(paths) > limits["paths"]:
        msg = f"paths must be a list of at most {limits['paths']} strings"
        raise GuidanceError(msg)
    cleaned = []
    for index, raw in enumerate(paths):
        if not isinstance(raw, str) or not raw or len(raw) > limits["path_chars"] or _CONTROL.search(raw):
            msg = f"paths[{index}] is not a short printable string"
            raise GuidanceError(msg)
        posix = raw.replace("\\", "/")
        if posix.startswith("/") or _DRIVE.match(posix):
            msg = f"paths[{index}] is absolute; give repo-relative paths"
            raise GuidanceError(msg)
        parts = [p for p in posix.split("/") if p not in ("", ".")]
        if ".." in parts or not parts:
            msg = f"paths[{index}] leaves the repo or names nothing; give repo-relative paths"
            raise GuidanceError(msg)
        cleaned.append("/".join(parts))
    return cleaned


def _enabled(repo: Path, policy: str) -> bool:
    try:
        config = load_config(repo)
        return policy_status(config, policy)["state"] != "disabled"
    except (OSError, ValueError, AttributeError) as exc:
        msg = f".chock/config.yaml cannot be read ({type(exc).__name__})"
        raise GuidanceError(msg) from exc


def _verdicts(repo: Path, rel: str, catalog_packs: dict[str, set[str]], cap: int) -> tuple[dict[str, str], str]:
    raw = read_text(repo, rel, cap)
    if raw is None:
        return {i: selection.DENY for ids in catalog_packs.values() for i in ids}, _NO_SELECTION
    return selection.parse(raw, catalog_packs), rel


def _for_policy(repo: Path, policy: str, cfg: dict, plan: str, paths: list[str]) -> tuple[list[Hit], dict]:
    spec = cfg["policies"][policy]
    limits, stopwords = cfg["limits"], frozenset(cfg["stopwords"])
    catalog = load_catalog(repo, policy, limits, stopwords)
    if catalog is None or not _enabled(repo, policy):
        return [], {}
    verdicts, source = _verdicts(repo, spec["selection"], catalog.packs(), limits["file_bytes"])
    weight = match.weights(catalog.rules, limits["generic_share"])
    query = match.expand(match.words(plan, stopwords), cfg["synonyms"], stopwords)
    globs = spec["pack_globs"]
    reachable = [
        r
        for r in catalog.rules
        if verdicts[r.id] != selection.ALLOW
        and (not paths or any(match.path_matches(p, globs.get(r.pack, ())) for p in paths))
    ]
    hits = match.rank(reachable, query, limits, weight)
    return hits, {"policy": policy, "selection": source, "verdicts": verdicts}


def _entry(hit: Hit, info: dict) -> dict[str, Any]:
    rule = hit.rule
    return {
        "id": rule.id,
        "verdict": info["verdicts"][rule.id],
        "policy": info["policy"],
        "pack": rule.pack,
        "constraint": rule.constraint,
        "cwe": list(rule.cwe),
    }


def guidance(repo: Path, plan: object, paths: object) -> dict[str, Any]:
    """The capped, ordered guidance for a plan. Raises GuidanceError for input it refuses."""
    cfg = data()
    limits = cfg["limits"]
    if not isinstance(plan, str) or len(plan) > limits["plan_chars"]:
        msg = f"plan must be a string of at most {limits['plan_chars']} characters"
        raise GuidanceError(msg)
    clean = clean_paths(paths if paths is not None else [], limits)
    entries: list[tuple[tuple, dict]] = []
    errors: list[str] = []
    sources: dict[str, str] = {}
    for policy in cfg["policies"]:
        try:
            hits, info = _for_policy(repo, policy, cfg, plan, clean)
        except GuidanceError as exc:
            errors.append(f"{policy}: {exc}")
            continue
        if info:
            sources[policy] = info["selection"]
        for hit in hits:
            entry = _entry(hit, info)
            entries.append(((_VERDICT_ORDER[entry["verdict"]], -hit.score, entry["id"]), entry))
    ordered = [e for _, e in sorted(entries, key=lambda pair: pair[0])]
    return _fit({"guidance": [], "selection": sources, "errors": errors, "truncated": False}, ordered, limits)


def _fit(payload: dict[str, Any], ordered: list[dict], limits: dict[str, int]) -> dict[str, Any]:
    """Add rules in order until the rule cap or the response byte budget is reached."""
    for index, entry in enumerate(ordered):
        payload["guidance"].append(entry)
        if index >= limits["rules"] or len(json.dumps(payload).encode()) > limits["response_bytes"]:
            payload["guidance"].pop()
            payload["truncated"] = True
            break
    return payload
