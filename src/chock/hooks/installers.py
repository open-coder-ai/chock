"""Low-level git-hook installers: dispatchers, validate hook, and policy wrappers."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

from chock.emit import write_generated
from chock.hooks.autocompile import auto_compile
from chock.hooks.ownership import (
    GENERATED_MARKER,
    is_ours,
    relocate_existing_hook,
    remove_self_relocated_hook,
)
from chock.resources import package_data_dir

_DATA_DIR = package_data_dir("chock.hooks", "data")
DISPATCHER_TEMPLATE = _DATA_DIR.joinpath("dispatcher.sh").read_text(encoding="utf-8")
_VALIDATE_WRAPPER_WINDOWS_TEMPLATE = _DATA_DIR.joinpath("validate_wrapper_windows.sh").read_text(encoding="utf-8")
_POLICY_WRAPPER_TEMPLATE = _DATA_DIR.joinpath("policy_wrapper.sh").read_text(encoding="utf-8")


def _git(repo_root: Path, *args: str) -> str | None:
    """Answer a read-only git query from inside `repo_root`. None when git cannot answer."""
    try:
        return subprocess.check_output(
            ["git", *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def is_git_repo(repo_root: Path) -> bool:
    """True when `repo_root` is itself the top level of a git working tree."""
    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    return bool(toplevel) and Path(toplevel).resolve() == Path(repo_root).resolve()


NOT_A_GIT_REPO = (
    "{root} is not a git repository, so git hooks cannot run there.\n"
    "  Run `git init` in that directory, then `chock sync`."
)


def get_hooks_dir(repo_root: Path) -> Path:
    """Ask git where hooks live instead of reconstructing its layout."""
    answer = _git(repo_root, "rev-parse", "--git-path", "hooks")
    if not answer:
        return repo_root / ".git" / "hooks"
    path = Path(answer)
    return path if path.is_absolute() else repo_root / path


def _backup_edited_dispatcher(dispatcher: Path, content: str) -> None:
    """Copy an ours-but-edited dispatcher aside before the overwrite below destroys it."""
    try:
        if not (dispatcher.exists() and not dispatcher.is_symlink() and is_ours(dispatcher)):
            return
        if dispatcher.read_text(encoding="utf-8") == content:
            return
        backup = dispatcher.with_name(f"{dispatcher.name}.chock-backup")
        n = 2
        while backup.exists() and backup.read_text(encoding="utf-8") != dispatcher.read_text(encoding="utf-8"):
            backup = dispatcher.with_name(f"{dispatcher.name}.chock-backup-{n}")
            n += 1
        if not backup.exists():
            shutil.copy2(dispatcher, backup)
        print(
            f"[KEPT] your edited {dispatcher.name} dispatcher was backed up to {backup.name}. "
            f"The dispatcher is regenerated on every sync -- put custom steps in {dispatcher.name}.d/ instead.",
            file=sys.stderr,
        )
    except (OSError, UnicodeDecodeError):
        return


def install_dispatcher(hooks_dir: Path, event: str) -> Path:
    """Install a dispatcher shell script for the given git hook event."""
    dispatcher = hooks_dir / event
    impl_dir = hooks_dir / f"{event}.d"
    impl_dir.mkdir(parents=True, exist_ok=True)
    relocate_existing_hook(dispatcher, impl_dir)
    remove_self_relocated_hook(impl_dir)
    content = DISPATCHER_TEMPLATE.replace("__EVENT__", event).replace("__MARKER__", GENERATED_MARKER)
    _backup_edited_dispatcher(dispatcher, content)
    write_generated(dispatcher, content)
    dispatcher.chmod(0o755)
    print(f"Installed {event} dispatcher to {dispatcher}")
    return impl_dir


INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"


def _repo_relative(path: Path, repo_root: Path) -> str:
    """A POSIX, repo-relative path suitable for embedding in a shell script."""
    try:
        return path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _render_hook(source: Path, dest: Path) -> None:
    """Write a packaged hook script with the current interpreter baked in."""
    rendered = source.read_text(encoding="utf-8").replace(INTERPRETER_PLACEHOLDER, sys.executable)
    write_generated(dest, rendered)


def install_validate_hook(hooks_dir: Path, _repo_root: Path) -> None:
    """Install the Chock validate hook into pre-commit.d/."""
    impl_dir = hooks_dir / "pre-commit.d"
    impl_dir.mkdir(parents=True, exist_ok=True)
    source_dir = package_data_dir("chock.hooks", "data")

    if sys.platform == "win32":
        impl = impl_dir / "99-chock-validate"
        impl_ps1 = impl_dir / "99-chock-validate.ps1"
        _render_hook(source_dir / "pre-commit.ps1", impl_ps1)
        content = _VALIDATE_WRAPPER_WINDOWS_TEMPLATE.replace("__MARKER__", GENERATED_MARKER).replace(
            "__SCRIPT_NAME__", impl_ps1.name
        )
        write_generated(impl, content)
    else:
        impl = impl_dir / "99-chock-validate"
        _render_hook(source_dir / "pre-commit", impl)

    with contextlib.suppress(OSError):
        impl.chmod(0o755)
    print(f"Implementation registered at {impl}")


def _discover_policy_hooks(repo_root: Path, script_name: str) -> list[Path]:
    """Discover compiled git-hook shims."""
    compiled_root = repo_root / ".chock" / "compiled"
    if compiled_root.exists():
        return sorted(compiled_root.rglob(f"*/git-hook/{script_name}"))
    return []


def install_policy_hooks(repo_root: Path, hooks_dir: Path) -> None:
    """Discover compiler-generated git-pre-commit.sh and git-pre-push.sh and register them."""
    if not is_git_repo(repo_root):
        print(f"[WARN] {NOT_A_GIT_REPO.format(root=repo_root)}", file=sys.stderr)
        return

    auto_compile(repo_root)

    events = {
        "pre-commit": "git-pre-commit.sh",
        "pre-merge-commit": "git-pre-commit.sh",
        "pre-push": "git-pre-push.sh",
    }

    for event, script_name in events.items():
        impl_dir = install_dispatcher(hooks_dir, event)

        for stale in impl_dir.glob("50-chock-policy-*"):
            stale.unlink()

        implementations = _discover_policy_hooks(repo_root, script_name)
        if not implementations:
            print(f"No {script_name} policies found; {event} dispatcher unchanged")
            continue

        for idx, impl_source in enumerate(implementations, start=1):
            wrapper = impl_dir / f"50-chock-policy-{idx:03d}"
            rel = _repo_relative(impl_source, repo_root)
            content = _POLICY_WRAPPER_TEMPLATE.replace("__MARKER__", GENERATED_MARKER).replace("__SOURCE_REL__", rel)
            write_generated(wrapper, content)
            with contextlib.suppress(OSError):
                wrapper.chmod(0o755)
        print(f"Registered {len(implementations)} {event} policy implementation(s)")
