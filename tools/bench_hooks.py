"""Time the real Claude Code hook commands of a chock adopter repo for a Bash and a Write call, per engine."""

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ENGINES = ["1.0.0", str(HERE.parent)]
AGENT_MARKERS = ("CLAUDECODE", "AI_AGENT")


def load_config(path: Path) -> dict:
    """The policies and payloads, read from the JSON file beside this script."""
    return json.loads(path.read_text(encoding="utf-8"))


GIT = shutil.which("git") or "git"
SHELL = shutil.which("bash") or shutil.which("sh") or "sh"
STUB_HOOKS = 4


def run(argv: list[str], cwd: Path) -> None:
    """Run a setup command and stop on failure."""
    subprocess.run(argv, cwd=cwd, check=True)  # noqa: S603 - argv built here from the harness's own venv


def prepare(work: Path, engine: str, cfg: dict) -> tuple[Path, str]:
    """Make a venv, install the engine, and build a scratch adopter repo; return (repo, engine id)."""
    marked = [m for m in AGENT_MARKERS if os.environ.get(m)]
    if marked:
        sys.exit(
            f"bench-hooks: chock refuses init/add/sync in an agent shell ({', '.join(marked)} set). Run this from your own shell."
        )
    work.mkdir(parents=True, exist_ok=True)
    venv = work / "venv"
    run([sys.executable, "-m", "venv", str(venv)], work)
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    py = str(bindir / ("python.exe" if os.name == "nt" else "python"))
    is_path = Path(engine).exists()
    run([py, "-m", "pip", "install", "-q", str(Path(engine).resolve()) if is_path else f"chock=={engine}"], work)
    repo = work / "adopter"
    repo.mkdir()
    run([GIT, "init", "-q"], repo)
    chock = [py, "-m", "chock"]
    run([*chock, "init", "."], repo)
    for policy in cfg["policies"]:
        pin = ["--ref", cfg["catalog_ref"], "--verify-sha", policy["verify_sha"], "--skip-compile"]
        run([*chock, "add", policy["id"], "--repo", ".", *pin], repo)
    run([*chock, "sync", "--repo", "."], repo)
    if is_path:
        done = subprocess.run([GIT, "-C", engine, "rev-parse", "HEAD"], capture_output=True, text=True, check=False)  # noqa: S603
        sha = done.stdout.strip()
        return repo, sha or f"path:{engine}"
    return repo, f"chock=={engine}"


def hooks_for(repo: Path, event: str, tool: str) -> list[dict]:
    """The hook entries of `event` in .claude/settings.json whose matcher selects `tool`."""
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    out = []
    for entry in settings.get("hooks", {}).get(event, []):
        matcher = entry.get("matcher")
        if matcher in (None, "", "*") or re.fullmatch(matcher, tool):
            out.extend(entry["hooks"])
    return out


class HookFailedError(RuntimeError):
    """A hook exited non-zero on a clean payload, so its timing says nothing."""

    def __init__(self, command: str, code: int, stderr: str) -> None:
        tail = stderr.strip()[-400:] or "(empty)"
        super().__init__(f"hook exited {code}; the run is invalid: {command}\nstderr tail: {tail}")


def fire(hook: dict, payload: bytes, repo: Path) -> int:
    """Run one hook command as the agent does (shell, repo root, payload on stdin); return 0 or raise."""
    done = subprocess.run([SHELL, "-c", hook["command"]], cwd=repo, input=payload, capture_output=True, check=False)  # noqa: S603
    if done.returncode:
        raise HookFailedError(hook["command"], done.returncode, done.stderr.decode("utf-8", "replace"))
    return done.returncode


def once(hooks: list[dict], payload: bytes, repo: Path, *, parallel: bool) -> tuple[float, list[int]]:
    """Wall time in ms of one tool call's hooks, one after another or all at once, with their exit codes."""
    start = time.perf_counter()
    if parallel:
        with ThreadPoolExecutor(max_workers=len(hooks)) as pool:
            codes = list(pool.map(lambda h: fire(h, payload, repo), hooks))
    else:
        codes = [fire(h, payload, repo) for h in hooks]
    return (time.perf_counter() - start) * 1000, codes


def stats(samples: list[float]) -> dict:
    """Median, p90, min, max and N of `samples`, in ms."""
    ordered = sorted(samples)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    return {
        "median_ms": round(statistics.median(ordered), 1),
        "p90_ms": round(p90, 1),
        "min_ms": round(ordered[0], 1),
        "max_ms": round(ordered[-1], 1),
        "n": len(ordered),
    }


