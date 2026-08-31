"""Generated artifacts must be written with LF on every platform."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from chock.compile.compiler import compile_policy
from chock.compile.surfaces import Surface
from chock.emit import write_generated, write_generated_json

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]

GENERATED_WRITERS = [
    "src/chock/compile/emitters/ambient.py",
    "src/chock/compile/emitters/claude_managed.py",
    "src/chock/compile/emitters/claude_pretooluse.py",
    "src/chock/compile/emitters/git_hook.py",
    "src/chock/index/cli.py",
    "src/chock/registry/core.py",
    "src/chock/scaffold/agents_md.py",
    "src/chock/scaffold/recompile.py",
]


def test_write_generated_emits_lf(tmp_path: Path) -> None:
    """Effective on Windows; a no-op assertion on platforms that never translate."""
    dest = tmp_path / "a.txt"
    write_generated(dest, "one\ntwo\n")
    assert dest.read_bytes() == b"one\ntwo\n"


def test_write_generated_json_emits_lf(tmp_path: Path) -> None:
    dest = tmp_path / "a.json"
    write_generated_json(dest, {"b": [1, 2]})
    assert b"\r\n" not in dest.read_bytes()


def test_generated_writers_do_not_call_write_text() -> None:
    """Structural guard, and the one that works on every platform."""
    offenders: list[str] = []
    for rel in GENERATED_WRITERS:
        text = (FRAMEWORK_ROOT / rel).read_text(encoding="utf-8")
        for match in re.finditer(r"\.write_text\(", text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{line}")
    assert not offenders, (
        f"generated-artifact writers must use chock.emit.write_generated(); bare write_text() found at: {offenders}"
    )


def test_compiled_output_contains_no_crlf(tmp_path: Path) -> None:
    """End-to-end: compiling a policy emits no CRLF into any artifact."""
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

    out = tmp_path / ".chock" / "compiled"
    compile_policy(policy_dir, targets=[s.value for s in Surface], output_root=out)

    emitted = [p for p in out.rglob("*") if p.is_file()]
    assert emitted, "compile produced no artifacts"
    offenders = [str(p.relative_to(out)) for p in emitted if b"\r\n" in p.read_bytes()]
    assert not offenders, f"compiled artifacts contain CRLF: {offenders}"
