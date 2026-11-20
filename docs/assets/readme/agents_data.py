"""Derive agents.json, the data behind the "Which agents, and how strongly Chock holds in each" picture.

Every row, count and grade is read from chock's code: SURFACE_AGENTS, in_agent_grade, agentseam's matrix and
the plugin warnings data. Only display names and the plain words for a grade are written here.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "agents.json"
NAMES = {
    "aider": "Aider",
    "antigravity": "Antigravity CLI",
    "claude": "Claude Code",
    "cline": "Cline",
    "codex": "Codex",
    "copilot": "Copilot",
    "cursor": "Cursor",
    "devin": "Devin",
    "factory-droid": "Factory Droid",
    "gemini": "Gemini",
    "goose": "goose",
    "grok": "Grok",
    "junie": "Junie",
    "kimi-code": "Kimi Code",
    "mistral-vibe": "Mistral Vibe",
    "openhands": "OpenHands",
    "replit": "Replit",
    "tabnine": "Tabnine",
    "vscode": "VS Code",
    "windsurf": "Windsurf",
}
PLUGIN_AGENT = {"claude-code": "claude"}
GRADE_WORDS = {
    "enforced": "fails closed",
    "enforceable": "can fail closed",
    "fail-to-ask": "asks when it fails",
    "best-effort": "fails open",
    "detect": "sees it after the fact",
    "none": "",
}
WORDS = {
    "title": "Where each coding agent can be stopped",
    "columns": [["ci", "CI", True], ["git", "commit", True], ["hook", "pre-tool", False], ["rule", "AGENTS.md", False]],
    "groups": {"tested live": "One plugin, tested live", "untested": "One plugin, untested", "": "Git hook and CI"},
    "plugin": {"tested": "tested live", "untested": "untested"},
    "legend": [
        {"hard": True, "text": "filled: refuses here"},
        {"hard": False, "text": "hollow: advice, or best effort"},
        {"hard": None, "text": "fails open: if the agent's hook dies, the action goes ahead"},
    ],
    "footer": "Read from Chock __CHOCK__ with agentseam __SEAM__. Grades are capped by their evidence.",
}


def derive() -> dict:
    """The picture's data, read from the code as it is now."""
    import agentseam  # noqa: PLC0415 -- chock and agentseam are needed only to derive
    from agentseam import matrix  # noqa: PLC0415

    import chock.install  # noqa: PLC0415
    from chock.compile.levels import in_agent_grade  # noqa: PLC0415
    from chock.compile.surfaces import SURFACE_AGENTS, Surface  # noqa: PLC0415
    from chock.vendors import CHOCK_AGENT  # noqa: PLC0415

    data_dir = Path(chock.install.__file__).parent / "data"
    clients = json.loads((data_dir / "install.json").read_text(encoding="utf-8"))["clients"]
    rules = json.loads((data_dir / "warnings.json").read_text(encoding="utf-8"))["rules"]
    untested = {c for r in rules if r["kind"] == "client" and r["says"].startswith("Untested:") for c in r["clients"]}
    plugin = {PLUGIN_AGENT.get(cid, cid): "untested" if cid in untested else "tested" for cid in clients}
    rows = []
    for agent, surfaces in SURFACE_AGENTS.items():
        own = next((s for s in (Surface.PRE_TOOL_USE, Surface.AGENT_HOOKS) if s in surfaces), None)
        grade = in_agent_grade(agent, own.value).level if own else "none"
        rows.append(
            {
                "id": agent,
                "name": NAMES[agent],
                "ci": Surface.CI_GATE in surfaces,
                "git": Surface.GIT_HOOK in surfaces,
                "hook_grade": grade,
                "hook": GRADE_WORDS[grade],
                "matrix_pre_tool": matrix.enforcement_level(CHOCK_AGENT[agent], "pre_tool"),
                "plugin": WORDS["plugin"].get(plugin.get(agent, ""), ""),
                "rule": Surface.AMBIENT_RULE in surfaces,
            }
        )
    order = {"tested live": 0, "untested": 1, "": 2}
    rows.sort(key=lambda r: (order[r["plugin"]], r["name"].lower()))
    count = lambda key, value: sum(1 for r in rows if r[key] == value)  # noqa: E731
    counts = {
        "agents": len(rows),
        "own_hook": sum(1 for r in rows if r["hook_grade"] != "none"),
        "plugin_tested": count("plugin", "tested live"),
        "plugin_untested": count("plugin", "untested"),
    }
    footer = WORDS["footer"].replace("__CHOCK__", version("chock")).replace("__SEAM__", agentseam.__version__)
    return {
        "source": {
            "file": "SURFACE_AGENTS, in_agent_grade, agentseam matrix, plugin warnings",
            "chock": version("chock"),
        },
        "title": WORDS["title"],
        "columns": [{"id": i, "label": label, "hard": hard} for i, label, hard in WORDS["columns"]],
        "counts": counts,
        "groups": WORDS["groups"],
        "legend": WORDS["legend"],
        "footer": footer,
        "rows": rows,
    }


def write() -> None:
    """Rewrite agents.json from the code as it is now."""
    OUT.write_text(json.dumps(derive(), indent=2) + "\n", encoding="utf-8")
