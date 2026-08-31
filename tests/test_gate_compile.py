"""Compile tests: declarative gate.json emission."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from conftest import baseline_policy

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.gate.build import build_gate_json


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_compile_declarative_emits_gate_json_and_shims(tmp_path: Path) -> None:
    """Compiling a declarative policy produces gate.json, the vendored runner, and shims."""
    policy_dir = baseline_policy("protect-main-branch")
    output_root = tmp_path / ".chock" / "compiled"

    result = compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    git_hook_dir = output_root / "protect-main-branch" / "git-hook"
    gate_json = git_hook_dir / "gate.json"
    assert gate_json.exists()
    assert (git_hook_dir / "git-pre-commit.sh").exists()
    assert (git_hook_dir / "git-pre-push.sh").exists()
    assert (tmp_path / ".chock" / "bin" / "gate.py").exists()

    spec = json.loads(gate_json.read_text(encoding="utf-8"))
    assert spec["kind"] == "forbidden_ref"
    assert spec["on"] == ["commit", "push"]
    assert spec["params"]["refs"] == ["main", "master"]
    assert "config_key" not in spec["params"]
    assert result.policy_id == "protect-main-branch"


def test_vendored_runner_is_byte_identical_to_source(tmp_path: Path) -> None:
    """The compiled .chock/bin/gate.py must be a verbatim copy of runner.py."""
    source = _framework_root() / "src" / "chock" / "gate" / "runner.py"
    output_root = tmp_path / ".chock" / "compiled"
    policy_dir = baseline_policy("scan-secrets")
    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    vendored = tmp_path / ".chock" / "bin" / "gate.py"
    assert vendored.read_bytes() == source.read_bytes()


def test_config_key_resolves_refs(tmp_path: Path) -> None:
    """forbidden_ref config_key is resolved and dropped from gate.json."""
    config = tmp_path / ".chock" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        yaml.safe_dump({"chock": {"defaults": {"protected_branches": ["main", "staging"]}}}),
        encoding="utf-8",
    )
    policy_dir = baseline_policy("protect-main-branch")
    spec = build_gate_json(policy_dir, tmp_path)

    assert spec is not None
    assert spec["params"]["refs"] == ["main", "staging"]
    assert "config_key" not in spec["params"]


def test_declarative_shim_probes_for_python_interpreter(tmp_path: Path) -> None:
    """The emitted shim probes for a working python3/python/py, not a hardcoded python3."""
    policy_dir = baseline_policy("scan-secrets")
    output_root = tmp_path / ".chock" / "compiled"

    compile_policy(policy_dir, targets=[Surface.GIT_HOOK.value], output_root=output_root)

    shim = output_root / "scan-secrets" / "git-hook" / "git-pre-commit.sh"
    text = shim.read_text(encoding="utf-8")
    assert "exec python3 " not in text, "shim must not hardcode a python3 invocation"
    assert "for c in python3 python py" in text
    assert '.chock/bin/gate.py" run' in text


def test_no_emission_removes_a_stale_surface_dir(tmp_path: Path) -> None:
    """A gateway gate that stops opting in must not leave its old gateway-gate.json behind."""
    from chock.compile.surfaces import Surface as _S

    policy_dir = baseline_policy("protect-main-branch")
    output_root = tmp_path / ".chock" / "compiled"
    surface_dir = output_root / "protect-main-branch" / _S.MCP_GATEWAY.value
    surface_dir.mkdir(parents=True)
    (surface_dir / "gateway-gate.json").write_text('{"kind": "egress_allowlist"}', encoding="utf-8")

    compile_policy(policy_dir, targets=[_S.MCP_GATEWAY.value], output_root=output_root)
    assert not surface_dir.exists(), "stale gateway surface dir/file survived recompile"
