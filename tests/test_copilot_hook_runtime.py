"""The emitted Copilot hook command, executed the way the client executes it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from chock import vendors
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


#: The shells a client may hand the command to; bash-as-sh exits 127 on a missing file, not 2.
SHELLS = [s for s in (["dash", "-c"], ["bash", "--posix", "-c"]) if shutil.which(s[0])]


def _run(command: str, root: str | None) -> list[subprocess.CompletedProcess]:
    env = {k: v for k, v in os.environ.items() if k != "PLUGIN_ROOT"}
    if root is not None:
        env["PLUGIN_ROOT"] = root
    payload = '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}'
    return [subprocess.run([*sh, command], input=payload, capture_output=True, text=True, env=env) for sh in SHELLS]


def test_hook_allows_when_the_plugin_root_cannot_be_resolved(policy, tmp_path: Path) -> None:
    """No plugin root must ALLOW: VS Code's agent-plugin format exports none, and refusing denied every call."""
    command = _emitted_command(policy, tmp_path)
    assert SHELLS, "no dash or bash to run the client's command under"
    for label, root in (("unset", None), ("empty", "")):
        for done in _run(command, root):
            assert done.returncode == 0, (
                f"plugin root {label}: hook exited {done.returncode}; anything non-zero is a deny in "
                f"VS Code, and 2 in particular blocks the call. stderr={done.stderr[:300]!r}"
            )


def test_hook_refuses_when_the_plugin_root_lacks_the_package(policy, tmp_path: Path) -> None:
    """A root that is set but holds no bundled hook is a broken install: it REFUSES with the blocking 2."""
    command = _emitted_command(policy, tmp_path)
    for done in _run(command, str(tmp_path / "nope")):
        assert done.returncode == 2, f"hook exited {done.returncode}, not the blocking 2: {done.stderr[:300]!r}"
        assert "Refusing" in done.stderr, done.stderr[:300]


def test_hook_judges_the_call_when_the_root_holds_the_package(policy, tmp_path: Path) -> None:
    out = tmp_path / "dist" / "copilot" / "block-destructive-commands"
    command = _emitted_command(policy, tmp_path)
    for done in _run(command, str(out)):
        assert done.returncode == 0 and "Refusing" not in done.stderr, (done.returncode, done.stderr[:300])


def test_copilot_and_claude_packages_run_the_same_hook(policy, tmp_path: Path) -> None:
    """Two formats, one enforcement system -- each vendor's own matcher, same guard bytes, own dialect."""
    pack = policy(GUARD_MANIFEST, guard=True)
    copilot = copilot_plugin_files(pack, GUARD_MANIFEST, tmp_path)
    claude = claude_plugin_files(pack, GUARD_MANIFEST, tmp_path)

    copilot_entry = json.loads(copilot[Path(HOOKS_REL)])["hooks"]["PreToolUse"][0]
    claude_entry = json.loads(claude[Path("hooks/hooks.json")])["hooks"]["PreToolUse"][0]
    assert copilot_entry["matcher"] == vendors.shell_matcher("vscode_copilot")
    assert claude_entry["matcher"] == vendors.shell_matcher("claude_code")
    assert copilot_entry["hooks"][0]["timeout"] == claude_entry["hooks"][0]["timeout"]
    copilot_command = copilot_entry["hooks"][0]["command"]
    claude_command = claude_entry["hooks"][0]["command"]
    for script in ("vscode_copilot.py", "block-destructive-commands.sh"):
        claude_script = script.replace("vscode_copilot.py", "claude_code.py")
        assert f"/scripts/{script}" in copilot_command
        assert f"/scripts/{claude_script}" in claude_command
    assert copilot_command.endswith(f'--guard "$r/scripts/{"block-destructive-commands.sh"}"')
    assert '[ -n "$r" ] || exit 0;' in copilot_command, "this format's hook must allow when its root is unset"
    assert "exit 2" in copilot_command, "a root without the bundled hook must refuse"

    assert copilot[Path("scripts/vscode_copilot.py")] == runtime_bundle.render("vscode_copilot")
    assert claude[Path("scripts/claude_code.py")] == runtime_bundle.render("claude_code")
    assert (
        copilot[Path("scripts/block-destructive-commands.sh")] == claude[Path("scripts/block-destructive-commands.sh")]
    )
