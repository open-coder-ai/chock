"""Discovery and loading of eval suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chock.eval.model import Case
from chock.manifest import load_manifest
from chock.validation.loading import discover_artifacts


def _suite_doc(policy_dir: Path) -> dict[str, Any]:
    suite_file = policy_dir / "evals" / "suite.yaml"
    if not suite_file.exists():
        return {}
    try:
        doc = yaml.safe_load(suite_file.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}
    if not isinstance(doc, dict):
        return {}
    suite = doc.get("suite") or doc.get("eval_suite") or {}
    return suite if isinstance(suite, dict) else {}


def load_cases(policy_dir: Path, policy_id: str) -> list[Case]:
    """Authored cases from a policy's suite.yaml. Prose-only cases carry no `execute`."""
    suite = _suite_doc(policy_dir)
    raw = suite.get("cases") or suite.get("test_cases") or []
    cases: list[Case] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        execute = entry.get("execute")
        cases.append(
            Case(
                id=str(entry.get("id", "")),
                category=str(entry.get("category", "")),
                prompt=str(entry.get("prompt", entry.get("description", ""))),
                expect=str(entry.get("expect", entry.get("expected_behavior", ""))),
                policy_id=policy_id,
                status=str(entry.get("status", "ready")),
                provenance=str(entry.get("provenance", "authored")),
                execute=execute if isinstance(execute, dict) else None,
            )
        )
    return cases


class Policy:
    """A discovered policy: its directory, manifest, and authored cases."""

    def __init__(self, policy_id: str, directory: Path, manifest: dict[str, Any]) -> None:
        self.id = policy_id
        self.dir = directory
        self.manifest = manifest

    @property
    def gate(self) -> dict[str, Any] | None:
        gate = (self.manifest.get("hook") or {}).get("gate")
        return gate if isinstance(gate, dict) and gate.get("kind") else None

    @property
    def guards(self) -> list[Path]:
        """Executable guard scripts shipped with the policy, if any."""
        impl = self.dir / "implementations"
        return sorted(impl.glob("*.sh")) if impl.is_dir() else []

    @property
    def deterministic(self) -> bool:
        """Mode is chosen from the policy, not configured."""
        return bool(self.gate) or bool(self.guards)

    def cases(self) -> list[Case]:
        return load_cases(self.dir, self.id)


def discover_policies(repo_root: Path, policy_id: str | None = None) -> list[Policy]:
    """Every policy in the repo, or the single one named. Sorted for stable output."""
    found: dict[str, Policy] = {}
    for _artifact_type, directory in discover_artifacts(Path(repo_root)):
        try:
            loaded = load_manifest(directory)
        except Exception:
            continue
        if loaded is None:
            continue
        manifest, _ = loaded
        found_id = str(manifest.get("id") or directory.name)
        if policy_id and found_id != policy_id:
            continue
        found.setdefault(found_id, Policy(found_id, directory, manifest))
    return [found[key] for key in sorted(found)]
