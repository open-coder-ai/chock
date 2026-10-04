"""A bundle installs once and denies what each member alone denies, without members colliding."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
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

from chock.plugin import bundle_build, bundles
from chock.plugin.bundle_build import CLIENTS, DEPENDS, MERGED, MergeCollisionError, bundle_files

WRITE = {
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_input": {"file_path": "src/App.java", "content": MARKER},
}
CLEAN = {**WRITE, "tool_input": {"file_path": "src/App.java", "content": "class App {}"}}
RM = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
MERGED_CLIENTS = sorted(name for name, client in CLIENTS.items() if client.route == MERGED)


# --- the data and its schema ----------------------------------------------------------------------


def _bundles_file(tmp_path: Path, doc: object) -> Path:
    path = tmp_path / "bundles.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


GOOD = {"id": "chock-java", "version": "0.1.0", "description": "Java.", "members": ["java-security", "scan-secrets"]}


def test_a_well_formed_bundles_file_loads_in_file_order(tmp_path: Path) -> None:
    other = {**GOOD, "id": "chock-other"}
    loaded = bundles.load_bundles(_bundles_file(tmp_path, {"bundles": [GOOD, other]}))
    assert [b["id"] for b in loaded] == ["chock-java", "chock-other"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"members": ["only-one"]}, "members"),
        ({"members": ["a-policy", "a-policy"]}, "members"),
        ({"id": "Not_A_Name"}, "id"),
        ({"version": "1.0"}, "version"),
        ({"description": ""}, "description"),
        ({"extra": 1}, "extra"),
    ],
)
def test_a_malformed_bundle_is_refused_with_the_field_named(tmp_path: Path, change: dict, message: str) -> None:
    with pytest.raises(bundles.BundleError, match=message):
        bundles.load_bundles(_bundles_file(tmp_path, {"bundles": [{**GOOD, **change}]}))


def test_a_missing_required_field_is_refused(tmp_path: Path) -> None:
    incomplete = {k: v for k, v in GOOD.items() if k != "version"}
    with pytest.raises(bundles.BundleError, match="version"):
        bundles.load_bundles(_bundles_file(tmp_path, {"bundles": [incomplete]}))


def test_duplicate_ids_and_nested_bundles_are_refused(tmp_path: Path) -> None:
    with pytest.raises(bundles.BundleError, match="duplicate"):
        bundles.load_bundles(_bundles_file(tmp_path, {"bundles": [GOOD, GOOD]}))
    outer = {**GOOD, "id": "chock-outer", "members": ["chock-java", "scan-secrets"]}
    with pytest.raises(bundles.BundleError, match="cannot contain a bundle"):
        bundles.load_bundles(_bundles_file(tmp_path, {"bundles": [GOOD, outer]}))


def test_members_must_be_known_policies_and_no_bundle_shadows_one() -> None:
    bundles.check_members([GOOD], {"java-security", "scan-secrets"})
    with pytest.raises(bundles.BundleError, match="unknown policies: java-security"):
        bundles.check_members([GOOD], {"scan-secrets"})
    with pytest.raises(bundles.BundleError, match="also a policy id"):
        bundles.check_members([GOOD], {"java-security", "scan-secrets", "chock-java"})


# --- the route each client takes ------------------------------------------------------------------


def test_claude_takes_the_dependency_route_and_every_other_client_merges() -> None:
    assert CLIENTS["claude"].route == DEPENDS
    assert MERGED_CLIENTS == ["codex", "copilot", "cursor", "devin"]


def test_the_claude_bundle_is_a_manifest_that_depends_on_its_members(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    out = tmp_path / "dist"
    build_claude_tree(tmp_path, members, out)
    manifest = json.loads((out / BUNDLE_ID / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"] == [GATE_ID, GUARD_ID]
    assert not (out / BUNDLE_ID / "hooks").exists() and not (out / BUNDLE_ID / "scripts").exists()


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
    write(out / BUNDLE_ID, bundle_files("claude", bundle(members), members, tmp_path))
    text = json.loads((out / BUNDLE_ID / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["description"]
    assert f"{ADVISORY_ID}: advisory only" in text
    assert f"{GUARD_ID}: refuses a matched shell command before it runs" in text
    assert text.endswith("Advisory skill only; enforcement needs chock installed in the repo.]")


def test_an_all_enforcing_bundle_states_the_enforcing_posture(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    text = json.loads(bundle_files("claude", bundle(members), members, tmp_path)[Path(".claude-plugin/plugin.json")])[
        "description"
    ]
    assert "Advisory skill only" not in text and "Session-enforced" in text
    assert "installs each member as a dependency" in text


# --- the merged route ----------------------------------------------------------------------------


def _merged(tmp_path: Path, client: str, *, with_advisory: bool = False) -> tuple[Path, list]:
    members = make_members(tmp_path, with_advisory=with_advisory)
    out = tmp_path / "dist" / client / BUNDLE_ID
    return write(out, bundle_files(client, bundle(members), members, tmp_path)), members


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
    assert targets == {f"scripts/{GATE_ID}/gate.json", f"scripts/{GUARD_ID}/{GUARD_ID}.py"}, (
        "one target per member, none shared"
    )
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


# --- the generic format, reproducibility ----------------------------------------------------------


def test_the_agent_plugins_bundle_carries_every_members_skill(tmp_path: Path) -> None:
    members = make_members(tmp_path)
    files = bundle_files("agent-plugins", bundle(members), members, tmp_path)
    assert {Path("plugin.json"), Path("skills") / GATE_ID / "SKILL.md", Path("skills") / GUARD_ID / "SKILL.md"} <= set(
        files
    )
    manifest = json.loads(files[Path("plugin.json")])
    assert manifest["name"] == BUNDLE_ID and "dependencies" not in manifest


@pytest.mark.parametrize("client", ["claude", "agent-plugins", *MERGED_CLIENTS])
def test_bundle_output_is_byte_reproducible(tmp_path: Path, client: str) -> None:
    members = make_members(tmp_path)
    first = write(tmp_path / "one", bundle_files(client, bundle(members), members, tmp_path))
    second = write(tmp_path / "two", bundle_files(client, bundle(list(members)), list(members), tmp_path))
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
