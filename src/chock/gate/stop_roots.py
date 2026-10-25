"""Which roots a Stop judges when the client names several, and the one decision their findings earn. Stdlib only."""

from __future__ import annotations

from pathlib import Path

from .gate_outcome import VERDICT_WARN
from .guard_runner import VERDICT_DENY, VERDICT_ESCALATE
from .workspace_root import workspace_roots

#: Of several roots' decisions, the Stop speaks the first of these any root earned.
_SEVERITY = (VERDICT_DENY, VERDICT_ESCALATE, VERDICT_WARN)
_GIT_DIR = ".git"


def repository_of(folder):
    """The repository `folder` is in: the nearest folder holding `.git`, or None outside one."""
    here = Path(folder).absolute()
    if not here.is_dir():
        return None
    return next((f for f in (here, *here.parents) if (f / _GIT_DIR).exists()), None)


def judged_root(named):
    """The top level of `named`'s repository; `named` as given when relative (a drive-lettered root on POSIX)."""
    path = Path(named)
    return (repository_of(path) or path) if path.is_absolute() else path


def stop_roots(event, fallback):
    """The top level of each repository the event's `cwd` and workspace roots are in; else [fallback].

    The top level, not the named folder: `git status` lists paths relative to it, so a subdirectory
    would resolve every listed path against the wrong folder and judge nothing.
    """
    by_repository = {}
    for named in filter(None, (getattr(event, "cwd", None), *workspace_roots(event))):
        repository = repository_of(named)
        if repository is not None:
            by_repository.setdefault(repository, judged_root(named))
    return list(by_repository.values()) or [fallback]


def per_root(said):
    """One (decision, judged files) for each root's own: the most severe verdict, findings under each root's name."""
    if len(said) == 1:
        return said[0][1:]
    spoken = [(root, decision) for root, decision, _judged in said if decision]
    judged = {path: text for _root, _decision, files in said for path, text in files.items()}
    if not spoken:
        return None, judged
    verdict = min((decision[0] for _root, decision in spoken), key=_SEVERITY.index)
    return (verdict, "\n".join(f"In {root}:\n{decision[1]}" for root, decision in spoken)), judged
