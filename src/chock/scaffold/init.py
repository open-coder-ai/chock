"""Deterministic `chock init` implementation."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from chock.compile.surfaces import AGENTS_ARG_REQUIRED_MSG
from chock.emit import write_generated
from chock.hooks.install import NOT_A_GIT_REPO, get_hooks_dir, install_validate_hook, is_git_repo
from chock.lock import build_lock, write_lock
from chock.scaffold.adapters import (
    CHOCK_AGENT,
    deselected_agents,
    parse_agent_selection,
    remove_instructions,
    write_instructions,
)
from chock.scaffold.agents_md import update_agents_md
from chock.scaffold.recompile import BookkeepingError, recompile
from chock.scaffold.templates import (
    GITATTRIBUTES_TEMPLATE,
    _dependency_allowlist_template,
    _preserve_or_write,
    packaged_template,
    write_vendored_guardrails,
)


def _write_agents_md(repo_root: Path, force: bool) -> Path:
    path = repo_root / "AGENTS.md"
    if force or not path.exists():
        repo_name = repo_root.name or "chock-consumer"
        write_generated(path, packaged_template("AGENTS.md").replace("{{repo_name}}", repo_name))
    else:
        update_agents_md(path)
    return path


def _fresh_config(agents: list[str], agent_agnostic: bool) -> dict[str, object]:
    text = packaged_template(".chock/config.yaml").format(
        agents=yaml.safe_dump(list(agents), default_flow_style=True).strip(),
        agent_agnostic="true" if agent_agnostic else "false",
        onboarded_at=datetime.now(timezone.utc).isoformat(),
    )
    return yaml.safe_load(text) or {}  # type: ignore[return-value]


def _fresh_policies(repo_root: Path, fresh: dict[str, object]) -> dict[str, object]:
    """The template's `policies` block, minus toggles for policies that are not installed."""
    from chock.scaffold.recompile import discover_policy_dirs

    policies = dict(fresh.get("policies") or {})  # type: ignore[arg-type]
    installed = {d.name for d in discover_policy_dirs(repo_root)}
    policies["disabled"] = [pid for pid in policies.get("disabled") or [] if pid in installed]
    policies.setdefault("overrides", {})
    return policies


def _write_config(repo_root: Path, agents: list[str], agent_agnostic: bool) -> Path:
    """Write .chock/config.yaml, preserving existing policies and user defaults."""
    path = repo_root / ".chock" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    from chock.config import load_config

    existing = load_config(repo_root) if path.exists() else {}
    fresh = _fresh_config(agents, agent_agnostic)

    existing_chock = existing.get("chock") or {}
    chock = {**existing_chock, **dict(fresh.get("chock", {}))}
    merged_defaults = {**dict(fresh.get("chock", {})).get("defaults", {}), **existing_chock.get("defaults", {})}
    if merged_defaults:
        chock["defaults"] = merged_defaults
    if "onboarded_at" in existing_chock:
        chock["onboarded_at"] = existing_chock["onboarded_at"]

    merged: dict[str, object] = dict(existing)
    merged["chock"] = chock
    merged["policies"] = existing["policies"] if "policies" in existing else _fresh_policies(repo_root, fresh)

    if not path.exists() or existing != merged:
        if path.exists():
            print("[WARN] .chock/config.yaml rewritten; YAML comments are not preserved", file=sys.stderr)
        path.write_text(
            yaml.safe_dump(merged, sort_keys=False, default_flow_style=None, allow_unicode=True),
            encoding="utf-8",
        )

    allowlist = path.parent / "dependency-allowlist.txt"
    if not allowlist.exists():
        allowlist.write_text(_dependency_allowlist_template(), encoding="utf-8")
    return path


def _normalize_agents(args_agents: list[str] | None, agent_agnostic: bool, repo_root: Path) -> list[str]:
    if agent_agnostic:
        return sorted(CHOCK_AGENT)
    if args_agents:
        return list(args_agents)
    from chock.config import agents_from_config, load_config

    if (load_config(repo_root).get("chock") or {}).get("supported_agents"):
        return agents_from_config(repo_root)
    return ["claude", "copilot", "gemini"]


