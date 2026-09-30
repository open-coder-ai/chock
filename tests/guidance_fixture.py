"""A repo with java-security installed: rules copied from the catalog's setup contract, plus helpers."""

from __future__ import annotations

import json
from pathlib import Path

#: (id, pack, title, refuses, constraint, first cwe id, first cwe name), as the catalog's contract records them.
RULES = json.loads((Path(__file__).parent / "fixtures" / "guidance_rules.json").read_text(encoding="utf-8"))


def contract() -> dict:
    rules = [
        {
            "id": i,
            "pack": pack,
            "title": title,
            "refuses": refuses,
            "constraint": constraint,
            "cwe": [{"id": cwe, "name": name}] if cwe else [],
        }
        for i, pack, title, refuses, constraint, cwe, name in RULES
    ]
    return {"version": 1, "rules": rules}


def install(root: Path, selection: object | None = None) -> Path:
    """Install java-security's manifest and contract under `root`; write a selection when one is given."""
    policy = root / ".agents" / "policies" / "java-security"
    (policy / "skills" / "java-security" / "references").mkdir(parents=True)
    (policy / "manifest.yaml").write_text("id: java-security\n", encoding="utf-8")
    (policy / "skills" / "java-security" / "references" / "setup-contract.json").write_text(
        json.dumps(contract()), encoding="utf-8"
    )
    if selection is not None:
        (root / ".chock").mkdir(exist_ok=True)
        text = selection if isinstance(selection, str) else json.dumps(selection)
        (root / ".chock" / "security.json").write_text(text, encoding="utf-8")
    return root


def select(**packs: object) -> dict:
    """A version-2 selection; each keyword is a pack name with its {verdict} or {rules} body."""
    return {"version": 2, "packs": packs}
