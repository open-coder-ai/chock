"""Emitters that translate policy manifests into target-surface enforcement artifacts."""

from pathlib import Path

from chock.resources import package_data_dir

#: Shared template/data directory for every emitter in this package.
DATA_DIR = package_data_dir("chock.compile.emitters", "data")

#: Suffixes a guard implementation may carry, in the order discovery prefers them.
GUARD_SUFFIXES = (".sh", ".py")

#: Git events a policy may back with its own script, each mapped to the filename segment
#: that names it: `implementations/<policy_id>-<segment>.{sh,py}`. The manifest's
#: `hook.script.on` speaks the keys; the files on disk speak the values.
SCRIPT_EVENTS = {"commit": "pre-commit", "push": "pre-push"}


def policy_rel_path(policy_dir: Path) -> str:
    """The policy's path relative to the repo root, derived from the policy, not the output."""
    path = Path(policy_dir).resolve()
    for parent in path.parents:
        if (parent / ".agents").is_dir() or (parent / ".chock").is_dir():
            try:
                return path.relative_to(parent).as_posix()
            except ValueError:  # pragma: no cover - relative_to cannot fail on a parent
                break
    return path.name
