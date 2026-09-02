"""Install bundled authoring skills into the consumer's canonical .agents/skills directory."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

import chock
from chock.index.cli import cmd_refresh
from chock.packs import packs_root, to_path
from chock.registry.core import rescan_and_report

AUTHORING_SKILLS = [
    "policy-init",
    "validate",
    "eval",
    "optimize",
]


def _schema_sources() -> list[Path]:
    """The packaged manifest schemas the `validate` skill needs at runtime."""
    schema_src = Path(chock.__file__).parent / "validation" / "schemas"
    return sorted(schema_src.glob("manifest*.json"))


def _inject_schemas(validate_dir: Path) -> None:
    """Copy the installed package's manifest schemas into the validate skill assets."""
    schema_dst = validate_dir / "assets"
    schema_dst.mkdir(parents=True, exist_ok=True)
    for schema_path in _schema_sources():
        shutil.copy2(schema_path, schema_dst / schema_path.name)


def shipped_root() -> Path:
    return to_path(packs_root()) / "_skills"


def installed_root(repo_root: Path) -> Path:
    return Path(repo_root) / ".agents" / "skills"


_IGNORED_DIRS = {"__pycache__"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _is_content(rel: Path) -> bool:
    return not (_IGNORED_DIRS & set(rel.parts)) and rel.suffix not in _IGNORED_SUFFIXES


def _relative_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {rel for p in root.rglob("*") if p.is_file() and _is_content(rel := p.relative_to(root))}


def installed_shipped_ids(repo_root: Path) -> list[str]:
    """Skill ids present in .agents/skills that this version also ships."""
    installed, shipped = installed_root(repo_root), shipped_root()
    if not installed.exists():
        return []
    return sorted(d.name for d in installed.iterdir() if d.is_dir() and (shipped / d.name).is_dir())


def differences(repo_root: Path) -> list[str]:
    """Every way an installed framework skill differs from what this version ships."""
    schemas = {Path("assets") / p.name for p in _schema_sources()}
    out: list[str] = []
    for skill_id in installed_shipped_ids(repo_root):
        shipped, installed = shipped_root() / skill_id, installed_root(repo_root) / skill_id
        injected = schemas if skill_id == "validate" else set()
        ship_files = _relative_files(shipped)
        have_files = _relative_files(installed) - injected
        prefix = Path(skill_id)
        out += [f"missing: {(prefix / rel).as_posix()}" for rel in sorted(ship_files - have_files)]
        out += [f"stale: {(prefix / rel).as_posix()}" for rel in sorted(have_files - ship_files)]
        out += [
            f"differs: {(prefix / rel).as_posix()}"
            for rel in sorted(ship_files & have_files)
            if not filecmp.cmp(shipped / rel, installed / rel, shallow=False)
        ]
    return out


def install_skills(repo_root: Path, skills: list[str] | None = None, *, overwrite: bool = True) -> list[str]:
    """Copy bundled authoring skills into the canonical .agents/skills directory."""
    selected = skills or sorted(set(AUTHORING_SKILLS) | set(installed_shipped_ids(repo_root)))
    source_root = to_path(packs_root())
    target_root = repo_root / ".agents" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    for skill_id in selected:
        src = source_root / "_skills" / skill_id
        if not src.exists():
            continue
        dst = target_root / skill_id
        if dst.exists():
            if not overwrite:
                continue
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        if skill_id == "validate":
            _inject_schemas(dst)
        installed.append(skill_id)
    return installed


def cmd_install_skills(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install bundled authoring skills into .agents/skills")
    parser.add_argument("repo", nargs="?", default=".", help="Target repo root")
    parser.add_argument("--skills", nargs="*", help="Specific skills to install (default: all authoring skills)")
    parser.add_argument("--check", action="store_true", help="Report drift and exit non-zero; write nothing")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()

    if args.check:
        drift = differences(repo_root)
        if drift:
            print(f"Installed skills are out of date ({len(drift)} difference(s)):")
            for line in drift:
                print(f"  {line}")
            print("Run `chock install-skills .`.")
            return 1
        print("Installed skills match the shipped ones.")
        return 0

    installed = install_skills(repo_root, skills=args.skills)
    if not installed:
        print("No skills installed", file=sys.stderr)
        return 1

    rescan_and_report(repo_root)

    print(f"Installed {len(installed)} skill(s) into .agents/skills/:")
    for skill_id in installed:
        print(f"  {skill_id}")

    cmd_refresh(["--repo", str(repo_root)])
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_install_skills(argv)
