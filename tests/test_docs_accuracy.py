"""Documentation must describe the software that exists.

Every fact here is checked against the code rather than proof-read. The drift these catch
was all real and all silent: `--help` carried a hand-maintained command list that omitted
`refresh` from the day it was added, and `concepts.md` documented six artifact types when
the schema accepts four.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
DOCS = [*(FRAMEWORK_ROOT / "docs").rglob("*.md"), *(FRAMEWORK_ROOT / "spec").rglob("*.md")]


def _docs_blob() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS)


def test_help_lists_every_advertised_command_and_hides_aliases() -> None:
    """--help shows the Everyday and Authoring sections, generated from the tables.

    The pre-launch ALIASES are dispatchable but deliberately unadvertised: an adopter's
    first `chock --help` should teach the 8-verb surface, not the 21-command history.
    This asserts the hiding too, so an alias cannot quietly climb back into the help.
    """
    from chock.cli import ALIASES, AUTHORING, EVERYDAY

    out = subprocess.run([sys.executable, "-m", "chock", "--help"], capture_output=True, text=True).stdout
    assert "Everyday:" in out and "Authoring:" in out, f"missing help sections:\n{out}"

    missing = [
        name
        for name in list(EVERYDAY) + list(AUTHORING)
        if not re.search(rf"^\s+{re.escape(name)}\s+\S", out, re.MULTILINE)
    ]
    assert not missing, f"advertised commands with no help detail line: {missing}"

    advertised = set(EVERYDAY) | set(AUTHORING)
    leaked = [
        name
        for name in ALIASES
        if name not in advertised and re.search(rf"^\s+{re.escape(name)}\s+\S", out, re.MULTILINE)
    ]
    assert not leaked, f"aliases leaked into --help: {leaked}"


def test_every_command_answers_help_without_doing_work(tmp_path) -> None:
    """`<command> --help` must explain itself, from anywhere, without side effects.

    `check-matrix` took no arguments, so it parsed none, and `chock check --only matrix --help`
    ran the check and exited 1 with `enforcement matrix not found`. Outside the framework repo
    that reads like a broken install rather than a misunderstanding about flags.

    Run from a directory that is not a Chock repo, because that is where someone
    reaching for `--help` usually is.
    """
    from chock.cli import COMMANDS

    failures = []
    for name in COMMANDS:
        proc = subprocess.run(
            [sys.executable, "-m", "chock", name, "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        if proc.returncode != 0:
            first = ((proc.stderr or proc.stdout).strip().splitlines() or [""])[0]
            failures.append(f"{name}: exit {proc.returncode} -- {first}")

    assert not failures, "commands whose --help fails:\n  " + "\n  ".join(failures)


def test_every_command_that_takes_a_repo_root_accepts_repo(tmp_path) -> None:
    """One spelling for "which repo", across the whole CLI.

    `chock check --only verify --repo .` failed with `unrecognized arguments: --repo .` while
    eighteen other call sites took exactly that flag. `verify`, `registry` and `new` had
    settled on `--root` instead, and nothing compared them -- so the quickstart's shape
    worked everywhere except the command that checks the install.

    `--root` still works on all three; this asserts the alias, not a rename, because the
    flag appears in `review/evidence.py`'s builtin check commands and in people's scripts.

    Read out of `--help` rather than by importing each parser: the parsers are built inside
    `main()` behind subcommand dispatch, and what a user can type is the actual claim.
    """
    from chock.cli import COMMANDS

    missing = []
    for name in COMMANDS:
        out = subprocess.run(
            [sys.executable, "-m", "chock", name, "--help"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        ).stdout
        if "--root" in out and "--repo" not in out:
            missing.append(name)

    assert not missing, f"commands offering --root but not --repo: {missing}"


def test_documented_artifact_types_match_the_schema() -> None:
    """concepts.md listed `subagent` and `command` as manifest artifact values.

    `command` was removed from the schema entirely; `subagent` is valid only in
    subagent.yaml, which has its own schema. Both were wrong in the manifest table.
    """
    schema = json.loads(
        (FRAMEWORK_ROOT / "src" / "chock" / "validation" / "schemas" / "manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    valid = set(schema["properties"]["artifact"]["enum"])

    concepts = (FRAMEWORK_ROOT / "docs" / "concepts.md").read_text(encoding="utf-8")
    table = concepts[concepts.index("| Type | What it is") : concepts.index("Those four are the complete set")]
    documented = set(re.findall(r"^\| `(\w+)` \|", table, re.MULTILINE))
    assert documented == valid, f"concepts.md artifact table {sorted(documented)} != schema {sorted(valid)}"


def test_documented_gate_kinds_match_the_code() -> None:
    from chock.gate.schema import KIND_PARAM_SCHEMAS

    spec = (FRAMEWORK_ROOT / "spec" / "gate-dsl.md").read_text(encoding="utf-8")
    for kind in KIND_PARAM_SCHEMAS:
        assert f"`{kind}`" in spec, f"gate kind {kind} is not documented in spec/gate-dsl.md"

    # And nothing documented that does not exist.
    documented = set(re.findall(r"### `kind: (\w+)`", spec))
    unknown = documented - set(KIND_PARAM_SCHEMAS)
    assert not unknown, f"spec/gate-dsl.md documents nonexistent gate kinds: {sorted(unknown)}"


def test_documented_manifest_formats_match_the_extractors() -> None:
    from chock.gate.schema import SUPPORTED_MANIFESTS

    spec = (FRAMEWORK_ROOT / "spec" / "gate-dsl.md").read_text(encoding="utf-8")
    for fmt in SUPPORTED_MANIFESTS:
        assert f"`{fmt}`" in spec, f"supported manifest format {fmt} is undocumented"


def test_every_installed_policy_is_documented() -> None:
    """A shipped policy nobody documented is one an adopter cannot evaluate."""
    policies = sorted(p.name for p in (FRAMEWORK_ROOT / ".agents" / "policies").iterdir() if p.is_dir())
    blob = _docs_blob()
    missing = [p for p in policies if p not in blob]
    assert not missing, f"policies present but undocumented: {missing}"


def test_docs_name_no_command_that_does_not_exist() -> None:
    """Prose describing a deleted command is drift nothing else catches.

    The existing checks compare docs to code fact-by-fact, so they cannot notice a paragraph
    about a subsystem that was removed. `sync-packs` was documented in four files after it
    was deleted, and every test stayed green.
    """
    from chock.cli import COMMANDS

    # Commands the docs are allowed to mention: the real ones, plus subcommands and the
    # deliberately-unimplemented `eval --mode agent`.
    known = set(COMMANDS) | {"scan", "list", "resolve", "get", "report", "init", "upgrade", "add", "remove"}
    referenced = set(re.findall(r"`chock ([a-z][a-z-]+)", _docs_blob()))
    unknown = sorted(referenced - known)
    assert not unknown, f"docs reference commands that do not exist: {unknown}"


def test_docs_name_no_repo_path_that_does_not_exist() -> None:
    """The same class, for paths.

    After the framework stopped bundling policies, nine files still described
    `.agents/policies/_baseline/` and `src/chock/packs/_baseline/`. Both were gone.
    """
    tracked = {
        ".agents/policies/",
        ".chock/",
        "src/chock/",
        "docs/",
        "spec/",
        "tests/",
        "acceptance/",
    }
    referenced = set(re.findall(r"`((?:\.agents|\.chock|src)/[A-Za-z0-9_./-]*)`", _docs_blob()))

    missing = []
    for ref in sorted(referenced):
        # Only judge concrete paths: placeholders like <id> are not filesystem claims.
        if any(ch in ref for ch in "<>*") or ref.endswith("/"):
            continue
        if not any(ref.startswith(prefix) for prefix in tracked):
            continue
        if not (FRAMEWORK_ROOT / ref).exists():
            missing.append(ref)
    assert not missing, f"docs reference paths that do not exist: {missing}"


def test_no_positional_repo_reaches_the_flag_only_verbs() -> None:
    """`sync`, `check` and `status` take `--repo`, never a positional (uv-sync semantics).

    `init .` teaches the positional shape, and it leaked: the `add` success hint and three
    quickstarts all said `chock sync .`, so the documented install's final paste failed with
    `unrecognized arguments: .`. Scan every surface an adopter copies from -- docs, README,
    promo sources, and hints printed by the CLI itself.
    """
    sources = [
        *DOCS,
        FRAMEWORK_ROOT / "README.md",
        *(FRAMEWORK_ROOT / "docs").rglob("*.js"),
        *(FRAMEWORK_ROOT / "src" / "chock").rglob("*.py"),
    ]
    offenders = [
        f"{path.relative_to(FRAMEWORK_ROOT)}: chock {match}"
        for path in sources
        for match in re.findall(r"chock ((?:sync|check|status)\s+\.(?!\w)\S*)", path.read_text(encoding="utf-8"))
    ]
    assert not offenders, "positional repo passed to a --repo-only command:\n  " + "\n  ".join(offenders)


def test_enable_and_disable_agree_on_unknown_policies(tmp_path: Path) -> None:
    """`enable` used to print success for a typo while `disable` rejected it."""
    import subprocess as sp

    env_root = tmp_path / "repo"
    env_root.mkdir()
    sp.run(["git", "init", "--quiet", "."], cwd=env_root, check=True)
    base = [sys.executable, "-m", "chock.cli"]
    env = {**__import__("os").environ, "PYTHONPATH": str(FRAMEWORK_ROOT / "src")}
    sp.run([*base, "init", ".", "--skip-hooks"], cwd=env_root, capture_output=True, env=env)

    enable = sp.run([*base, "enable", "no-such-policy"], cwd=env_root, capture_output=True, env=env)
    disable = sp.run([*base, "disable", "no-such-policy"], cwd=env_root, capture_output=True, env=env)
    assert enable.returncode != 0, "enable accepted an unknown policy id"
    assert disable.returncode != 0, "disable accepted an unknown policy id"


def test_readme_agents_md_sample_is_the_block_the_code_writes() -> None:
    """The README shows the compiled `AGENTS.md` block and calls it verbatim. It has to be.

    A sample that drifts from `POINTER_BLOCK` is worse than no sample: it teaches an adopter
    to expect wiring `chock sync` does not produce, and it is the one snippet on the page a
    reader can check against their own repo in five seconds.
    """
    from chock.scaffold.agents_md import POINTER_BLOCK

    lines = [ln for ln in POINTER_BLOCK.splitlines() if ln.startswith(("before(", "fresh_clone:", "scope:"))]
    assert len(lines) == 3, "POINTER_BLOCK's shape changed; the README sample needs rewriting, not re-anchoring"

    readme = (FRAMEWORK_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [ln for ln in lines if ln not in readme]
    assert not missing, "README's AGENTS.md sample no longer matches POINTER_BLOCK:\n  " + "\n  ".join(missing)
    # Contiguous and in order, not merely all present somewhere. The README calls the sample
    # verbatim; three correct lines shuffled or split apart are no longer the block chock writes,
    # and checking only membership passes on a rearrangement -- which is what a reader would copy.
    assert "\n".join(lines) in readme, "the README's sample has the right lines in the wrong shape"


def test_readme_policy_example_points_at_a_policy_that_exists() -> None:
    """The `.agents/policies/scan-secrets/` walkthrough is this repo's own installed policy.

    The README names its files and quotes its manifest keys; if the policy is renamed or its
    gate reshaped, the walkthrough becomes fiction about the repo the reader is looking at.
    """
    import yaml

    policy = FRAMEWORK_ROOT / ".agents" / "policies" / "scan-secrets"
    readme = (FRAMEWORK_ROOT / "README.md").read_text(encoding="utf-8")
    assert ".agents/policies/scan-secrets/" in readme, "walkthrough moved; re-point this test"
    assert (policy / "manifest.yaml").is_file(), "README shows manifest.yaml for a policy that has none"
    assert (policy / "evals").is_dir(), "README shows an evals/ directory that does not exist"

    gate = yaml.safe_load((policy / "manifest.yaml").read_text(encoding="utf-8"))["hook"]["gate"]
    quoted = f"kind: {gate['kind']} · on: {gate['on']} · action: {gate['action']}".replace("'", "")
    assert quoted in readme, f"README describes a gate the manifest no longer declares; it now reads {quoted!r}"
