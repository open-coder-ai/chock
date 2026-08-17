"""Install compiled PreToolUse fragments into .claude/settings.json.

Without this, `compile` wrote fragments to `.chock/compiled/<id>/pre-tool-use/` that
nothing ever read. The policies looked wired up and enforced nothing.

Two rules govern how this writes to the adopter's settings file:

  Only Chock's own entries are touched. They are identified by the adapter path in
  their command, so hand-written hooks and every other settings key survive untouched.

  Removing a policy removes its hook. Stale entries are dropped on each run, the same way
  `install_policy_hooks` clears its wrappers, so a disabled policy stops enforcing.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from pathlib import Path

from chock.emit import write_generated_json

SETTINGS_REL = Path(".claude") / "settings.json"
ADAPTER_REL = Path(".chock") / "bin" / "pretooluse.py"
# Every Chock-owned hook command contains this; nothing else should.
_OWNED_MARKER = "/.chock/bin/pretooluse.py"

# The emitted fragment carries this placeholder, not a literal `python`. `python` is absent
# on python3-only systems (stock Ubuntu/Debian), where Claude Code ran the hook, got exit 127,
# and -- treating any non-2 exit as non-blocking -- allowed everything while coverage, keyed
# on the fragment being installed, reported `enforced`. Install bakes the interpreter that ran
# it (which by definition works) into settings.json; the compiled fragment keeps the
# placeholder so committed compiled output stays portable and deterministic. Kept in sync with
# the literal in compile/emitters/claude_pretooluse.py, which a test pins.
INTERPRETER_PLACEHOLDER = "@CHOCK_PYTHON@"


def _bake_interpreter(fragment: dict) -> dict:
    """A copy of `fragment` with the interpreter placeholder replaced by this machine's python.

    An absolute, double-quoted path runs the same under both a POSIX shell and cmd.exe, so
    the baked command is shell-agnostic.
    """
    exe = f'"{sys.executable}"'
    baked = copy.deepcopy(fragment)
    for hook in baked.get("hooks", []) or []:
        if isinstance(hook, dict) and isinstance(hook.get("command"), str):
            hook["command"] = hook["command"].replace(INTERPRETER_PLACEHOLDER, exe)
    return baked


# The interpreter token is everything before the quoted adapter path. `python` (the historic
# literal), an absolute baked path, and the placeholder are all the same hook wearing
# different interpreters. Matches any vendored `.chock/bin/*.py` adapter, so
# `sessionstart_install` shares one normalisation instead of growing a drifting copy.
_COMMAND_TAIL_RE = re.compile(r'^.*?(?="\$\{CLAUDE_PROJECT_DIR\}[^"]*?/\.chock/bin/[a-z_]+\.py")')
# Any command running a vendored adapter is normalisable; only Chock writes into .chock/bin/.
_BIN_MARKER = "/.chock/bin/"


def _normalize_fragment(fragment: dict) -> dict:
    """A copy of `fragment` with the interpreter token normalised to the placeholder.

    Identity of an installed hook must not depend on which machine's interpreter is baked
    into it: `.claude/settings.json` may be a COMMITTED file (the catalog commits it), and a
    committed file cannot be machine-specific. Comparing baked forms directly made coverage
    flip between machines -- derived `enforced` on the machine whose interpreter was baked,
    `advisory` everywhere else, so `sync --check` failed CI on a repo nobody touched.
    """
    normalized = copy.deepcopy(fragment)
    for hook in normalized.get("hooks", []) or []:
        command = hook.get("command") if isinstance(hook, dict) else None
        if isinstance(command, str) and _BIN_MARKER in command:
            hook["command"] = _COMMAND_TAIL_RE.sub(f"{INTERPRETER_PLACEHOLDER} ", command, count=1)
    return normalized


def vendor_adapter(repo_root: Path) -> Path:
    """Copy the stdlib-only PreToolUse adapter into the consumer repo."""
    source = Path(__file__).resolve().parent.parent / "gate" / "pretooluse.py"
    if not source.exists():  # pragma: no cover - packaging failure
        raise FileNotFoundError(
            f"PreToolUse adapter source not found at {source}. "
            "If this is a packaged binary, ensure gate/pretooluse.py is bundled as data."
        )
    dest = Path(repo_root) / ADAPTER_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    try:
        dest.chmod(0o755)
    except OSError:
        pass  # best-effort: chmod is a no-op/denied on Windows; the adapter is invoked as `python <path>`
    return dest


def _compiled_fragments(repo_root: Path) -> list[dict]:
    """Every compiled PreToolUse fragment, ordered by policy id for determinism."""
    compiled = Path(repo_root) / ".chock" / "compiled"
    if not compiled.exists():
        return []
    fragments: list[dict] = []
    for path in sorted(compiled.glob("*/pre-tool-use/pretooluse.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # a malformed fragment must not take the others down
        if isinstance(fragment, dict) and fragment.get("hooks"):
            fragments.append(fragment)
    return fragments


def _is_ours(entry: dict) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    if not isinstance(hooks, list):
        return False
    return any(_OWNED_MARKER in str(h.get("command", "")) for h in hooks if isinstance(h, dict))


def install_pretooluse_hooks(repo_root: Path) -> list[str]:
    """Merge compiled fragments into .claude/settings.json. Returns matchers installed."""
    repo_root = Path(repo_root)
    fragments = _compiled_fragments(repo_root)

    settings_path = repo_root / SETTINGS_REL
    settings: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except (json.JSONDecodeError, OSError):
            # Refuse to overwrite a file we cannot parse: it is the adopter's, and a
            # rewrite would silently discard whatever they had in it.
            raise ValueError(f"{settings_path} is not readable JSON; leaving it untouched") from None

    hooks = settings.setdefault("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    settings["hooks"] = hooks
    existing = hooks.get("PreToolUse")
    ours_before = [e for e in existing if _is_ours(e)] if isinstance(existing, list) else []
    kept = [e for e in existing if not _is_ours(e)] if isinstance(existing, list) else []

    def _install_form(fragment: dict) -> dict:
        # An already-installed entry that is this fragment under a different interpreter is
        # kept byte-for-byte. settings.json may be committed, and rewriting a committed
        # file with this machine's interpreter path on every sync is diff churn at best and
        # a leaked local path at worst. Only a new or genuinely changed fragment is baked.
        wanted = _normalize_fragment(fragment)
        for entry in ours_before:
            if _normalize_fragment(entry) == wanted:
                return entry
        return _bake_interpreter(fragment)

    if not fragments:
        vendored = repo_root / ADAPTER_REL
        if kept:
            hooks["PreToolUse"] = kept
        else:
            hooks.pop("PreToolUse", None)
            if not hooks:
                settings.pop("hooks", None)
        if vendored.exists():
            vendored.unlink()
    else:
        vendor_adapter(repo_root)
        # Compiled fragments on disk keep the placeholder; what settings.json runs is either
        # the entry already installed (unchanged) or a fresh bake of this machine's python.
        hooks["PreToolUse"] = kept + [_install_form(f) for f in fragments]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    write_generated_json(settings_path, settings)
    return [f.get("matcher", "?") for f in fragments]


def installed_pretooluse_policy_ids(repo_root: Path) -> set[str]:
    """Policy ids whose compiled PreToolUse fragment is actually present in settings.json.

    This replaces `record_coverage`, which wrote `enforced` into coverage.json at install
    time. That made two commands disagree about one file: `install-hooks` raised the claim,
    the next `recompile` derived it again and put it back to `advisory`, so
    `recompile --check` reported the repo out of date the moment hooks were installed and
    running `recompile` silently dropped the claim.

    The original reasoning was sound -- a fragment nothing installs enforces nothing, so
    only the installer could honestly assert otherwise. The mistake was treating install
    state as unobservable. `.claude/settings.json` is a committed file, so "is this fragment
    installed" is a question about repo contents, and a derived artifact may depend on it:
    CI reproduces the same answer from the same checkout.

    Identity is the fragment itself, not the policy id, because that is what an edit
    changes. Recompiling a guard whose fragment no longer matches the installed entry drops
    the claim, which is correct -- what is wired up is the old fragment.
    """
    repo_root = Path(repo_root)
    settings_path = repo_root / SETTINGS_REL
    if not settings_path.exists():
        return set()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()  # unreadable settings prove nothing is installed, which is the safe claim
    entries = (settings.get("hooks") or {}).get("PreToolUse") if isinstance(settings, dict) else None
    if not isinstance(entries, list):
        return set()

    compiled = repo_root / ".chock" / "compiled"
    installed: set[str] = set()
    for path in sorted(compiled.glob("*/pre-tool-use/pretooluse.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # Compare interpreter-normalised forms on BOTH sides: settings.json may hold the
        # historic bare `python`, this machine's baked path, or another machine's -- the
        # catalog commits its settings.json, so the file is not machine-specific and the
        # coverage verdict must not be either. Comparing baked forms directly made the same
        # checkout derive `enforced` on one machine and `advisory` on the next.
        wanted = _normalize_fragment(fragment)
        if any(_normalize_fragment(e) == wanted for e in entries if isinstance(e, dict)):
            installed.add(path.parent.parent.name)
    return installed
