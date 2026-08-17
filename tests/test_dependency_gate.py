"""Behavioural tests for the verify-dependency-exists gate.

These drive the vendored runner against a real git index rather than asserting on
manifest fields. The policy first shipped claiming ASI04 `full` coverage without anyone
executing the gate; it in fact passed hallucinated dependencies in pyproject.toml and
go.mod, and flagged name/version/scripts in package.json. A compliance claim is only
worth what an executed test says it is.

Each format is covered three ways, because all three can fail independently:
  adds an unlisted dependency  -> blocked
  adds an allowlisted one      -> allowed
  changes nothing              -> allowed (the HEAD diff; see below)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import baseline_policy

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
RUNNER = FRAMEWORK_ROOT / "src" / "chock" / "gate" / "runner.py"
POLICY_ID = "verify-dependency-exists"
POLICY = baseline_policy(POLICY_ID) / "manifest.yaml"

BASE_ALLOWLIST = "requests\ngithub.com/ok/requests\n"

# (filename, committed content, staged content, name the staged content adds)
FORMATS = [
    (
        "requirements.txt",
        "requests==2.31.0\n",
        "requests==2.31.0\nevil-pkg==1.0\n",
        "evil-pkg",
    ),
    (
        "pyproject.toml",
        '[project]\ndependencies = ["requests>=2"]\n',
        '[project]\ndependencies = ["requests>=2", "evil-pkg>=1"]\n',
        "evil-pkg",
    ),
    (
        "package.json",
        '{\n "name": "app",\n "version": "1.0.0",\n "scripts": {"b": "tsc"},\n "dependencies": {"requests": "^2"}\n}\n',
        '{\n "name": "app",\n "version": "1.0.0",\n "scripts": {"b": "tsc"},\n'
        ' "dependencies": {"requests": "^2", "evil-pkg": "^1"}\n}\n',
        "evil-pkg",
    ),
    (
        "go.mod",
        "module x\n\nrequire (\n\tgithub.com/ok/requests v1.2.3\n)\n",
        "module x\n\nrequire (\n\tgithub.com/ok/requests v1.2.3\n\tgithub.com/evil/pkg v0.1.0\n)\n",
        "github.com/evil/pkg",
    ),
]
FORMAT_IDS = [f[0] for f in FORMATS]


def _gate() -> dict:
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))["hook"]["gate"]


def _repo(tmp_path: Path, allowlist: str, filename: str, committed: str | None) -> Path:
    """Git repo with the runner vendored and, optionally, a committed baseline manifest."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", "."], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)

    gate = _gate()
    (repo / ".chock").mkdir(parents=True, exist_ok=True)
    (repo / gate["params"]["allowlist_file"]).write_text(allowlist, encoding="utf-8")
    (repo / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
    shutil.copy2(RUNNER, repo / "gate.py")

    if committed is not None:
        (repo / filename).write_text(committed, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    return repo


def _stage_and_run(repo: Path, filename: str, staged: str) -> subprocess.CompletedProcess:
    (repo / filename).write_text(staged, encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=repo, check=True)
    return subprocess.run(
        [sys.executable, "gate.py", "run", "--gate", "gate.json", "--event", "pre-commit"],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("filename,committed,staged,added", FORMATS, ids=FORMAT_IDS)
def test_unlisted_dependency_is_blocked(tmp_path: Path, filename: str, committed: str, staged: str, added: str) -> None:
    repo = _repo(tmp_path, BASE_ALLOWLIST, filename, committed)
    result = _stage_and_run(repo, filename, staged)
    output = result.stdout + result.stderr
    assert result.returncode == 1, f"{filename} should block:\n{output}"
    assert added in output, f"{filename} blocked without naming {added}:\n{output}"


@pytest.mark.parametrize("filename,committed,staged,added", FORMATS, ids=FORMAT_IDS)
def test_allowlisted_dependency_is_permitted(
    tmp_path: Path, filename: str, committed: str, staged: str, added: str
) -> None:
    repo = _repo(tmp_path, BASE_ALLOWLIST + f"{added}\n", filename, committed)
    result = _stage_and_run(repo, filename, staged)
    assert result.returncode == 0, f"{filename} blocked an allowlisted dep:\n{result.stdout}{result.stderr}"


@pytest.mark.parametrize("filename,committed,staged,added", FORMATS, ids=FORMAT_IDS)
def test_touching_a_manifest_without_adding_deps_is_allowed(
    tmp_path: Path, filename: str, committed: str, staged: str, added: str
) -> None:
    """Only newly ADDED dependencies count.

    The extractor reads the whole staged file, so without diffing against HEAD a
    pre-existing unlisted package would block any commit that merely touched the
    manifest. A gate that fires on untouched lines is one people switch off.
    """
    repo = _repo(tmp_path, "", filename, committed)
    result = _stage_and_run(repo, filename, committed + "\n")
    assert result.returncode == 0, (
        f"{filename}: touching a manifest with pre-existing unlisted deps must not block:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_package_json_metadata_keys_are_not_dependencies(tmp_path: Path) -> None:
    """The original bug: a generic quoted-key regex flagged name/version/scripts."""
    body = '{\n "name": "app",\n "version": "1.0.0",\n "scripts": {"build": "tsc"},\n "dependencies": {}\n}\n'
    repo = _repo(tmp_path, "", "package.json", None)
    result = _stage_and_run(repo, "package.json", body)
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"metadata keys were treated as dependencies:\n{output}"


def test_new_manifest_file_has_all_deps_checked(tmp_path: Path) -> None:
    """A manifest added in this commit has no HEAD version; every dep is new."""
    repo = _repo(tmp_path, "", "requirements.txt", None)
    (repo / "seed.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)

    result = _stage_and_run(repo, "requirements.txt", "brand-new-pkg==1.0\n")
    assert result.returncode == 1
    assert "brand-new-pkg" in (result.stdout + result.stderr)


def test_allowlist_matching_ignores_version_and_case(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "Requests\n", "requirements.txt", None)
    assert _stage_and_run(repo, "requirements.txt", "requests==2.31.0\n").returncode == 0


def test_comments_and_blank_lines_are_not_dependencies(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "requests\n", "requirements.txt", None)
    body = "# pinned for CVE-2024-1234\n\nrequests==2.31.0\n"
    assert _stage_and_run(repo, "requirements.txt", body).returncode == 0


def test_malformed_manifest_does_not_block(tmp_path: Path) -> None:
    """A parse error must not become a block; the gate reports what it can read."""
    repo = _repo(tmp_path, "", "pyproject.toml", None)
    result = _stage_and_run(repo, "pyproject.toml", "[project\nthis is not toml\n")
    assert result.returncode == 0, f"a malformed manifest must not block:\n{result.stdout}{result.stderr}"


def test_policy_claims_full_coverage_backed_by_the_matrix(tmp_path: Path) -> None:
    """ASI04 may claim `full` only while every watched format is exercised above."""
    manifest = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    watched = set(manifest["hook"]["gate"]["params"]["manifests"])
    assert watched == set(FORMAT_IDS), (
        "every watched format must have block/allow coverage in FORMATS; "
        f"watched={sorted(watched)} tested={sorted(FORMAT_IDS)}"
    )
    asi04 = [c for c in manifest["compliance"]["owasp_asi"] if c.get("control") == "ASI04"]
    assert asi04 and asi04[0]["coverage"] == "full"


def test_init_disables_the_policy_only_when_it_is_installed(tmp_path: Path) -> None:
    """A fresh adopter must not inherit a gate that blocks their first dependency.

    The template disables this policy because it blocks every unlisted dependency on
    arrival. The framework no longer installs it, so on an empty repo the toggle names
    nothing and `validate` warns about a decision the adopter never made -- a warning on
    every clean install. The toggle must survive exactly when the policy does.
    """
    import shutil

    from chock.scaffold.init import _write_config

    empty = tmp_path / "fresh"
    empty.mkdir()
    config = yaml.safe_load(_write_config(empty, ["claude"], agent_agnostic=True).read_text(encoding="utf-8"))
    assert config["policies"]["disabled"] == []
    assert (empty / ".chock" / "dependency-allowlist.txt").exists()

    installed = tmp_path / "with-policy"
    shutil.copytree(baseline_policy(POLICY_ID), installed / ".agents" / "policies" / POLICY_ID)
    config = yaml.safe_load(_write_config(installed, ["claude"], agent_agnostic=True).read_text(encoding="utf-8"))
    assert config["policies"]["disabled"] == [POLICY_ID]


def test_init_preserves_an_existing_policies_block(tmp_path: Path) -> None:
    """Re-running init must not undo an adopter's own enable/disable choices."""
    from chock.scaffold.init import _write_config

    repo = tmp_path / "existing"
    (repo / ".chock").mkdir(parents=True)
    (repo / ".chock" / "config.yaml").write_text(
        "chock:\n  version: '0.0.1'\npolicies:\n  disabled: []\n  overrides: {}\n",
        encoding="utf-8",
    )

    config_path = _write_config(repo, ["claude"], agent_agnostic=True)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["policies"]["disabled"] == []


def test_unsupported_manifest_format_fails_validation(tmp_path: Path) -> None:
    """A format with no extractor must be rejected at validate time, not ignored at runtime.

    Before this, `manifests: [Gemfile]` validated cleanly and then did nothing when the
    gate ran -- a policy reporting enforcement it did not provide.
    """
    from chock.gate.schema import SUPPORTED_MANIFESTS
    from chock.validation.checks_gate_shape import _validate_gate
    from chock.validation.report import Report

    def _gate_with(manifests: list[str]) -> dict:
        return {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "blocked",
            "params": {"manifests": manifests, "allowlist_file": "a.txt"},
        }

    bad = Report()
    _validate_gate(_gate_with(["Gemfile"]), "test", bad)
    assert bad.errors, "an unsupported manifest format must be a validation error"

    good = Report()
    _validate_gate(_gate_with(list(SUPPORTED_MANIFESTS)), "test", good)
    assert not good.errors, f"every supported format must validate: {[f.message for f in good.errors]}"
