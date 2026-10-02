"""The manifest schema's hook gate kinds and the engine's kind registries cannot drift apart."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

from chock.compile.emitters import mcp_gateway as emitter
from chock.gate.runner import KINDS
from chock.gate.schema import GATEWAY_ONLY_KINDS, KIND_PARAM_SCHEMAS
from chock.gateway import gates as gateway_gates
from chock.validation.engine import validate_artifact
from chock.validation.loading import load_schema
from chock.validation.report import Report

SCHEMA_KINDS = set(load_schema("manifest.hook.json")["properties"]["gate"]["properties"]["kind"]["enum"])
_EGRESS = {
    "kind": "egress_allowlist",
    "on": ["tool_use"],
    "action": "block",
    "message": "host not on the egress allowlist",
    "params": {"allowed_hosts": ["api.example.com"]},
}


def test_schema_enum_equals_engine_registry() -> None:
    assert SCHEMA_KINDS == set(KINDS) | GATEWAY_ONLY_KINDS


def test_every_kind_has_a_param_schema() -> None:
    assert SCHEMA_KINDS == set(KIND_PARAM_SCHEMAS)


def test_gateway_only_kinds_have_a_gateway_runtime_and_no_git_runtime() -> None:
    assert GATEWAY_ONLY_KINDS <= set(gateway_gates.RUNTIME_KINDS)
    assert GATEWAY_ONLY_KINDS <= set(emitter.RUNTIME_KINDS)
    assert not GATEWAY_ONLY_KINDS & set(KINDS)


def _errors(tmp_path: Path, gate: dict) -> list[str]:
    source = baseline_policy("protect-main-branch")
    policy_dir = tmp_path / ".agents" / "policies" / source.name
    shutil.copytree(source, policy_dir)
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["hook"] = {"gate": gate}
    (policy_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    report = Report()
    validate_artifact("hook", policy_dir, "agnostic", report, tmp_path, registry_check=False)
    return [f"{f.check}: {f.message}" for f in report.errors]


def test_egress_allowlist_manifest_validates(tmp_path: Path) -> None:
    assert _errors(tmp_path, _EGRESS) == []


@pytest.mark.parametrize(
    ("gate", "needle"),
    [
        ({**_EGRESS, "on": ["commit"]}, "no commit/push runtime"),
        ({**_EGRESS, "on": ["tool_use", "push"]}, "no commit/push runtime"),
        ({**_EGRESS, "params": {}}, "'allowed_hosts' is a required property"),
        ({**_EGRESS, "params": {"allowed_hosts": []}}, "allowed_hosts"),
        ({**_EGRESS, "params": {"allowed_hosts": ["a.com"], "allowlist_pragma": "x"}}, "Additional properties"),
        ({**_EGRESS, "kind": "egress_allowlist_v2"}, "is not one of"),
    ],
)
def test_egress_allowlist_misuse_still_fails(tmp_path: Path, gate: dict, needle: str) -> None:
    assert any(needle in e for e in _errors(tmp_path, gate))
