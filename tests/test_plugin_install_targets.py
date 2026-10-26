"""goose, grok, antigravity and openhands plugins: the documented layout, each runtime's grammar, a local install."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
import yaml
from bundle_fixtures import ADVISORY_ID, GATE_ID, GUARD_ID, bundle, hook_commands, make_members, project, run_command
from install_fixtures import make_catalog, selection, write_selection
from packaging_helpers import golden_posix, tree_bytes
from runtime_payloads import DENY_ON_THE_WIRE, PAYLOADS

from chock.guardrails import toggle
from chock.install import cli, package, place
from chock.install.selection import DEFAULT_BUNDLE
from chock.plugin import antigravity, hook_dir
from chock.plugin import cli as plugin_cli
from chock.plugin.build import PluginNameError
from chock.plugin.bundle_build import CLIENTS, merged_files

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

TARGETS = ("goose", "grok", "antigravity", "openhands")
INSTALL_CLIENTS = TARGETS
GOLDEN = Path(__file__).parent / "fixtures" / "plugin_targets"
#: (manifest, hooks file) each vendor page documents (src/chock/plugin/data/stores/<format>.json cites them).
LAYOUT = {
    "goose": (None, "hooks/hooks.json"),
    "grok": (None, "hooks/hooks.json"),
    "antigravity": ("plugin.json", "hooks.json"),
    "openhands": (".plugin/plugin.json", "hooks/hooks.json"),
}
BINARY = {"grok": "grok", "antigravity": "agy"}


def snapshot(fmt: str, root: Path) -> dict:
    """What the golden file pins: the file list, the manifest and the hooks document of a demo bundle."""
    members = make_members(root, with_advisory=True)
    files = merged_files(fmt, bundle(members), members, root)
    manifest_rel, hooks_rel = LAYOUT[fmt]
    return {
        "files": sorted(p.as_posix() for p in files),
        "manifest": json.loads(files[Path(manifest_rel)]) if manifest_rel else None,
        "hooks": json.loads(files[Path(hooks_rel)]),
    }


@pytest.mark.parametrize("fmt", TARGETS)
def test_a_build_matches_its_golden_layout_manifest_and_hooks(tmp_path: Path, fmt: str, monkeypatch) -> None:
    golden_posix(monkeypatch, GOLDEN / f"{fmt}.json", lambda: snapshot(fmt, tmp_path))


@pytest.mark.parametrize("fmt", TARGETS)
def test_the_layout_is_the_documented_one(tmp_path: Path, fmt: str) -> None:
    found = snapshot(fmt, tmp_path)
    manifest_rel, hooks_rel = LAYOUT[fmt]
    assert CLIENTS[fmt].layout()[:2] == (manifest_rel, hooks_rel)
    assert hooks_rel in found["files"]
    assert not any(f.endswith("plugin.json") for f in found["files"] if not manifest_rel)
    for member in (GATE_ID, GUARD_ID, ADVISORY_ID):
        assert f"skills/{member}/SKILL.md" in found["files"]


def test_goose_entries_fail_closed_and_antigravity_keeps_its_hook_group(tmp_path: Path) -> None:
    goose = snapshot("goose", tmp_path / "g")["hooks"]["hooks"]
    pre_tool = [entry for rule in goose["PreToolUse"] for entry in rule["hooks"]]
    assert pre_tool and all(entry["on_failure"] == "block" for entry in pre_tool)
    assert all("${PLUGIN_ROOT}/scripts/" in c for c in hook_commands(goose))
    assert all("${GROK_PLUGIN_ROOT}/scripts/" in c for c in hook_commands(snapshot("grok", tmp_path / "k")["hooks"]))
    antigravity = snapshot("antigravity", tmp_path / "a")
    assert list(antigravity["hooks"]) == ["agentseam"]
    assert set(antigravity["hooks"]["agentseam"]) == {"PreToolUse", "Stop"}
    assert all(hook_dir.ROOT_TOKEN in c for c in hook_commands(antigravity["hooks"]))


def test_the_antigravity_manifest_holds_only_the_schemas_two_fields(tmp_path: Path) -> None:
    manifest = snapshot("antigravity", tmp_path)["manifest"]
    assert set(manifest) == {"name", "description"}
    assert manifest["name"] == "demo-bundle"
    assert "absolute path" in antigravity.manifest_posture(enforced=True, guard=True)
    with pytest.raises(PluginNameError, match="Antigravity"):
        antigravity.build_antigravity_manifest({"id": "a.b"}, tmp_path, enforced=False)


@pytest.mark.parametrize("fmt", TARGETS)
def test_the_runtime_answers_its_agents_golden_payload_in_its_own_grammar(tmp_path: Path, fmt: str) -> None:
    members = make_members(tmp_path)
    guard = next(m for m in members if m.id == GUARD_ID)
    out = tmp_path / "pkg"
    agent = CLIENTS[fmt].agent
    files = hook_dir.resolve_root(CLIENTS[fmt].files(guard.policy_dir, guard.manifest, tmp_path), out)
    for rel, content in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(content, encoding="utf-8")
    commands = hook_commands(json.loads((out / LAYOUT[fmt][1]).read_text(encoding="utf-8")))
    repo = project(tmp_path)

    def answers(command: str) -> list:
        payload = json.loads(json.dumps(PAYLOADS[agent](command)).replace('"/x"', json.dumps(repo.as_posix())))
        return [run_command(c, out, repo, payload) for c in commands]

    denied = answers("rm -rf /")
    assert any(p.returncode == 0 and f'"{DENY_ON_THE_WIRE[agent]}"' in p.stdout for p in denied), denied
    assert not any(DENY_ON_THE_WIRE[agent] in p.stdout for p in answers("ls"))


@pytest.mark.parametrize("fmt", TARGETS)
def test_chock_plugin_build_writes_a_target_and_check_finds_it_current(tmp_path: Path, fmt: str) -> None:
    members = make_members(tmp_path)
    args = ["build", "--repo", str(tmp_path), "--format", fmt, "--out-dir", str(tmp_path / "dist")]
    assert plugin_cli.main(args) == 0
    built = tmp_path / "dist" / fmt / GUARD_ID
    assert (built / LAYOUT[fmt][1]).is_file()
    assert hook_dir.ROOT_TOKEN not in (built / LAYOUT[fmt][1]).read_text(encoding="utf-8")
    assert plugin_cli.main([*args, "--check"]) == 0
    assert {m.id for m in members} <= {p.name for p in (tmp_path / "dist" / fmt).iterdir()}


def test_antigravity_hooks_name_the_folder_they_were_written_to(tmp_path: Path) -> None:
    files = {Path("hooks.json"): f'"{hook_dir.ROOT_TOKEN}/scripts/antigravity.py"'}
    assert (
        hook_dir.resolve_root(files, tmp_path / "p")[Path("hooks.json")]
        == f'"{(tmp_path / "p").as_posix()}/scripts/antigravity.py"'
    )


def test_a_windows_folder_is_named_with_forward_slashes() -> None:
    folder = PureWindowsPath(r"C:\Users\me\.chock\marketplace\antigravity\chock-guardrails")
    assert hook_dir.root_path(folder) == "C:/Users/me/.chock/marketplace/antigravity/chock-guardrails"
    files = {Path("hooks.json"): f'"{hook_dir.ROOT_TOKEN}/scripts/launch.sh"'}
    assert "C:/Users/me/" in hook_dir.resolve_root(files, folder)[Path("hooks.json")]


def test_a_windows_profile_with_a_space_is_named_as_one_path() -> None:
    folder = PureWindowsPath(r"C:\Users\Jo Smith\.chock\marketplace\antigravity\chock-guardrails")
    files = {Path("hooks.json"): f'"{hook_dir.ROOT_TOKEN}/scripts/launch.sh"'}
    resolved = hook_dir.resolve_root(files, folder)[Path("hooks.json")]
    assert resolved == '"C:/Users/Jo Smith/.chock/marketplace/antigravity/chock-guardrails/scripts/launch.sh"'


def test_a_spaced_root_reaches_the_launcher_as_exact_single_arguments(tmp_path: Path) -> None:
    """Executed: the rendered Antigravity command, run by sh, hands each path to the launcher whole."""
    root = tmp_path / "First Last" / "plugin dir"
    stub = "import json, sys\nprint(json.dumps(sys.argv[1:]))\n"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "argv.py").write_text(stub, encoding="utf-8")
    launcher = f'exec "{sys.executable}" "$(dirname "$0")/argv.py" "$@"\n'
    (root / "scripts" / "launch.sh").write_text(launcher, encoding="utf-8")
    command = hook_dir.hook_command(antigravity.SPEC, "--guard", "g.py")
    resolved = hook_dir.resolve_root({Path("c"): command}, root)[Path("c")]
    done = subprocess.run(["sh", "-c", resolved], cwd=project(tmp_path), capture_output=True, text=True, check=False)
    scripts = root.as_posix() + "/scripts"
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [f"{scripts}/antigravity.py", "--guard", f"{scripts}/g.py"]


@pytest.mark.parametrize(
    "folder",
    [Path("/home/a\tb/p"), Path("/home/a\nb/p"), Path("/home/a\u00a0b/p"), Path("/home/a$b/p"), Path('/x/"q"/p')],
)
def test_a_folder_a_quoted_hook_command_cannot_carry_is_refused(folder) -> None:
    with pytest.raises(ValueError, match="choose another --dest"):
        hook_dir.resolve_root({Path("hooks.json"): hook_dir.ROOT_TOKEN}, folder)


# --- chock install --client goose|grok|antigravity -------------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path) -> tuple[Path, str]:
    return make_catalog(tmp_path)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def _install(tmp_path: Path, root: Path, ref: str, client: str, *extra: str) -> int:
    base = selection(root, ref)
    picks = [{"from": "catalog", **p} for p in base["policies"]]
    data = {**base, "schema": 2, "client": client, "bundle": {"version": "2.0.0"}, "policies": picks}
    path = write_selection(tmp_path / "chock.selection.yaml", data)
    return cli.main(["--selection", str(path), "--allow-source", str(root), *extra])


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _format(client: str) -> str:
    return package.client(client)["format"]


@pytest.mark.parametrize("client", INSTALL_CLIENTS)
def test_install_stages_the_folder_prints_the_steps_and_touches_nothing_else(
    catalog, tmp_path: Path, home: Path, client: str, capsys, monkeypatch
) -> None:
    root, ref = catalog
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p))
    absent = BINARY.get(client)
    if absent:
        assert shutil.which(absent) is None, f"{absent} is on PATH; this test needs it absent"
    before = _tree(home)
    code = _install(tmp_path, root, ref, client, "--apply")
    out = capsys.readouterr()
    folder = place.plugin_dir(client, place.default_dest(client), DEFAULT_BUNDLE)
    assert code == (1 if absent else 0)
    assert (folder / LAYOUT[_format(client)][1]).is_file() and (folder / package.MARKER).is_file()
    added = _tree(home) - before
    rel = folder.relative_to(home).as_posix()
    assert all(p == rel or p.startswith(f"{rel}/") or rel.startswith(f"{p}/") for p in added), added
    for step in package.client(client)["steps"]:
        if "command" in step:
            assert " ".join(step["command"][:3]) in out.out
    if absent:
        assert f"--apply needs the `{absent}` command on PATH" in out.err


@pytest.mark.parametrize("client", INSTALL_CLIENTS)
def test_a_second_install_changes_nothing(catalog, tmp_path: Path, home: Path, client: str) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, client) == 0
    folder = place.plugin_dir(client, place.default_dest(client), DEFAULT_BUNDLE)
    first = tree_bytes(folder)
    assert _install(tmp_path, root, ref, client) == 0
    assert tree_bytes(folder) == first


def test_the_goose_plugin_is_a_user_plugin_under_dot_agents(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, "goose") == 0
    assert (home / ".agents" / "plugins" / DEFAULT_BUNDLE / "hooks" / "hooks.json").is_file()


def test_antigravity_install_names_its_final_folder_not_the_staging_one(catalog, tmp_path: Path, home: Path) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, "antigravity") == 0
    folder = place.plugin_dir("antigravity", place.default_dest("antigravity"), DEFAULT_BUNDLE)
    commands = hook_commands(json.loads((folder / "hooks.json").read_text(encoding="utf-8")))
    assert commands and all(f'"{folder.as_posix()}/scripts/' in c for c in commands)


THROUGH = "best-effort, and a hook error lets the action through (agentseam vendor-docs): "
CONFIGURABLE = "best-effort, and what a hook error does is configurable (agentseam vendor-docs): "


@pytest.mark.parametrize(
    ("client", "prefix", "evidence"),
    [
        ("goose", CONFIGURABLE, "agentseam/issues/177"),
        ("grok", THROUGH, "agentseam/issues/188"),
        ("antigravity", THROUGH, "agentseam/issues/129"),
        ("openhands", THROUGH, "agentseam/issues/181"),
    ],
)
def test_labels_come_from_the_tier_table_and_warnings_link_the_evidence_issue(
    catalog, tmp_path: Path, home: Path, capsys, client: str, prefix: str, evidence: str
) -> None:
    root, ref = catalog
    assert _install(tmp_path, root, ref, client) == 0
    out = capsys.readouterr().out
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  demo-")}
    assert f"{prefix}refuses a matched shell command" in lines[GUARD_ID]
    assert "advisory only" in lines[ADVISORY_ID] and prefix not in lines[ADVISORY_ID]
    kept = {"goose": "sh must be on PATH", "grok": "returns malformed output", "antigravity": "only at turn end"}
    witnessed = client in kept
    assert ("warning: Untested: chock has not seen an install work in this client in a live run" in out) != witnessed
    assert {"Evidence wanted" in out, evidence in out} == {not witnessed}
    assert kept.get(client, "") in out


def test_an_ask_gate_is_labelled_not_enforced_where_the_client_cannot_ask(catalog, tmp_path: Path) -> None:
    members = make_members(tmp_path / "m")
    gate = next(m for m in members if m.id == GATE_ID)
    gate.manifest["hook"]["gate"]["action"] = "ask"
    (gate.policy_dir / "manifest.yaml").write_text(yaml.safe_dump(gate.manifest), encoding="utf-8")
    labels = {label.policy_id: label.says for label in package.labels(members, tmp_path / "m", "goose")}
    assert labels[GATE_ID].endswith(". The ask is not enforced here (goose cannot prompt for confirmation)")
    # Antigravity's gate runs at Stop only, where agentseam records it cannot prompt either.
    labels = {label.policy_id: label.says for label in package.labels(members, tmp_path / "m", "antigravity")}
    assert labels[GATE_ID].endswith(". The ask is not enforced here (Antigravity cannot prompt at Stop)")


def test_the_toggle_lookup_reads_goose_and_antigravity_folders(tmp_path: Path) -> None:
    goose = json.dumps({"event": "PreToolUse", "working_dir": str(tmp_path / "g")}).encode()
    antigravity = json.dumps({"toolCall": {}, "workspacePaths": [str(tmp_path / "a")]}).encode()
    assert toggle._wheres(goose) == [tmp_path / "g"]
    assert toggle._wheres(antigravity) == [tmp_path / "a"]
