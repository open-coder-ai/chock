"""Run a guard script against a shell command, and log the verdict."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GUARD_VIOLATION = 1
#: A guard that wants the user asked before the command runs, with its own reason.
GUARD_ASK_EXIT = 3

PYTHON_SUFFIX = ".py"

#: Lower-cased markers of an interpreter crash: exit 1 with one of these (or with no output at
#: all) is a guard that failed, not one that refused, so it asks instead of blocking.
_CRASH_MARKERS = ("traceback (most recent call last)", "syntax error", "syntaxerror", "unexpected eof")
#: What CHOCK_TOOL says when the hook payload names no shell tool this runner recognises.
TOOL_UNKNOWN = "unknown"
#: Set to 1 in the guard's environment when argv is a plain whitespace split, not a shell parse.
ARGV_FALLBACK_ENV = "CHOCK_ARGV_FALLBACK"

_POSIX_BASH = ("bash", "/bin/bash", "/usr/bin/bash")
#: Where Git for Windows installs when `git` is not on PATH to say where it is.
_GIT_FOR_WINDOWS = (r"C:\Program Files\Git", r"C:\Program Files (x86)\Git")
#: Git's own launcher first: bin/bash.exe sets up the environment usr/bin/bash.exe expects.
_GIT_BASH_DIRS = (("bin",), ("usr", "bin"))
_BASH_EXE = "bash.exe"
#: `bash` on a bare Windows PATH is System32's WSL launcher or a Store stub, neither of which
#: can see a Windows path: never a guard's interpreter.
_WINDOWS_STUB_DIRS = ("/system32/", "/windowsapps/")
#: Git's coreutils (sed, grep) live in usr/bin; a guard calling them needs it on PATH.
_COREUTILS_MARKER = "sed.exe"
_WINDOWS = "nt"
#: The bash found by the first probe, reused for every later guard in this process.
_FOUND_BASH = {}

GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576

_GUARD_TIMEOUT_SECONDS = 30

GUARD_BLOCKED = "blocked"
GUARD_CLEAN = "clean"
GUARD_ASKED = "asked"
GUARD_UNCHECKED = "unchecked"
GUARD_ERRORED = "errored"

VERDICT_DENY = "deny"
VERDICT_ESCALATE = "escalate"


def guard_path_from_argv(argv: list[str]) -> Path | None:
    """The `--guard <path>` argument a vendored runtime was invoked with, or None."""
    if "--guard" in argv:
        i = argv.index("--guard")
        if i + 1 < len(argv):
            return Path(argv[i + 1])
    return None


def _git_roots() -> list[Path]:
    """Git for Windows install roots: from `git` on PATH (cmd/ or mingw64/bin/), then the defaults."""
    git = shutil.which("git")
    near = [Path(git).parent.parent, Path(git).parent.parent.parent] if git else []
    return [*near, *(Path(root) for root in _GIT_FOR_WINDOWS)]


def bash_candidates() -> list[str]:
    """Bash interpreters to try, best first; on Windows Git's own, never the WSL launcher."""
    if os.name != _WINDOWS:
        return list(_POSIX_BASH)
    found = [str(root.joinpath(*sub, _BASH_EXE)) for root in _git_roots() for sub in _GIT_BASH_DIRS]
    on_path = shutil.which("bash")
    if on_path and not any(stub in on_path.lower().replace("\\", "/") for stub in _WINDOWS_STUB_DIRS):
        found.append(on_path)
    return [c for i, c in enumerate(found) if c not in found[:i] and Path(c).is_file()]


def interpreter_env(interpreter: str) -> dict[str, str]:
    """The environment a guard runs in: on Windows, Git's usr/bin ahead on PATH for sed and grep."""
    env = dict(os.environ)
    if os.name != _WINDOWS:
        return env
    home = Path(interpreter).parent
    usr_bin = next((d for d in (home.parent / "usr" / "bin", home) if (d / _COREUTILS_MARKER).is_file()), None)
    if usr_bin is not None:
        env["PATH"] = str(usr_bin) + os.pathsep + env.get("PATH", "")
    return env


