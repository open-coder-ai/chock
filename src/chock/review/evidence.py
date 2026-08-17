"""Build and verify reviewer evidence.

The format's one job is keeping two kinds of claim apart. A `verified` claim is worth what an
independent re-run says it is worth; an `attested` claim is worth what the named reviewer is
worth. Blurring them would be the review-time version of crediting an enforcement surface
nothing installs -- the failure this project exists to avoid.

Three rules do the work, and each exists because the obvious implementation is unsafe:

    The verifier never runs a command from the evidence file. It looks `check` up in the
    repository's registry and runs *that*. Evidence is contributor-authored; executing a string
    from it would turn a review artefact into arbitrary code in CI.

    `unattestable` is recomputed from repo config, not read from the file. Otherwise a
    submitter shortens the list and self-certifies the checking machinery.

    `diff_sha` excludes the evidence directory. Without that, writing the evidence changes the
    diff it attests to and no file can ever be valid.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chock.config import load_config

SCHEMA_URL = "https://open-coder-ai.github.io/chock/schemas/v0/reviewer-evidence-v1.json"

#: SHA-256 of the empty string, which is what `diff_sha` computes when the diff is empty.
#: Named rather than inlined because the value is otherwise unrecognisable in output, and the
#: first time it appeared it read as a plausible digest rather than as "there is no change".
EMPTY_DIFF_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: Where evidence lives, and the path excluded from `diff_sha`.
EVIDENCE_DIR = Path(".chock") / "evidence"

#: Framework checks any adopter can re-derive. Values are argv templates; `{root}` is the only
#: substitution, so nothing here can be widened by a caller into a shell.
BUILTIN_CHECKS: dict[str, list[str]] = {
    "validate": ["validate", "{root}"],
    "eval": ["eval", "--repo", "{root}"],
    "recompile-check": ["recompile", "--repo", "{root}", "--check"],
    "verify": ["verify", "--root", "{root}"],
}

#: Paths a contributor may not self-certify when config names none. Deliberately non-empty:
#: a repo that has thought about nothing should still not accept an attestation covering its
#: own checking machinery.
DEFAULT_UNATTESTABLE = ["tools/", ".github/workflows/"]


class EvidenceError(RuntimeError):
    """Evidence that cannot be produced or read."""


def _git(root: Path, *args: str) -> str:
    # encoding pinned, not platform-preferred: `diff_sha` re-encodes this output to hash it,
    # so a locale-decoded diff (cp1252 on Windows) hashes mojibake and two machines disagree
    # about the same commit. errors="replace" keeps the digest deterministic either way.
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise EvidenceError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def merge_base(root: Path, base_ref: str) -> str:
    return _git(root, "merge-base", base_ref, "HEAD").strip()


def diff_sha(root: Path, base_ref: str) -> str:
    """Digest of the change, with the evidence directory excluded.

    Excluding it is not tidiness. The evidence file is committed alongside the change, so
    including it would mean writing the file changed the diff the file attests to -- no
    evidence could ever verify.
    """
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
    """Built-in checks plus any the repository declares.

    Repo-declared entries are safe for the same reason `unattestable_paths` is: they live in
    committed config, which CODEOWNERS routes for review. Evidence supplies none of this.
    """
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
        # Same encoding pin as _git: the first line of this output is recorded verbatim in
        # the evidence file, and `verify` compares it against a re-run on another machine.
        proc = subprocess.run(resolved, cwd=root, capture_output=True, encoding="utf-8", errors="replace")
        code, out = proc.returncode, (proc.stdout or proc.stderr)
    else:
        # Framework checks run in-process: faster, and it keeps the argv a list rather than
        # anything a shell would re-interpret.
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cli_main(resolved)
        out = buffer.getvalue()
    first = next((line for line in out.splitlines() if line.strip()), "")
    return ("pass" if code == 0 else "fail"), first[:2000]


def working_tree_is_dirty(root: Path) -> bool:
    return bool(_git(root, "status", "--porcelain").strip())


def build(
    root: Path, base_ref: str, produced_by: dict[str, str], checks: list[str], allow_empty: bool = False
) -> dict[str, Any]:
    """Run every named check and record the result. Attestations are added by a reviewer.

    Refuses an empty diff unless asked not to. `diff_sha` is computed from committed state, so
    running this with the work still uncommitted produces evidence describing *no change* while
    the checks report on a working tree that has it -- the digest is the SHA of the empty
    string, which looks like a real one. It fails safe (`verify` recomputes and reports stale
    once the work lands) but silently, hours later, and the message here is the one that would
    have saved the time.
    """
    if not allow_empty and diff_sha(root, base_ref) == EMPTY_DIFF_SHA:
        hint = (
            "the working tree has uncommitted changes -- `diff_sha` is computed from committed state, so commit first"
            if working_tree_is_dirty(root)
            else f"HEAD is identical to {base_ref}"
        )
        raise EvidenceError(
            f"nothing to attest: the diff against {base_ref} is empty ({hint}). "
            f"Pass --allow-empty to record evidence for an empty change anyway."
        )

    registry = check_registry(root)
    unknown = [c for c in checks if c not in registry]
    if unknown:
        raise EvidenceError(f"unknown check(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(registry))}")

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
    """Re-derive every verified claim. Returns failures; empty means the evidence holds.

    Attestations are deliberately absent from this function. There is nothing here to check
    them against, and reporting them as anything other than unchecked would be the overclaim
    the format exists to prevent. The caller surfaces them without a verdict.
    """
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
        raise EvidenceError(f"cannot read evidence at {path}: {exc}") from exc
