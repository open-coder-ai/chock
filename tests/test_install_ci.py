"""`install-ci`: idempotent, never clobbers an unrelated file, and gates the coverage claim."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import chock
from chock.compile.surfaces import Surface, coverage_level
from chock.scaffold import install_ci
from chock.scaffold.install_ci import MARKER, ci_workflow_installed, main


def test_install_writes_the_workflow(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    assert dest.exists()
    assert MARKER in dest.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    first = dest.read_bytes()
    assert main([str(tmp_path)]) == 0
    assert dest.read_bytes() == first


def test_install_refuses_to_clobber_an_unrelated_workflow(tmp_path: Path) -> None:
    dest = tmp_path / ".github" / "workflows" / "chock.yml"
    dest.parent.mkdir(parents=True)
    dest.write_text("name: someone-elses-workflow\n", encoding="utf-8")

    assert main([str(tmp_path)]) != 0
    assert dest.read_text(encoding="utf-8") == "name: someone-elses-workflow\n"


def test_ci_workflow_installed_is_false_until_the_marker_is_present(tmp_path: Path) -> None:
    assert ci_workflow_installed(tmp_path) is False
    main([str(tmp_path)])
    assert ci_workflow_installed(tmp_path) is True


def test_coverage_does_not_credit_ci_gate_until_install_ci_has_run() -> None:
    """The exact defect this PR fixes, pinned at the coverage layer: emitting a compiled"""
    emitted = {Surface.CI_GATE, Surface.AMBIENT_RULE}
    assert coverage_level(emitted, "cursor", ci_gate_installed=False) == "advisory"
    assert coverage_level(emitted, "cursor", ci_gate_installed=True) == "enforced-at-commit"


def test_coverage_still_credits_git_hook_alongside_uninstalled_ci_gate() -> None:
    """git-hook's claim does not regress: it is installed automatically by `recompile` and is"""
    emitted = {Surface.GIT_HOOK, Surface.CI_GATE}
    assert coverage_level(emitted, "cursor", ci_gate_installed=False) == "enforced-at-commit"


_SHA = "0123456789abcdef0123456789abcdef01234567"


def _installed(tmp_path: Path) -> str:
    assert main([str(tmp_path)]) == 0
    return (tmp_path / ".github" / "workflows" / "chock.yml").read_text(encoding="utf-8")


def test_workflow_pins_the_engine_commit_that_generated_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install_ci, "engine_commit", lambda: _SHA)
    text = _installed(tmp_path)
    assert f'pip install "chock @ git+https://github.com/open-coder-ai/chock@{_SHA}"' in text
    assert "__ENGINE_" not in text
    assert "__COMMIT__" not in text


@pytest.mark.parametrize("commit", [None, "", "main", _SHA[:12], f"{_SHA}; rm -rf ~"])
def test_without_a_known_commit_the_workflow_pins_the_pypi_version_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit: str | None
) -> None:
    monkeypatch.setattr(install_ci, "engine_commit", lambda: commit)
    text = _installed(tmp_path)
    assert f'pip install "chock=={chock.__version__}"' in text
    assert "git+" not in text
    assert (
        f"# No engine commit was known when this was generated (a PyPI install), so this pins chock {chock.__version__}"
        in text
    )


def test_a_new_engine_commit_refreshes_the_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install_ci, "engine_commit", lambda: _SHA)
    _installed(tmp_path)
    monkeypatch.setattr(install_ci, "engine_commit", lambda: "f" * 40)
    assert "f" * 40 in _installed(tmp_path)


def test_both_rendered_workflows_parse_with_the_same_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered = []
    for commit in (_SHA, None):
        monkeypatch.setattr(install_ci, "engine_commit", lambda c=commit: c)
        rendered.append(yaml.safe_load(install_ci.render())["jobs"]["chock-gate"]["steps"])
    assert [s.get("name") for s in rendered[0]] == [s.get("name") for s in rendered[1]]
