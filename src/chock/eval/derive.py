"""Cases generated from a policy's own gate declaration."""

from __future__ import annotations

from typing import Any

from chock.eval.model import Case
from chock.gate.schema import DEPENDENCY_ALLOWLIST_KIND

UNLISTED = "chock-derived-eval-absent-package"

_MANIFEST_BODIES = {
    "requirements.txt": lambda dep: f"{dep}==1.0.0\n",
    "pyproject.toml": lambda dep: f'[project]\nname = "derived"\nversion = "0.0.1"\ndependencies = ["{dep}"]\n',
    "package.json": lambda dep: '{"name": "derived", "version": "1.0.0", "dependencies": {"%s": "^1.0.0"}}\n' % dep,
    "go.mod": lambda dep: f"module derived\n\ngo 1.21\n\nrequire (\n\tgithub.com/absent/{dep} v1.0.0\n)\n",
}

_GO_PREFIX = "github.com/absent/"

DERIVABLE_KINDS = ("forbidden_ref", DEPENDENCY_ALLOWLIST_KIND)


def _case(policy_id: str, suffix: str, category: str, prompt: str, expect: str, execute: dict[str, Any]) -> Case:
    return Case(
        id=f"derived-{suffix}",
        category=category,
        prompt=prompt,
        expect=expect,
        policy_id=policy_id,
        provenance="derived",
        execute=execute,
    )


def _forbidden_ref(policy_id: str, gate: dict[str, Any]) -> list[Case]:
    params = gate.get("params") or {}
    refs = [str(r) for r in (params.get("refs") or [])]
    events = [str(e) for e in (gate.get("on") or [])]
    cases: list[Case] = []

    for ref in refs:
        if "commit" in events:
            cases.append(
                _case(
                    policy_id,
                    f"ref-commit-{ref}",
                    "trigger",
                    f"A commit is made directly on the protected branch {ref}.",
                    "The gate blocks the commit.",
                    {"branch": ref, "files": {"note.txt": "work\n"}, "event": "commit", "expect": "block"},
                )
            )
        if "push" in events:
            cases.append(
                _case(
                    policy_id,
                    f"ref-push-{ref}",
                    "trigger",
                    f"A push targets refs/heads/{ref}.",
                    "The gate blocks the push.",
                    {"event": "push", "push_refs": [f"refs/heads/{ref}"], "expect": "block"},
                )
            )

    if refs and "commit" in events:
        cases.append(
            _case(
                policy_id,
                "ref-commit-unprotected",
                "negative_trigger",
                "A commit is made on a feature branch.",
                "The gate allows the commit.",
                {
                    "branch": "chock-eval/feature",
                    "files": {"note.txt": "work\n"},
                    "event": "commit",
                    "expect": "allow",
                },
            )
        )
    return cases


def _dependency_allowlist(policy_id: str, gate: dict[str, Any]) -> list[Case]:
    params = gate.get("params") or {}
    allowlist = str(params.get("allowlist_file") or "")
    cases: list[Case] = []

    for manifest in [str(m) for m in (params.get("manifests") or [])]:
        body = _MANIFEST_BODIES.get(manifest)
        if body is None:
            continue
        listed = _GO_PREFIX + UNLISTED if manifest == "go.mod" else UNLISTED
        cases.append(
            _case(
                policy_id,
                f"dep-block-{manifest}",
                "trigger",
                f"A commit adds an unlisted dependency to {manifest}.",
                "The gate blocks the commit.",
                {
                    "files": {manifest: body(UNLISTED)},
                    "repo_files": {allowlist: "# empty\n"} if allowlist else {},
                    "event": "commit",
                    "expect": "block",
                },
            )
        )
        cases.append(
            _case(
                policy_id,
                f"dep-allow-{manifest}",
                "negative_trigger",
                f"A commit adds a dependency to {manifest} that is on the allowlist.",
                "The gate allows the commit.",
                {
                    "files": {manifest: body(UNLISTED)},
                    "repo_files": {allowlist: f"{listed}\n"} if allowlist else {},
                    "event": "commit",
                    "expect": "allow",
                },
            )
        )
    return cases


_DERIVERS = {
    "forbidden_ref": _forbidden_ref,
    DEPENDENCY_ALLOWLIST_KIND: _dependency_allowlist,
}


def derive_cases(policy_id: str, gate: dict[str, Any] | None) -> list[Case]:
    """Every case implied by a gate declaration. Empty for kinds with no derivation."""
    if not gate:
        return []
    deriver = _DERIVERS.get(str(gate.get("kind")))
    return deriver(policy_id, gate) if deriver else []
