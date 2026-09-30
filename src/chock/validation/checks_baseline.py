"""Refuse a branch whose policy set is weaker than its base's: a hook cannot guard its own config."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chock import yamlio
from chock.config import policy_status
from chock.gate.runner import ROLLOUT_RANK, committed_rollout, rollout_from_text
from chock.validation.report import Finding, Report, emit
from chock.validation.selection_baseline import KINDS, Kind, SelectionInvalidError, loosened

CONFIG_REL = Path(".chock") / "config.yaml"
_CATEGORY = "policy_baseline"


class BaselineError(RuntimeError):
    """The comparison cannot be made, which is not the same as passing it."""


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- reading a git revision is this check's whole job
        ["git", "-C", str(repo_root), *args],  # noqa: S607 -- git from PATH
        capture_output=True,
        text=True,
        check=False,
    )


def _parse(text: str, where: str) -> dict[str, Any]:
    try:
        loaded = yamlio.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"{CONFIG_REL.as_posix()} at {where} is not valid YAML: {exc}"
        raise BaselineError(msg) from exc
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True)
class Weakening:
    """One policy this branch enforces less of than its base does."""

    policy_id: str
    was: str
    now: str

    def render(self) -> str:
        return f"{self.policy_id}: {self.was} -> {self.now}"


def config_at(repo_root: Path, ref: str) -> dict[str, Any] | None:
    """The config as of `ref`, or None when that revision carried none. A ref that does not resolve raises."""
    if _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        msg = f"base ref {ref!r} does not resolve in this checkout; fetch it before comparing against it"
        raise BaselineError(msg)
    result = _git(repo_root, "show", f"{ref}:{CONFIG_REL.as_posix()}")
    return _parse(result.stdout, ref) if result.returncode == 0 else None


def config_in_worktree(repo_root: Path) -> dict[str, Any] | None:
    """The config this branch would merge, read from the checkout CI already has."""
    path = Path(repo_root) / CONFIG_REL
    if not path.is_file():
        return None
    return _parse(path.read_text(encoding="utf-8"), "HEAD")


def _named(config: dict[str, Any] | None) -> set[str]:
    policies = (config or {}).get("policies") or {}
    return set(policies.get("disabled") or []) | set((policies.get("overrides") or {}).keys())


def _reach(config: dict[str, Any] | None, policy_id: str) -> tuple[int, frozenset[str], str]:
    """How much of a policy a config lets run: (rank, surfaces, description)."""
    status = policy_status(config or {}, policy_id)
    if status["state"] == "disabled":
        return 0, frozenset(), "disabled"
    targets = frozenset(status["targets"] or ())
    if status["state"] == "enabled":
        return 1, targets, "enabled"
    return 1, targets, "limited to " + ", ".join(sorted(targets))


def weakenings(base: dict[str, Any] | None, head: dict[str, Any] | None) -> list[Weakening]:
    """Every policy the head config lets run less of than the base config does.

    A policy named by neither config is enabled in both, so only the ids either one names
    can differ. No config at all is not an absence of policy: it is every policy enabled.
    """
    found = []
    for policy_id in sorted(_named(base) | _named(head)):
        base_rank, base_targets, was = _reach(base, policy_id)
        head_rank, head_targets, now = _reach(head, policy_id)
        if head_rank < base_rank or (head_rank == base_rank and not head_targets >= base_targets):
            found.append(Weakening(policy_id, was, now))
    return found


def rollout_weakening(repo_root: Path, base: str) -> Weakening | None:
    """A rollout level the head lowers below the base's, read the way the runtime reads it.

    The runtime reads `rollout:` line by line, without YAML; comparing parsed YAML here would let a
    config that the two read differently (a quoted multi-line value, a file that is not a mapping)
    run at observe while this check saw enforce. A symlinked config counts at its target's level,
    the looser reading, so a link can never hide a downgrade from this check.
    """
    path = Path(repo_root) / CONFIG_REL
    try:
        now = rollout_from_text(path.read_text(encoding="utf-8")) if path.is_file() else rollout_from_text("")
    except (OSError, UnicodeDecodeError):
        now = rollout_from_text("")
    was = committed_rollout(Path(repo_root), base)
    return Weakening("rollout", was, now) if ROLLOUT_RANK[now] < ROLLOUT_RANK[was] else None


def _selection_text(repo_root: Path, kind: Kind, ref: str | None) -> str | None:
    """A selection file at `ref` (None: the worktree); None when that revision carried none."""
    if ref is None:
        path = repo_root / kind.filename
        return path.read_text(encoding="utf-8") if path.is_file() else None
    result = _git(repo_root, "show", f"{ref}:{kind.filename}")
    return result.stdout if result.returncode == 0 else None


def check_selections(repo_root: Path, base: str, report: Report) -> None:
    """One error per rule verdict the rule-selection files loosen against `base`, or cannot be read."""
    for kind in KINDS:
        path = str(repo_root / kind.filename)
        try:
            base_text = _selection_text(repo_root, kind, base)
            head_text = _selection_text(repo_root, kind, None)
            found = loosened(kind, base_text, head_text)
        except (SelectionInvalidError, OSError, UnicodeDecodeError) as exc:
            report.add(Finding(path, _CATEGORY, "error", f"{exc} -- nothing was compared"))
            continue
        for item in found:
            msg = (
                f"{item.render()} -- looser than {base}. A rule's verdict is loosened in a pull request "
                "a human approves, never as a side effect of the change that needed it gone."
            )
            report.add(Finding(path, _CATEGORY, "error", msg))


def check_baseline(repo_root: Path, base: str, report: Report) -> None:
    """One error per policy `.chock/config.yaml` weakens relative to `base`, a lowered rollout level, a loosened rule."""
    repo_root = Path(repo_root)
    try:
        found = weakenings(config_at(repo_root, base), config_in_worktree(repo_root))
        lowered = rollout_weakening(repo_root, base)
        found = [lowered, *found] if lowered else found
    except BaselineError as exc:
        report.add(Finding(str(repo_root / CONFIG_REL), _CATEGORY, "error", f"{exc} -- nothing was compared"))
        return
    for weakening in found:
        report.add(
            Finding(
                str(repo_root / CONFIG_REL),
                _CATEGORY,
                "error",
                f"{weakening.render()} -- weaker than {base}. A policy is switched off or narrowed in a "
                "pull request a human approves, never as a side effect of the change that needed it gone.",
            )
        )
    check_selections(repo_root, base, report)


def main(argv: list[str] | None = None) -> int:
    """`chock check --only baseline --base <ref>`: every policy the head lets run less of than `ref`."""
    parser = argparse.ArgumentParser(prog="chock check --only baseline")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--base", required=True, help="Git ref whose policy set this branch may not weaken")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    report = Report()
    check_baseline(Path(args.repo).resolve(), args.base, report)
    emit(report, use_json=args.json)
    return 0 if report.is_clean() else 1


if __name__ == "__main__":
    raise SystemExit(main())
