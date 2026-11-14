"""The floor's default control-plane list (W2-A1v2.1 L1) against every repo-relative path the engine writes."""

from __future__ import annotations

import json
from importlib import resources

import pytest
from agentseam import instructions, permissions_data
from agentseam.vendor_config import VENDOR_CONFIG

from chock import vendors
from chock.config import CONFIG_DIR
from chock.gate.runner.constants import COMPILED_PREFIX, POLICIES_PREFIX
from chock.guardrails.toggle import FILENAME as GUARDRAILS_TOGGLE
from chock.hooks.launch import LAUNCHER_REL
from chock.plugin.marketplace_core import TREES
from chock.plugin.marketplace_devin import DEVIN_ROOT_MANIFEST_REL
from chock.scaffold.install_ci import DEFAULT_PATH as CI_WORKFLOW
from chock.validation import control_plane as cp

DEFAULT = cp.ControlPlane(cp.REFUSE, cp.default_patterns())
_REPO_SCOPES = ("project", "local")


def _data(package: str, rel: str) -> dict:
    return json.loads(resources.files(package).joinpath(rel).read_text(encoding="utf-8"))


def _hook_files() -> list[str]:
    return sorted({p for p in map(vendors.config_path, VENDOR_CONFIG) if not p.startswith("~")})


def _engine_paths() -> list[str]:
    """Every repo-relative file or folder chock or agentseam writes hooks, permissions, MCP servers, plugins,
    CI or its own state into. A folder is given with a trailing `/`."""
    found = set(_hook_files())
    found |= {
        e["path"] for files in permissions_data.CONFIG_FILES.values() for e in files if e["scope"] in _REPO_SCOPES
    }
    found |= {c["path"] for c in _data("chock", "data/mcp_clients.json").values()}
    found |= {p.as_posix() for tree in TREES.values() for p in tree["index_paths"]} | {
        DEVIN_ROOT_MANIFEST_REL.as_posix()
    }
    install = _data("chock.install", "data/install.json")
    found |= {i["path"] for client in install["clients"].values() for i in client.get("index", [])}
    stores = resources.files("chock.plugin").joinpath("data/stores")
    layouts = [json.loads(f.read_text(encoding="utf-8")).get("layout", {}) for f in stores.iterdir()]
    # A plugin manifest in its own folder (`.factory-plugin/plugin.json`); a bare `plugin.json` is the package root's.
    found |= {m for layout in layouts if "/" in (m := layout.get("manifest") or "")}
    found |= {CI_WORKFLOW, LAUNCHER_REL, GUARDRAILS_TOGGLE, COMPILED_PREFIX, POLICIES_PREFIX, f"{CONFIG_DIR}/"}
    return sorted(found)


def _agent_folder(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2] if parts[0] == ".github" else parts[:1])


@pytest.mark.parametrize("path", _engine_paths())
def test_every_path_the_engine_writes_is_control_plane(path):
    assert path.startswith(".") or "/" not in path, path  # repo-relative, never a home path
    assert DEFAULT.covers(path) or DEFAULT.covers(f"{path.rstrip('/')}/x"), path


@pytest.mark.parametrize("folder", sorted({_agent_folder(p) for p in _hook_files() if "/" in p}))
def test_every_agent_folder_is_control_plane_whole(folder):
    for rel in ("skills/x/SKILL.md", "agents/x.md", "cli.json", ".env", "rules/x.md", "x"):
        assert DEFAULT.covers(f"{folder}/{rel}"), f"{folder}/{rel}"
    assert DEFAULT.covers(folder), f"a symlink or gitlink at {folder} is not matched"


@pytest.mark.parametrize(
    "path",
    sorted({f for e in instructions.INSTRUCTION_FILES.values() for f in e["files"] if "/" in f}),
)
def test_instruction_files_inside_an_agent_folder_are_covered_by_it(path):
    """Whole folders: an instruction file inside one is listed with it; one beside them (`.github/x.md`) is not."""
    assert DEFAULT.covers(path) == DEFAULT.covers(f"{_agent_folder(path)}/x"), path


@pytest.mark.parametrize(
    "path", sorted({f for e in instructions.INSTRUCTION_FILES.values() for f in e["files"] if "/" not in f})
)
def test_root_instruction_files_stay_out(path):
    assert not DEFAULT.covers(path), path


@pytest.mark.parametrize("path", [".mcp.json", ".vscode/settings.json", ".vscode/mcp.json", ".env", ".cursor/cli.json"])
def test_client_config_and_env_files_named_by_the_review_are_control_plane(path):
    assert DEFAULT.covers(path)
