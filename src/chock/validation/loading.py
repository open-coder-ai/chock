"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml
from referencing import Registry, Resource

from chock.manifest import MANIFEST_NAMES, SKILL_MD
from chock.resources import package_data_dir
from chock.validation.report import Finding, Report

SCHEMA_DIR = package_data_dir("chock.validation", "schemas")

BUDGETS = {
    "skill_md_lines": 150,
    "description_chars": 500,
    "reference_file_lines": 300,
    "rule_lines": 2,
    "eval_suite_min_cases": 3,
    "eval_trigger_cases_min": 1,
    "eval_negative_trigger_cases_min": 1,
    "eval_behavior_cases_min": 1,
}


def _build_schema_store() -> dict[str, Any]:
    store: dict[str, Any] = {}
    for p in SCHEMA_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        schema_id = data.get("$id")
        if schema_id:
            store[schema_id] = data
    return store


SCHEMA_STORE = _build_schema_store()


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        if name.endswith(".json"):
            return json.load(f)
        return yaml.safe_load(f)


ARTIFACT_TYPES: frozenset[str] = frozenset(load_schema("manifest.schema.json")["properties"]["artifact"]["enum"])


def _registry() -> Registry:
    return Registry().with_resources((sid, Resource.from_contents(doc)) for sid, doc in SCHEMA_STORE.items())


def get_validator(name: str) -> jsonschema.Draft7Validator:
    schema = load_schema(name)
    return jsonschema.Draft7Validator(schema, registry=_registry())


def schema_validator(schema: dict[str, Any]) -> jsonschema.Draft7Validator:
    return jsonschema.Draft7Validator(schema, registry=_registry())


def validate_yaml_against_schema(data: dict[str, Any], schema: dict[str, Any], path: str, report: Report) -> bool:
    validator = schema_validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if not errors:
        return True
    for exc in errors:
        path_str = "/".join(str(p) for p in exc.path)
        report.add(Finding(path, "schema", "error", f"{exc.message} at {path_str}"))
    return False


def discover_artifacts(root: Path) -> Iterable[tuple[str, Path]]:
    for candidate in (*MANIFEST_NAMES, "subagent.yaml"):
        manifest = root / candidate
        if not manifest.exists():
            continue
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            yield ("unknown", root)
            return
        art = data.get("artifact") or ("subagent" if candidate == "subagent.yaml" else None)
        if art:
            yield (art, root)
            return
        yield ("unknown", root)
        return

    candidates = [
        (".agents/skills", "skill"),
        ("skills", "skill"),
        (".agents/policies", None),
        ("policies", None),
        ("hooks", "hook"),
        ("rules", "rule"),
        ("evals", "eval"),
        ("subagents", "subagent"),
    ]

    def _yield_policy_dir(sub: Path, default_type: str | None) -> None:
        if default_type is not None:
            yield (default_type, sub)
            return

        for candidate in (*MANIFEST_NAMES, "subagent.yaml"):
            manifest = sub / candidate
            if not manifest.exists():
                continue
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
                art = (data or {}).get("artifact")
            except yaml.YAMLError:
                yield ("unknown", sub)
                break
            yield (art or "unknown", sub)
            break

    for rel_dir, default_type in candidates:
        base = root / rel_dir
        if not base.exists():
            continue

        if default_type == "eval":
            for eval_file in base.rglob("suite.yaml"):
                if not rel_dir.startswith(".agents/"):
                    try:
                        doc = yaml.safe_load(eval_file.read_text(encoding="utf-8"))
                    except (yaml.YAMLError, OSError):
                        continue
                    if not isinstance(doc, dict) or not ("eval_suite" in doc or "suite" in doc):
                        continue
                yield ("eval", eval_file.parent)
            continue

        chock_namespace = rel_dir.startswith(".agents/")
        for sub in base.iterdir():
            if not sub.is_dir():
                continue
            if not chock_namespace and find_manifest(sub, default_type or "subagent") is None:
                continue
            yield from _yield_policy_dir(sub, default_type)


def find_manifest(artifact_dir: Path, artifact_type: str) -> Path | None:
    name_map = {
        "skill": [*MANIFEST_NAMES, SKILL_MD],
        "hook": [*MANIFEST_NAMES, "hook.yaml"],
        "rule": [*MANIFEST_NAMES, "rule.yaml"],
        "eval": ["suite.yaml"],
        "subagent": ["subagent.yaml", *MANIFEST_NAMES],
    }
    for candidate in name_map.get(artifact_type, [*MANIFEST_NAMES]):
        path = artifact_dir / candidate
        if path.exists():
            return path
    return None


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())
