"""Compiled output must not depend on hash randomisation.

`compile_policy` iterated its target surfaces as a set. Set iteration over enum members
follows hash order, which PYTHONHASHSEED randomises per process, so which surfaces were
emitted -- and in what order -- varied run to run. Measured across seeds 0-7 before the
fix, protect-main-branch emitted its ci-gate step in 5 runs and skipped it in 3.

Two consequences, both worse than the flakiness itself:

  The CI gate is the backstop for the mandatory guards. Whether that backstop existed was
  a coin flip at compile time, and its absence looks identical to "this policy has no CI
  step" -- nothing failed, so nothing surfaced it.

  Byte-identity of compiled gates is the evidence we use to show an enforcement change did
  not alter enforcement. That evidence is worthless if the compiler is not deterministic.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
SEEDS = ["0", "1", "4", "5", "7"]  # includes seeds observed to drop ci-gate before the fix


def _policy(tmp_path: Path) -> Path:
    policy_dir = tmp_path / ".agents" / "policies" / "demo"
    policy_dir.mkdir(parents=True)
    (policy_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "version": "0.0.1",
                "description": "demo hook",
                "artifact": "hook",
                "enforcement": "block",
                "hook": {
                    "gate": {
                        "kind": "forbidden_ref",
                        "on": ["commit", "push"],
                        "action": "block",
                        "message": "blocked",
                        "params": {"refs": ["main"]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return policy_dir


def _compile_under_seed(policy_dir: Path, out: Path, seed: str) -> str:
    """Compile in a subprocess so PYTHONHASHSEED actually takes effect, return a tree hash."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env["PYTHONPATH"] = str(FRAMEWORK_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "from pathlib import Path\n"
        "from chock.compile.compiler import compile_policy\n"
        "from chock.compile.surfaces import Surface\n"
        f"compile_policy(Path(r'{policy_dir}'), targets=[s.value for s in Surface], "
        f"output_root=Path(r'{out}'))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

    h = hashlib.sha256()
    for path in sorted(out.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(out).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def test_compiled_tree_is_identical_across_hash_seeds(tmp_path: Path) -> None:
    policy_dir = _policy(tmp_path)
    hashes = {seed: _compile_under_seed(policy_dir, tmp_path / f"out-{seed}", seed) for seed in SEEDS}
    assert len(set(hashes.values())) == 1, f"compiled output varies with PYTHONHASHSEED: {hashes}"


def test_the_enforcing_gate_is_emitted_under_every_seed(tmp_path: Path) -> None:
    """The artifact that must never vanish: the gate that actually blocks the commit.

    This used to watch `ci-gate/step.yaml`, the surface the seed-dependent bug happened to
    drop. That surface is no longer emitted (it could not enforce -- see EMITTERS in
    compiler.py), so the witness moved to `git-hook`, which is both still emitted and the
    one whose disappearance would silently end enforcement.
    """
    policy_dir = _policy(tmp_path)
    missing = []
    for seed in SEEDS:
        out = tmp_path / f"gate-{seed}"
        _compile_under_seed(policy_dir, out, seed)
        if not (out / "demo" / "git-hook" / "gate.json").exists():
            missing.append(seed)
    assert not missing, f"git-hook gate.json missing under PYTHONHASHSEED={missing}"


def test_no_emitter_depends_on_another_having_run(tmp_path: Path) -> None:
    """Emitting one surface alone must produce that surface's complete output.

    The original defect was a `ci-gate` emitter that read the filesystem for git-hook's
    shims, so it produced nothing when compiled first. `ci-gate` is gone, but the coupling
    it demonstrated is a property of every emitter, so the check outlives it: compile each
    surface in isolation and require that any surface which emits in a full compile also
    emits on its own.
    """
    from chock.compile.compiler import EMITTERS, compile_policy

    policy_dir = _policy(tmp_path)
    full = compile_policy(policy_dir, targets=[s.value for s in EMITTERS], output_root=tmp_path / "full")

    for surface in EMITTERS:
        if not full.artifacts.get(surface.value):
            continue
        alone = compile_policy(policy_dir, targets=[surface.value], output_root=tmp_path / f"only-{surface.value}")
        assert alone.artifacts.get(surface.value), f"{surface.value} emits nothing unless another emitter ran first"


def test_the_ci_step_is_one_that_can_fail(tmp_path: Path) -> None:
    """The emitter the coupling check above was written against, now that it emits again.

    The step this replaced could not fail under any input: its push branch was
    `echo '<fixed refs>' | bash git-pre-push.sh || true`, and its commit branch gated
    `git diff --cached` in a CI checkout, where there is no index. Asserting the absence of
    `|| true` is not style -- it is the whole difference between a backstop and a decoration.
    """
    from chock.compile.compiler import compile_policy
    from chock.compile.surfaces import Surface

    policy_dir = _policy(tmp_path)
    out = tmp_path / "ci-only"
    compile_policy(policy_dir, targets=[Surface.CI_GATE.value], output_root=out)

    step = out / "demo" / "ci-gate" / "step.yaml"
    assert step.exists(), "ci-gate must emit from the manifest even when git-hook has not run"
    assert (out / "demo" / "ci-gate" / "gate.json").exists(), "ci-gate resolves its own gate, not git-hook's"

    body = step.read_text(encoding="utf-8")
    assert "--event ci" in body and "gate.py" in body
    assert "|| true" not in body, "a step that cannot fail enforces nothing"


def test_surfaces_are_processed_in_declaration_order(tmp_path: Path) -> None:
    """Pin the compiler fix itself, not just the symptom it caused.

    Once ci-gate stopped reading the filesystem, the output became correct regardless of
    iteration order -- so the tests above pass even with the set restored. This asserts the
    ordering directly: `artifacts` is keyed in insertion order, so it reveals the order the
    emitters actually ran in. A set would follow hash order and vary by PYTHONHASHSEED.
    """
    from chock.compile.compiler import compile_policy
    from chock.compile.surfaces import Surface

    policy_dir = _policy(tmp_path)
    result = compile_policy(
        policy_dir,
        targets=[s.value for s in Surface],
        output_root=tmp_path / "ordered",
    )

    emitted_order = list(result.artifacts)
    expected = [s.value for s in Surface if s.value in set(emitted_order)]
    assert emitted_order == expected, (
        f"surfaces must be processed in Surface declaration order; got {emitted_order}, expected {expected}"
    )
