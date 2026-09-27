"""The review policy a change is judged by: the base's and the head's, whichever is stricter per setting."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from chock import yamlio
from chock.config import CONFIG_DIR, CONFIG_NAME, load_config

BUILTIN_CHECKS: dict[str, list[str]] = {
    "validate": ["validate", "{root}"],
    "eval": ["eval", "--repo", "{root}"],
    "recompile-check": ["recompile", "--repo", "{root}", "--check"],
    "verify": ["verify", "--root", "{root}"],
}

DEFAULT_UNATTESTABLE = ["tools/", ".github/workflows/"]


class ReviewPolicyError(RuntimeError):
    """A committed review policy that cannot be read."""


def _review_section(config: Any) -> dict[str, Any]:
    review = (config.get("chock") or {}).get("review") if isinstance(config, dict) else None
    return review if isinstance(review, dict) else {}


def _review_at(root: Path, ref: str) -> dict[str, Any] | None:
    """The review policy committed at `ref`, or None when that revision carried no config."""
    shown = subprocess.run(  # noqa: S603 -- reading a committed file via git is this helper's job
        ["git", "show", f"{ref}:{CONFIG_DIR}/{CONFIG_NAME}"],  # noqa: S607 -- git from PATH
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if shown.returncode != 0:
        return None
    text = shown.stdout
    try:
        return _review_section(yamlio.safe_load(text))
    except yaml.YAMLError as exc:
        msg = f"{CONFIG_DIR}/{CONFIG_NAME} at {ref} is not valid YAML: {exc}"
        raise ReviewPolicyError(msg) from exc


def review_policies(root: Path, base_ref: str | None = None) -> list[dict[str, Any]]:
    """The review policy a change is judged by: the base's and the head's, whichever is stricter per setting.

    A pull request edits `.chock/config.yaml` like any other file, so the head alone would let it
    drop the checks or the floor it is about to fail. The base's policy binds until it is merged away.
    """
    head = _review_section(load_config(root))
    if not base_ref:
        return [head]
    base = _review_at(root, base_ref)
    return [head] if base is None else [base, head]


def unattestable_paths(root: Path, base_ref: str | None = None) -> list[str]:
    """The repository's own list, unioned across base and head. Never taken from evidence."""
    paths: set[str] = set()
    for review in review_policies(root, base_ref):
        configured = review.get("unattestable_paths")
        paths |= set(configured) if isinstance(configured, list) and configured else set(DEFAULT_UNATTESTABLE)
    return sorted(paths)


def required_checks(root: Path, base_ref: str | None = None) -> list[str]:
    """The repository's own required set, unioned across base and head. Never from evidence."""
    names: set[str] = set()
    for review in review_policies(root, base_ref):
        configured = review.get("required_checks")
        if isinstance(configured, list):
            names |= {str(n) for n in configured}
    return sorted(names)


def attestation_floor(root: Path, base_ref: str | None = None) -> int:
    """Minimum attestations needed once the diff touches an unattestable path: the higher of base and head."""
    floors = [review.get("attestation_floor") for review in review_policies(root, base_ref)]
    return max((f for f in floors if isinstance(f, int) and f > 0), default=0)


def applies_to(root: Path) -> str:
    """Who `review require` gates: all | forks | first_time. Informational -- for the adopter's own CI wiring."""
    value = ((load_config(root).get("chock") or {}).get("review") or {}).get("applies_to")
    return value if value in {"all", "forks", "first_time"} else "all"


def command_set_hash(root: Path, base_ref: str | None = None) -> str:
    """Digest over the required set's names AND resolved commands -- a redefinition changes it, not just an omission."""
    registry = check_registry(root, base_ref)
    resolved = {name: registry.get(name, []) for name in required_checks(root, base_ref)}
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_registry(root: Path, base_ref: str | None = None) -> dict[str, list[str]]:
    """Built-in checks plus any the repository declares; a check the base defines runs as the base defines it."""
    registry = dict(BUILTIN_CHECKS)
    for review in reversed(review_policies(root, base_ref)):
        checks = review.get("checks")
        for name, argv in checks.items() if isinstance(checks, dict) else ():
            if isinstance(argv, list) and all(isinstance(a, str) for a in argv):
                registry[str(name)] = argv
    return registry
