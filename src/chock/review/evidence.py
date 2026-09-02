"""Build and verify reviewer evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chock.config import load_config

SCHEMA_URL = "https://open-coder-ai.github.io/chock/schemas/v0/reviewer-evidence-v1.json"

EMPTY_DIFF_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EVIDENCE_DIR = Path(".chock") / "evidence"

BUILTIN_CHECKS: dict[str, list[str]] = {
    "validate": ["validate", "{root}"],
    "eval": ["eval", "--repo", "{root}"],
    "recompile-check": ["recompile", "--repo", "{root}", "--check"],
    "verify": ["verify", "--root", "{root}"],
}

DEFAULT_UNATTESTABLE = ["tools/", ".github/workflows/"]


class EvidenceError(RuntimeError):
    """Evidence that cannot be produced or read."""


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        msg = f"git {' '.join(args)} failed: {proc.stderr.strip()}"
        raise EvidenceError(msg)
    return proc.stdout


def merge_base(root: Path, base_ref: str) -> str:
    return _git(root, "merge-base", base_ref, "HEAD").strip()


def diff_sha(root: Path, base_ref: str) -> str:
    """Digest of the change, with the evidence directory excluded."""
    diff = _git(
        root,
        "diff",
        "--no-color",
        f"{merge_base(root, base_ref)}...HEAD",
        "--",
        ".",
        f":(exclude){EVIDENCE_DIR.as_posix()}/*",
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def unattestable_paths(root: Path) -> list[str]:
    """The repository's own list. Never taken from evidence."""
    review = (load_config(root).get("chock") or {}).get("review") or {}
    paths = review.get("unattestable_paths")
    return sorted(paths) if isinstance(paths, list) and paths else sorted(DEFAULT_UNATTESTABLE)


def check_registry(root: Path) -> dict[str, list[str]]:
    """Built-in checks plus any the repository declares."""
    registry = dict(BUILTIN_CHECKS)
    review = (load_config(root).get("chock") or {}).get("review") or {}
    for name, argv in (review.get("checks") or {}).items():
        if isinstance(argv, list) and all(isinstance(a, str) for a in argv):
            registry[str(name)] = argv
    return registry


def run_check(root: Path, argv: list[str]) -> tuple[str, str]:
    """Run one registry entry. Returns (pass|fail, first line of output)."""
    from chock.cli import main as cli_main

    resolved = [a.replace("{root}", str(root)) for a in argv]
    if resolved and resolved[0] == "python":
        proc = subprocess.run(resolved, cwd=root, capture_output=True, encoding="utf-8", errors="replace")
        code, out = proc.returncode, (proc.stdout or proc.stderr)
    else:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                code = cli_main(resolved)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        out = buffer.getvalue()
    first = next((line for line in out.splitlines() if line.strip()), "")
    return ("pass" if code == 0 else "fail"), first[:2000]


def working_tree_is_dirty(root: Path) -> bool:
    return bool(_git(root, "status", "--porcelain").strip())


def build(
    root: Path, base_ref: str, produced_by: dict[str, str], checks: list[str], allow_empty: bool = False
) -> dict[str, Any]:
    """Run every named check and record the result. Attestations are added by a reviewer."""
    if not allow_empty and diff_sha(root, base_ref) == EMPTY_DIFF_SHA:
        hint = (
            "the working tree has uncommitted changes -- `diff_sha` is computed from committed state, so commit first"
            if working_tree_is_dirty(root)
            else f"HEAD is identical to {base_ref}"
        )
        msg = (
            f"nothing to attest: the diff against {base_ref} is empty ({hint}). "
            f"Pass --allow-empty to record evidence for an empty change anyway."
        )
        raise EvidenceError(msg)

    registry = check_registry(root)
    unknown = [c for c in checks if c not in registry]
    if unknown:
        msg = f"unknown check(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(registry))}"
        raise EvidenceError(msg)

    verified = []
    for name in checks:
        result, detail = run_check(root, registry[name])
        verified.append(
            {
                "check": name,
                "command": "chock " + " ".join(registry[name]).replace("{root}", "."),
                "result": result,
                "detail": detail,
            }
        )

    return {
        "$schema": SCHEMA_URL,
        "diff_sha": diff_sha(root, base_ref),
        "base_ref": base_ref,
        "head_sha": _git(root, "rev-parse", "HEAD").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "produced_by": produced_by,
        "verified": verified,
        "attested": [],
        "unattestable": unattestable_paths(root),
    }


def verify(root: Path, evidence: dict[str, Any], base_ref: str) -> list[str]:
    """Re-derive every verified claim. Returns failures; empty means the evidence holds."""
    failures: list[str] = []

    current = diff_sha(root, base_ref)
    if evidence.get("diff_sha") != current:
        return [
            f"evidence is stale: it describes diff {str(evidence.get('diff_sha'))[:12]}, "
            f"the branch is now {current[:12]}. Re-run `chock review emit`."
        ]

    expected_unattestable = unattestable_paths(root)
    if sorted(evidence.get("unattestable") or []) != expected_unattestable:
        failures.append(
            f"unattestable paths disagree with repository config: evidence says "
            f"{sorted(evidence.get('unattestable') or [])}, repo says {expected_unattestable}"
        )

    registry = check_registry(root)
    for entry in evidence.get("verified") or []:
        name = entry.get("check")
        if name not in registry:
            failures.append(f"{name}: not a known check, so nothing can re-derive it")
            continue
        expected_command = "chock " + " ".join(registry[name]).replace("{root}", ".")
        if entry.get("command") and entry["command"] != expected_command:
            failures.append(f"{name}: evidence records `{entry['command']}`, registry runs `{expected_command}`")
        actual, detail = run_check(root, registry[name])
        if actual != entry.get("result"):
            failures.append(f"{name}: evidence claims {entry.get('result')}, re-running gives {actual}. {detail}")

    return failures


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot read evidence at {path}: {exc}"
        raise EvidenceError(msg) from exc
