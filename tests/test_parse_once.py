"""`chock check` parses each YAML text and extracts each bundled module once, and never reads stale."""

from __future__ import annotations

import ast
import inspect
import os

import yaml

from chock import yamlio
from chock.gate import edit_image, guard_runner, patch_image, runtime_bundle, sessionstart, write_gate


def test_the_libyaml_loader_is_used_when_present() -> None:
    assert yamlio.SAFE_LOADER is getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def test_a_text_is_parsed_once(monkeypatch) -> None:
    yamlio._parsed.cache_clear()
    calls = []
    real = yaml.load
    monkeypatch.setattr(yaml, "load", lambda *a, **k: calls.append(a) or real(*a, **k))
    text = "id: parse-once-probe\nlist: [1, 2]\n"
    assert yamlio.safe_load(text) == yamlio.safe_load(text) == {"id": "parse-once-probe", "list": [1, 2]}
    assert len(calls) == 1


def test_a_caller_cannot_edit_another_callers_document() -> None:
    first = yamlio.safe_load("list: [1]\n")
    first["list"].append(2)
    assert yamlio.safe_load("list: [1]\n") == {"list": [1]}


def test_a_file_rewritten_in_place_is_never_read_stale(tmp_path) -> None:
    """Same size, same mtime: a stat-keyed cache would serve the old document; a text key cannot."""
    path = tmp_path / "manifest.yaml"
    path.write_text("id: aaaa\n", encoding="utf-8")
    stamp = path.stat().st_mtime_ns
    assert yamlio.safe_load(path.read_text(encoding="utf-8")) == {"id": "aaaa"}
    path.write_text("id: bbbb\n", encoding="utf-8")
    os.utime(path, ns=(stamp, stamp))
    assert yamlio.safe_load(path.read_text(encoding="utf-8")) == {"id": "bbbb"}


def test_the_bundle_segments_match_ast_exactly() -> None:
    """The one-split slicer must return what ast.get_source_segment would, byte for byte."""
    for module in (guard_runner, edit_image, patch_image, write_gate, sessionstart):
        source = inspect.getsource(module)
        lines = source.encode("utf-8").splitlines(keepends=True)
        for node in ast.parse(source).body:
            assert runtime_bundle._segment(lines, node) == ast.get_source_segment(source, node)


def test_a_runtime_is_rendered_once_per_process(monkeypatch) -> None:
    runtime_bundle.render.cache_clear()
    calls = []
    real = runtime_bundle.bundler.bundle
    monkeypatch.setattr(runtime_bundle.bundler, "bundle", lambda agent: calls.append(agent) or real(agent))
    assert runtime_bundle.render("claude_code") == runtime_bundle.render("claude_code")
    assert calls == ["claude_code"]
    runtime_bundle.render.cache_clear()
