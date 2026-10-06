"""`chock new policy <id> --kind <kind>`: five packaged templates that validate and pass their own evals as written."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from chock.lifecycle import check_main
from chock.scaffold import new

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
TOKEN = re.compile(r"__[A-Z]+__")
#: What each kind must ship beside its manifest and eval suite.
OWN_FILES = {
    "content_regex": set(),
    "guard": {"implementations/my-demo.py"},
    "script": {"implementations/check.py"},
    "rule": set(),
    "skill": {"skill/body.md"},
}


def test_every_kind_has_a_template() -> None:
    assert set(new.KINDS) == set(OWN_FILES) == {p.name for p in new.kinds_dir().iterdir() if p.is_dir()}


@pytest.mark.parametrize("kind", new.KINDS)
def test_each_template_validates_and_passes_its_own_evals(tmp_path: Path, kind: str, capsys) -> None:
    assert new.cmd_new(["policy", "demo", "--kind", kind, "--root", str(tmp_path)]) == 0
    folder = tmp_path / ".agents" / "policies" / "my-demo"
    files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert files == {"manifest.yaml", "evals/suite.yaml"} | OWN_FILES[kind]
    for path in folder.rglob("*"):
        if path.is_file():
            assert not TOKEN.search(path.read_text(encoding="utf-8")), f"{path} keeps a template token"
    capsys.readouterr()
    assert check_main(["--repo", str(tmp_path), "--only", "validate,evals"]) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "[ERROR]" not in out
    assert " FAIL " not in out


@pytest.mark.parametrize("kind", ["guard", "script"])
def test_executable_templates_are_executable(tmp_path: Path, kind: str) -> None:
    assert new.cmd_new(["policy", "demo", "--kind", kind, "--root", str(tmp_path)]) == 0
    (script,) = (tmp_path / ".agents" / "policies" / "my-demo" / "implementations").iterdir()
    assert script.stat().st_mode & 0o111


def test_outside_a_catalog_the_id_gains_the_custom_prefix_once(tmp_path: Path) -> None:
    assert new.cmd_new(["policy", "demo", "--kind", "rule", "--root", str(tmp_path)]) == 0
    assert new.cmd_new(["policy", "my-other", "--kind", "rule", "--root", str(tmp_path)]) == 0
    assert {p.name for p in (tmp_path / ".agents" / "policies").iterdir() if p.is_dir()} == {"my-demo", "my-other"}


def test_inside_a_catalog_the_id_is_kept(tmp_path: Path) -> None:
    (tmp_path / "registry.yaml").write_text("policies: []\n", encoding="utf-8")
    assert new.custom_id("demo", tmp_path) == "demo"


def test_an_existing_policy_is_never_overwritten(tmp_path: Path) -> None:
    assert new.cmd_new(["policy", "demo", "--kind", "guard", "--root", str(tmp_path)]) == 0
    manifest = tmp_path / ".agents" / "policies" / "my-demo" / "manifest.yaml"
    manifest.write_text("mine\n", encoding="utf-8")
    assert new.cmd_new(["policy", "demo", "--kind", "rule", "--root", str(tmp_path)]) == 2
    assert manifest.read_text(encoding="utf-8") == "mine\n"


@pytest.mark.parametrize("argv", [["skill", "demo", "--kind", "rule"], ["policy", "Bad_Id", "--kind", "rule"]])
def test_kind_refuses_a_skill_or_an_invalid_id(tmp_path: Path, argv: list[str]) -> None:
    assert new.cmd_new([*argv, "--root", str(tmp_path)]) == 2
    assert not (tmp_path / ".agents").exists()


def test_render_is_byte_stable_for_the_site(tmp_path: Path) -> None:
    """The site copies the templates byte for byte and fills the same three tokens; rendering is pure."""
    first = new.render_kind("guard", "my-demo", "2026-10-06")
    assert first == new.render_kind("guard", "my-demo", "2026-10-06")
    assert 'created_at: "2026-10-06T00:00:00Z"' in first[Path("manifest.yaml")]
