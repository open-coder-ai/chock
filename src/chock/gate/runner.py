#!/usr/bin/env python3
"""Chock vendored gate runner — SELF-CONTAINED, STDLIB ONLY."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_GIT = shutil.which("git") or "git"


@dataclass
class GateResult:
    allowed: bool
    message: str = ""
    matches: list[str] = field(default_factory=list)


class GateContext:
    """Read-only git facts. Every accessor swallows git errors and returns empty."""

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
        try:
            proc = subprocess.run(  # noqa: S603 -- reading repo facts via git is this class's whole job
                [_GIT, "-c", "core.quotePath=false", *args],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, UnicodeError):
            return ""
        else:
            return proc.stdout or ""

    def rev_exists(self, ref: str) -> bool:
        """True when `ref` resolves to a commit. Used to fail CI closed on a missing base."""
        return bool(self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip())

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
        """Content before the change, or "" when the path is new in it."""
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
            if len(parts) >= _PUSH_LINE_MIN_PARTS:
                refs.append(parts[2])
        return refs


def _kind_content_regex(ctx: GateContext, params: dict, _event: str) -> GateResult:
    content_re = re.compile(params["content_pattern"])
    forbidden_path_regex = params.get("forbidden_path_regex")
    path_re = re.compile(forbidden_path_regex) if forbidden_path_regex else None
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


def _kind_forbidden_ref(ctx: GateContext, params: dict, event: str) -> GateResult:
    protected = [str(r) for r in params.get("refs", [])]
    if event == "push":
        candidates = [(r, r.removeprefix("refs/heads/")) for r in ctx.push_refs() if r.startswith("refs/heads/")]
    else:
        branch = ctx.head_ref or ctx.current_branch()
        candidates = [(b, b) for b in [branch] if b and b != "HEAD"]
    for shown, name in candidates:
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in protected):
            return GateResult(allowed=False, matches=[shown])
    return GateResult(allowed=True)


_REQ_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)")
_GOMOD_RE = re.compile(r"^\s*([A-Za-z0-9._~/-]+\.[A-Za-z0-9._~/-]+)\s+v")


def _deps_requirements(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "-")):
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
    except Exception:  # noqa: BLE001 -- untrusted, possibly-malformed manifest content; never crash the gate on it
        return set()


def _kind_dependency_allowlist(ctx: GateContext, params: dict, _event: str) -> GateResult:
    watched = set(params.get("manifests", []))
    allow: set[str] = set()
    allow_path = ctx.repo_root / params["allowlist_file"]
    if allow_path.exists():
        for line in allow_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                allow.add(s.lower())

    matches: list[str] = []
    staged = sorted(p for p in ctx.staged_paths() if p.rsplit("/", 1)[-1] in watched)
    for path in staged:
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


GATE_LOG_ENV = "CHOCK_GATE_LOG"
_LOG_MAX_BYTES = 1_048_576
_LOG_MATCH_CAP = 20

#: A pre-push stdin line is `<local ref> <local sha> <remote ref> <remote sha>`;
#: at least 3 whitespace-separated parts to reach the remote ref at index 2.
_PUSH_LINE_MIN_PARTS = 3

#: `<repo>/.chock/compiled/<policy>/git-hook/<script>`.resolve().parents needs at
#: least 4 entries to reach the `compiled` directory at index 2 and its parent
#: (the `.chock` root) at index 3.
_MIN_COMPILED_PATH_DEPTH = 4


def _log_outcome(gate_path: Path, event: str, spec: dict, result: GateResult) -> None:
    """Append one outcome record. Best effort: never raises, never changes the verdict."""
    try:
        if os.environ.get(GATE_LOG_ENV) == "0":
            return
        parents = gate_path.resolve().parents
        if len(parents) < _MIN_COMPILED_PATH_DEPTH or parents[2].name != "compiled":
            return
        log_dir = parents[3] / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gate-events.jsonl"
        if log_path.exists() and log_path.stat().st_size > _LOG_MAX_BYTES:
            log_path.replace(log_dir / "gate-events.1.jsonl")
        record = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy_id": parents[1].name,
            "surface": parents[0].name,
            "event": event,
            "kind": spec.get("kind"),
            "verdict": "allow" if result.allowed else "block",
            "match_count": len(result.matches),
            "matches": result.matches[:_LOG_MATCH_CAP],
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- best effort logging: never raises, never changes the verdict
        return


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
        return 0
    try:
        spec = json.loads(gate_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"gate: cannot read {gate_path}: {exc}", file=sys.stderr)
        return 2
    if event == "ci":
        name, covered = "ci", "commit" in spec.get("on", [])
    else:
        name = _EVENT_NAME.get(event, event)
        covered = name in spec.get("on", [])
    if not covered:
        return 0
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        print(f"gate: unknown kind {spec.get('kind')!r}", file=sys.stderr)
        return 2
    ctx = GateContext(repo_root=repo_root, push_stdin=push_stdin, base=base, head_ref=head_ref)
    if event == "ci" and base and not ctx.rev_exists(base):
        print(
            f"gate: base ref {base!r} does not resolve -- refusing to scan an empty range. "
            "Fetch it (e.g. actions/checkout with fetch-depth: 0) or pass a base that exists.",
            file=sys.stderr,
        )
        return 2
    result = kind(ctx, spec.get("params", {}), name)
    _log_outcome(gate_path, name, spec, result)
    if not result.allowed:
        print(result.message or spec.get("message", ""), file=sys.stderr)
        for m in result.matches:
            print(f"  - {m}", file=sys.stderr)
        return 1
    return 0


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(  # noqa: S603 -- finding the repo root via git is this fallback's job
            [_GIT, "rev-parse", "--show-toplevel"], text=True, encoding="utf-8", errors="replace"
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

    if args.event == "ci" and not args.base:
        parser.error("--event ci requires --base")

    push_stdin = sys.stdin.read() if args.event == "pre-push" and not sys.stdin.isatty() else None
    return run(Path(args.gate), args.event, push_stdin, _repo_root(), base=args.base, head_ref=args.head_ref)


if __name__ == "__main__":
    raise SystemExit(main())
