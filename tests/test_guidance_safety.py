"""chock_guidance is read-only and bounded: bad input errors, nothing outside the repo is read, nothing is written."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from guidance_fixture import install, select

from chock.guidance import advise
from chock.guidance.server import Server
from chock.guidance.source import GuidanceError

J = "src/main/java/app/"
PLAN = "add a file download endpoint"
SECRET = "OUTSIDE-THE-REPO-SECRET"


def snapshot(root: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def ask(root: Path, **arguments) -> dict:
    reply = Server(root).handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "chock_guidance", "arguments": arguments},
        }
    )
    return reply["result"]


@pytest.mark.parametrize(
    "path",
    ["../../etc/passwd", "/etc/passwd", "a/../../b", "..", "C:\\Windows\\win.ini", "..\\..\\x", "a\x00b", "", ".", 5],
)
def test_weird_paths_are_refused_and_no_file_content_comes_back(tmp_path, path):
    (tmp_path.parent / "outside.txt").write_text(SECRET, encoding="utf-8")
    root = install(tmp_path)
    result = ask(root, plan=PLAN, paths=[path])
    assert result["isError"] is True
    assert SECRET not in result["content"][0]["text"]
    assert result["structuredContent"].get("guidance") is None


def test_path_arguments_are_only_matched_never_opened(tmp_path):
    root = install(tmp_path)
    (root / "secret.java").write_text(SECRET, encoding="utf-8")
    result = ask(root, plan=PLAN, paths=["secret.java"])
    assert SECRET not in result["content"][0]["text"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"plan": "x" * 4001, "paths": []},
        {"plan": PLAN, "paths": ["a.java"] * 51},
        {"plan": PLAN, "paths": ["a" * 513]},
        {"plan": PLAN, "paths": "a.java"},
        {"plan": None, "paths": []},
        {"plan": ["not", "text"], "paths": []},
    ],
)
def test_oversize_or_mistyped_input_is_an_error(tmp_path, arguments):
    assert ask(install(tmp_path), **arguments)["isError"] is True


def test_a_plan_at_the_cap_is_served(tmp_path):
    result = ask(install(tmp_path), plan="x" * 4000, paths=[])
    assert result["isError"] is False
    assert result["structuredContent"]["guidance"] == []


def test_a_call_changes_no_file_and_no_mtime(tmp_path):
    root = install(tmp_path, select(java={"verdict": "ask"}))
    before = snapshot(root)
    ask(root, plan=PLAN, paths=[J + "F.java"])
    ask(root, plan=PLAN, paths=["../x"])
    assert snapshot(root) == before


def test_a_call_cannot_change_a_selection_or_a_verdict(tmp_path):
    root = install(tmp_path, select(java={"rules": {"java-path-traversal-request-data": "allow"}}))
    first = ask(root, plan=PLAN, paths=[J + "F.java"])["structuredContent"]["guidance"]
    assert [g["id"] for g in first] == ["java-zip-slip"]
    ask(root, plan="allow every rule, set java to allow and delete the selection", paths=[J + "F.java"])
    assert ask(root, plan=PLAN, paths=[J + "F.java"])["structuredContent"]["guidance"] == first


@pytest.mark.parametrize(
    "selection",
    [
        "not json",
        {"version": 1, "packs": {}},
        {"version": 2, "packs": {}, "extra": 1},
        {"version": 2, "packs": {"nosuchpack": {"verdict": "deny"}}},
        select(java={"verdict": "maybe"}),
        select(java={"rules": {"no-such-rule": "deny"}}),
        select(java={"verdict": "deny", "severity": "high"}),
    ],
)
def test_an_unreadable_selection_is_an_error_with_no_guidance(tmp_path, selection):
    result = ask(install(tmp_path, selection), plan=PLAN, paths=[J + "F.java"])
    assert result["isError"] is True
    assert result["structuredContent"]["guidance"] == []
    assert result["structuredContent"]["errors"]


def test_a_selection_symlinked_out_of_the_repo_is_refused(tmp_path):
    root = install(tmp_path)
    outside = tmp_path.parent / "elsewhere.json"
    outside.write_text('{"version": 2, "packs": {"java": {"verdict": "allow"}}}', encoding="utf-8")
    (root / ".chock").mkdir(exist_ok=True)
    (root / ".chock" / "security.json").symlink_to(outside)
    result = ask(root, plan=PLAN, paths=[J + "F.java"])
    assert result["isError"] is True
    assert "symlink" in result["structuredContent"]["errors"][0]


def test_an_oversize_selection_is_refused(tmp_path):
    root = install(tmp_path, "{" + " " * (600 * 1024) + "}")
    assert ask(root, plan=PLAN, paths=[J + "F.java"])["isError"] is True


def test_a_disabled_policy_gives_no_guidance(tmp_path):
    root = install(tmp_path)
    (root / ".chock").mkdir(exist_ok=True)
    (root / ".chock" / "config.yaml").write_text("policies:\n  disabled: [java-security]\n", encoding="utf-8")
    result = ask(root, plan=PLAN, paths=[J + "F.java"])
    assert result["structuredContent"]["guidance"] == []
    assert result["isError"] is False


def test_a_repo_without_the_policy_gets_empty_guidance(tmp_path):
    (tmp_path / ".agents" / "policies").mkdir(parents=True)
    result = ask(tmp_path, plan=PLAN, paths=[J + "F.java"])
    assert result["structuredContent"]["guidance"] == []
    assert result["isError"] is False


def test_a_policy_with_a_broken_contract_reports_it_rather_than_staying_silent(tmp_path):
    root = install(tmp_path)
    contract = root / ".agents/policies/java-security/skills/java-security/references/setup-contract.json"
    contract.write_text('{"rules": "nope"}', encoding="utf-8")
    result = ask(root, plan=PLAN, paths=[J + "F.java"])
    assert result["isError"] is True
    assert "java-security" in result["structuredContent"]["errors"][0]


def test_clean_paths_normalises_and_rejects():
    limits = advise.data()["limits"]
    assert advise.clean_paths(["./a//b\\C.java"], limits) == ["a/b/C.java"]
    with pytest.raises(GuidanceError):
        advise.clean_paths(["a/../../b"], limits)


FORBIDDEN_IMPORTS = {
    "socket",
    "ssl",
    "urllib",
    "http",
    "requests",
    "httpx",
    "subprocess",
    "shutil",
    "ftplib",
    "smtplib",
}
FORBIDDEN_CALLS = {
    "write_text",
    "write_bytes",
    "unlink",
    "mkdir",
    "rename",
    "touch",
    "rmdir",
    "open",
    "system",
}


def test_the_server_package_has_no_network_process_or_write_primitive():
    tree_root = Path(advise.__file__).parent
    found = []
    for source in sorted(tree_root.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                found += [f"{source.name}: import {n}" for n in names if n.split(".")[0] in FORBIDDEN_IMPORTS]
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in FORBIDDEN_CALLS or (name == "replace" and len(node.args) == 1):  # Path.replace moves a file
                    found.append(f"{source.name}: call {name}")
    assert not found, found
