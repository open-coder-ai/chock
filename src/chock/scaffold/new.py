"""Deterministic `chock new <artifact> <id>` skeleton generator."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import chock
from chock.index.cli import cmd_refresh
from chock.registry.core import rescan_and_report


class TemplateError(RuntimeError):
    """Raised when a packaged scaffold template cannot be rendered."""


def _templates_dir() -> Path:
    return Path(chock.__file__).parent / "packs" / "_skills" / "policy-init" / "assets" / "templates"


def _render_template(filename: str, **values: str) -> str:
    path = _templates_dir() / filename
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Unable to read template '{path}': {exc.strerror or exc}"
        raise TemplateError(msg) from exc
    if not template.strip():
        msg = f"Template '{path}' is empty"
        raise TemplateError(msg)
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError) as exc:
        msg = f"Malformed template '{path}': {exc}"
        raise TemplateError(msg) from exc


def _new_policy(id_: str, root: Path) -> None:
    now = datetime.now(timezone.utc)
    policy_dir = root / ".agents" / "policies" / id_
    evals_dir = policy_dir / "evals"
    policy_dir.mkdir(parents=True, exist_ok=True)
    evals_dir.mkdir(parents=True, exist_ok=True)

    name = " ".join(word.capitalize() for word in id_.replace("-", " ").split())
    values = {"id": id_, "name": name, "now": now.isoformat(), "date": now.date().isoformat()}
    (policy_dir / "manifest.yaml").write_text(_render_template("manifest.yaml.tmpl", **values), encoding="utf-8")
    (evals_dir / "suite.yaml").write_text(_render_template("eval-suite.yaml.tmpl", **values), encoding="utf-8")


def _new_skill(id_: str, root: Path) -> None:
    skill_dir = root / ".agents" / "skills" / id_
    skill_dir.mkdir(parents=True, exist_ok=True)
    name = " ".join(word.capitalize() for word in id_.replace("-", " ").split())
    (skill_dir / "SKILL.md").write_text(_render_template("SKILL.md.tmpl", id=id_, name=name), encoding="utf-8")


def _new_subagent(id_: str, root: Path) -> None:
    now = datetime.now(timezone.utc)
    subagent_dir = root / ".agents" / "skills" / id_
    subagent_dir.mkdir(parents=True, exist_ok=True)
    name = " ".join(word.capitalize() for word in id_.replace("-", " ").split())
    (subagent_dir / "subagent.yaml").write_text(
        _render_template("subagent.yaml.tmpl", id=id_, name=name, now=now.isoformat()), encoding="utf-8"
    )


def cmd_new(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a deterministic artifact skeleton")
    parser.add_argument("artifact", choices=["policy", "skill", "subagent"], help="Artifact type")
    parser.add_argument("id", help="Artifact id")
    parser.add_argument("--root", "--repo", default=".", dest="root", help="Repo root")
    args = parser.parse_args(argv)

    if not args.id:
        print("Artifact id cannot be empty", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    try:
        if args.artifact == "policy":
            _new_policy(args.id, root)
        elif args.artifact == "skill":
            _new_skill(args.id, root)
        elif args.artifact == "subagent":
            _new_subagent(args.id, root)
    except TemplateError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    rescan_and_report(root)

    cmd_refresh(["--repo", str(root)])

    print(f"Created {args.artifact} '{args.id}' at {root / '.agents'}")
    print(f"Next:  python -m chock check {args.root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_new(argv)
