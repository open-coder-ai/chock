"""Low-level git-hook installers: dispatchers, validate hook, and policy wrappers.

Split out of `install.py` so lower layers (`scaffold.recompile`) can install policy
hooks without importing the command entrypoint, whose post-install refresh imports
the orchestrator back. `install.py` keeps `main()` and re-exports these names.
"""

from __future__ import annotations

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

DISPATCHER_TEMPLATE = """#!/bin/sh
{marker}
# Runs every executable script in {event}.d/.
set -e
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
STDIN_FILE=$(mktemp)
trap 'rm -f "$STDIN_FILE"' EXIT
cat > "$STDIN_FILE"
for hook in "$HOOK_DIR/{event}.d/"*; do
    [ -e "$hook" ] || continue
    [ -x "$hook" ] || continue
    "$hook" "$@" < "$STDIN_FILE"
done
"""


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
    """True when `repo_root` is itself the top level of a git working tree.

    Every caller below eventually does `hooks_dir.mkdir(parents=True)`, which happily
    conjures a `.git/` directory out of nothing. In a non-git directory that produced a
    fake `.git/hooks/` full of hooks git will never run, while `init` printed success --
    the adopter believed they had commit-time enforcement and had none. Claiming
    enforcement that cannot fire is worse than declining to install it.

    The check is `--show-toplevel`, not `.git` exists: a subdirectory of a repo answers
    yes to `rev-parse` but its hooks live in the parent's `.git`, so installing into
    `<subdir>/.git/hooks` would create the same dead directory one level down.
    """
    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    return bool(toplevel) and Path(toplevel).resolve() == Path(repo_root).resolve()


NOT_A_GIT_REPO = (
    "{root} is not a git repository, so git hooks cannot run there.\n"
    "  Run `git init` in that directory, then `chock sync`."
)


def get_hooks_dir(repo_root: Path) -> Path:
    """Ask git where hooks live instead of reconstructing its layout.

    This used to build `repo_root/.git/hooks` by hand, with a special case for
    `core.hooksPath`. Inside a linked worktree `.git` is a *file* holding a gitdir pointer,
    so the constructed path cannot exist and the `mkdir(parents=True)` every caller does
    next raises NotADirectoryError -- `init` and `install-hooks` crashed outright in any
    `git worktree add` checkout, and the only way to work there was `--skip-hooks`.

    `rev-parse --git-path hooks` is correct for a plain clone, a linked worktree and
    `core.hooksPath` alike, which is why the special case is deleted rather than kept
    beside it. Git answers relative to the directory the query ran in.
    """
    answer = _git(repo_root, "rev-parse", "--git-path", "hooks")
    if not answer:
        # No git to ask. Callers gate on `is_git_repo` before creating anything here.
        return repo_root / ".git" / "hooks"
    path = Path(answer)
    return path if path.is_absolute() else repo_root / path


def _backup_edited_dispatcher(dispatcher: Path, content: str) -> None:
    """Copy an ours-but-edited dispatcher aside before the overwrite below destroys it.

    The marker keeps an adopter-customized dispatcher from being relocated as foreign
    (`is_ours` is True), so appending steps to the installed file -- the natural move --
    used to be silently overwritten on the next sync with no copy anywhere. The backup
    lands next to the hook under a non-hook name, so git never executes it.
    """
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
        return  # unreadable: the relocation path already preserves what it can


def install_dispatcher(hooks_dir: Path, event: str) -> Path:
    """Install a dispatcher shell script for the given git hook event."""
    dispatcher = hooks_dir / event
    impl_dir = hooks_dir / f"{event}.d"
    impl_dir.mkdir(parents=True, exist_ok=True)
    relocate_existing_hook(dispatcher, impl_dir)
    remove_self_relocated_hook(impl_dir)
    content = DISPATCHER_TEMPLATE.format(event=event, marker=GENERATED_MARKER)
    _backup_edited_dispatcher(dispatcher, content)
    # write_generated, not write_text: the dispatcher is an executed shell script, and
    # write_text emits CRLF on Windows -- exactly what `_render_hook` documents and guards
    # against for the fragment it renders. This was the one generated executable that still
    # slipped through, so the installed .git/hooks/pre-commit carried CRLF on Windows.
    write_generated(dispatcher, content)
    dispatcher.chmod(0o755)
    print(f"Installed {event} dispatcher to {dispatcher}")
    return impl_dir


#: Replaced at install time with the interpreter running the installer. That interpreter is
#: by definition one that can import chock, which a bare `python` on PATH is not.
INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"


def _repo_relative(path: Path, repo_root: Path) -> str:
    """A POSIX, repo-relative path suitable for embedding in a shell script.

    Generated hooks must survive the repo being moved, renamed, or mounted at a different
    prefix inside a container, so nothing they reference inside the repo may be absolute.
    """
    try:
        return path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        # Outside the repo: there is no relative form, so an absolute one is the honest
        # answer. `_discover_policy_hooks` only globs inside `.chock/compiled`,
        # so this is a guard against a future caller, not a path taken today.
        return path.resolve().as_posix()


