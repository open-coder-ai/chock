"""chock_guidance: the rules of the repo's installed policies a plan touches, and what each one does."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chock import resources, yamlio
from chock.config import policy_status
from chock.guidance import match, selection
from chock.guidance.match import Hit
from chock.guidance.source import GuidanceError, load_catalog, read_text

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_VERDICT_ORDER = {selection.DENY: 0, selection.ASK: 1}
_NO_SELECTION = "repo selection absent: every rule denies (a user-level ~/.chock/security.json is not read)"
_CONFIG = ".chock/config.yaml"


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


#: How deeply a config may nest before it is refused unparsed: the YAML parser can crash the process
#: (not raise) on pathological nesting, so depth is measured first, over-counting on the safe side.
_MAX_DEPTH = 64


def _too_deep(text: str) -> bool:
    depth = 0
    for char in text:
        if char in "[{":
            depth += 1
            if depth > _MAX_DEPTH:
                return True
        elif char in "]}":
            depth = max(depth - 1, 0)
    return any(len(line) - len(line.lstrip(" ")) > 2 * _MAX_DEPTH for line in text.splitlines())


def _enabled(repo: Path, policy: str, cap: int) -> bool:
    """Whether the repo's config leaves the policy on. The config is read like every other file here:
    no symlink, no oversize file; a config that cannot be parsed is an error, never a guess."""
    raw = read_text(repo, _CONFIG, cap)
    if raw is not None and _too_deep(raw):
        msg = f"{_CONFIG} nests deeper than {_MAX_DEPTH} levels; refusing to parse it"
        raise GuidanceError(msg)
    try:
        config = (yamlio.safe_load(raw) or {}) if raw is not None else {}
        return policy_status(config if isinstance(config, dict) else {}, policy)["state"] != "disabled"
    except Exception as exc:
        msg = f"{_CONFIG} cannot be read ({type(exc).__name__})"
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
    if catalog is None or not _enabled(repo, policy, limits["file_bytes"]):
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
    clean = clean_paths(paths, limits)
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


#: The JSON-RPC envelope around a tool result: jsonrpc, id, result, content, type, isError and their punctuation.
_ENVELOPE_BYTES = 200


def wire_bytes(payload: dict[str, Any]) -> int:
    """How many bytes the payload costs on the wire: the server sends it twice, as escaped text content and
    as structuredContent, inside the JSON-RPC envelope."""
    text = json.dumps(payload)
    return len(json.dumps(text).encode()) + len(text.encode()) + _ENVELOPE_BYTES


def _fit(payload: dict[str, Any], ordered: list[dict], limits: dict[str, int]) -> dict[str, Any]:
    """Add rules in order until the rule cap or the response byte budget (the whole response line) is reached."""
    for index, entry in enumerate(ordered):
        payload["guidance"].append(entry)
        if index >= limits["rules"] or wire_bytes(payload) > limits["response_bytes"]:
            payload["guidance"].pop()
            payload["truncated"] = True
            break
    return payload
