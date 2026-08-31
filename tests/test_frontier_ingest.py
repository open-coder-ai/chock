"""frontier_ingest turns upstream agent-standard docs into the pinned JSON the"""

from __future__ import annotations

import json

from chock.validation import frontier_ingest as fi

AGENTSKILLS_DOC = """
The `name` field. Max 64 characters. Must be 1-64 characters.
The `description` field. Max 1024 characters.
Keep your main `SKILL.md` under 500 lines.
Instructions (<5000 tokens ideally).
"""

CLAUDE_DOC = """
Skills live in .claude/skills/<skill-name>/SKILL.md within a project.
Dynamic context injection uses the !`command` syntax.
"""


def test_extract_number_first_matching_pattern_wins():
    assert fi.extract_number("Max 64 characters", [r"Max\s+(\d+)\s+characters"]) == 64
    assert fi.extract_number("nothing here", [r"Max\s+(\d+)"]) is None
    assert fi.extract_number("Max 64", [r"Max\s+\d+", r"Max\s+(\d+)"]) == 64


def test_fetch_url_refuses_non_https(capsys):
    assert fi.fetch_url("http://example.com/spec") == ""
    assert fi.fetch_url("file:///etc/passwd") == ""
    err = capsys.readouterr().err
    assert err.count("refusing non-https fetch") == 2


def test_parse_agentskills_extracts_limits():
    data = fi.parse_agentskills(AGENTSKILLS_DOC)
    assert data["skill_name"]["max_length"] == 64
    assert data["skill_description"]["max_length"] == 1024
    assert data["skill_md_body"]["max_lines"] == 500
    assert data["skill_md_body"]["max_tokens"] == 5000


def test_parse_agentskills_empty_doc_keeps_base_keys_only():
    data = fi.parse_agentskills("")
    assert set(data) == {"source", "description"}


def test_parse_claude_code_detects_paths_and_injection():
    data = fi.parse_claude_code(CLAUDE_DOC)
    assert data["skill_path"]["project"] == ".claude/skills/<skill-name>/SKILL.md"
    assert data["dynamic_context_injection"]["allowed"] is True
    bare = fi.parse_claude_code("unrelated text")
    assert "skill_path" not in bare and "dynamic_context_injection" not in bare


def test_merge_into_seed_recursive_and_seed_preserving():
    seed = {"a": {"x": 1, "y": 2}, "keep": "seed", "list": [1]}
    fetched = {"a": {"y": 3}, "list": [9], "new": True}
    merged = fi._merge_into_seed(seed, fetched)
    assert merged["a"] == {"x": 1, "y": 3}, "nested dicts merge; seed defaults survive"
    assert merged["keep"] == "seed"
    assert merged["list"] == [9], "fetched lists take precedence"
    assert merged["new"] is True
    assert seed["a"]["y"] == 2, "the seed itself is not mutated at the top level"


def test_ingest_offline_returns_seed(capsys):
    data = fi.ingest("agentskills", use_network=False)
    assert data == fi.SEEDS["agentskills"]


def test_ingest_falls_back_to_seed_when_fetch_empty(monkeypatch, capsys):
    monkeypatch.setattr(fi, "fetch_url", lambda url: "")
    data = fi.ingest("claude-code", use_network=True)
    assert data == fi.SEEDS["claude-code"]
    assert "using built-in seed" in capsys.readouterr().err


def test_ingest_merges_fetched_over_seed(monkeypatch):
    monkeypatch.setattr(fi, "fetch_url", lambda url: "The `name` field. Max 48 characters.")
    data = fi.ingest("agentskills", use_network=True)
    assert data["skill_name"]["max_length"] == 48, "fetched limit overrides the seed"
    assert data["skill_name"]["must_match_parent_dir"] is True, "seed defaults survive the merge"


def test_ingest_claude_code_always_extends_agentskills(monkeypatch):
    monkeypatch.setattr(fi, "fetch_url", lambda url: CLAUDE_DOC)
    data = fi.ingest("claude-code", use_network=True)
    assert data["extends"] == "agentskills"


def test_save_and_load_standard_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "STANDARDS_DIR", tmp_path)
    path = fi.save_standard("agentskills", dict(fi.SEEDS["agentskills"]))
    assert path == tmp_path / "agentskills.json"
    loaded = fi.load_standard("agentskills")
    assert loaded["skill_name"]["max_length"] == 64
    assert "fetched_at" in loaded
    assert fi.load_standard("missing-agent") is None


def test_main_requires_agent_or_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fi, "STANDARDS_DIR", tmp_path)
    assert fi.main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()
    assert list(tmp_path.iterdir()) == []


def test_main_offline_single_agent_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "STANDARDS_DIR", tmp_path)
    assert fi.main(["--agent", "agentskills", "--offline"]) == 0
    written = json.loads((tmp_path / "agentskills.json").read_text(encoding="utf-8"))
    assert written["skill_name"]["pattern"] == fi.SEEDS["agentskills"]["skill_name"]["pattern"]


def test_main_all_offline_writes_every_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "STANDARDS_DIR", tmp_path)
    assert fi.main(["--all", "--offline"]) == 0
    assert sorted(p.stem for p in tmp_path.glob("*.json")) == sorted(fi.SEEDS)
