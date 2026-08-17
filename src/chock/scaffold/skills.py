"""Install bundled authoring skills into the consumer's canonical .agents/skills directory."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

import chock
from chock.packs import packs_root, to_path

# Authoring skills a consumer repo uses. `chock-init` is the onboarding
# skill and is intentionally excluded — a consumer is already onboarded.
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
    """Copy the installed package's manifest schemas into the validate skill assets.

    The `validate` skill needs the JSON schemas at runtime. They are packaged data
    under `chock.validation.schemas` (wheel, editable, and PyInstaller) and
    are injected here instead of being hand-maintained in `packs/_skills/validate/assets`.
    """
    schema_dst = validate_dir / "assets"
    schema_dst.mkdir(parents=True, exist_ok=True)
    for schema_path in _schema_sources():
        shutil.copy2(schema_path, schema_dst / schema_path.name)


def shipped_root() -> Path:
    return to_path(packs_root()) / "_skills"


def installed_root(repo_root: Path) -> Path:
    return Path(repo_root) / ".agents" / "skills"


#: Interpreter droppings, never skill content. A skill ships template `.py` files; importing
#: or byte-compiling one writes `__pycache__/` beside it, and inside a pip-installed package
#: that lands in the shipped tree. `--check` then demanded an adopter hold a `.pyc` built on
#: another machine, for another Python version -- unsatisfiable by `install-skills` itself.
#: Only surfaced in CI, where the package is installed rather than run from a checkout.
_IGNORED_DIRS = {"__pycache__"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _is_content(rel: Path) -> bool:
    return not (_IGNORED_DIRS & set(rel.parts)) and rel.suffix not in _IGNORED_SUFFIXES


def _relative_files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {rel for p in root.rglob("*") if p.is_file() and _is_content(rel := p.relative_to(root))}


def installed_shipped_ids(repo_root: Path) -> list[str]:
    """Skill ids present in .agents/skills that this version also ships.

    A skill an adopter wrote lives in the same directory and is not ours to compare,
    reinstall, or report on.
    """
    installed, shipped = installed_root(repo_root), shipped_root()
    if not installed.exists():
        return []
    return sorted(d.name for d in installed.iterdir() if d.is_dir() and (shipped / d.name).is_dir())


def differences(repo_root: Path) -> list[str]:
    """Every way an installed framework skill differs from what this version ships.

    Injected schemas are excluded: they come from the package, not the pack, so they have
    no shipped counterpart and would otherwise be reported as stale on every run.
    """
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
    """Copy bundled authoring skills into the canonical .agents/skills directory.

    Skills live in exactly one place (.agents/skills). Agent wrappers already
    redirect to AGENTS.md, which points every agent here — so there is no per-agent
    copy. This matches the agent-agnostic model and the framework's own layout.

    `overwrite=False` installs only what is absent. `init` needs that: this function
    replaces a skill wholesale, so calling it unconditionally on every `init` would
    destroy an adopter's edits — the exact data loss that had to be fixed for AGENTS.md
    and the adapter wrappers. Running `install-skills` explicitly still refreshes
    everything, because there the overwrite is what was asked for.
    """
    # Anything already installed is refreshed too, not just the default set. Otherwise
    # `install-skills .` could not repair the drift `--check` reports for a skill outside
    # AUTHORING_SKILLS -- this repo installs `chock-init`, and its copy is the one
    # that drifted, scaffolding four config keys that had been deleted as dead.
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
        # Same exclusion as `differences`, or the installer writes the very files the
        # check then has to forgive -- and an adopter commits another machine's bytecode.
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

    # Refresh the registry so `validate` passes right after install (no manual scan).
    from chock.registry.core import save_registry, scan

    entries, skips = scan(repo_root)
    if skips:
        print(f"[WARN] {len(skips)} manifest(s) skipped during registry scan:")
        for skip in skips:
            print(f"  [ERROR] {skip.path} :: manifest_parse: {skip.reason}")
    save_registry(entries, repo_root)

    print(f"Installed {len(installed)} skill(s) into .agents/skills/:")
    for skill_id in installed:
        print(f"  {skill_id}")

    from chock.index.cli import cmd_refresh

    cmd_refresh(["--repo", str(repo_root)])
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_install_skills(argv)
