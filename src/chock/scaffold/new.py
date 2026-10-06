"""Deterministic `chock new <artifact> <id>` skeleton generator."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import chock
from chock.index.cli import cmd_refresh
from chock.output import error
from chock.policy_id import POLICY_ID_RE
from chock.registry.core import rescan_and_report

#: `chock new policy <id> --kind <kind>`: one template folder each under data/kinds/, copied with __TOKEN__s replaced.
KINDS = ("content_regex", "guard", "script", "rule", "skill")
#: Reserved for a person's own policies, so a catalog id never collides with one; added outside a catalog.
CUSTOM_PREFIX = "my-"
_TEMPLATE_SUFFIX = ".tmpl"
_CATALOG_REGISTRY = "registry.yaml"


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


def kinds_dir() -> Path:
    """The packaged per-kind templates; the site copies these files byte for byte."""
    return Path(__file__).resolve().parent / "data" / "kinds"


def custom_id(id_: str, root: Path) -> str:
    """`id_`, prefixed `my-` unless it already is or `root` is a catalog (it has a registry.yaml)."""
    if id_.startswith(CUSTOM_PREFIX) or (root / _CATALOG_REGISTRY).is_file():
        return id_
    return CUSTOM_PREFIX + id_


def render_kind(kind: str, id_: str, today: str) -> dict[Path, str]:
    """Each file of the `kind` template, by its path inside the policy folder, with the tokens filled in."""
    name = " ".join(word.capitalize() for word in id_.removeprefix(CUSTOM_PREFIX).replace("-", " ").split())
    tokens = {"__ID__": id_, "__NAME__": name, "__DATE__": today}
    folder = kinds_dir() / kind
    out = {}
    for src in sorted(folder.rglob(f"*{_TEMPLATE_SUFFIX}")):
        rel = src.relative_to(folder).as_posix().removesuffix(_TEMPLATE_SUFFIX)
        text = src.read_text(encoding="utf-8")
        for token, value in tokens.items():
            rel, text = rel.replace(token, value), text.replace(token, value)
        out[Path(rel)] = text
    return out


def _new_kind(id_: str, kind: str, root: Path) -> Path:
    policy_dir = root / ".agents" / "policies" / id_
    if policy_dir.exists():
        msg = f"{policy_dir} already exists; choose another id or remove it first"
        raise TemplateError(msg)
    today = datetime.now(timezone.utc).date().isoformat()
    for rel, text in render_kind(kind, id_, today).items():
        dest = policy_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        if rel.parts[0] == "implementations":
            dest.chmod(0o755)
    return policy_dir


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
    parser.add_argument(
        "--kind",
        choices=KINDS,
        help="policy only: start from a tested template of this kind (outside a catalog the id gains `my-`)",
    )
    args = parser.parse_args(argv)

    if not args.id:
        print("Artifact id cannot be empty", file=sys.stderr)
        return 2
    if args.kind and args.artifact != "policy":
        print("--kind applies to `chock new policy` only", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    if args.kind:
        args.id = custom_id(args.id, root)
        if not POLICY_ID_RE.fullmatch(args.id):
            print(f"policy id {args.id!r} must match {POLICY_ID_RE.pattern}", file=sys.stderr)
            return 2
    try:
        if args.kind:
            _new_kind(args.id, args.kind, root)
        elif args.artifact == "policy":
            _new_policy(args.id, root)
        elif args.artifact == "skill":
            _new_skill(args.id, root)
        elif args.artifact == "subagent":
            _new_subagent(args.id, root)
    except TemplateError as exc:
        error(str(exc))
        return 2

    rescan_and_report(root)

    cmd_refresh(["--repo", str(root)])

    print(f"Created {args.artifact} '{args.id}' at {root / '.agents'}")
    print(f"Next:  python -m chock check {args.root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_new(argv)