def find_bash(guard: Path) -> str | None:
    """First bash that can actually see `guard`, probed once per process; None when none can."""
    if "bash" in _FOUND_BASH:
        return _FOUND_BASH["bash"]
    for candidate in bash_candidates():
        try:
            proc = subprocess.run(  # noqa: S603 -- probing candidate shells is this function's job
                [candidate, "-c", f'test -f "{guard.as_posix()}"'],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            _FOUND_BASH["bash"] = candidate
            return candidate
    return None


def find_interpreter(guard: Path) -> str | None:
    """The interpreter that can run `guard`: this Python for `.py`, otherwise a usable bash."""
    if guard.suffix == PYTHON_SUFFIX:
        return sys.executable or None
    return find_bash(guard)


def normalize_tool(tool: str | None) -> str:
    """The hook payload's tool name as `bash` | `powershell` | `shell` | `unknown`."""
    name = (tool or "").lower()
    if name in ("powershell", "pwsh"):
        return "powershell"
    if name == "bash":
        return "bash"
    if name == "sh" or "shell" in name:
        return "shell"
    return TOOL_UNKNOWN


def is_guard_crash(output: str) -> bool:
    """True when a guard's exit-1 output is empty or shows an interpreter crash, not a refusal."""
    lowered = output.lower()
    return not lowered or any(marker in lowered for marker in _CRASH_MARKERS)


def split_command(command: str) -> tuple[list[str], bool]:
    """POSIX `shlex.split` argv, else a whitespace split; the flag is True on the fallback."""
    try:
        return shlex.split(command), False
    except ValueError:
        return command.split(), True


def run_guard(guard: Path, command: str, tool: str = "") -> str:
    """`GUARD_BLOCKED` / `GUARD_ASKED` / `GUARD_CLEAN` when the guard ran, otherwise why it did not."""
    return run_guard_detailed(guard, command, tool)[0]


def run_guard_detailed(guard: Path, command: str, tool: str = "") -> tuple[str, str]:
    """`run_guard`'s verdict plus the guard's own first line, which an ask carries to the user."""
    args, fallback = split_command(command)
    if not args:
        return GUARD_UNCHECKED, ""

    interpreter = find_interpreter(guard)
    if interpreter is None:
        reason = (
            f"no usable bash was found to run {guard.name}; on Windows install Git for Windows "
            "(it ships bash), elsewhere put bash on PATH"
        )
        print(f"chock: {reason}", file=sys.stderr)
        return GUARD_ERRORED, reason

    try:
        env = {**interpreter_env(interpreter), "CHOCK_RAW_COMMAND": command, "CHOCK_TOOL": normalize_tool(tool)}
        if fallback:
            env[ARGV_FALLBACK_ENV] = "1"
        proc = subprocess.run(  # noqa: S603 -- running the guard script against the command is the feature
            [interpreter, str(guard), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_GUARD_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"chock: guard timed out after {_GUARD_TIMEOUT_SECONDS}s, not checked",
            file=sys.stderr,
        )
        return GUARD_ERRORED, ""
    except (OSError, UnicodeError) as exc:
        print(f"chock: guard could not run, not checked: {exc}", file=sys.stderr)
        return GUARD_ERRORED, ""

    output = ((proc.stderr or "") + (proc.stdout or "")).strip()
    first_line = output.splitlines()[0].strip() if output else ""
    if proc.returncode == GUARD_VIOLATION:
        if is_guard_crash(output):
            print(f"chock: guard {Path(guard).name} exited 1 without a reason (crash?), not checked", file=sys.stderr)
            return GUARD_ERRORED, ""
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        return GUARD_BLOCKED, first_line
    if proc.returncode == GUARD_ASK_EXIT:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        return GUARD_ASKED, first_line
    if proc.returncode != 0:
        print(
            f"chock: guard exited {proc.returncode}, not checked" + (f": {first_line[:120]}" if first_line else ""),
            file=sys.stderr,
        )
        return GUARD_ERRORED, ""
    return GUARD_CLEAN, ""


def append_gate_log(chock_root: Path, record: dict) -> None:
    """Append one record, stamped, to `<chock_root>/log/gate-events.jsonl`, rotating past the size cap."""
    log_dir = chock_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gate-events.jsonl"
    if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
        log_path.replace(log_dir / "gate-events.1.jsonl")
    stamped = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **record}
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")


def log_outcome(guard: Path, tool: str, *, verdict: str) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
        guard = guard.resolve()
        if guard.parent.name != "implementations":
            return
        artifact_root = None
        for parent in guard.parents:
            if (parent / ".chock").is_dir():
                artifact_root = parent / ".chock"
                break
        if artifact_root is None:
            return
        record = {
            "policy_id": guard.parent.parent.name,
            "surface": "pre-tool-use",
            "event": "tool_use",
            "kind": guard.stem,
            "tool": tool,
            "verdict": verdict,
        }
        append_gate_log(artifact_root, record)
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


def evaluate(argv: list[str], command: str, tool: str = "") -> tuple[str, str] | None:
    """Run the guard named on `argv` (`--guard <path>`) against `command`."""
    guard = guard_path_from_argv(argv)
    if guard is None:
        return None
    if not guard.exists():
        # The hook config names this guard, so its absence is a broken install, not "nothing to check".
        return (
            VERDICT_DENY,
            f"chock guard {guard} is missing, so this command cannot be checked. "
            "Run `chock sync --repo .` to reinstall the policy's guards.",
        )
    verdict, message = run_guard_detailed(guard, command, tool)
    logged = {GUARD_BLOCKED: "block", GUARD_ASKED: "ask", GUARD_CLEAN: "allow"}
    if verdict in logged:
        log_outcome(guard, tool, verdict=logged[verdict])
    if verdict == GUARD_BLOCKED:
        return (VERDICT_DENY, f"Blocked by chock policy: {guard.stem}")
    if verdict == GUARD_ASKED:
        # The guard's own line is the prompt: it names what needs confirming, never the
        # raw command, which would put a live tool argument into the client's UI.
        return (
            VERDICT_ESCALATE,
            f"chock policy {guard.stem} asks before this runs: {message}"
            if message
            else f"chock policy {guard.stem} asks for confirmation before this runs (guard gave no reason).",
        )
    if verdict == GUARD_ERRORED:
        why = message or f"the {guard.stem} guard did not complete (see this hook's stderr)"
        return (
            VERDICT_ESCALATE,
            f"chock could not check this command against {guard.stem}: {why}. Approving runs it unchecked.",
        )
    return None
