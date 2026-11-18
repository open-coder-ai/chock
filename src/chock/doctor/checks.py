"""One target's checks, each PASS, WARN, FAIL or INFO with a one-line fix. Reads only; never runs a client."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentseam import recordings

from chock import __version__, vendors
from chock.doctor import fired
from chock.doctor.targets import ROUTE_SYNC, Target, marker_engine
from chock.gate import runtime_bundle
from chock.gate.runner import journal
from chock.hooks import launch
from chock.scaffold.pin import engine_commit

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
#: The interpreters the launcher tries, in its own order.
PYTHONS = ("python3", "python", "py")
_PROBE = "import sys; print('%d.%d' % sys.version_info[:2])"
_PROBE_TIMEOUT = 10
#: The heartbeat check looks back over this many sessions by default.
SESSIONS = 3


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str
    fix: str = ""


def rebuild(target: Target) -> str:
    """The one-line fix for a target whose hooks are missing, stale or broken."""
    if target.route == ROUTE_SYNC:
        return f"run `chock sync --repo {target.root}`"
    return f"rebuild it: `chock install --selection <your selection> --client {target.client}`"


def hooks_present(target: Target) -> Check:
    if target.wired() and target.runtime.is_file():
        return Check(PASS, "hooks", f"{target.hooks} runs {target.runtime.name}")
    if target.wired():
        return Check(FAIL, "hooks", f"{target.hooks} runs {target.runtime}, which is missing", rebuild(target))
    return Check(FAIL, "hooks", f"{target.hooks} does not run {target.runtime.name}", rebuild(target))


def _python_version(name: str) -> tuple[int, ...] | None:
    found = shutil.which(name)
    if found is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603 -- a local interpreter's own version, as the launcher would find it
            [found, "-c", _PROBE], capture_output=True, text=True, timeout=_PROBE_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return tuple(int(part) for part in done.stdout.strip().split("."))
    except ValueError:
        return None


def launcher(target: Target) -> Check:
    if not target.launcher.is_file():
        return Check(FAIL, "launcher", f"{target.launcher} is missing: every hook refuses", rebuild(target))
    least = ".".join(map(str, launch.MIN_PYTHON))
    usable = [(n, v) for n in PYTHONS if (v := _python_version(n)) is not None and v >= launch.MIN_PYTHON]
    if not usable:
        return Check(FAIL, "python", f"no python3, python or py {least}+ on PATH", f"install Python {least} or newer")
    name, version = usable[0]
    return Check(PASS, "launcher", f"{target.launcher.name} present; {name} is {'.'.join(map(str, version))}")


def _engine_names() -> str:
    commit = engine_commit()
    return f"chock {__version__}" + (f" ({commit[:12]})" if commit else "")


def engine(target: Target) -> Check:
    """Whether the installed runtime is the one this chock would build now, and (plugins) the commit it recorded."""
    shared = target.runtime.with_name(runtime_bundle.SHARED_FILE)
    for path, expected in (
        (target.runtime, runtime_bundle.render(target.agent)),
        (shared, runtime_bundle.render_shared()),
    ):
        try:
            same = path.read_text(encoding="utf-8") == expected
        except (OSError, UnicodeDecodeError):
            return Check(FAIL, "engine", f"{path} is unreadable", rebuild(target))
        if not same:
            return Check(FAIL, "engine", f"{path.name} was not built by {_engine_names()}", rebuild(target))
    if target.route == ROUTE_SYNC:
        return Check(PASS, "engine", f"runtime matches {_engine_names()}")
    built = marker_engine(target)
    recorded, version = built.get("commit"), built.get("version")
    if version != __version__ or (recorded and engine_commit() and recorded != engine_commit()):
        what = f"chock {version}" + (f" ({str(recorded)[:12]})" if recorded else "")
        return Check(WARN, "engine", f"runtime matches, but built by {what}, not {_engine_names()}", rebuild(target))
    return Check(PASS, "engine", f"runtime matches; built by {_engine_names()}")


def trust(target: Target) -> Check | None:
    """Codex runs a hook only once a person trusts it; where that is recorded is not readable by chock."""
    if not vendors.entry(target.agent).get("needs_trust"):
        return None
    hint = vendors.entry(target.agent).get("trust_hint") or "trust the hooks in the client"
    return Check(INFO, "trust", f"{target.agent} hooks run only once trusted; chock cannot read that record", hint)


def client_version(target: Target, given: str | None) -> Check:
    seen = recordings.versions(target.agent)
    if not seen:
        return Check(
            INFO,
            "client",
            f"agentseam has witnessed no {target.agent} version",
            "see agentseam's evidence wanted issues",
        )
    if given is None:
        return Check(
            INFO,
            "client",
            f"agentseam witnessed {', '.join(seen)}; doctor does not run the client",
            "pass --client-version to compare",
        )
    if given in seen:
        return Check(PASS, "client", f"{given} is a version agentseam witnessed")
    return Check(
        WARN,
        "client",
        f"{given} is not a version agentseam witnessed ({', '.join(seen)})",
        "behaviour there is unwitnessed",
    )


def _heartbeat(target: Target, beats: list[dict], hooks: list[dict], sessions: int, repo: Path) -> Check:
    if not vendors.session_start_documented(target.agent):
        return Check(INFO, "heartbeat", f"no heartbeat available: {target.agent} documents no session-start event")
    if not beats:
        what = "hook records but no session_start heartbeat" if hooks else "no session_start heartbeat yet"
        return Check(
            WARN,
            "heartbeat",
            what,
            f"start a new session; if none appears, the client is not loading it: {rebuild(target)}",
        )
    since = beats[-sessions:][0]["ts"]
    quiet = not any(r["ts"] >= since for r in hooks)
    last = f"last heartbeat {beats[-1]['ts']}"
    if quiet and journal.log_settings(repo)[0] == journal.LOG_OFF:
        return Check(INFO, "heartbeat", f"{last}; level off logs nothing since", "set level info to log every call")
    if quiet:  # every allowed tool call is an info line: a session with none means no hook fired
        return Check(
            WARN,
            "heartbeat",
            f"{last}; no hook fired in the last {len(beats[-sessions:])} session(s)",
            "check the client loads the pre-tool hooks",
        )
    return Check(PASS, "heartbeat", f"{last}; hooks fired since")


def activity(target: Target, sessions: int, repo: Path) -> list[Check]:
    beats, hooks = fired.split(fired.records(target))
    last = fired.last_by_surface(hooks)
    seen = "; ".join(f"{surface} {ts}" for surface, ts in last.items())
    fired_check = Check(PASS, "last fired", seen) if last else Check(INFO, "last fired", "no hook record yet")
    return [fired_check, _heartbeat(target, beats, hooks, sessions, repo)]


def run(target: Target, repo: Path, sessions: int = SESSIONS, version: str | None = None) -> list[Check]:
    found = [hooks_present(target), launcher(target), engine(target)]
    found += [c for c in (trust(target),) if c is not None]
    return [*found, client_version(target, version), *activity(target, sessions, repo)]
