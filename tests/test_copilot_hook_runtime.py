"""The emitted Copilot hook command, executed the way the client executes it.

Split from `test_copilot_plugin.py`, which checks what the emitter *writes*. This file
checks what the written thing *does* when a shell runs it, which is a different activity
and — as the defect below shows — the one that was never covered.

A guard reaches a developer as a string in a JSON file that some client hands to a shell.
Every test that stops at the string is testing our intent. Only running it tests the
control.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from chock.gate import runtime_bundle
from chock.plugin.claude import claude_plugin_files
from chock.plugin.copilot import HOOKS_REL, build_copilot_plugin, copilot_plugin_files

GUARD_MANIFEST = {
    "id": "block-destructive-commands",
    "name": "Block Destructive Commands",
    "version": "0.0.1",
    "description": "Block rm -rf and friends before they run.",
    "artifact": "hook",
    "enforcement": "block",
    "provenance": {
        "author": "chock-core",
        "license": "Apache-2.0",
        "source_repo": "https://github.com/open-coder-ai/chock",
    },
}
GUARD_BODY = "#!/usr/bin/env bash\nexit 0  # test fixture guard\n"


@pytest.fixture
def policy(tmp_path: Path):
    def _make(manifest: dict, guard: bool = False) -> Path:
        pack = tmp_path / ".agents" / "policies" / manifest["id"]
        pack.mkdir(parents=True)
        (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        if guard:
            impl = pack / "implementations"
            impl.mkdir()
            (impl / f"{manifest['id']}.sh").write_text(GUARD_BODY, encoding="utf-8")
        return pack

    return _make


def _emitted_command(policy, tmp_path: Path) -> str:
    pack = policy(GUARD_MANIFEST, guard=True)
    out = tmp_path / "dist" / "copilot" / "block-destructive-commands"
    build_copilot_plugin(pack, GUARD_MANIFEST, tmp_path, out)
    hooks = json.loads((out / "com.github.copilot" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_hook_allows_when_the_plugin_root_cannot_be_resolved(policy, tmp_path: Path) -> None:
    """An unresolvable plugin root must ALLOW. It used to deny every tool call in the session.

    This is the regression test for a defect that reached published packages. VS Code's
    `AGENT_PLUGIN_FORMAT` declares `pluginRootTokens: []` and `pluginRootEnvVars: []`
    (src/vs/platform/agentPlugins/common/pluginParsers.ts), where `CLAUDE_FORMAT`,
    `OPEN_PLUGIN_FORMAT` and legacy `COPILOT_FORMAT` all declare both. So the old command's
    `${PLUGIN_ROOT}` reached `sh -c` verbatim, expanded to nothing, and `python3` exited 2 on
    the missing file -- which is VS Code's *blocking* code, not its error code. Matchers are
    ignored in that client, so the blast radius was every tool call: reads, edits, searches.

    Nothing caught it. CI was green, `chock check` passed, the eval suite passed, and the
    string-pinning test above asserted the broken command was exactly what we meant to ship.
    What was missing was any test that RAN the thing. So this one runs it, through `sh -c`,
    the way the client does, and asserts the number that decides whether a developer's
    session works.

    Fail-open is the correct posture here and is what every description already claims: a
    guard that cannot find itself must not be the reason a session stops.
    """
    command = _emitted_command(policy, tmp_path)

    env = {k: v for k, v in os.environ.items() if k != "PLUGIN_ROOT"}
    for label, extra in (("unset", {}), ("set but wrong", {"PLUGIN_ROOT": str(tmp_path / "nope")})):
        done = subprocess.run(  # noqa: S602 - `shell=True` IS the client's invocation under test
            command,
            shell=True,
            input='{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}',
            capture_output=True,
            text=True,
            env={**env, **extra},
        )
        assert done.returncode == 0, (
            f"plugin root {label}: hook exited {done.returncode}; anything non-zero is a deny in "
            f"VS Code, and 2 in particular blocks the call. stderr={done.stderr[:300]!r}"
        )


def test_copilot_and_claude_packages_run_the_same_hook(policy, tmp_path: Path) -> None:
    """Two formats, one enforcement system -- same matcher, same guard bytes, own dialect.

    The GUARD script is byte-identical in both layouts. The adapter itself is legitimately
    NOT byte-identical any more: `vscode_copilot.py`/`claude_code.py` are two different
    agentseam bundles (`gate/runtime_bundle.py`), each speaking that vendor's own
    live-verified dialect -- a real difference the old shared, sniffing adapter only
    approximated. What must never differ is matcher/timeout and the guard's bytes.
    """
    pack = policy(GUARD_MANIFEST, guard=True)
    copilot = copilot_plugin_files(pack, GUARD_MANIFEST, tmp_path)
    claude = claude_plugin_files(pack, GUARD_MANIFEST, tmp_path)

    copilot_entry = json.loads(copilot[Path(HOOKS_REL)])["hooks"]["PreToolUse"][0]
    claude_entry = json.loads(claude[Path("hooks/hooks.json")])["hooks"]["PreToolUse"][0]
    assert copilot_entry["matcher"] == claude_entry["matcher"]
    assert copilot_entry["hooks"][0]["timeout"] == claude_entry["hooks"][0]["timeout"]
    # No longer a token-substitution of one another, and that is the fix, not drift: Claude's
    # format interpolates and exports; Agent Plugins 1.0 does neither (`pluginRootTokens: []`).
    # What must still match is what enforces -- same adapter, same guard, same layout.
    copilot_command = copilot_entry["hooks"][0]["command"]
    claude_command = claude_entry["hooks"][0]["command"]
    for script in ("vscode_copilot.py", "block-destructive-commands.sh"):
        claude_script = script.replace("vscode_copilot.py", "claude_code.py")
        assert f"/scripts/{script}" in copilot_command
        assert f"/scripts/{claude_script}" in claude_command
    assert copilot_command.endswith(f'--guard "$r/scripts/{"block-destructive-commands.sh"}"')
    assert "exit 0" in copilot_command, "this format's hook must allow when its root is unresolved"

    assert copilot[Path("scripts/vscode_copilot.py")] == runtime_bundle.render("vscode_copilot")
    assert claude[Path("scripts/claude_code.py")] == runtime_bundle.render("claude_code")
    assert (
        copilot[Path("scripts/block-destructive-commands.sh")] == claude[Path("scripts/block-destructive-commands.sh")]
    )
