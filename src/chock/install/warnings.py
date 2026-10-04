"""Selection warnings: rules are data (data/warnings.json); each kind is one predicate over the selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from chock.resources import package_data_dir

Predicate = Callable[[dict[str, Any], list[str], dict[str, str], Path], list[str]]


def _missing_partner(rule: dict[str, Any], chosen: list[str], _grades: dict[str, str], _cwd: Path) -> list[str]:
    present = [p for p in rule["policies"] if p in chosen]
    absent = [p for p in rule["policies"] if p not in chosen]
    return [_say(rule, present, ABSENT=", ".join(absent))] if present and absent else []


def _all_present(rule: dict[str, Any], chosen: list[str], _grades: dict[str, str], _cwd: Path) -> list[str]:
    return [_say(rule, rule["policies"])] if all(p in chosen for p in rule["policies"]) else []


def _file_absent(rule: dict[str, Any], chosen: list[str], _grades: dict[str, str], cwd: Path) -> list[str]:
    present = [p for p in rule["policies"] if p in chosen]
    return [_say(rule, present, FILE=rule["file"])] if present and not (cwd / rule["file"]).is_file() else []


def _grade(rule: dict[str, Any], chosen: list[str], grades: dict[str, str], _cwd: Path) -> list[str]:
    return [_say(rule, [p]) for p in chosen if grades.get(p) == rule["grade"]]


KINDS: dict[str, Predicate] = {
    "missing_partner": _missing_partner,
    "all_present": _all_present,
    "file_absent": _file_absent,
    "grade": _grade,
}


def _say(rule: dict[str, Any], present: list[str], **tokens: str) -> str:
    text = rule["says"].replace("__PRESENT__", " and ".join(present))
    for name, value in tokens.items():
        text = text.replace(f"__{name}__", value)
    return text


def load_rules() -> list[dict[str, Any]]:
    """The packaged warning rules."""
    text = package_data_dir("chock.install", "data").joinpath("warnings.json").read_text(encoding="utf-8")
    return json.loads(text)["rules"]


def warnings_for(chosen: list[str], grades: dict[str, str], cwd: Path, rules: list[dict[str, Any]]) -> list[str]:
    """Every warning `rules` raise for the chosen ids, given each id's grade keyword; none refuses."""
    return [line for rule in rules for line in KINDS[rule["kind"]](rule, chosen, grades, cwd)]