def _render_hook(source: Path, dest: Path) -> None:
    """Write a packaged hook script with the current interpreter baked in.

    LF explicitly: `write_text` without `newline=` emits CRLF on Windows, and a shell
    script with CRLF line endings dies on Linux with `bad interpreter: /usr/bin/env bash^M`.
    The hook is one of the few generated files that is *executed*, so the usual "git
    normalises it on commit" safety net does not apply -- it runs from the working tree.
    """
    rendered = source.read_text(encoding="utf-8").replace(INTERPRETER_PLACEHOLDER, sys.executable)
    write_generated(dest, rendered)


def install_validate_hook(hooks_dir: Path, repo_root: Path) -> None:
    """Install the Chock validate hook into pre-commit.d/."""
    impl_dir = hooks_dir / "pre-commit.d"
    impl_dir.mkdir(parents=True, exist_ok=True)
    source_dir = package_data_dir("chock.hooks", "data")

    if sys.platform == "win32":
        # Git for Windows runs the dispatcher as a shell script; the implementation
        # itself is PowerShell. Write a bash wrapper plus the PowerShell script.
        impl = impl_dir / "99-chock-validate"
        impl_ps1 = impl_dir / "99-chock-validate.ps1"
        _render_hook(source_dir / "pre-commit.ps1", impl_ps1)
        write_generated(
            impl,
            "#!/usr/bin/env bash\n"
            f"{GENERATED_MARKER}\n"
            # The PowerShell script is this wrapper's own sibling, so locate it from $0
            # rather than baking in the path the installer happened to see.
            'hook_dir="$(cd "$(dirname "$0")" && pwd)"\n'
            f'script="$hook_dir/{impl_ps1.name}"\n'
            # powershell.exe cannot open an MSYS path like /c/Users/...; cygpath ships with
            # Git for Windows and converts it to a form PowerShell understands.
            'if command -v cygpath >/dev/null 2>&1; then script="$(cygpath -w "$script")"; fi\n'
            'powershell.exe -ExecutionPolicy Bypass -File "$script" "$@"\n',
        )
    else:
        impl = impl_dir / "99-chock-validate"
        _render_hook(source_dir / "pre-commit", impl)

    try:
        impl.chmod(0o755)
    except Exception:
        pass  # best-effort: chmod is a no-op/denied on Windows; the dispatcher invokes fragments explicitly
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
        # `recompile` reaches here without passing through `init`, and installing anyway
        # would recreate the fake `.git/hooks/` A3 exists to prevent.
        print(f"[WARN] {NOT_A_GIT_REPO.format(root=repo_root)}", file=sys.stderr)
        return

    auto_compile(repo_root)

    events = {
        "pre-commit": "git-pre-commit.sh",
        # A clean (auto) merge creates a commit without ever firing pre-commit -- git runs
        # pre-merge-commit for that, and if no such hook exists the commit gates are skipped
        # entirely, so `git merge --no-ff feature` could land a secret on a protected branch.
        # It runs the same commit shims: "must not enter the codebase" is the same claim
        # whether the commit is a merge or not.
        "pre-merge-commit": "git-pre-commit.sh",
        "pre-push": "git-pre-push.sh",
    }

    for event, script_name in events.items():
        impl_dir = install_dispatcher(hooks_dir, event)

        # Remove stale wrappers so deleted policies disappear on re-run.
        for stale in impl_dir.glob("50-chock-policy-*"):
            stale.unlink()

        implementations = _discover_policy_hooks(repo_root, script_name)
        if not implementations:
            print(f"No {script_name} policies found; {event} dispatcher unchanged")
            continue

        for idx, impl_source in enumerate(implementations, start=1):
            wrapper = impl_dir / f"50-chock-policy-{idx:03d}"
            rel = _repo_relative(impl_source, repo_root)
            write_generated(
                wrapper,
                "#!/bin/sh\n"
                f"{GENERATED_MARKER}\n"
                f"# Source: {rel}\n"
                "set -e\n"
                # Resolved at run time, never baked in. An absolute path breaks the moment
                # the repo is moved, renamed, or mounted at a different prefix in a
                # container -- and on Windows it was a backslash path inside a /bin/sh
                # script, where backslashes are literal, not separators.
                'repo_root="$(git rev-parse --show-toplevel)"\n'
                # Guards are bash scripts (arrays, process substitution). Invoke with
                # bash, not sh — sh is dash on Debian/Ubuntu and would fail to parse them.
                f'bash "$repo_root/{rel}" "$@"\n',
            )
            try:
                wrapper.chmod(0o755)
            except Exception:
                pass  # best-effort: chmod is a no-op/denied on Windows; the dispatcher runs wrappers via bash
        print(f"Registered {len(implementations)} {event} policy implementation(s)")