def measure(repo: Path, cfg: dict, n: int) -> dict:
    """Time every configured tool call n times in both orders."""
    result = {}
    (repo / "notes").mkdir(exist_ok=True)
    for tool, spec in cfg["events"].items():
        hooks = hooks_for(repo, spec["event"], tool)
        payload = json.dumps(spec["payload"]).replace("__REPO__", repo.as_posix()).encode()
        entry = {"hooks": len(hooks)}
        for name, parallel in (("sequential", False), ("parallel", True)):
            once(hooks, payload, repo, parallel=parallel)
            runs = [once(hooks, payload, repo, parallel=parallel) for _ in range(n)]
            entry[name] = stats([ms for ms, _ in runs])
            entry[name]["exit_codes"] = sorted({c for _, codes in runs for c in codes})
        result[tool] = entry
    return result


def check(ok: bool, what: str) -> None:  # noqa: FBT001 - a two-line helper, not an API
    """Stop the self-test with `what` when `ok` is false."""
    if not ok:
        sys.exit(f"self-test failed: {what}")


def self_test(cfg: dict) -> None:
    """Check the timing code against a stub repo with sleeping hooks; this measures nothing about chock."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".claude").mkdir()
        sleeper = f'"{sys.executable}" -c "import time; time.sleep(0.05)"'
        hooks = [{"type": "command", "command": sleeper}] * 3
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell", "hooks": hooks}, {"hooks": hooks[:1]}]}}
        (repo / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        check(len(hooks_for(repo, "PreToolUse", "Bash")) == STUB_HOOKS, "matcher selects the Bash hooks")
        check(len(hooks_for(repo, "PreToolUse", "Write")) == 1, "matcher selects the unmatched hook only")
        got = measure(repo, {"events": {"Bash": cfg["events"]["Bash"]}}, 3)["Bash"]
        check(got["sequential"]["median_ms"] > got["parallel"]["median_ms"], f"sequential should be slower: {got}")
        sys.stdout.write(f"self-test ok {json.dumps(got['sequential'])} {json.dumps(got['parallel'])}\n")


def git_version() -> str:
    """The `git --version` line."""
    done = subprocess.run([GIT, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return done.stdout.strip()


def markdown(report: list[dict]) -> str:
    """A job-summary table of the medians, one row per engine, tool and order."""
    rows = [
        "| engine | tool | hooks | order | median ms | p90 ms | min ms | max ms | n |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report:
        for tool, entry in item["results"].items():
            for order in ("sequential", "parallel"):
                s = entry[order]
                rows.append(
                    f"| {item['engine']} | {tool} | {entry['hooks']} | {order} | {s['median_ms']} | {s['p90_ms']} "
                    f"| {s['min_ms']} | {s['max_ms']} | {s['n']} |"
                )
    return "\n".join(rows) + "\n"


def main() -> None:
    """Parse arguments, measure each engine in turn, print a JSON list (and optionally a markdown table)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--engine",
        action="append",
        help="chock version on PyPI or a checkout path; repeat for several (default: 1.0.0 and this checkout)",
    )
    ap.add_argument("--repo", type=Path, help="an already prepared adopter repo (skips setup; one engine label only)")
    ap.add_argument("--work", type=Path, help="scratch folder for setup (default: a new temp folder)")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--config", type=Path, default=HERE / "bench_hooks.json")
    ap.add_argument("--markdown", type=Path, help="also write a markdown table of the medians here")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    try:
        run_all(args, cfg)
    except HookFailedError as exc:
        sys.exit(f"bench-hooks: {exc}")


def run_all(args: argparse.Namespace, cfg: dict) -> None:
    """Self-test, or measure each engine and write the report."""
    if args.self_test:
        self_test(cfg)
        return
    engines = args.engine or DEFAULT_ENGINES
    base = args.work or Path(tempfile.mkdtemp(prefix="bench-hooks-"))
    report = []
    for idx, spec in enumerate(engines):
        if args.repo:
            repo, engine = args.repo.resolve(), f"prepared repo, engine {spec}"
        else:
            repo, engine = prepare(base / f"engine{idx}", spec, cfg)
        report.append(
            {
                "os": platform.platform(),
                "python": platform.python_version(),
                "engine": engine,
                "git": git_version(),
                "results": measure(repo, cfg, args.n),
            }
        )
    if args.markdown:
        args.markdown.write_text(markdown(report), encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
