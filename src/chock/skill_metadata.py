"""The SKILL.md frontmatter metadata codec."""

from __future__ import annotations

from typing import Any


def _expand_dotted_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Turn flat dotted keys into nested dicts, merging with existing nesting."""
    tree: dict[str, Any] = {}
    for raw_key, value in data.items():
        if "." not in raw_key:
            if raw_key in tree and isinstance(tree[raw_key], dict) and isinstance(value, dict):
                tree[raw_key] = _merge_dicts(tree[raw_key], value)
            else:
                tree[raw_key] = value
            continue

        parts = raw_key.split(".")
        node = tree
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    return tree


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _chock_metadata(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Extract the metadata.chock map, expanding dotted keys."""
    metadata = frontmatter.get("metadata") or {}
    if not isinstance(metadata, dict):
        return {}
    expanded = _expand_dotted_keys(metadata)
    return expanded.get("chock") or {}


def _as_list(value: Any) -> Any:
    """A list, decoded from the flat-string metadata encoding when needed."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def _as_bool(value: Any) -> Any:
    """A boolean, decoded from the flat-string metadata encoding when needed."""
    if isinstance(value, str) and value in ("true", "false"):
        return value == "true"
    return value
