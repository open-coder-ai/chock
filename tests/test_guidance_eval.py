"""chock_guidance replay: fixed plans against java-security's 129 real rules; the exact rules and verdicts returned."""

from __future__ import annotations

import json

import pytest
from guidance_fixture import install, select

from chock.guidance.advise import guidance

J = "src/main/java/app/"
DENY, ASK = "deny", "ask"
TRAVERSAL, ZIPSLIP = "java-path-traversal-request-data", "java-zip-slip"
SQLI, SQLCAT = "java-sqli-mybatis-interpolation", "persistence-sql-string-concat"

#: (plan, paths, selection, [(rule id, verdict), ...] in the order returned)
CASES = {
    "download": (
        "add a file download endpoint",
        [J + "FilesController.java"],
        None,
        [(TRAVERSAL, DENY), (ZIPSLIP, DENY)],
    ),
    "unzip": ("unzip an uploaded archive into the data folder", [J + "Importer.java"], None, [(ZIPSLIP, DENY)]),
    "url": (
        "call a URL that the caller supplies and return the body",
        [J + "Proxy.java"],
        None,
        [("java-ssrf-request-url", DENY)],
    ),
    "xml": ("parse the uploaded XML document", [J + "XmlImport.java"], None, [("java-xxe-parser", DENY)]),
    "sql": ("build a SQL query from the search text", [J + "Repo.java"], None, [(SQLI, DENY), (SQLCAT, DENY)]),
    "cipher": ("encrypt the customer token with a cipher", [J + "Vault.java"], None, [("crypto-weak-cipher", DENY)]),
    "shell": ("run a shell command from the admin page", [J + "Admin.java"], None, [("java-command-injection", DENY)]),
    "csrf": (
        "disable csrf for the api",
        ["src/main/resources/application.yml"],
        None,
        [("spring-csrf-disabled", DENY)],
    ),
    "maven": (
        "pin the maven repository over http",
        ["pom.xml"],
        None,
        [("build-insecure-repository", DENY), ("build-dynamic-version", DENY)],
    ),
    "no-paths": ("add a file download endpoint", [], None, [(TRAVERSAL, DENY), (ZIPSLIP, DENY)]),
    "neg-unrelated": ("rename a variable for readability", [J + "A.java"], None, []),
    "neg-empty-plan": ("", [J + "A.java"], None, []),
    "neg-wrong-path": ("add a file download endpoint", ["README.md"], None, []),
    "neg-pack-path": ("disable csrf for the api", ["src/main/webapp/index.html"], None, []),
    "pack-allow": (
        "add a file download endpoint",
        [J + "F.java"],
        select(java={"rules": {TRAVERSAL: "deny", ZIPSLIP: "allow"}}),
        [(TRAVERSAL, DENY)],
    ),
    "all-allow": ("add a file download endpoint", [J + "F.java"], select(java={"verdict": "allow"}), []),
    "ask-after-deny": (
        "add a file download endpoint",
        [J + "F.java"],
        select(java={"rules": {TRAVERSAL: "ask"}}),
        [(ZIPSLIP, DENY), (TRAVERSAL, ASK)],
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_replay_returns_exactly_the_expected_rules(name, tmp_path):
    plan, paths, selection, expected = CASES[name]
    root = install(tmp_path, selection)
    result = guidance(root, plan, paths)
    assert [(g["id"], g["verdict"]) for g in result["guidance"]] == expected
    assert result["errors"] == []


def test_done_when_case_returns_the_path_traversal_rule_with_its_fix(tmp_path):
    root = install(tmp_path, select(java={"rules": {TRAVERSAL: "deny"}}))
    first = guidance(root, "add a file download endpoint", [J + "FilesController.java"])["guidance"][0]
    assert first["id"] == TRAVERSAL
    assert first["constraint"].endswith("take getFileName, resolve against a fixed base, check startsWith")
    assert first["cwe"] == ["CWE-22"]  # the fixture keeps each rule's first CWE only


def test_replay_is_deterministic(tmp_path):
    root = install(tmp_path)
    runs = {repr(guidance(root, CASES["sql"][0], CASES["sql"][1])) for _ in range(3)}
    assert len(runs) == 1


def test_a_long_plan_is_capped_to_twelve_rules_and_the_byte_budget(tmp_path):
    root = install(tmp_path)
    plan = "url file path xml sql cipher command session password log template http jwt zip archive token " * 30
    result = guidance(root, plan[:4000], [J + "A.java", "pom.xml", "src/main/resources/application.yml"])
    assert 0 < len(result["guidance"]) <= 12
    assert len(json.dumps(result).encode()) <= 4000
    assert result["truncated"] is True
