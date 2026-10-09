"""CU-1: the write-time gate judges a write however Windows spells the path, the root and the cwd.

Witnessed on Windows (2026-10-09, chock 3786b59): Cursor 3.22.12's `Write` and Copilot CLI 1.0.94's
`create` of `.github/workflows/witness.yml` both went through at write time while a gate covered it.
Cursor sends no `cwd`, spells the workspace root `/c:/...` and runs the hook from a cwd of its own;
Copilot sends `cwd` and `tool_input.path`. Each client's hooks run here the way the client runs them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from bundle_fixtures import MARKER
from conftest import init_repo, run_hook_command
from guardrails_support import build, outcomes, refused
from test_plugin_gate import POLICY_ID, _manifest
from test_plugin_gate import policy as shared_policy

from chock.install.package import client
from chock.plugin import cursor

#: The shared fixture under a name no test parameter shadows.
gate_policy = shared_policy

SCOPE = ".github/workflows/*"
WORKFLOW = (".github", "workflows", "witness.yml")
WINDOWS = os.name == "nt"
ON_WINDOWS = pytest.mark.skipif(not WINDOWS, reason="drive-letter spellings are Windows paths")


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


FILE_FORMS = ["C:/fwd", "C:\\back", "c:\\back", "c:/fwd"]


# Cursor: the per-policy package, path-scoped like pin-github-actions.


@pytest.fixture
def plugin(gate_policy, tmp_path: Path) -> Path:
    manifest = _manifest(kind="content_regex")
    manifest["applies_to"] = {"paths": [SCOPE]}
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


def _cursor_write(out: Path, cwd: Path, file_path: str, roots: list[str], content: str = "FORBIDDEN") -> str:
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
    command = json.loads((out / cursor.HOOKS_REL).read_text(encoding="utf-8"))["hooks"]["preToolUse"][0]["command"]
    env = {**os.environ, "CURSOR_PLUGIN_ROOT": out.as_posix()}
    # No BOM: the shared runner writes stdin in the locale encoding, cp1252 on a Windows runner.
    proc = run_hook_command(command, cwd, json.dumps(payload), env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["permission"]


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
    assert _cursor_write(plugin, _elsewhere(tmp_path), target, [str(repo)]) == "deny"
    assert _cursor_write(plugin, _elsewhere(tmp_path), target, [str(repo)], content="ok") == "allow"
    assert _cursor_write(plugin, _elsewhere(tmp_path), str(repo / "A.java"), [str(repo)]) == "allow", "out of scope"


@ON_WINDOWS
@pytest.mark.parametrize("root_form", ["/c:/", "/C:/", "c:\\", "C:/"])
@pytest.mark.parametrize("file_form", FILE_FORMS)
def test_every_windows_spelling_of_a_scoped_write_is_refused(
    plugin: Path, repo: Path, tmp_path: Path, root_form: str, file_form: str
) -> None:
    file_path = _drive_spellings(repo.joinpath(*WORKFLOW))[file_form]
    root = _root_spellings(repo)[root_form]
    assert _cursor_write(plugin, _elsewhere(tmp_path), file_path, [root]) == "deny", (file_path, root)
    assert _cursor_write(plugin, _elsewhere(tmp_path), file_path, [root], content="ok") == "allow"


@ON_WINDOWS
@pytest.mark.parametrize("cwd_kind", ["home", "elsewhere"])
def test_a_scoped_write_is_refused_whatever_the_hook_cwd(plugin: Path, repo: Path, tmp_path: Path, cwd_kind) -> None:
    cwd = Path.home() if cwd_kind == "home" else _elsewhere(tmp_path)
    file_path = _drive_spellings(repo.joinpath(*WORKFLOW))["C:/fwd"]
    assert _cursor_write(plugin, cwd, file_path, [_root_spellings(repo)["/c:/"]]) == "deny"


# Copilot CLI: the merged bundle as `--client copilot` ships it, judged on a `create` {path, file_text}.


@pytest.fixture
def copilot(tmp_path: Path) -> tuple[Path, Path, list[str], Path]:
    """(plugin, repo, the PreToolUse commands a `create` fires, home)."""
    plugin, project, _ = build(tmp_path, client("copilot")["format"])
    project.joinpath(*WORKFLOW).parent.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    entries = json.loads(next(plugin.rglob("hooks.json")).read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [h["command"] for e in entries if "Write" in e.get("matcher", "").split("|") for h in e["hooks"]]
    assert commands, "no PreToolUse entry fires for Copilot's create"
    return plugin, project, commands, home


def _copilot_refuses(copilot: tuple, cwd: str, path: str, text: str = f"{MARKER}\n") -> bool:
    plugin, project, commands, home = copilot
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "timestamp": "2026-10-09T00:00:00.000Z",
        "cwd": cwd,
        "tool_name": "Write",
        "tool_input": {"path": path, "file_text": text},
    }
    return any(refused(p) for p in outcomes(commands, plugin, project, payload, home))


def test_a_copilot_create_is_refused_by_its_absolute_path(copilot: tuple) -> None:
    """The baseline on every OS."""
    _, project, _, _ = copilot
    target = str(project.joinpath(*WORKFLOW))
    assert _copilot_refuses(copilot, str(project), target)
    assert not _copilot_refuses(copilot, str(project), target, "jobs: {}\n")


@ON_WINDOWS
@pytest.mark.parametrize("cwd_form", ["C:\\back", "c:\\back"])
@pytest.mark.parametrize("file_form", FILE_FORMS)
def test_every_windows_spelling_of_a_copilot_create_is_refused(copilot: tuple, cwd_form: str, file_form: str) -> None:
    _, project, _, _ = copilot
    cwd = _drive_spellings(project)[cwd_form]
    path = _drive_spellings(project.joinpath(*WORKFLOW))[file_form]
    assert _copilot_refuses(copilot, cwd, path), (cwd, path)
    assert not _copilot_refuses(copilot, cwd, path, "jobs: {}\n")
