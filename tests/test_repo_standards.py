"""Repo-wide coding standards, mechanically enforced."""

from pathlib import Path

MAX_LINES = 300

EXEMPT = {
    ".chock/registry.json",
    ".chock/coverage.json",
    "LICENSE",
    "CHANGELOG.md",
    "requirements/semgrep.txt",
    "requirements/brand-assets.txt",
    "src/chock/gate/runner.py",
}

# .chock/bin/ is bundler output (generated, review lives at its sources); runtime_goldens
# freeze that same generated output per vendor.
EXEMPT_PREFIXES = (".chock/log/", "src/chock/authoring/data/", ".chock/bin/", "tests/fixtures/runtime_goldens/")

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".claude",
    "node_modules",
    ".venv",
    "build",
    "dist",
}
SKIP_SUFFIXES = {".png", ".pyc"}
SKIP_DIR_SUFFIXES = (".egg-info",)


def test_no_file_exceeds_line_budget():
    repo_root = Path(__file__).resolve().parents[1]
    violations = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if set(path.parts) & SKIP_DIRS or path.suffix in SKIP_SUFFIXES or rel in EXEMPT:
            continue
        if rel.startswith(EXEMPT_PREFIXES):
            continue
        if any(part.endswith(SKIP_DIR_SUFFIXES) for part in path.parts):
            continue
        try:
            count = len(path.read_text(encoding="utf-8").splitlines())
        except (UnicodeDecodeError, OSError):
            continue
        if count > MAX_LINES:
            violations.append(f"{rel}: {count} lines")
    assert not violations, "Files exceed the 300-line review budget (split by activity):\n" + "\n".join(violations)
