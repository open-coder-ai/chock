"""Step definitions binding the feature files to the `Adopter` driver.

The vocabulary is deliberately policy-agnostic. "Given a policy blocking X is installed /
When the agent attempts Y / Then the attempt is refused" reads the same whether a git hook
or a live agent does the enforcing, so tier 3 can reuse these steps rather than inventing a
parallel set.

Steps assert only on what an adopter can observe. Nothing here imports chock --
`test_isolation.py` enforces that.
"""

from __future__ import annotations

import json

from conftest import Adopter
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features")


# ------------------------------------------------------------------------------- given
@given("a fresh repository", target_fixture="repo")
def _fresh_repository(adopter: Adopter) -> Adopter:
    return adopter


@given("the repository is onboarded", target_fixture="repo")
def _onboarded(repo: Adopter) -> Adopter:
    result = repo.chock("init", ".")
    assert result.ok, f"init failed:\n{result!r}"
    return repo


@given(parsers.parse('a policy blocking "{token}" is installed'))
def _policy_installed(repo: Adopter, fixture_policy_for, token: str) -> None:
    fixture_policy_for(repo, token)


@given("the guard policies are copied in")
def _guard_policies(repo: Adopter, copy_guard_policies) -> None:
    copy_guard_policies(repo)


@given("hooks are installed")
def _hooks_installed(repo: Adopter) -> None:
    result = repo.chock("install-hooks", ".")
    assert result.ok, f"install-hooks failed:\n{result!r}"


@given("the adopter is on a feature branch")
def _feature_branch(repo: Adopter) -> None:
    # The baseline protects main; working on a branch is the behaviour, not a workaround.
    assert repo.git("checkout", "-b", "feature/work").ok


@given("the current index is recorded", target_fixture="index_before")
def _record_index(repo: Adopter) -> str:
    """An explicit step, not a fixture: pytest-bdd builds fixtures on first request, so an
    `index_before` fixture asked for by a Then would be read *after* the When that changes it.
    """
    return repo.read(".agents/policies/INDEX.md")


@given("the adopter has a hand-written PreToolUse hook")
def _hand_written_hook(repo: Adopter) -> None:
    repo.write(
        ".claude/settings.json",
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls *)"]},
                "hooks": {"PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "mine.sh"}]}]},
            }
        ),
    )


# -------------------------------------------------------------------------------- when
@when(parsers.parse('the adopter runs "{args}"'), target_fixture="result")
def _run_cli(repo: Adopter, args: str):
    return repo.chock(*args.split())


@when(parsers.parse('they commit "{filename}" containing "{content}"'), target_fixture="result")
def _commit_file(repo: Adopter, filename: str, content: str):
    # Stage the named file only. A content_regex policy necessarily contains its own
    # pattern in its manifest, so `git add -A` would make the policy block the commit
    # that introduces it -- real behaviour, but not what these scenarios assert.
    repo.write(filename, content + "\n")
    return repo.commit(f"add {filename}", filename)


@when(parsers.parse('the agent attempts "{command}"'), target_fixture="refused")
def _agent_attempts(repo: Adopter, command: str) -> bool:
    """Fire the installed PreToolUse hooks with the payload Claude Code sends."""
    return repo.fire_pretooluse(command)


# -------------------------------------------------------------------------------- then
@then("the command succeeds")
def _command_succeeds(result) -> None:
    assert result.ok, f"{result!r}"


@then("the commit succeeds")
def _commit_succeeds(result) -> None:
    assert result.ok, f"the commit was blocked:\n{result!r}"


@then("the commit is blocked")
def _commit_blocked(result) -> None:
    assert not result.ok, f"the commit was allowed:\n{result!r}"


@then(parsers.parse('the output mentions "{text}"'))
def _output_mentions(result, text: str) -> None:
    assert text.lower() in result.output.lower(), f"{text!r} not in output:\n{result!r}"


@then(parsers.parse('the output does not mention "{text}"'))
def _output_omits(result, text: str) -> None:
    assert text not in result.output, f"{text!r} unexpectedly present:\n{result!r}"


@then(parsers.parse('the file "{path}" exists'))
def _file_exists(repo: Adopter, path: str) -> None:
    assert repo.exists(path), f"{path} was not created"


@then("the attempt is refused")
def _attempt_refused(refused: bool) -> None:
    assert refused, "a command that should be refused was allowed"


@then("the attempt is allowed")
def _attempt_allowed(refused: bool) -> None:
    assert not refused, "a safe command was refused"


@then("no policies are installed")
def _no_policies_installed(repo: Adopter) -> None:
    """Checked on disk, not via `policies`, so a reporting bug cannot hide a written file."""
    policies = repo.repo / ".agents" / "policies"
    assert policies.is_dir(), "init did not create .agents/policies"
    folders = sorted(p.name for p in policies.iterdir() if p.is_dir())
    assert not folders, f"init installed policies it does not own: {folders}"


@then("the index is unchanged")
def _index_unchanged(repo: Adopter, index_before: str) -> None:
    assert repo.read(".agents/policies/INDEX.md") == index_before


@then("every installed hook uses the documented schema")
def _hook_schema(repo: Adopter) -> None:
    entries = repo.read_json(".claude/settings.json")["hooks"]["PreToolUse"]
    assert entries, "no PreToolUse entries installed"
    for entry in entries:
        assert entry["matcher"], "an entry has no matcher"
        for hook in entry["hooks"]:
            assert hook["type"] == "command"
            assert "${CLAUDE_PROJECT_DIR}" in hook["command"], "paths must survive a repo move"


@then("the hand-written hook survives")
def _hand_written_survives(repo: Adopter) -> None:
    settings = repo.read_json(".claude/settings.json")
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "mine.sh" in commands, f"a hand-written hook was discarded: {commands}"


@then("their other settings survive")
def _other_settings_survive(repo: Adopter) -> None:
    assert repo.read_json(".claude/settings.json")["permissions"] == {"allow": ["Bash(ls *)"]}


@then("no policy claims enforcement without a compiled gate")
def _coverage_is_backed(repo: Adopter) -> None:
    coverage = repo.read_json(".chock/coverage.json")
    for policy_id, agents in coverage.items():
        if agents.get("claude") != "enforced-at-commit":
            continue
        gate = repo.repo / ".chock" / "compiled" / policy_id / "git-hook" / "gate.json"
        assert gate.exists(), f"{policy_id} claims enforcement without a compiled gate"
