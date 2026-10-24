"""Gate runner: who acts (agent or person), the rollout level in force, waivers and `CHOCK_ALLOW`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .constants import (
    _ACTOR_CLIENT_CAP,
    _ACTOR_UNSAFE,
    _CONFIG_ITEM_RE,
    _CONFIG_KEY_RE,
    _CONFIG_PATH,
    _CONFIG_ROLLOUT_RE,
    _ENV_NAME_RE,
    _GIT_EVENTS,
    _HUMAN_ENV,
    ACTOR_AGENT_PREFIX,
    ACTOR_PERSON,
    AGENT_COMMIT_ENV,
    AGENT_COMMIT_EVENT,
    AI_AGENT_ENV,
    ALLOW_ENV,
    CLAUDECODE_ENV,
    HEAD_WAIVER_EVENTS,
    ROLLOUT_ENFORCE,
    ROLLOUT_ENV,
    ROLLOUT_RANK,
    WAIVABLE_EVENTS,
)


# >>> gate.py 03
def _config_agent_env(repo_root: Path) -> list[str]:
    """Names under `agent_commit_env:` in `.chock/config.yaml`, in the working tree and as committed at HEAD.

    Both, so an uncommitted edit that drops a name never hides the agent it named. Read without a YAML parser:
    only an inline list (`[A, B]`), one scalar, or a block list of `- NAME` lines is read; the runner is
    stdlib-only, and anything else yields no names rather than a guess.
    """
    try:
        working = repo_root.joinpath(*_CONFIG_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        working = ""
    names = _env_names(working)
    return names + [name for name in _env_names(_committed_config(repo_root, "HEAD") or "") if name not in names]


def _env_names(text: str) -> list[str]:
    lines = text.splitlines()
    raw: list[str] = []
    block = False
    for line in lines:
        if block:
            item = _CONFIG_ITEM_RE.match(line)
            if item:
                raw.append(item.group("name"))
                continue
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            block = False
        key = _CONFIG_KEY_RE.match(line)
        if key:
            rest = key.group("rest").strip()
            block = not rest
            raw.extend(part for part in rest.strip("[]").split(",") if part.strip())
    names = (name.strip().strip("'\"") for name in raw)
    return [name for name in names if _ENV_NAME_RE.match(name)]


def agent_signal(repo_root: Path | None = None) -> str | None:
    """The first agent marker set, or None for a person's shell: a truthy `CHOCK_AGENT_COMMIT`, `CLAUDECODE=1`,
    a non-empty `AI_AGENT`, or any non-empty variable named under the repository's `agent_commit_env`.

    One rule for every check (commit, push, tool call, stop, resume, the person-only commands). `CHOCK_AGENT_COMMIT=0`
    clears nothing a vendor set, since an agent can set it too: a person's git in an agent's terminal is told apart
    by having no vendor marker, which is what their own shell has.
    """
    env = os.environ
    named = env.get(AGENT_COMMIT_ENV, "").strip().lower()
    checks = (
        (AGENT_COMMIT_ENV, bool(named) and named not in _HUMAN_ENV),
        (f"{CLAUDECODE_ENV}=1", env.get(CLAUDECODE_ENV) == "1"),
        (AI_AGENT_ENV, bool(env.get(AI_AGENT_ENV, "").strip())),
        *((name, bool(env.get(name))) for name in (_config_agent_env(repo_root) if repo_root is not None else [])),
    )
    return next((signal for signal, present in checks if present), None)


def actor_of(signal: str | None) -> str:
    """Who acted, as a log record names it: `person`, or `agent:<client>` from the marker (`unknown` when it names none)."""
    if signal is None:
        return ACTOR_PERSON
    client = "claude_code" if signal == f"{CLAUDECODE_ENV}=1" else ""
    if signal == AI_AGENT_ENV:  # `claude-code_<version>_agent`: the client is the first word
        client = _ACTOR_UNSAFE.sub("", os.environ.get(AI_AGENT_ENV, "").split("_")[0].replace("-", "_").lower())
    return ACTOR_AGENT_PREFIX + (client[:_ACTOR_CLIENT_CAP] or "unknown")


def agent_commit(repo_root: Path | None = None) -> bool:
    """True when the environment marks this commit as a coding agent's."""
    return agent_signal(repo_root) is not None


# >>> gate.py 05
def rollout_level(raw: object) -> str:
    """The level `raw` names; anything absent, unreadable or unknown is enforce, never a looser guess."""
    value = raw.strip().strip("'\"") if isinstance(raw, str) else None
    return value if value in ROLLOUT_RANK else ROLLOUT_ENFORCE


