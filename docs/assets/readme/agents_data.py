"""Derive agents.json, the data behind the "Which agents, and how strongly Chock holds in each" picture.

Every row, count and grade is read from chock's code: SURFACE_AGENTS, in_agent_grade, agentseam's matrix and
the plugin warnings data. Only display names and the plain words for a grade are written here.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "agents.json"
ROOT = HERE.parents[2]
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
    "enforced": "blocks, verified to fail closed",
    "enforceable": "can block, can be set to fail closed",
    "fail-to-ask": "can block, asks a person when it cannot decide",
    "best-effort": "can block, fails open",
    "detect": "sees it after the fact",
    "none": "",
}
WORDS = {
    "title": "Which agents, and how strongly Chock holds in each",
    "columns": [
        ["ci", "CI check", True],
        ["git", "Git hook", True],
        ["hook", "Agent's own hook", False],
        ["plugin", "One plugin", False],
        ["rule", "AGENTS.md rule", False],
    ],
    "groups": {"tested live": "Plugin tested live", "untested": "Plugin untested", "": "No plugin"},
    "ci": "refuses",
    "git": "refuses at commit",
    "rule": "advice the agent reads",
    "plugin": {"tested": "tested live", "untested": "untested"},
    "summary": "All __AGENTS__ get a CI check, a git hook and an AGENTS.md rule. __NATIVE__ also get their own hook. "
    "As one plugin: __TESTED__ tested live, __UNTESTED__ untested.",
    "legend_title": "How to read it",
    "legend": [
        "Filled diamond: always refuses. Hollow: depends on the agent, or only advice the agent reads.",
        "Fails open: if the agent's hook dies, the action goes ahead. The git hook and CI check still run.",
        "Tested live: the plugin ran in that client. Untested: it is built, but has not run there.",
    ],
    "footer": "Read from chock at __COMMIT__ with agentseam __SEAM__. Grades are capped by their evidence.",
}


def _commit() -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S607
    return done.stdout.strip()


def derive(commit: str) -> dict:
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
                "ci": WORDS["ci"] if Surface.CI_GATE in surfaces else "",
                "git": WORDS["git"] if Surface.GIT_HOOK in surfaces else "",
                "hook_grade": grade,
                "hook": GRADE_WORDS[grade],
                "matrix_pre_tool": matrix.enforcement_level(CHOCK_AGENT[agent], "pre_tool"),
                "plugin": WORDS["plugin"].get(plugin.get(agent, ""), ""),
                "rule": WORDS["rule"] if Surface.AMBIENT_RULE in surfaces else "",
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
    summary = WORDS["summary"]
    for key, value in (("AGENTS", counts["agents"]), ("NATIVE", counts["own_hook"])):
        summary = summary.replace(f"__{key}__", str(value))
    summary = summary.replace("__TESTED__", str(counts["plugin_tested"])).replace(
        "__UNTESTED__", str(counts["plugin_untested"])
    )
    footer = WORDS["footer"].replace("__COMMIT__", commit[:7]).replace("__SEAM__", agentseam.__version__)
    return {
        "source": {"file": "SURFACE_AGENTS, in_agent_grade, agentseam matrix, plugin warnings", "commit": commit},
        "title": WORDS["title"],
        "columns": [{"id": i, "label": label, "hard": hard} for i, label, hard in WORDS["columns"]],
        "counts": counts,
        "summary": summary,
        "groups": WORDS["groups"],
        "legend_title": WORDS["legend_title"],
        "legend": WORDS["legend"],
        "footer": footer,
        "rows": rows,
    }


def write() -> None:
    """Rewrite agents.json at the current commit."""
    OUT.write_text(json.dumps(derive(_commit()), indent=2) + "\n", encoding="utf-8")
