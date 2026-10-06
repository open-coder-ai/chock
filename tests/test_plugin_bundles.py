"""A bundle is one merged plugin per client: it denies what each member alone denies, without members colliding."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from bundle_fixtures import (
    ADVISORY_ID,
    BUNDLE_ID,
    GATE_ID,
    GUARD_ID,
    MARKER,
    SIBLING,
    build_claude_tree,
    bundle,
    denies,
    hook_commands,
    make_members,
    project,
    run_command,
    write,
)
from packaging_helpers import tree_bytes

from chock.guardrails.plugin import PROTECT_ID
from chock.plugin import bundle_build
from chock.plugin.bundle_build import CLIENTS, MergeCollisionError, merged_files

WRITE = {
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_input": {"file_path": "src/App.java", "content": MARKER},
}
CLEAN = {**WRITE, "tool_input": {"file_path": "src/App.java", "content": "class App {}"}}
RM = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
MERGED_CLIENTS = sorted(CLIENTS)


# --- one route for every client: the merged plugin -------------------------------------------------
# The Claude dependency meta-plugin and bundles.yaml are retired (builder v2 design 2.1b):
# a bundle is a selection, built by `chock install --selection`.


def test_every_client_merges_including_claude(tmp_path: Path) -> None:
    assert MERGED_CLIENTS == ["claude", "codex", "copilot", "cursor", "devin"]
    members = make_members(tmp_path)
    out = tmp_path / "dist"
    build_claude_tree(tmp_path, members, out)
    manifest = json.loads((out / BUNDLE_ID / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "dependencies" not in manifest
    assert (out / BUNDLE_ID / "hooks" / "hooks.json").is_file()


def _closure(out: Path, name: str) -> list[Path]:
    """The packages a Claude install of `name` puts on the agent: itself and its dependencies, resolved in this marketplace."""
    manifest = json.loads((out / name / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return [out / name] + [pkg for dep in manifest.get("dependencies", []) for pkg in _closure(out, dep)]


def _installed_hooks(out: Path, name: str) -> list[tuple[Path, str]]:
    found = []
    for pkg in _closure(out, name):
        hooks = pkg / "hooks" / "hooks.json"
        if hooks.is_file():
            found += [(pkg, c) for c in hook_commands(json.loads(hooks.read_text(encoding="utf-8")))]
    return found


def _blocked(installed: list[tuple[Path, str]], repo: Path, payload: dict) -> bool:
    return any(denies(run_command(command, pkg, repo, payload)) for pkg, command in installed)


def test_one_claude_bundle_install_denies_what_each_member_alone_denies(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    out = tmp_path / "dist"
    build_claude_tree(tmp_path, members, out)
    repo = project(tmp_path)
    for payload, alone in ((WRITE, GATE_ID), (RM, GUARD_ID)):
        assert _blocked(_installed_hooks(out, alone), repo, payload), f"{alone} alone must deny"
        assert _blocked(_installed_hooks(out, BUNDLE_ID), repo, payload), (
            f"the bundle install must deny what {alone} does"
        )
    assert not _blocked(_installed_hooks(out, BUNDLE_ID), repo, CLEAN)


def test_the_bundle_grades_no_stronger_than_its_weakest_member(tmp_path: Path) -> None:
    members = make_members(tmp_path, with_advisory=True)
    out = tmp_path / "dist"
    write(out / BUNDLE_ID, merged_files("claude", bundle(members), members, tmp_path))
    text = json.loads((out / BUNDLE_ID / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["description"]
    assert f"{ADVISORY_ID}: advisory only" in text
    assert f"{GUARD_ID}: refuses a matched shell command before it runs" in text
    assert text.endswith("Advisory skill only; enforcement needs chock installed in the repo.]")


def test_an_all_enforcing_bundle_states_the_enforcing_posture(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    text = json.loads(merged_files("claude", bundle(members), members, tmp_path)[Path(".claude-plugin/plugin.json")])[
        "description"
    ]
    assert "Advisory skill only" not in text and "Session-enforced" in text


# --- the merged route ----------------------------------------------------------------------------


def _merged(tmp_path: Path, client: str, *, with_advisory: bool = False) -> tuple[Path, list]:
    members = make_members(tmp_path, with_advisory=with_advisory)
    out = tmp_path / "dist" / client / BUNDLE_ID
    return write(out, merged_files(client, bundle(members), members, tmp_path)), members


def _hooks_file(out: Path) -> Path:
    return next(p for p in out.rglob("hooks.json"))


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_every_member_keeps_its_own_skills_scripts_and_sibling_package(tmp_path: Path, client: str) -> None:
    out, _ = _merged(tmp_path, client)
    for member in (GATE_ID, GUARD_ID):
        assert (out / "skills" / member / "SKILL.md").is_file()
    assert (out / "scripts" / GUARD_ID / f"{GUARD_ID}.py").is_file()
    assert (out / "scripts" / GUARD_ID / SIBLING / "__init__.py").is_file()
    assert not (out / "scripts" / SIBLING).exists(), "a sibling package stays under its member"


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_no_path_or_hook_command_collides_and_every_command_reaches_a_shipped_file(tmp_path: Path, client: str) -> None:
    out, _ = _merged(tmp_path, client)
    commands = hook_commands(json.loads(_hooks_file(out).read_text(encoding="utf-8")))
    targets = {re.search(r"--(?:guard|gate) \"?[^\s\"]*?(scripts/[^\s\"]+)", c).group(1) for c in commands}
    protect = f"scripts/{PROTECT_ID}"
    expected = {f"scripts/{GATE_ID}/gate.json", f"scripts/{GUARD_ID}/{GUARD_ID}.py", f"{protect}/{PROTECT_ID}.py"}
    assert targets - {f"{protect}/gate.json"} == expected, "one target per member and the built-in, none shared"
    for command in commands:
        paths = re.findall(r"scripts/[\w./-]+", command)
        assert paths and all((out / p).is_file() for p in paths), (command, paths)


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_the_merged_manifest_is_the_bundles_own_and_states_each_member(tmp_path: Path, client: str) -> None:
    out, _ = _merged(tmp_path, client)
    manifest_path = next(p for p in out.rglob("plugin.json") if "skills" not in p.parts)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == BUNDLE_ID
    assert f"{GUARD_ID}: " in manifest["description"] and f"{GATE_ID}: " in manifest["description"]


def test_a_merged_codex_bundle_denies_what_each_member_alone_denies(tmp_path: Path) -> None:
    out, _ = _merged(tmp_path, "codex")
    repo = project(tmp_path)
    commands = hook_commands(json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8")))
    for payload in (WRITE, RM):
        assert any(denies(run_command(c, out, repo, payload)) for c in commands)
    assert not any(denies(run_command(c, out, repo, CLEAN)) for c in commands)


def test_two_members_writing_different_bytes_to_one_path_is_a_collision(tmp_path: Path) -> None:
    files: dict[Path, str] = {}
    bundle_build._place(files, Path("LICENSE"), "a")
    bundle_build._place(files, Path("LICENSE"), "a")
    with pytest.raises(MergeCollisionError, match="different bytes"):
        bundle_build._place(files, Path("LICENSE"), "b")


def test_hook_documents_that_disagree_on_a_scalar_are_a_collision() -> None:
    with pytest.raises(MergeCollisionError, match="disagree"):
        bundle_build._merge_docs({"version": 1, "hooks": {}}, {"version": 2, "hooks": {}})


def test_a_hook_command_naming_no_member_script_is_refused() -> None:
    with pytest.raises(MergeCollisionError, match="cannot be namespaced"):
        bundle_build._repoint_command("echo hi", {"scripts/a.py": "scripts/m/a.py"})


# --- reproducibility ----------------------------------------------------------


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_bundle_output_is_byte_reproducible(tmp_path: Path, client: str) -> None:
    members = make_members(tmp_path)
    first = write(tmp_path / "one", merged_files(client, bundle(members), members, tmp_path))
    second = write(tmp_path / "two", merged_files(client, bundle(list(members)), list(members), tmp_path))
    assert tree_bytes(first) == tree_bytes(second)


def test_a_merged_bundle_without_aggregate_keeps_each_member_label_and_drops_the_posture(tmp_path: Path) -> None:
    members = make_members(tmp_path, with_advisory=True)
    manifest_rel = Path(".claude-plugin/plugin.json")
    default = json.loads(bundle_build.merged_files("claude", bundle(members), members, tmp_path)[manifest_rel])
    per_member = json.loads(
        bundle_build.merged_files("claude", bundle(members), members, tmp_path, aggregate=False)[manifest_rel]
    )
    assert default["description"].endswith("]")
    assert per_member["description"] == default["description"].rsplit(" [", 1)[0]
    assert "advise" in default["keywords"]
    assert "advise" not in per_member["keywords"]
