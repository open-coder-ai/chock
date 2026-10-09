"""CU-1: Cursor's write-time gate judges a scoped write however Windows spells the path and the root.

Witnessed on Windows (Cursor 3.22.12, 2026-10-09): a `Write` of `.github/workflows/witness.yml`
went through `preToolUse` while a path-scoped gate covered it. Cursor sends no `cwd`, spells the
workspace root `/c:/...` and the file `C:/...` or `C:\\...`, and runs the hook from a cwd of its own.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import init_repo
from test_plugin_gate import POLICY_ID, _manifest
from test_plugin_gate import policy as shared_policy

from chock.plugin import cursor

#: The shared fixture under a name no test parameter shadows.
gate_policy = shared_policy

SCOPE = ".github/workflows/*"
WORKFLOW = (".github", "workflows", "witness.yml")
WINDOWS = os.name == "nt"


def _scoped_manifest() -> dict:
    manifest = _manifest(kind="content_regex")
    manifest["applies_to"] = {"paths": [SCOPE]}
    return manifest


@pytest.fixture
def plugin(gate_policy, tmp_path: Path) -> Path:
    manifest = _scoped_manifest()
    out = tmp_path / "dist" / "cursor" / POLICY_ID
    cursor.build_cursor_plugin(gate_policy(manifest), manifest, tmp_path, out)
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    project = tmp_path / "witness-repo-cursor"
    (project / ".github" / "workflows").mkdir(parents=True)
    init_repo(project)
    return project


def _elsewhere(tmp_path: Path) -> Path:
    """A process cwd that is not the workspace, as Cursor's own install or the user's home is."""
    away = tmp_path / "cursor-install"
    away.mkdir(exist_ok=True)
    return away


def _write(out: Path, cwd: Path, file_path: str, roots: list[str], content: str = "FORBIDDEN") -> str:
    """The `permission` Cursor gets for a `Write`; the payload carries no `cwd`, as Cursor's does not."""
    payload = {
        "conversation_id": "c",
        "generation_id": "g",
        "cursor_version": "3.22.12",
        "workspace_roots": roots,
        "hook_event_name": "preToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }
    hooks = json.loads((out / cursor.HOOKS_REL).read_text(encoding="utf-8"))["hooks"]
    command = hooks["preToolUse"][0]["command"].replace("${CURSOR_PLUGIN_ROOT}", str(out))
    proc = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        env={**os.environ, "CURSOR_PLUGIN_ROOT": str(out)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        input="\ufeff" + json.dumps(payload),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["permission"]


def _drive_spellings(path: Path) -> dict[str, str]:
    """`path` as Windows clients write it: forward or back slashes, upper- or lower-case drive."""
    text = str(path)
    upper, lower = text[0].upper() + text[1:], text[0].lower() + text[1:]
    return {
        "C:/fwd": upper.replace("\\", "/"),
        "C:\\back": upper.replace("/", "\\"),
        "c:\\back": lower.replace("/", "\\"),
        "c:/fwd": lower.replace("\\", "/"),
    }


def _root_spellings(root: Path) -> dict[str, str]:
    """The workspace root as Cursor (`/c:/...`) and other clients spell it."""
    forms = _drive_spellings(root)
    return {
        "/c:/": "/" + forms["c:/fwd"],
        "/C:/": "/" + forms["C:/fwd"],
        "c:\\": forms["c:\\back"],
        "C:/": forms["C:/fwd"],
    }


def test_a_scoped_write_is_refused_with_no_cwd_from_elsewhere(plugin: Path, repo: Path, tmp_path: Path) -> None:
    """The baseline on every OS: the root comes from `workspace_roots`, not the hook's process cwd."""
    target = str(repo.joinpath(*WORKFLOW))
    assert _write(plugin, _elsewhere(tmp_path), target, [str(repo)]) == "deny"
    assert _write(plugin, _elsewhere(tmp_path), target, [str(repo)], content="ok") == "allow"
    assert _write(plugin, _elsewhere(tmp_path), str(repo / "A.java"), [str(repo)]) == "allow", "outside the scope"


@pytest.mark.skipif(not WINDOWS, reason="drive-letter spellings are Windows paths")
@pytest.mark.parametrize("root_form", ["/c:/", "/C:/", "c:\\", "C:/"])
@pytest.mark.parametrize("file_form", ["C:/fwd", "C:\\back", "c:\\back", "c:/fwd"])
def test_every_windows_spelling_of_a_scoped_write_is_refused(
    plugin: Path, repo: Path, tmp_path: Path, root_form: str, file_form: str
) -> None:
    file_path = _drive_spellings(repo.joinpath(*WORKFLOW))[file_form]
    root = _root_spellings(repo)[root_form]
    assert _write(plugin, _elsewhere(tmp_path), file_path, [root]) == "deny", (file_path, root)
    assert _write(plugin, _elsewhere(tmp_path), file_path, [root], content="ok") == "allow"


@pytest.mark.skipif(not WINDOWS, reason="drive-letter spellings are Windows paths")
@pytest.mark.parametrize("cwd_kind", ["home", "elsewhere"])
def test_a_scoped_write_is_refused_whatever_the_hook_cwd(plugin: Path, repo: Path, tmp_path: Path, cwd_kind) -> None:
    cwd = Path.home() if cwd_kind == "home" else _elsewhere(tmp_path)
    file_path = _drive_spellings(repo.joinpath(*WORKFLOW))["C:/fwd"]
    assert _write(plugin, cwd, file_path, [_root_spellings(repo)["/c:/"]]) == "deny"
