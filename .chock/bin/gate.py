#!/usr/bin/env python3
"""Chock vendored gate runner — SELF-CONTAINED, STDLIB ONLY.

Copied verbatim to <repo>/.chock/bin/gate.py by `chock compile`.
MUST NOT import any third-party package (no pyyaml) or anything from `chock`.
Reads a compiled gate.json and enforces a deterministic gate at git-hook time, or over a
commit range in CI.

Usage (from a compiled shim):
  python3 .chock/bin/gate.py run --gate <path/to/gate.json> --event {pre-commit,pre-push}
  python3 .chock/bin/gate.py run --gate <path/to/gate.json> --event ci --base <ref> \
      [--head-ref <name>]
Exit codes: 0 = allow, 1 = block, 2 = usage/spec error.

This file is exempt from the repo's 300-line review budget (tests/test_repo_standards.py).
It is vendored into adopter repos as ONE self-contained file, so "split it by activity" --
the remedy the budget assumes -- is not available here without breaking that guarantee.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class GateResult:
    allowed: bool
    message: str = ""
    matches: list[str] = field(default_factory=list)


class GateContext:
    """Read-only git facts. Every accessor swallows git errors and returns empty.

    `base` selects what "the change" means. None is index mode (pre-commit/pre-push): the
    accessors read the staged index, exactly as before. Set, they diff `base...HEAD` -- the
    whole range a pull request adds. A CI checkout has no staged index, so an index-mode gate
    run there scans nothing and passes everything, which is why the previous CI step could not
    have enforced anything regardless of how it was wired.

    Three dots, not two: `base...HEAD` is the head side since the merge base, so a gate does
    not fire on work that arrived on the base branch after the PR was opened.
    """

    def __init__(
        self,
        repo_root: Path,
        push_stdin: str | None = None,
        base: str | None = None,
        head_ref: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self._push_stdin = push_stdin or ""
        self.base = base
        self.head_ref = head_ref

    def _range(self) -> list[str]:
        """The git-diff scope: a commit range in CI, the staged index otherwise."""
        return [f"{self.base}...HEAD"] if self.base else ["--cached"]

    def _git(self, *args: str) -> str:
        # Explicit encoding, never the locale's: `text=True` alone decodes with cp1252 on Windows, so a staged
        # U+2190 arrow (E2 86 90; 0x90 undefined there) crashed the hook and blocked the commit with a traceback
        # instead of a verdict. errors="replace" keeps scanning -- a scanner dying on odd bytes protects nothing.
        #
        # core.quotePath=false: with git's default, a path containing any non-ASCII byte is
        # emitted by --name-only wrapped in quotes with octal escapes ("caf\303\251.txt"). The
        # follow-up `git show :<that-string>` then fails and this method swallows the error, so
        # a secret committed in `sécrets.txt` was scanned as zero lines and allowed. Forcing raw
        # UTF-8 output makes every path round-trip to the show/diff calls unchanged.
        try:
            proc = subprocess.run(
                ["git", "-c", "core.quotePath=false", *args],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return proc.stdout or ""
        except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
            return ""

    def rev_exists(self, ref: str) -> bool:
        """True when `ref` resolves to a commit. Used to fail CI closed on a missing base."""
        return bool(self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())

    # ACMRT, not AM: a rename-with-edit reports as R and a file swapped for a symlink as T,
    # both of which git's default rename detection hid from an AM filter -- `git mv notes.txt
    # config.txt` then pasting a secret was never scanned. D (delete) stays out: nothing to scan.
    def staged_paths(self, diff_filter: str = "ACMRT") -> list[str]:
        out = self._git("diff", *self._range(), "--name-only", f"--diff-filter={diff_filter}")
        return [line.strip() for line in out.splitlines() if line.strip()]

    def added_lines(self, path: str) -> list[str]:
        out = self._git("diff", *self._range(), "-U0", "--", path)
        lines: list[str] = []
        for line in out.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])
        return lines

    def staged_blob(self, path: str) -> str:
        """The proposed content: staged in index mode, committed at HEAD in range mode."""
        return self._git("show", f"HEAD:{path}" if self.base else f":{path}")

    def head_blob(self, path: str) -> str:
        """Content before the change, or "" when the path is new in it.

        In range mode this must read the BASE side. Left as HEAD it would compare the
        proposed file against itself, so `dependency_allowlist` -- which reports only what a
        change ADDS -- would compute an empty set and pass every unlisted package in CI.
        """
        return self._git("show", f"{self.base or 'HEAD'}:{path}")

    def current_branch(self) -> str:
        branch = self._git("symbolic-ref", "--short", "HEAD").strip()
        if branch:
            return branch
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def push_refs(self) -> list[str]:
        refs: list[str] = []
        for line in self._push_stdin.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                refs.append(parts[2])  # <local_ref> <local_sha> <remote_ref> <remote_sha>
        return refs


# ------------------------------------------------------------------ kind: content_regex
def _kind_content_regex(ctx: GateContext, params: dict, event: str) -> GateResult:
    content_re = re.compile(params["content_pattern"])
    path_re = re.compile(params["forbidden_path_regex"]) if params.get("forbidden_path_regex") else None
    pragma_re = re.compile(params["allowlist_pragma"]) if params.get("allowlist_pragma") else None
    scan = params.get("scan", "added_lines")
    diff_filter = params.get("diff_filter", "ACMRT")

    matches: list[str] = []
    for path in ctx.staged_paths(diff_filter):
        if path_re and path_re.search(path):
            blob = ctx.staged_blob(path)
            if not (pragma_re and pragma_re.search(blob)):
                matches.append(f"{path}: forbidden path")
        lines = ctx.staged_blob(path).splitlines() if scan == "staged_blob" else ctx.added_lines(path)
        for line in lines:
            if pragma_re and pragma_re.search(line):
                continue
            if content_re.search(line):
                matches.append(f"{path}: content pattern")
                break
    return GateResult(allowed=not matches, matches=matches)


# ------------------------------------------------------------------ kind: forbidden_ref
def _kind_forbidden_ref(ctx: GateContext, params: dict, event: str) -> GateResult:
    # fnmatchcase, never fnmatch: fnmatch normcases on Windows while git refs are case-sensitive everywhere.
    # With no metacharacter it degrades to plain equality, so exact refs behave exactly as before; `*` spans `/`,
    # so `release/*` also covers `release/1.2/rc` -- protecting a namespace means protecting the whole namespace.
    protected = [str(r) for r in params.get("refs", [])]
    # One branch-name test drives every event, so a pattern cannot enforce on push and not on commit.
    if event == "push":
        candidates = [(r, r.removeprefix("refs/heads/")) for r in ctx.push_refs() if r.startswith("refs/heads/")]
    else:
        # `head_ref` names the branch under test when git cannot: a CI checkout is normally a
        # detached HEAD, where current_branch() finds nothing. Without the override the
        # detached case still yields no candidate and allows, exactly as before -- a ref gate
        # that guessed a branch name in CI would block work it was never pointed at.
        branch = ctx.head_ref or ctx.current_branch()
        candidates = [(b, b) for b in [branch] if b and b != "HEAD"]
    for shown, name in candidates:
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in protected):
            return GateResult(allowed=False, matches=[shown])
    return GateResult(allowed=True)


# ------------------------------------------------------------ kind: dependency_allowlist
# Extractors parse the WHOLE staged file, not added diff lines. A diff line carries no
# section context, so the previous generic "quoted key" regex could not tell a dependency
# from any other key: it flagged name/version/scripts in package.json and matched nothing
# at all in pyproject.toml or go.mod, silently passing hallucinated packages.
_REQ_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)")
_GOMOD_RE = re.compile(r"^\s*([A-Za-z0-9._~/-]+\.[A-Za-z0-9._~/-]+)\s+v")


def _deps_requirements(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-"):
            continue
        m = _REQ_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def _deps_pyproject(text: str) -> set[str]:
    data = tomllib.loads(text)
    names: set[str] = set()
    project = data.get("project") or {}
    specs = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        specs.extend(extra or [])
    for spec in specs:
        m = _REQ_RE.match(str(spec))
        if m:
            names.add(m.group(1))
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    names.update(k for k in poetry if k.lower() != "python")
    return names


def _deps_package_json(text: str) -> set[str]:
    data = json.loads(text)
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.update(section)
    return names


def _deps_go_mod(text: str) -> set[str]:
    names: set[str] = set()
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("require ("):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        candidate = s[len("require ") :] if s.startswith("require ") else (s if in_block else "")
        m = _GOMOD_RE.match(candidate)
        if m:
            names.add(m.group(1))
    return names


# Only formats with a real extractor may be watched. `chock check` rejects
# anything absent here, so a policy cannot claim a format the runtime silently ignores.
EXTRACTORS = {
    "requirements.txt": _deps_requirements,
    "pyproject.toml": _deps_pyproject,
    "package.json": _deps_package_json,
    "go.mod": _deps_go_mod,
}


def _extract(path: str, text: str) -> set[str]:
    fn = EXTRACTORS.get(path.rsplit("/", 1)[-1])
    if fn is None or not text.strip():
        return set()
    try:
        return fn(text)
    except Exception:  # malformed file: report nothing rather than block on a parse error
        return set()


def _kind_dependency_allowlist(ctx: GateContext, params: dict, event: str) -> GateResult:
    watched = set(params.get("manifests", []))
    allow: set[str] = set()
    allow_path = ctx.repo_root / params["allowlist_file"]
    if allow_path.exists():
        for line in allow_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                allow.add(s.lower())

    # Match on basename, not full path: `watched` holds bare names ("package.json"), while
    # staged paths are repo-relative ("web/package.json"). A set intersection only ever hit a
    # root-level manifest, so every nested manifest in a monorepo was silently unscanned.
    matches: list[str] = []
    staged = sorted(p for p in ctx.staged_paths() if p.rsplit("/", 1)[-1] in watched)
    for path in staged:
        # Report only dependencies this commit ADDS. Scanning the staged file alone would
        # block a commit that merely touches a manifest already containing an unlisted
        # package -- a gate that fires on untouched lines gets switched off.
        added = _extract(path, ctx.staged_blob(path)) - _extract(path, ctx.head_blob(path))
        for name in sorted(added):
            if name.lower() not in allow:
                matches.append(f"{path}: {name}")
    return GateResult(allowed=not matches, matches=matches)


KINDS = {
    "content_regex": _kind_content_regex,
    "forbidden_ref": _kind_forbidden_ref,
    "dependency_allowlist": _kind_dependency_allowlist,
}


# -------------------------------------------------------------------------- outcome log
# Local evidence, never telemetry: one JSONL line per gate that actually evaluated, so
# "has this gate ever fired, and does it fire wrongly" stops being unanswerable. Nothing
# leaves the machine. Disable with CHOCK_GATE_LOG=0 -- an env var because the runner
# is stdlib-only and so cannot read .chock/config.yaml, which needs a yaml parser.
GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576
_LOG_MATCH_CAP = 20


def _log_outcome(gate_path: Path, event: str, spec: dict, result: GateResult) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
        # `<artifact_root>/compiled/<policy_id>/<surface>/gate.json` is the only shape a
        # compiled shim invokes, and the path carries the policy id that gate.json
        # deliberately does not -- which is why logging needs no change to compiled specs.
        # Any other shape (an eval replaying a spec against a temp repo) is not an
        # enforcement event, so it is not evidence and is not recorded.
        parents = gate_path.resolve().parents
        if len(parents) < 4 or parents[2].name != "compiled":
            return
        log_dir = parents[3] / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gate-events.jsonl"
        # One generation of rotation. An append-only file in a repo that never shrinks is a
        # slow disk leak, and the recent tail is the part anyone reads.
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            log_path.replace(log_dir / "gate-events.1.jsonl")
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": "allow" if result.allowed else "block",
            # Recorded separately from `matches` so the cap below can never understate a hit.
            "match_count": len(result.matches),
            # Safe to record only because no kind puts scanned content in `matches`: they
            # carry paths, ref names and package names. scan-secrets reports "<path>: content
            # pattern", never the credential it matched -- keep it that way, or this log
            # becomes the plaintext secret store that policy exists to prevent.
            "matches": result.matches[:_LOG_MATCH_CAP],
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # a gate that fails while logging must still deliver its verdict
        return


# ------------------------------------------------------------------------------- runner
_EVENT_NAME = {"pre-commit": "commit", "pre-push": "push"}


def run(
    gate_path: Path,
    event: str,
    push_stdin: str | None,
    repo_root: Path,
    base: str | None = None,
    head_ref: str | None = None,
) -> int:
    gate_path = Path(gate_path)
    if not gate_path.exists():
        return 0  # no gate -> allow
    try:
        spec = json.loads(gate_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"gate: cannot read {gate_path}: {exc}", file=sys.stderr)
        return 2
    if event == "ci":
        # A gate declaring `commit` runs here too: "this must not enter the codebase" is the
        # same claim whether it is checked at the index or over a pull request's range, and CI
        # exists to catch the commit-time gate that was skipped with --no-verify.
        #
        # `push`-only gates are deliberately NOT promoted. CI has no equivalent of pushing to a
        # named ref, so running one here would invent an enforcement point no policy declared.
        name, covered = "ci", "commit" in spec.get("on", [])
    else:
        name = _EVENT_NAME.get(event, event)
        covered = name in spec.get("on", [])
    if not covered:
        return 0  # event not covered -> allow
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        print(f"gate: unknown kind {spec.get('kind')!r}", file=sys.stderr)
        return 2
    ctx = GateContext(repo_root=repo_root, push_stdin=push_stdin, base=base, head_ref=head_ref)
    # Fail closed, not open, on a base CI cannot resolve. A shallow checkout, an empty
    # GITHUB_BASE_REF, or a renamed base branch makes `git diff <base>...HEAD` error; every
    # accessor then swallows the error and returns empty, so the gate would scan nothing and
    # pass -- the CI backstop reporting green over a diff it never read. Better to break the
    # build with a diagnosis than to vouch for an unscanned range.
    if event == "ci" and base and not ctx.rev_exists(base):
        print(
            f"gate: base ref {base!r} does not resolve -- refusing to scan an empty range. "
            "Fetch it (e.g. actions/checkout with fetch-depth: 0) or pass a base that exists.",
            file=sys.stderr,
        )
        return 2
    result = kind(ctx, spec.get("params", {}), name)
    # Logged here, after a kind ran: the early returns above (no gate file, event not
    # covered, unknown kind) are "this gate did not apply", which is not an outcome.
    _log_outcome(gate_path, name, spec, result)
    if not result.allowed:
        print(result.message or spec.get("message", ""), file=sys.stderr)
        for m in result.matches:
            print(f"  - {m}", file=sys.stderr)
        return 1
    return 0


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
        )
        return Path(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
        return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run a compiled gate")
    run_p.add_argument("--gate", required=True, help="Path to compiled gate.json")
    run_p.add_argument("--event", required=True, choices=["pre-commit", "pre-push", "ci"])
    run_p.add_argument("--base", help="Base ref to diff HEAD against (required for --event ci)")
    run_p.add_argument("--head-ref", help="Branch under test, e.g. $GITHUB_HEAD_REF (used by forbidden_ref)")
    args = parser.parse_args(argv)

    # Refused rather than defaulted. Guessing a base (origin/main, say) would silently scan
    # the wrong range and report a clean result for a diff nobody checked.
    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())
