"""Per-policy on/off inside the agent: every merged hook checks its own entry in the toggle file before judging."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from bundle_fixtures import BUNDLE_ID, GATE_ID, GUARD_ID
from guardrails_support import (
    MERGED_CLIENTS,
    TOGGLE,
    any_refused,
    build,
    outcomes,
    set_toggles,
    shell,
    write_call,
)

from chock.guardrails import toggle
from chock.guardrails.plugin import MEMBERS, PROTECT_ID, WRAPPER, WrapError, wrap
from chock.validation.loading import load_schema

RM = "rm -rf /"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_a_member_switched_off_allows_and_logs_one_line(
    tmp_path: Path, home: Path, client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")  # every log here lands in the test's own folders
    plugin, repo, commands = build(tmp_path, client)
    payload = shell(client, repo, RM)
    assert any_refused(commands, plugin, repo, payload, home), "on by default: no file at all"
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "on"}})
    assert any_refused(commands, plugin, repo, payload, home), "an explicit on"
    set_toggles(repo, {BUNDLE_ID: {GUARD_ID: "off"}})
    procs = outcomes(commands, plugin, repo, payload, home)
    assert not any(p.returncode or '"deny"' in p.stdout or '"block"' in p.stdout for p in procs), [
        (p.returncode, p.stdout, p.stderr) for p in procs
    ]
    log = [json.loads(line) for line in (repo / ".chock/log/gate-events.jsonl").read_text().splitlines()]
    assert [(r["policy_id"], r["bundle"], r["verdict"]) for r in log] == [(GUARD_ID, BUNDLE_ID, "off")]


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_off_reaches_only_its_own_member_and_bundle(tmp_path: Path, home: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    payload = shell(client, repo, RM)
    set_toggles(repo, {BUNDLE_ID: {GATE_ID: "off"}, "other-bundle": {GUARD_ID: "off"}})
    assert any_refused(commands, plugin, repo, payload, home)


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_a_write_gate_member_switches_too(tmp_path: Path, home: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    payload = write_call(client, repo, str(repo / "src" / "App.java"))
    if not any_refused(commands, plugin, repo, payload, home):
        pytest.skip(f"{client}: the gate is judged at turn end only, not at the write")
    set_toggles(repo, {BUNDLE_ID: {GATE_ID: "off"}})
    assert not any_refused(commands, plugin, repo, payload, home)


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        '{"version": 2, "bundles": {}}',
        '{"version": true, "bundles": {}}',
        '{"bundles": {}}',
        '{"version": 1, "bundles": {}, "extra": 1}',
        f'{{"version": 1, "bundles": {{"{BUNDLE_ID}": {{"{GUARD_ID}": "OFF"}}}}}}',
        f'{{"version": 1, "bundles": {{"{BUNDLE_ID}": {{"{GUARD_ID}": "off", "x": "off"}}}}}}',
        f'{{"version": 1, "bundles": {{"{BUNDLE_ID}": {{"{GUARD_ID}": {{"pattern": "rm"}}}}}}}}',
        f'{{"version": 1, "bundles": {{"{BUNDLE_ID}": ["{GUARD_ID}"]}}}}',
    ],
)
def test_an_invalid_file_keeps_every_member_on_with_a_warning(tmp_path: Path, home: Path, text: str) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    set_toggles(repo, text)
    procs = outcomes(commands, plugin, repo, shell("claude", repo, RM), home)
    assert any('"deny"' in p.stdout for p in procs)
    warned = [p.stderr for p in procs if "every guardrail stays on" in p.stderr]
    assert warned and all(len(w.strip().splitlines()) >= 1 for w in warned)
    assert not (repo / ".chock/log").exists(), "nothing was switched off, so nothing is logged"


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_an_unreadable_file_keeps_every_member_on(tmp_path: Path, home: Path, client: str) -> None:
    plugin, repo, commands = build(tmp_path, client)
    (repo / TOGGLE).mkdir(parents=True)
    set_toggles(home, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert any_refused(commands, plugin, repo, shell(client, repo, RM), home), "a folder governs, as all on"


def test_the_user_file_governs_only_where_the_repository_has_none(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHOCK_GATE_LOG")
    plugin, repo, commands = build(tmp_path, "claude")
    payload = shell("claude", repo, RM)
    set_toggles(home, {BUNDLE_ID: {GUARD_ID: "off"}})
    assert not any_refused(commands, plugin, repo, payload, home)
    assert (home / ".chock/log/gate-events.jsonl").is_file(), "logged beside the governing file"
    set_toggles(repo, {})
    assert any_refused(commands, plugin, repo, payload, home), "the repository's own file governs it"
    outside = tmp_path / "scratch"
    outside.mkdir()
    assert not any_refused(commands, plugin, outside, shell("claude", outside, RM), home)


def test_the_built_in_protection_cannot_be_switched_off(tmp_path: Path, home: Path) -> None:
    plugin, repo, commands = build(tmp_path, "claude")
    set_toggles(repo, {BUNDLE_ID: {PROTECT_ID: "off", GUARD_ID: "off"}})
    payload = shell("claude", repo, f"echo '{{}}' > {TOGGLE}")
    assert any_refused(commands, plugin, repo, payload, home)
    assert all("--member chock-guardrails-protect" not in c for c in commands)


@pytest.mark.parametrize("client", MERGED_CLIENTS)
def test_every_member_hook_is_wrapped_and_the_plugin_lists_its_members(tmp_path: Path, client: str) -> None:
    plugin, _repo, commands = build(tmp_path, client)
    member_commands = [c for c in commands if PROTECT_ID not in c]
    assert member_commands and all(WRAPPER in c and f"--bundle {BUNDLE_ID} --member " in c for c in member_commands)
    assert (plugin / WRAPPER).read_text(encoding="utf-8") == Path(toggle.__file__).read_text(encoding="utf-8")
    listed = json.loads((plugin / MEMBERS).read_text(encoding="utf-8"))
    assert listed["bundle"] == BUNDLE_ID and {m["id"] for m in listed["members"]} == {GATE_ID, GUARD_ID}
    skill = (plugin / "skills/customize-guardrails/SKILL.md").read_text(encoding="utf-8")
    assert f"`{GUARD_ID}`" in skill and f"`{GATE_ID}`" in skill and f"--bundle {BUNDLE_ID}" in skill


def test_a_command_not_running_the_adapter_once_is_refused() -> None:
    with pytest.raises(WrapError):
        wrap('python3 "x/scripts/other.py" --guard "g"', "claude_code", "b-b-b", "m-m-m")
    with pytest.raises(WrapError):
        wrap('python3 "x/scripts/claude_code.py" --guard "g"', "claude_code", "b-b-b", "m; rm -rf /")


@pytest.mark.parametrize(
    ("text", "valid"),
    [
        ('{"version": 1, "bundles": {}}', True),
        ('{"version": 1, "bundles": {"chock-guardrails": {"block-x": "off", "my-own": "on"}}}', True),
        ('{"version": 1, "bundles": {"chock-guardrails": {"block-x": "maybe"}}}', False),
        ('{"version": 1, "bundles": {"Bad": {}}}', False),
        ('{"version": 1, "bundles": {"ok-name": {"x": "on"}}}', False),
        ('{"version": 1}', False),
        ("[]", False),
    ],
)
def test_the_runtime_parser_and_the_committed_schema_agree(text: str, *, valid: bool) -> None:
    schema = load_schema("guardrails.schema.json")
    document = json.loads(text)
    assert jsonschema.Draft7Validator(schema).is_valid(document) is valid
    if valid:
        toggle.parse(text)
    else:
        with pytest.raises(toggle.ToggleError):
            toggle.parse(text)
