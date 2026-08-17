"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from chock.validation.report import Finding, Report


def _staged_paths(root: Path) -> list[str] | None:
    """Repo-relative staged paths, or None when there is no index to read."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.split("\0") if p]


def _drift_severity(root: Path, event: str | None, policy_dirs: list[Path]) -> tuple[str, str]:
    """Severity for a drift finding, and the prefix that explains a softened one.

    At commit time, drift a commit did not touch is drift it did not introduce. Blocking
    every commit until someone repairs an artifact their diff never went near -- an engine
    upgrade changing what `recompile` emits is the common case -- teaches adopters that the
    gate fires on the wrong person, which is how gates get disabled. So under
    `--event commit`, drift stays an error only when the staged diff touches policy source
    or the compiled tree; otherwise it is a warning that names the same fix.

    Outside commit (plain `validate`, CI) it stays strict: those are exactly the places
    pre-existing drift should fail.

    Shared by both drift checks rather than copied. Two statements of one rule is how the
    packaging check would end up quietly stricter than the compiled one, on a judgement
    that was argued once.
    """
    if event != "commit":
        return "error", ""
    staged = _staged_paths(root)
    if staged is None:
        return "error", ""
    watched = [".chock/"] + [d.relative_to(root).as_posix() + "/" for d in policy_dirs]
    if any(p.startswith(tuple(watched)) for p in staged):
        return "error", ""
    return "warning", "Pre-existing drift; this commit does not touch it. "


def check_compiled_drift(root: Path, report: Report, event: str | None = None) -> None:
    """The compiled tree must still be what the manifests produce.

    `.chock/compiled/` and the vendored runner in `.chock/bin/` are what
    actually enforce. Nothing an adopter runs noticed when they stopped matching their
    source: deleting a `gate.json`, weakening its regex in place, or replacing the runner's
    `run()` with `return 0` all disabled enforcement silently while `validate`, `verify` and
    `eval` each exited 0 -- and `eval` reports a policy as passing regardless, because it
    rebuilds the gate from the manifest instead of reading the installed one.

    Only `recompile --check` caught any of it, and that runs in CI, not in the pre-commit
    hook this check is reached from. Putting it here is the point: the adopter learns at
    commit time, in the repo where it matters.

    `event="commit"` scopes the severity, not the check: drift the staged diff never
    touched is reported as a warning instead of blocking a commit that did not cause it.

    Imported lazily. `chock.scaffold.recompile` imports the compiler, and importing
    that at module scope makes the validation package depend on the compile package for
    every caller, including the ones that only load schemas.
    """
    from chock.compile.compiler import _load_manifest
    from chock.config import agents_from_config as _agents_from_config
    from chock.policies import discover_policy_dirs
    from chock.scaffold.recompile import compiled_differences

    compiled_root = root / ".chock" / "compiled"

    # "Never compiled" is not "compiled and then changed", and only the second is drift.
    # A repo straight after `init`, or one where `new policy` has just scaffolded a folder,
    # has a policy with no compiled output yet -- `recompile` is the documented next step,
    # and failing validation before the adopter has run it would break the first commit of
    # every onboarding. So a policy with no compiled directory at all is skipped, per
    # policy: an uncompiled newcomer never masks drift in a policy that *is* compiled.
    #
    # `recompile --check` stays strict and reports both, which is why it, not this, is the
    # command CI should run.
    uncompiled = set()
    policy_dirs = list(discover_policy_dirs(root))
    for pack_dir in policy_dirs:
        policy_id = _load_manifest(pack_dir).get("id") or pack_dir.name
        if not (compiled_root / policy_id).exists():
            uncompiled.add(policy_id)

    severity, preexisting = _drift_severity(root, event, policy_dirs)

    # A config with unknown agent names cannot be judged for drift -- report the config
    # itself instead of crashing the validation run with a traceback.
    try:
        config_agents = _agents_from_config(root)
    except ValueError as exc:
        report.add(
            Finding(
                str(root / ".chock" / "config.yaml"),
                "compiled_drift",
                severity,
                f"{exc}. Compiled drift cannot be judged until the config names real agents.",
            )
        )
        return

    for difference in compiled_differences(root, config_agents):
        _, _, rel = difference.partition(": ")
        head = rel.split("/")[0]
        if head in uncompiled:
            continue
        # coverage.json is repo-wide, so an uncompiled policy legitimately explains a
        # mismatch. Judge it only when every policy has been compiled at least once.
        if head == "coverage.json" and uncompiled:
            continue
        report.add(
            Finding(
                str(root / ".chock"),
                "compiled_drift",
                severity,
                f"{preexisting}Compiled artifact does not match its source ({difference}). "
                "This is what enforces, so it is out of step with the policy it claims to apply. "
                "Run 'chock sync --repo .' and commit the result.",
            )
        )


def check_plugin_drift(root: Path, report: Report, event: str | None = None) -> None:
    """Packaged Agent Plugins output must still be what the manifest produces.

    The same drift class `check_compiled_drift` closes, left open one layer up. Editing a
    policy's `description` and running `recompile` in an adopter repo left `plugin.json`
    describing the old policy while `validate`, `recompile --check` and `eval` all exited 0.
    Only `chock plugin build --check` noticed, and nothing in the adopter flow tells
    anyone that command exists -- `init`, `new policy` and the `policy-init` skill emit no
    packaged output at all, so an adopter meets `plugin.json` only as a file that arrived
    with a copied catalog policy.

    Worse than compiled drift in one respect: compiled artifacts are local, but a stale
    `plugin.json` is read by clients we do not control and cannot correct.

    **Opt-in, by presence.** A policy with no `plugin.json` is not packaged and is skipped
    entirely -- this check must never be the reason a repo that never asked for Agent
    Plugins starts failing, and packaging deliberately is not a compile Surface. Copying a
    policy from the catalog opts you in, because the catalog commits its packaged output,
    which is exactly the case where drift would otherwise be silent.

    Imported lazily, for the reason `check_compiled_drift` gives.
    """
    from chock.compile.compiler import _load_manifest
    from chock.plugin.build import PluginNameError, plugin_differences
    from chock.policies import discover_policy_dirs

    policy_dirs = list(discover_policy_dirs(root))
    packaged = [d for d in policy_dirs if (d / "plugin.json").exists()]
    if not packaged:
        return

    severity, preexisting = _drift_severity(root, event, policy_dirs)

    for policy_dir in packaged:
        manifest = _load_manifest(policy_dir)
        if not manifest:
            continue
        try:
            differences = plugin_differences(policy_dir, manifest, root)
        except PluginNameError as exc:
            # A packaged policy whose id is no longer a legal plugin name cannot be rebuilt,
            # so reporting it as drift would name a fix that does not work. Say the real
            # thing instead, and never let it surface as a traceback out of `validate`.
            report.add(
                Finding(
                    str(policy_dir),
                    "plugin_drift",
                    "error",
                    f"Packaged as an Agent Plugin, but its id is not a legal plugin name ({exc}). "
                    "Rename the policy, or delete plugin.json and skills/ to stop publishing it.",
                )
            )
            continue
        for difference in differences:
            report.add(
                Finding(
                    str(policy_dir),
                    "plugin_drift",
                    severity,
                    f"{preexisting}Packaged Agent Plugins output does not match its manifest ({difference}). "
                    "This is what other clients read, so it publishes a policy that no longer exists. "
                    "Run 'chock plugin build --repo .' and commit the result.",
                )
            )


def check_registry_freshness(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, root: Path, report: Report
) -> None:
    """Detect stale or missing registry entries."""
    registry_file = root / ".chock" / "registry.json"
    if not registry_file.exists():
        report.add(
            Finding(
                str(artifact_dir),
                "registry_freshness",
                "warning",
                "No registry found. Run 'chock registry scan'.",
            )
        )
        return

    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        registered = registry.get("entries", {})
    except (json.JSONDecodeError, OSError):
        report.add(Finding(str(registry_file), "registry_freshness", "error", "Registry file is unreadable."))
        return

    artifact_id = manifest.get("id", "")
    artifact_version = manifest.get("version", "")

    versions = registered.get(artifact_id, [])
    matching = [e for e in versions if e.get("version") == artifact_version and e.get("artifact") == artifact_type]
    if not matching:
        report.add(
            Finding(
                str(artifact_dir),
                "registry_freshness",
                "error",
                f"Registry is stale: {artifact_type} '{artifact_id}' v{artifact_version} not found. Run registry scan.",
            )
        )

    # Note if the same ID is reused across artifact types; resolution is now type-aware.
    if artifact_id in registered:
        seen_types = {e.get("artifact") for e in registered[artifact_id]}
        if len(seen_types) > 1:
            report.add(
                Finding(
                    str(artifact_dir),
                    "registry_freshness",
                    "info",
                    f"ID '{artifact_id}' is registered as {', '.join(sorted(seen_types))}. Resolution now filters by artifact type.",
                )
            )
