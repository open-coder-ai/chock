"""A built plugin runs one pinned index per (event, matcher): the verdicts of its per-policy hooks, and `--root` cannot be used to escape."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from bundle_fixtures import ADVISORY_ID, GUARD_ID, bundle, hook_commands, make_members, project, run_command, write
from runtime_payloads import DENY_ON_THE_WIRE, PAYLOADS

from chock.gate.multi import load_index, off_from_argv, root_from_argv
from chock.plugin import hook_dir
from chock.plugin.bundle_build import merged_files
from chock.plugin.clients import CLIENTS

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

RUNNABLE = sorted(name for name, client in CLIENTS.items() if client.agent in PAYLOADS)
PIN = re.compile(r"--index-sha256 [0-9a-f]{64}")
INDEX_REF = re.compile(r'--multi "?[^" ]*/(scripts/chock_index/[^" ]+\.json)"?')


def _sha(text: bytes | str) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def _install(client: str, files: dict[Path, str], out: Path) -> dict[str, Any]:
    """The package written where a client would run it, plugin-root token resolved; its hooks document."""
    write(out, hook_dir.resolve_root(files, out))
    return json.loads((out / CLIENTS[client].layout()[1]).read_text(encoding="utf-8"))


def _verdicts(client: str, out: Path, repo: Path, command: str) -> tuple[bool, str]:
    """(whether any hook denied, the text the denying hooks spoke) for a shell command."""
    agent = CLIENTS[client].agent
    doc = json.loads((out / CLIENTS[client].layout()[1]).read_text(encoding="utf-8"))
    payload = json.loads(json.dumps(PAYLOADS[agent](command)).replace('"/x"', json.dumps(repo.as_posix())))
    denied, spoke = False, []
    for hook in hook_commands(doc):
        proc = run_command(hook, out, repo, payload)
        assert proc.returncode in (0, 2), (hook, proc.stdout, proc.stderr)
        if proc.returncode == 2 or DENY_ON_THE_WIRE[agent] in proc.stdout:
            denied = True
            spoke.append(proc.stdout if proc.stdout.strip() else proc.stderr)
    return denied, "\n".join(spoke)


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_a_single_policy_plugin_folds_to_a_one_member_index_of_its_per_policy_hooks(
    tmp_path: Path, client: str
) -> None:
    guard = next(m for m in make_members(tmp_path) if m.id == GUARD_ID)
    per_policy = CLIENTS[client].files(guard.policy_dir, guard.manifest, tmp_path, folded=False)
    folded = CLIENTS[client].files(guard.policy_dir, guard.manifest, tmp_path)
    hooks_rel = Path(CLIENTS[client].layout()[1])
    commands = hook_commands(json.loads(folded[hooks_rel]))
    pinned = [c for c in commands if "--multi" in c]
    assert pinned and not any(" --guard " in c for c in commands), commands
    index_rel = Path(INDEX_REF.search(pinned[0]).group(1))
    body = folded[index_rel]
    assert f"--index-sha256 {_sha(body)}" in pinned[0]
    members = json.loads(body)["members"]
    assert [m["argv"][0] for m in members] == ["--guard"]
    assert set(folded) - set(per_policy) == {index_rel}
    for member in members:
        assert all(not a.startswith("/") and ".." not in a.split("/") for a in member["argv"][1:])
        assert {Path(rel): sha for rel, sha in member["files"].items()} == {
            Path(rel): _sha(folded[Path(rel)]) for rel in member["files"]
        }


@pytest.mark.parametrize("client", RUNNABLE)
def test_a_built_plugin_answers_as_its_per_policy_hooks_do(tmp_path: Path, client: str) -> None:
    members = make_members(tmp_path, with_advisory=True)
    repo = project(tmp_path)
    answers = {}
    for folded in (False, True):
        out = tmp_path / ("folded" if folded else "per-policy")
        _install(client, merged_files(client, bundle(members), members, tmp_path, folded=folded), out)
        commands = hook_commands(json.loads((out / CLIENTS[client].layout()[1]).read_text(encoding="utf-8")))
        assert any("--multi" in c for c in commands) == folded
        answers[folded] = {c: _verdicts(client, out, repo, c) for c in ("rm -rf /", "ls -la")}
    assert answers[True]["rm -rf /"][0] and "no rm -rf" in answers[True]["rm -rf /"][1]
    for command in ("rm -rf /", "ls -la"):
        per, one = answers[False][command], answers[True][command]
        assert one[0] == per[0]
        assert ("no rm -rf" in one[1]) == ("no rm -rf" in per[1])


@pytest.mark.parametrize("client", RUNNABLE)
def test_a_single_policy_plugin_answers_as_its_per_policy_hooks_do(tmp_path: Path, client: str) -> None:
    guard = next(m for m in make_members(tmp_path) if m.id == GUARD_ID)
    repo = project(tmp_path)
    out_for = {}
    for folded in (False, True):
        out = tmp_path / ("folded" if folded else "per-policy")
        _install(client, CLIENTS[client].files(guard.policy_dir, guard.manifest, tmp_path, folded=folded), out)
        out_for[folded] = {c: _verdicts(client, out, repo, c) for c in ("rm -rf /", "ls -la")}
    assert out_for[True]["rm -rf /"][0] and out_for[True] == out_for[False]


@pytest.mark.parametrize("client", RUNNABLE)
def test_a_bundle_folds_its_members_into_one_entry_per_event_and_matcher(tmp_path: Path, client: str) -> None:
    members = make_members(tmp_path, with_advisory=True)
    doc = json.loads(merged_files(client, bundle(members), members, tmp_path)[Path(CLIENTS[client].layout()[1])])
    commands = [c for c in hook_commands(doc) if "--multi" in c]
    assert commands and all("--members" in c and "--member " not in c for c in commands), commands


# --- refusals through a built plugin ----------------------------------------------------------------------------


def _built(tmp_path: Path) -> tuple[Path, Path, str]:
    """(package, repo, the one folded hook command) of the claude guard plugin."""
    guard = next(m for m in make_members(tmp_path) if m.id == GUARD_ID)
    out = tmp_path / "pkg"
    _install("claude", CLIENTS["claude"].files(guard.policy_dir, guard.manifest, tmp_path), out)
    doc = json.loads((out / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    command = next(c for c in hook_commands(doc) if "--multi" in c)
    return out, project(tmp_path), command


def _refused(out: Path, repo: Path, command: str, bash: str = "rm -rf /") -> str:
    proc = run_command(command, out, repo, PAYLOADS["claude_code"](bash))
    assert proc.returncode == 0 and '"deny"' in proc.stdout, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout + proc.stderr


def _reindex(out: Path, command: str, edit) -> str:
    """The command pinned to an index changed by `edit(members)`; the new index replaces the old on disk."""
    rel = INDEX_REF.search(command).group(1)
    data = json.loads((out / rel).read_text(encoding="utf-8"))
    edit(data["members"])
    body = json.dumps(data, indent=2, sort_keys=True) + "\n"
    (out / rel).write_text(body, encoding="utf-8")
    return PIN.sub(f"--index-sha256 {_sha(body)}", command)


def test_the_built_command_runs_and_denies_with_its_root(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    assert "--root" in command and "scripts/chock_index/" in command
    assert "no rm -rf" in _refused(out, repo, command)
    assert not run_command(command, out, repo, PAYLOADS["claude_code"]("ls")).stdout.count("deny")


def test_a_checkout_that_converted_line_endings_still_matches_its_pins(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    for path in [*(out / "scripts").rglob("*.py"), *(out / "scripts" / "chock_index").glob("*.json")]:
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert "no rm -rf" in _refused(out, repo, command)


def test_a_bad_pin_refuses(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    assert "does not match the hash the hook pins" in _refused(
        out, repo, PIN.sub(f"--index-sha256 {'0' * 64}", command)
    )


def test_a_drifted_member_file_refuses(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    script = out / "scripts" / f"{GUARD_ID}.py"
    script.write_text(script.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert "does not match the hash the policy index pins" in _refused(out, repo, command, "ls")


@pytest.mark.parametrize("escape", ["../outside.py", "/etc/passwd", "C:/outside.py", "scripts/../../outside.py"])
def test_a_path_that_escapes_the_root_refuses_even_when_pinned(tmp_path: Path, escape: str) -> None:
    out, repo, command = _built(tmp_path)

    def point(members: list[dict]) -> None:
        members[0]["argv"] = ["--guard", escape]

    assert "outside the repository root" in _refused(out, repo, _reindex(out, command, point), "ls")


def test_an_escaping_file_pin_refuses_even_when_pinned(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)

    def point(members: list[dict]) -> None:
        members[0]["files"] = {"../outside.py": _sha("x")}

    assert "outside the repository root" in _refused(out, repo, _reindex(out, command, point), "ls")


def test_an_empty_index_refuses(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    assert "lists no policies" in _refused(out, repo, _reindex(out, command, lambda members: members.clear()), "ls")


def test_an_empty_root_refuses(tmp_path: Path) -> None:
    out, repo, command = _built(tmp_path)
    assert "empty plugin root" in _refused(out, repo, re.sub(r'--root "[^"]*"', '--root ""', command), "ls")


# --- load_index, root and flags ----------------------------------------------------------------------------------


def _index(root: Path, member: dict) -> tuple[Path, str]:
    path = root / "index.json"
    body = json.dumps({"members": [member]})
    path.write_text(body, encoding="utf-8")
    return path, _sha(body)


def test_load_index_joins_a_rooted_member_to_the_root_and_a_cwd_member_stays_relative(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "g.py"
    script.write_text("x", encoding="utf-8")
    path, pin = _index(tmp_path, {"argv": ["--guard", "scripts/g.py"], "files": {"scripts/g.py": _sha("x")}})
    rooted, why = load_index(str(path), pin, str(tmp_path), rooted=True)
    assert why is None and rooted[0]["argv"] == ["--guard", str(tmp_path / "scripts" / "g.py")]
    plain, why = load_index(str(path), pin, str(tmp_path))
    assert why is None and plain[0]["argv"] == ["--guard", "scripts/g.py"]


@pytest.mark.parametrize("escape", ["../g.py", "/g.py", "C:/g.py", "a/../../g.py", "\\g.py"])
def test_load_index_refuses_an_escaping_path_whatever_the_root(tmp_path: Path, escape: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "g.py").write_text("x", encoding="utf-8")
    path, pin = _index(root, {"argv": ["--guard", escape], "files": {}})
    for rooted in (False, True):
        members, why = load_index(str(path), pin, str(root), rooted=rooted)
        assert members is None and "outside the repository root" in why


def test_load_index_refuses_an_empty_root(tmp_path: Path) -> None:
    path, pin = _index(tmp_path, {"argv": ["--guard", "g.py"], "files": {}})
    members, why = load_index(str(path), pin, "", rooted=True)
    assert members is None and "empty plugin root" in why


def test_the_flags_are_read_from_the_command_line() -> None:
    assert root_from_argv(["--multi", "i", "--root", "/r"]) == "/r"
    assert root_from_argv(["--multi", "i"]) is None
    assert root_from_argv(["--root"]) == ""
    assert off_from_argv(["--off", "a,b"]) == {"a", "b"}
    assert off_from_argv(["--multi", "i"]) == set()
    assert ADVISORY_ID


def test_an_absent_or_failed_toggle_lookup_leaves_every_member_on(tmp_path: Path, monkeypatch) -> None:
    from chock.guardrails import toggle

    index = tmp_path / "index.json"
    index.write_text(json.dumps({"members": [{"argv": [], "files": {}, "member": "mem-one"}]}), encoding="utf-8")
    payload = json.dumps({"cwd": str(tmp_path), "session_id": "s"}).encode("utf-8")
    argv = ["--bundle", "bun-dle", "--members", "adapter.py", "--multi", str(index)]
    off = {"bun-dle": {"mem-one": "off"}}
    monkeypatch.setattr(toggle, "load", lambda _start: (tmp_path / "g.json", "repo", off, None))
    assert toggle.wrapped(argv, payload)[-2:] == ["--off", "mem-one"]
    monkeypatch.setattr(toggle, "load", lambda _start: (None, None, off, None))
    assert "--off" not in toggle.wrapped(argv, payload)
    monkeypatch.setattr(toggle, "load", lambda _start: (_ for _ in ()).throw(OSError("unreadable")))
    assert "--off" not in toggle.wrapped(argv, payload)


@pytest.mark.parametrize("member", ["scripts/g.py", "scripts/a b/g.py", "scripts/chock_index/x.json"])
def test_no_relative_posix_member_path_reads_as_an_escape_on_either_flavour(member: str) -> None:
    from chock.gate.multi import _escapes

    assert not _escapes(member)


def test_an_unreadable_payload_on_a_repo_multi_hook_refuses(tmp_path: Path) -> None:
    import subprocess

    from decision_log_support import hook_env
    from test_multi_dispatch import _repo

    repo, command = _repo(tmp_path, ("alpha",))
    done = subprocess.run(
        command.split(), cwd=repo, env=hook_env(repo.parent), input="not json", capture_output=True, text=True
    )
    assert "could not read" in done.stderr and "deny" in done.stdout, (done.returncode, done.stdout, done.stderr)