CATALOG_URL = "https://github.com/open-coder-ai/chock-catalog"


def _report_policy_state(repo_root: Path) -> None:
    """Say plainly whether anything is being enforced, and how to change that."""
    from chock.scaffold.recompile import discover_policy_dirs

    installed = discover_policy_dirs(repo_root)
    if installed:
        print(f"Policies: {len(installed)} installed. Nothing was added or overwritten -- they are yours.")
        return
    print("Policies: none. This repo enforces nothing yet.")
    print(f"  1. copy a policy folder from {CATALOG_URL} (base/<id>/) into .agents/policies/<id>/")
    print("  2. chock sync --repo .")


def cmd_init(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize a consumer repo with Chock")
    parser.add_argument("repo", nargs="?", default=".", help="Target repo root")
    parser.add_argument("--agents", nargs="*", help="Agents to generate wrappers for (comma- or space-separated)")
    parser.add_argument("--agent-agnostic", action="store_true", help="Generate wrappers for all supported agents")
    parser.add_argument("--skip-hooks", action="store_true", help="Skip git hook installation")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite scaffolded files that have local edits (destructive)"
    )
    args = parser.parse_args(argv)

    selection: list[str] | None = None
    if args.agents is not None:
        try:
            selection = parse_agent_selection(args.agents)
        except ValueError as exc:
            parser.error(str(exc))
        if not selection:
            parser.error(AGENTS_ARG_REQUIRED_MSG)

    repo_root = Path(args.repo).resolve()
    repo_root.mkdir(parents=True, exist_ok=True)

    try:
        agents = _normalize_agents(selection, args.agent_agnostic, repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    hookable = is_git_repo(repo_root)
    skip_hooks = args.skip_hooks or not hookable
    if not hookable and not args.skip_hooks:
        print(f"[WARN] {NOT_A_GIT_REPO.format(root=repo_root)}\n[WARN] Scaffolding only: no enforcement is active.")

    (repo_root / ".chock").mkdir(exist_ok=True)
    (repo_root / ".agents" / "policies").mkdir(parents=True, exist_ok=True)
    (repo_root / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs").mkdir(exist_ok=True)

    preserved: list[str] = []
    _write_agents_md(repo_root, args.force)
    if _preserve_or_write(repo_root / "docs" / "README.md", packaged_template("docs/README.md"), args.force):
        preserved.append("docs/README.md")
    if _preserve_or_write(repo_root / ".gitattributes", GITATTRIBUTES_TEMPLATE, args.force):
        preserved.append(".gitattributes")
    preserved += write_vendored_guardrails(repo_root, args.force)
    _write_config(repo_root, agents, args.agent_agnostic)

    from chock.scaffold.skills import install_skills

    installed_skills = install_skills(repo_root, overwrite=False)

    try:
        recompile(repo_root, agents, skip_hooks=skip_hooks)
    except BookkeepingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    from chock.index.cli import cmd_refresh

    cmd_refresh(["--repo", str(repo_root)])

    write_instructions(repo_root, agents)
    remove_instructions(repo_root, deselected_agents(agents))

    if not skip_hooks:
        install_validate_hook(get_hooks_dir(repo_root), repo_root)

    try:
        write_lock(build_lock(repo_root), repo_root)
    except OSError as exc:
        print(
            f"[ERROR] chock.lock was not written ({exc}). Re-run `chock init` once the cause is fixed.", file=sys.stderr
        )
        return 1

    from chock.registry.core import rescan_and_report
    from chock.validation import engine as validator_engine

    rescan_and_report(repo_root)

    if validator_engine.main([str(repo_root)]) != 0:
        return 1

    print(f"Initialized Chock in {repo_root}")
    print(f"Agents: AGENTS.md + {', '.join(agents)}")
    for rel in sorted(set(preserved)):
        print(f"[KEPT] {rel} has local edits; left unchanged (use --force to overwrite)")
    if installed_skills:
        print(f"Skills: {', '.join(installed_skills)} (refresh with `chock install-skills .`)")
    _report_policy_state(repo_root)
    print("Verify anytime with:  chock check --only verify")
    return 0


def main(argv: list[str] | None = None) -> int:
    return cmd_init(argv)