def rollout_from_text(text: str) -> str:
    """The level a config's text names, read line by line and never by a YAML parser, so every reader
    (the runtime, `chock status`, the baseline check) agrees: one top-level `rollout:` line, else enforce."""
    found = [m.group("rest") for m in map(_CONFIG_ROLLOUT_RE.match, text.splitlines()) if m]
    return rollout_level(found[0]) if len(found) == 1 else ROLLOUT_ENFORCE


def _config_rollout(repo_root: Path) -> str:
    """`rollout:` in the working tree's `.chock/config.yaml`; a symlink, or an unreadable file, is enforce."""
    path = repo_root.joinpath(*_CONFIG_PATH)
    try:
        if path.is_symlink():
            return ROLLOUT_ENFORCE
        return rollout_from_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ROLLOUT_ENFORCE


def _committed_config(repo_root: Path, ref: str) -> str | None:
    """`.chock/config.yaml` as committed at `ref`; None when git cannot show it."""
    try:
        shown = subprocess.run(  # noqa: S603 -- reading one committed file
            ["git", "-C", str(repo_root), "show", f"{ref}:{'/'.join(_CONFIG_PATH)}"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    return shown.stdout if shown.returncode == 0 else None


def committed_rollout(repo_root: Path, ref: str) -> str:
    """`rollout:` as committed at `ref`; a ref or file git cannot show is enforce."""
    text = _committed_config(repo_root, ref)
    return ROLLOUT_ENFORCE if text is None else rollout_from_text(text)


def _stricter(*levels: str) -> str:
    return max(levels, key=ROLLOUT_RANK.__getitem__)


def rollout(repo_root: Path, event: str, signal: str | None, base: str | None = None) -> str:
    """The level in force. Nothing the actor being judged can edit may lower it:

    - at ci, the base's committed level caps the head's, so a pull request cannot lower its own gates;
    - an agent (a tool call, the turn's end, an agent's commit) is held to HEAD's committed level too,
      so an uncommitted edit to the config never lowers an agent's gates;
    - `CHOCK_ROLLOUT` counts only for a person's own commit or push.
    """
    level = _config_rollout(repo_root)
    if event == "ci":
        return _stricter(level, committed_rollout(repo_root, base)) if base else ROLLOUT_ENFORCE
    if signal is not None or event not in _GIT_EVENTS:
        return _stricter(level, committed_rollout(repo_root, "HEAD"))
    override = os.environ.get(ROLLOUT_ENV, "").strip()
    return override if override in ROLLOUT_RANK else level


def _judged_event(name: str, *, agent: bool) -> str:
    """The event a gate is judged at: an agent's commit reads `agent-commit`, not `commit`."""
    return AGENT_COMMIT_EVENT if name == "commit" and agent else name


def _waiver_pattern(params: dict, event: str) -> str | None:
    """The waiver pattern for events that honour a waiver at all, else None."""
    pragma = params.get("allowlist_pragma") if event in WAIVABLE_EVENTS | HEAD_WAIVER_EVENTS else None
    return str(pragma) if pragma else None


# >>> gate.py 16
def allowed_ids() -> set[str]:
    """Policy ids a person named in `CHOCK_ALLOW`, comma separated."""
    return {name.strip() for name in os.environ.get(ALLOW_ENV, "").split(",") if name.strip()}


def git_email(repo_root: Path | None = None) -> str:
    """The person's git `user.email`, as their shell's git reads it; empty when git names none."""
    where = ["-C", str(repo_root)] if repo_root is not None else []
    try:
        shown = subprocess.run(  # noqa: S603 -- reading one git setting
            ["git", *where, "config", "user.email"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ""
    return shown.stdout.strip() if shown.returncode == 0 else ""


def approval(repo_root: Path | None = None) -> dict[str, str]:
    """What an override's record keeps of who approved it: `CHOCK_ALLOW` and the person's git email. Local log only."""
    return {"override": ALLOW_ENV, "approver": git_email(repo_root) or "unknown"}


def _ask_refusal(policy_id: str | None, signal: str | None) -> str:
    """Why a hook refuses an `ask`, and the one way through: a person's explicit override, which only a person is told."""
    if policy_id is None:
        return f"gate: this gate asks a person, a hook cannot prompt, and it has no policy id for {ALLOW_ENV} to name."
    lead = f"gate: {policy_id} asks a person to decide, and a hook cannot prompt."
    if signal:
        return (
            f"{lead} This is treated as an agent's ({signal}), and an agent cannot answer for the person: "
            "ask them. If they agree, they run this one command from their own shell."
        )
    return f"{lead} To go ahead, a person runs this one command from their own shell with {ALLOW_ENV}={policy_id} set."


def _ask_answered(policy_id: str | None, signal: str | None) -> bool:
    """A person's `CHOCK_ALLOW` names this policy and no agent marker is on the command."""
    return policy_id is not None and policy_id in allowed_ids() and signal is None
