"""Agent Plugins packaging: conformance to the published schema, and the honesty boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.plugin.build import (
    NAMESPACE,
    SCHEMA_URL,
    PluginNameError,
    build_manifest,
    build_plugin,
    plugin_differences,
    plugin_name,
)
from chock.plugin.cli import main as plugin_main

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "chock" / "validation" / "schemas" / "agent-plugins-1.0.0.plugin.schema.json"

GATE_MANIFEST = {
    "id": "protect-main-branch",
    "name": "Protect Main Branch",
    "version": "0.0.1",
    "description": "Block direct commits and pushes to main or master.",
    "artifact": "hook",
    "enforcement": "block",
    "compliance": {"owasp_asi": ["ASI02"]},
    "provenance": {
        "author": "chock-core",
        "license": "Apache-2.0",
        "source_repo": "https://github.com/open-coder-ai/chock",
    },
    "hook": {
        "gate": {
            "kind": "forbidden_ref",
            "on": ["commit", "push"],
            "action": "block",
            "message": "Direct commits to ({refs}) are blocked.",
            "params": {"refs": ["main", "master"]},
        }
    },
}

RULE_MANIFEST = {
    "id": "code-safety",
    "name": "Code Safety Rule",
    "version": "0.0.1",
    "description": "Advisory rule with no gate.",
    "artifact": "rule",
    "enforcement": "advise",
    "rule": {"text": "never(commit): secrets|keys|tokens"},
}


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    """A policy directory on disk, since the gate resolver reads the manifest back."""

    def _make(manifest: dict, name: str | None = None) -> Path:
        pack = tmp_path / ".agents" / "policies" / (name or manifest["id"])
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        return pack

    return _make


@pytest.fixture
def validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_the_vendored_schema_is_the_one_we_claim(validator: Draft202012Validator) -> None:
    """`$schema` is a `const` in the schema, so a drifted constant invalidates every manifest."""
    assert validator.schema["properties"]["$schema"]["const"] == SCHEMA_URL


@pytest.mark.parametrize("manifest", [GATE_MANIFEST, RULE_MANIFEST], ids=["gate", "rule"])
def test_generated_manifests_conform(manifest: dict, policy, validator: Draft202012Validator) -> None:
    pack = policy(manifest)
    validator.validate(build_manifest(manifest, pack))


def test_unknown_keys_would_be_rejected(validator: Draft202012Validator) -> None:
    """Guards the reading of `additionalProperties: false` that `MANIFEST_KEYS` depends on."""
    assert not validator.is_valid({"$schema": SCHEMA_URL, "name": "x", "surface": "git-hook"})


def test_packaging_raises_no_coverage_claim(policy, tmp_path: Path) -> None:
    """Packaging a policy must not change one character of its coverage verdict."""
    pack = policy(GATE_MANIFEST)
    repo = tmp_path
    out = repo / ".chock" / "compiled"

    before = compile_policy(pack, output_root=out, agents=["claude"], repo_root=repo).coverage
    build_plugin(pack, GATE_MANIFEST, repo)
    after = compile_policy(pack, output_root=out, agents=["claude"], repo_root=repo).coverage

    assert before == after
    assert "agent-plugin" not in {s.value for s in Surface}


def test_the_skill_states_its_own_limits(policy, tmp_path: Path) -> None:
    """The advisory note is the load-bearing sentence, not decoration."""
    pack = policy(GATE_MANIFEST)
    build_plugin(pack, GATE_MANIFEST, tmp_path)
    skill = (pack / "skills" / "protect-main-branch" / "SKILL.md").read_text(encoding="utf-8")

    assert "advisory: the client reading it has no mechanism to enforce it" in skill
    assert "chock.coverage_without_chock: advisory" in skill


def test_the_skill_shows_the_resolved_gate_not_the_manifest_default(policy, tmp_path: Path) -> None:
    """Body text comes from `advisory_lines`, which reads the resolved gate."""
    pack = policy(GATE_MANIFEST)
    build_plugin(pack, GATE_MANIFEST, tmp_path)
    skill = (pack / "skills" / "protect-main-branch" / "SKILL.md").read_text(encoding="utf-8")

    assert "main|master" in skill
    assert "{refs}" not in skill


def test_output_is_byte_stable(policy, tmp_path: Path) -> None:
    """Generated files are committed, so a second build must produce identical bytes."""
    pack = policy(GATE_MANIFEST)
    build_plugin(pack, GATE_MANIFEST, tmp_path)
    first = {p: p.read_bytes() for p in sorted(pack.rglob("*")) if p.is_file()}
    build_plugin(pack, GATE_MANIFEST, tmp_path)

    assert {p: p.read_bytes() for p in sorted(pack.rglob("*")) if p.is_file()} == first


def test_check_detects_drift_and_writes_nothing(policy, tmp_path: Path) -> None:
    """`--check` must judge the tree without touching it."""
    pack = policy(GATE_MANIFEST)
    assert plugin_differences(pack, GATE_MANIFEST, tmp_path), "unpackaged policy should read as missing"
    assert not (pack / "plugin.json").exists(), "--check must not create the file it reports as missing"

    build_plugin(pack, GATE_MANIFEST, tmp_path)
    assert not plugin_differences(pack, GATE_MANIFEST, tmp_path)

    (pack / "plugin.json").write_text('{"name": "tampered"}', encoding="utf-8")
    assert any("differs" in d for d in plugin_differences(pack, GATE_MANIFEST, tmp_path))


def test_cli_check_exits_non_zero_on_drift(policy, tmp_path: Path, capsys) -> None:
    policy(GATE_MANIFEST)
    assert plugin_main(["build", "--repo", str(tmp_path), "--check"]) == 1
    assert plugin_main(["build", "--repo", str(tmp_path)]) == 0
    assert plugin_main(["build", "--repo", str(tmp_path), "--check"]) == 0
    assert "matches manifests" in capsys.readouterr().out


def test_a_policy_id_that_cannot_be_a_plugin_name_is_refused() -> None:
    """Refuse rather than sanitise."""
    assert plugin_name("scan-secrets") == "scan-secrets"
    for bad in ["Scan-Secrets", "-leading", "trailing-", "double--hyphen", "dot..dot", "x" * 65]:
        with pytest.raises(PluginNameError):
            plugin_name(bad)


def test_namespace_is_a_domain_we_control() -> None:
    """Spec section 8 says a client SHOULD base its namespace on a domain it controls."""
    assert NAMESPACE == "io.github.open-coder-ai"
