"""Adopter-safety regressions from the 2026-08 audit tail (P1-G2/G3/G4, E3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import init_repo

from chock.hooks.installers import DISPATCHER_TEMPLATE, GENERATED_MARKER, get_hooks_dir, install_dispatcher
from chock.hooks.ownership import relocate_existing_hook
from chock.scaffold.init import cmd_init


def test_edited_dispatcher_is_backed_up_before_overwrite(tmp_path: Path, capsys) -> None:
    init_repo(tmp_path)
    hooks = get_hooks_dir(tmp_path)
    install_dispatcher(hooks, "pre-commit")
    dispatcher = hooks / "pre-commit"
    edited = dispatcher.read_text(encoding="utf-8") + "\necho my-custom-step\n"
    dispatcher.write_text(edited, encoding="utf-8", newline="\n")

    install_dispatcher(hooks, "pre-commit")

    backup = hooks / "pre-commit.chock-backup"
    assert backup.exists(), "the adopter's edited dispatcher vanished with no copy"
    assert "my-custom-step" in backup.read_text(encoding="utf-8")
    rendered = DISPATCHER_TEMPLATE.replace("__EVENT__", "pre-commit").replace("__MARKER__", GENERATED_MARKER)
    assert dispatcher.read_text(encoding="utf-8") == rendered
    assert "backed up" in capsys.readouterr().err


def test_unedited_dispatcher_reinstall_leaves_no_backup(tmp_path: Path) -> None:
    init_repo(tmp_path)
    hooks = get_hooks_dir(tmp_path)
    install_dispatcher(hooks, "pre-commit")
    install_dispatcher(hooks, "pre-commit")
    assert not (hooks / "pre-commit.chock-backup").exists()


def test_second_foreign_hook_does_not_clobber_first_relocation(tmp_path: Path) -> None:
    impl_dir = tmp_path / "pre-commit.d"
    impl_dir.mkdir()
    hook = tmp_path / "pre-commit"

    hook.write_text("#!/bin/sh\necho first-tool\n", encoding="utf-8")
    relocate_existing_hook(hook, impl_dir)
    hook.write_text("#!/bin/sh\necho second-tool\n", encoding="utf-8")
    relocate_existing_hook(hook, impl_dir)

    texts = sorted(p.read_text(encoding="utf-8") for p in impl_dir.glob("00-preexisting*"))
    assert any("first-tool" in t for t in texts), "the first relocated hook was destroyed"
    assert any("second-tool" in t for t in texts)


def test_init_rerun_preserves_unknown_config_keys_and_comments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    config = repo / ".chock" / "config.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["my_team_section"] = {"owner": "platform"}
    text = "# why: we disable X during the migration\n" + yaml.safe_dump(data, sort_keys=False)
    config.write_text(text, encoding="utf-8")

    cmd_init([str(repo), "--skip-hooks"])

    after = config.read_text(encoding="utf-8")
    assert "my_team_section" in after, "an unknown top-level key was dropped"
    assert yaml.safe_load(after)["my_team_section"] == {"owner": "platform"}
    assert after == text, "a no-op init re-run rewrote config.yaml (comments would be lost)"


def test_init_rerun_does_not_resurrect_template_over_empty_policies(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    config = repo / ".chock" / "config.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["policies"] = {}
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cmd_init([str(repo), "--skip-hooks"])
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["policies"] == {}


def test_lock_write_failure_fails_the_sync(tmp_path: Path, monkeypatch) -> None:
    from chock.scaffold import recompile as recompile_mod
    from chock.toggles import recompile_main

    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])

    def boom(*_a, **_k):
        raise OSError("disk full / file locked")

    monkeypatch.setattr(recompile_mod, "_refresh_bookkeeping", recompile_mod._refresh_bookkeeping)
    import chock.lock as lock_mod

    monkeypatch.setattr(lock_mod, "write_lock", boom)
    rc = recompile_main(["--repo", str(repo), "--skip-hooks"])
    assert rc == 1, "a stale lockfile after recompile must fail the command, not warn"


def test_bookkeeping_error_carries_the_remedy(tmp_path: Path, monkeypatch) -> None:
    from chock.scaffold.recompile import BookkeepingError, recompile

    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    import chock.lock as lock_mod

    monkeypatch.setattr(lock_mod, "write_lock", lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(BookkeepingError, match="chock sync"):
        recompile(repo, ["claude"], skip_hooks=True)


def test_init_scaffolds_gitattributes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cmd_init([str(repo), "--skip-hooks"])
    ga = (repo / ".gitattributes").read_text(encoding="utf-8")
    assert "chock.lock text eol=lf" in ga
    assert ".chock/** text eol=lf" in ga
    assert ".agents/** text eol=lf" in ga


def test_init_preserves_an_adopter_gitattributes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")
    cmd_init([str(repo), "--skip-hooks"])
    assert (repo / ".gitattributes").read_text(encoding="utf-8") == "*.png binary\n"
