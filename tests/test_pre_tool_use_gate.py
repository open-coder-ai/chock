"""A declarative gate at the write path: which vendors get one, and which honestly cannot.

A policy that declares `on: [commit, tool_use]` has been asking for this all along and has
been getting only the commit half, because the emitter looked for a bash guard script and
nothing else. What it does NOT do matters as much: a pre-tool hook needs a matcher, most
vendors record no write-tool vocabulary, and inventing one would gate a tool name nobody
verified the vendor uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from chock import vendors
from chock.compile.emitters.in_agent import GATE_FILE, WRITE_FRAGMENT, emit_pre_tool_use

PATTERN = r"uses:\s*[A-Za-z0-9._/-]+@(?![0-9a-fA-F]{40})[A-Za-z0-9._/-]+"

#: The vendors agentseam records a `tools.write` vocabulary for, derived rather than listed.
RECORDED = sorted(v for v in vendors.in_agent_vendors() if vendors.write_matcher(v))


def _policy(tmp_path: Path, *, on, kind="content_regex", script=False, paths=None) -> tuple[Path, dict]:
    policy = tmp_path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    params = {"content_pattern": PATTERN} if kind == "content_regex" else {"refs": ["main"]}
    manifest = {
        "id": "pinned",
        "name": "Pinned",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {"gate": {"kind": kind, "on": list(on), "action": "block", "message": "m", "params": params}},
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    if paths is not None:
        manifest["applies_to"] = {"paths": paths}
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if script:
        impl = policy / "implementations"
        impl.mkdir(exist_ok=True)
        (impl / "pinned.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return policy, manifest


def _emit(tmp_path: Path, policy: Path, manifest: dict) -> dict[str, dict]:
    out = tmp_path / ".chock" / "compiled" / "pinned" / "pre-tool-use"
    out.mkdir(parents=True, exist_ok=True)
    written = emit_pre_tool_use(policy, out, manifest)
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in written}


# --- a policy that asked for this event ------------------------------------------------------------


def test_a_declared_tool_use_gate_now_reaches_the_write_path(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"))
    emitted = _emit(tmp_path, policy, manifest)
    assert GATE_FILE in emitted
    assert WRITE_FRAGMENT in emitted, "claude_code records write tools, so it gets a fragment"


def test_the_matcher_is_the_vendors_own_recorded_write_vocabulary(tmp_path: Path) -> None:
    """Not a literal typed here: a vendor that gains a write tool gains it in the matcher."""
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"))
    emitted = _emit(tmp_path, policy, manifest)
    assert emitted[WRITE_FRAGMENT]["matcher"] == vendors.write_matcher("claude_code")


def test_the_hook_points_at_the_compiled_gate_beside_it(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"))
    emitted = _emit(tmp_path, policy, manifest)
    command = emitted[WRITE_FRAGMENT]["hooks"][0]["command"]
    assert "--gate" in command
    assert f"pinned/pre-tool-use/{GATE_FILE}" in command


def test_the_scope_a_policy_declared_rides_into_the_compiled_gate(tmp_path: Path) -> None:
    """Without it a pattern refuses the file documenting it, so the bound must travel here."""
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"), paths=[".github/workflows/*"])
    emitted = _emit(tmp_path, policy, manifest)
    assert emitted[GATE_FILE]["paths"] == [".github/workflows/*"]


# --- what it refuses to claim ------------------------------------------------------------------------


def test_only_vendors_with_a_recorded_write_vocabulary_get_a_fragment(tmp_path: Path) -> None:
    """The others are unrecorded, not toolless. A guessed matcher is a claimed reach."""
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"))
    emitted = _emit(tmp_path, policy, manifest)
    fragments = {name for name in emitted if name != GATE_FILE}
    assert len(fragments) == len(RECORDED)
    for vendor in vendors.in_agent_vendors():
        if vendors.write_matcher(vendor) is None:
            assert not any(vendor in name for name in fragments), f"{vendor} records no write tools"


def test_a_commit_only_gate_stays_out_of_the_session(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit",))
    assert _emit(tmp_path, policy, manifest) == {}


def test_a_kind_a_write_cannot_answer_emits_nothing(tmp_path: Path) -> None:
    """forbidden_ref reads a branch name; the runner would refuse, so installing it is noise."""
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"), kind="forbidden_ref")
    assert _emit(tmp_path, policy, manifest) == {}


def test_a_policy_with_neither_a_script_nor_a_gate_emits_nothing(tmp_path: Path) -> None:
    policy = tmp_path / "policy"
    policy.mkdir()
    manifest = {
        "id": "bare",
        "name": "Bare",
        "version": "0.0.1",
        "description": "d",
        "artifact": "rule",
        "enforcement": "advise",
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert _emit(tmp_path, policy, manifest) == {}


# --- the shell path is untouched -----------------------------------------------------------------------


def test_a_guard_script_still_emits_what_it_did(tmp_path: Path) -> None:
    """The shell half must not move: it is what every enforcing policy ships today."""
    policy, manifest = _policy(tmp_path, on=("commit", "tool_use"), script=True)
    emitted = _emit(tmp_path, policy, manifest)
    assert "pretooluse.json" in emitted
    assert emitted["pretooluse.json"]["matcher"] == vendors.shell_matcher("claude_code")
    assert "--guard" in emitted["pretooluse.json"]["hooks"][0]["command"]
    assert GATE_FILE in emitted, "the gate rides beside the guard"
    assert emitted[WRITE_FRAGMENT]["matcher"] == vendors.write_matcher("claude_code")
    assert "--gate" in emitted[WRITE_FRAGMENT]["hooks"][0]["command"]


def test_the_installer_looks_for_both_fragments(tmp_path: Path) -> None:
    """Emitting a fragment nothing installs would be machinery that never runs."""
    from chock.hooks.in_agent_merged import MERGED

    globs = [w.fragment_glob for w in MERGED["claude_code"].wirings]
    for name in ("pretooluse.json", WRITE_FRAGMENT):
        assert any(Path(f"x/pre-tool-use/{name}").match(glob) for glob in globs), name
