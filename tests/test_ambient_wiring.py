"""Compiled advisory text has exactly one destination, and it is not AGENTS.md.

`compile/emitters/ambient.py` derives correct, config-aware advisory text per policy.
INDEX.md publishes it: generated, config-resolved, and required reading via the pointer
AGENTS.md carries at line ~60. Inlining the same text into AGENTS.md as per-policy
`chock:hooks` blocks made the always-loaded surface half a second copy of its other
half -- +112% on the one file every agent loads on every task -- which is what
`minimal_content: {target: [redundancy, ...]}` forbids and what PR #62 had already
compressed away once.

So AGENTS.md carries the pointer and nothing per-policy, and refresh strips both legacy
inlined forms. The objection that an agent might skip the pointer is answered by the repo's
own design: anything that must always hold is a hook, so skipping INDEX.md loses guidance,
never enforcement.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import baseline_policy

from chock.index.cli import cmd_refresh
from chock.scaffold.agents_md import update_agents_md
from chock.scaffold.recompile import recompile

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_TEMPLATE = FRAMEWORK_ROOT / "src" / "chock" / "packs" / "_skills" / "chock-init" / "assets" / "templates"

ADOPTER_AGENTS_MD = """# repo

Hand-written preamble the adopter owns.

## Rules

## Hooks

```
install: chock sync
```

## Hard rules

```
budgets: {SKILL.md: <=150, ambient_rule: <=2}
```

Trailing adopter prose.
"""

INLINED = """<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/alpha/) -->
```
on(commit|push): block direct writes to main/master
```
<!-- chock:hooks:end -->
"""

CUSTOMISED = """
chock:
  defaults:
    protected_branches: [main, release, production]
"""


def _adopter_repo(tmp_path: Path, hooks: str = "") -> Path:
    body = ADOPTER_AGENTS_MD.replace("## Hard rules", f"{hooks}\n## Hard rules") if hooks else ADOPTER_AGENTS_MD
    (tmp_path / "AGENTS.md").write_text(body, encoding="utf-8")
    return tmp_path


def _compiled(repo: Path, policy_id: str, body: str) -> Path:
    """The compiler's ambient output for one policy, which AGENTS.md must NOT absorb."""
    dest = repo / ".chock" / "compiled" / policy_id / "ambient-rule"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "ambient.md"
    path.write_text(
        f"<!-- chock:hooks:start (compiled by chock -- edit .agents/policies/{policy_id}/) -->\n"
        f"```\n{body}\n```\n"
        f"<!-- chock:hooks:end -->\n",
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------ AGENTS.md must not accumulate copies
def test_compiled_ambient_text_is_not_inlined(tmp_path: Path) -> None:
    """The regression worth preventing: AGENTS.md growing one block per installed policy."""
    repo = _adopter_repo(tmp_path)
    _compiled(repo, "alpha", "never(x): y")
    _compiled(repo, "beta", "never(p): q")

    update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "chock:hooks:start" not in text
    assert "never(x): y" not in text
    assert "never(p): q" not in text


def test_an_inlined_block_is_stripped(tmp_path: Path) -> None:
    """The hand-copied form that shipped for two policies, with pre-resolution text."""
    repo = _adopter_repo(tmp_path, hooks=INLINED)
    update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "chock:hooks" not in text
    assert "block direct writes to main/master" not in text


def test_the_pointer_to_index_survives(tmp_path: Path) -> None:
    """Stripping the copies is only safe because the pointer to the original stays."""
    repo = _adopter_repo(tmp_path, hooks=INLINED)
    update_agents_md(repo / "AGENTS.md")
    assert "read(.agents/policies/INDEX.md)" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_this_repo_carries_no_inlined_blocks() -> None:
    """AGENTS.md is loaded on every task; every line in it is paid for on every task."""
    text = (FRAMEWORK_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "chock:hooks" not in text
    assert "chock:rules" not in text


def test_the_shipped_template_carries_no_hand_copied_blocks() -> None:
    """A template block names a policy the framework may no longer ship."""
    text = (SHIPPED_TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
    assert "chock:hooks:start" not in text


def test_refresh_is_idempotent(tmp_path: Path) -> None:
    repo = _adopter_repo(tmp_path, hooks=INLINED)
    update_agents_md(repo / "AGENTS.md")
    first = (repo / "AGENTS.md").read_bytes()
    assert update_agents_md(repo / "AGENTS.md") is False
    assert (repo / "AGENTS.md").read_bytes() == first


# -------------------------------------------------------------------- what must not be lost
def test_hand_written_content_outside_the_markers_survives(tmp_path: Path) -> None:
    """This repo just fixed a data-loss bug of exactly this shape."""
    repo = _adopter_repo(tmp_path, hooks=INLINED)

    for _ in range(2):
        update_agents_md(repo / "AGENTS.md")
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    for owned in (
        "Hand-written preamble the adopter owns.",
        "## Hooks",
        "install: chock sync",
        "Trailing adopter prose.",
    ):
        assert owned in text, owned


# -------------------------------------------------------------- the assertion that matters
def test_customised_protected_branches_reach_the_agent(tmp_path: Path) -> None:
    """config -> recompile -> refresh -> the branches named in what the agent is told to read.

    Before PR #67 this said "main/master" whatever the adopter configured, so an agent
    concluded `production` was writable and was then blocked by a gate naming branches its
    guidance had never mentioned. The text must be resolved and reachable in one hop from
    AGENTS.md -- but it lives in INDEX.md rather than being copied into AGENTS.md.
    """
    repo = _adopter_repo(tmp_path)
    dest = repo / ".agents" / "policies" / "protect-main-branch"
    dest.parent.mkdir(parents=True)
    shutil.copytree(baseline_policy("protect-main-branch"), dest)
    (repo / ".chock").mkdir(exist_ok=True)
    (repo / ".chock" / "config.yaml").write_text(CUSTOMISED, encoding="utf-8")

    recompile(repo, ["claude"])
    assert cmd_refresh(["--repo", str(repo)]) == 0

    index = (repo / ".agents" / "policies" / "INDEX.md").read_text(encoding="utf-8")
    for branch in ("main", "release", "production"):
        assert branch in index, index
    assert "master" not in index, index

    agents_md = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "read(.agents/policies/INDEX.md)" in agents_md
    assert "production" not in agents_md, "advisory text belongs in INDEX.md, not AGENTS.md"
    assert "Hand-written preamble the adopter owns." in agents_md


# ---------------------------------------------------------------------- staleness reporting
def test_check_reports_an_inlined_block(tmp_path: Path) -> None:
    """No check covered AGENTS.md's managed form before, so drift survived until refresh ran."""
    repo = _adopter_repo(tmp_path)
    assert cmd_refresh(["--repo", str(repo)]) == 0
    assert cmd_refresh(["--repo", str(repo), "--check"]) == 0

    (repo / "AGENTS.md").write_text((repo / "AGENTS.md").read_text(encoding="utf-8") + "\n" + INLINED, encoding="utf-8")
    assert cmd_refresh(["--repo", str(repo), "--check"]) == 1


def test_check_writes_nothing(tmp_path: Path) -> None:
    """A check that repairs what it measures cannot report a failing build twice."""
    repo = _adopter_repo(tmp_path)
    cmd_refresh(["--repo", str(repo)])

    tampered = (repo / "AGENTS.md").read_text(encoding="utf-8") + "\n" + INLINED
    (repo / "AGENTS.md").write_text(tampered, encoding="utf-8")
    assert cmd_refresh(["--repo", str(repo), "--check"]) == 1
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == tampered
