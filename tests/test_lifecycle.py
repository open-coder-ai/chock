"""The umbrella verbs are flag-translation contracts: `sync`/`check`/`status` each"""

from __future__ import annotations

import pytest

from chock import lifecycle


class Recorder:
    def __init__(self, rc: int = 0):
        self.rc = rc
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv or []))
        return self.rc


def test_sync_translates_flags_to_recompile(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("chock.toggles.recompile_main", rec)
    assert lifecycle.sync_main(["--repo", "R", "--agents", "claude", "cursor", "--skip-hooks"]) == 0
    assert rec.calls == [["--repo", "R", "--agents", "claude", "cursor", "--skip-hooks"]]


def test_sync_check_short_circuits_installers(monkeypatch):
    rec = Recorder(rc=0)
    ci = Recorder()
    monkeypatch.setattr("chock.toggles.recompile_main", rec)
    monkeypatch.setattr("chock.scaffold.install_ci.main", ci)
    assert lifecycle.sync_main(["--repo", "R", "--check", "--ci"]) == 0
    assert rec.calls == [["--repo", "R", "--check"]]
    assert ci.calls == [], "--check must never run installers"


def test_sync_failure_rc_propagates_and_stops(monkeypatch):
    rec = Recorder(rc=3)
    ci = Recorder()
    monkeypatch.setattr("chock.toggles.recompile_main", rec)
    monkeypatch.setattr("chock.scaffold.install_ci.main", ci)
    assert lifecycle.sync_main(["--repo", "R", "--ci"]) == 3
    assert ci.calls == [], "a failed recompile must not proceed to installers"


def test_sync_ci_and_skills_installers_receive_repo(monkeypatch):
    rec = Recorder()
    ci = Recorder()
    skills = Recorder()
    monkeypatch.setattr("chock.toggles.recompile_main", rec)
    monkeypatch.setattr("chock.scaffold.install_ci.main", ci)
    monkeypatch.setattr("chock.scaffold.skills.main", skills)
    assert lifecycle.sync_main(["--repo", "R", "--ci", "--skills"]) == 0
    assert ci.calls == [["R"]]
    assert skills.calls == [["R"]]


def test_sync_installer_failure_raises_rc(monkeypatch):
    monkeypatch.setattr("chock.toggles.recompile_main", Recorder(rc=0))
    monkeypatch.setattr("chock.scaffold.install_ci.main", Recorder(rc=2))
    assert lifecycle.sync_main(["--repo", "R", "--ci"]) == 2


def test_check_rejects_unknown_subset(capsys):
    assert lifecycle.check_main(["--only", "validate,nope"]) == 2
    assert "Unknown check(s): nope" in capsys.readouterr().err


def test_check_validate_passes_mode_and_event(monkeypatch):
    val = Recorder()
    monkeypatch.setattr("chock.validation.engine.main", val)
    assert lifecycle.check_main(["--repo", "R", "--only", "validate", "--mode", "m", "--event", "commit"]) == 0
    assert val.calls == [["R", "--mode", "m", "--event", "commit"]]


def test_check_verify_and_evals_and_index_wiring(monkeypatch):
    verify, evals, index = Recorder(), Recorder(), Recorder()
    monkeypatch.setattr("chock.lock.main", verify)
    monkeypatch.setattr("chock.eval.cli.main", evals)
    monkeypatch.setattr("chock.index.cli.cmd_refresh", index)
    assert lifecycle.check_main(["--repo", "R", "--only", "verify,evals,index"]) == 0
    assert verify.calls == [["--repo", "R"]]
    assert evals.calls == [["--repo", "R"]]
    assert index.calls == [["--repo", "R", "--check"]]


def test_check_matrix_skipped_in_adopter_repo(tmp_path, monkeypatch, capsys):
    matrix = Recorder()
    monkeypatch.setattr("chock.authoring.matrix.main", matrix)
    for mod, name in [
        ("chock.validation.engine", "main"),
        ("chock.lock", "main"),
        ("chock.eval.cli", "main"),
        ("chock.index.cli", "cmd_refresh"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", Recorder())
    assert lifecycle.check_main(["--repo", str(tmp_path)]) == 0
    assert matrix.calls == []
    assert "skipped: no spec/enforcement-matrix.md" in capsys.readouterr().out


def test_check_matrix_explicit_only_runs_even_without_file(tmp_path, monkeypatch):
    matrix = Recorder()
    monkeypatch.setattr("chock.authoring.matrix.main", matrix)
    assert lifecycle.check_main(["--repo", str(tmp_path), "--only", "matrix"]) == 0
    assert matrix.calls == [[]]


def test_check_mechanisms_skipped_in_adopter_repo(tmp_path, monkeypatch, capsys):
    mechanisms = Recorder()
    monkeypatch.setattr("chock.validation.checks_matrix_mechanisms.main", mechanisms)
    for mod, name in [
        ("chock.validation.engine", "main"),
        ("chock.lock", "main"),
        ("chock.eval.cli", "main"),
        ("chock.index.cli", "cmd_refresh"),
    ]:
        monkeypatch.setattr(f"{mod}.{name}", Recorder())
    assert lifecycle.check_main(["--repo", str(tmp_path)]) == 0
    assert mechanisms.calls == []
    assert "skipped: no spec/enforcement-matrix.md" in capsys.readouterr().out


def test_check_mechanisms_explicit_only_runs_even_without_file(tmp_path, monkeypatch):
    mechanisms = Recorder()
    monkeypatch.setattr("chock.validation.checks_matrix_mechanisms.main", mechanisms)
    assert lifecycle.check_main(["--repo", str(tmp_path), "--only", "mechanisms"]) == 0
    assert mechanisms.calls == [["--repo", str(tmp_path)]]


def test_check_rc_is_max_of_members(monkeypatch):
    monkeypatch.setattr("chock.lock.main", Recorder(rc=1))
    monkeypatch.setattr("chock.eval.cli.main", Recorder(rc=0))
    assert lifecycle.check_main(["--repo", "R", "--only", "verify,evals"]) == 1


def test_status_defaults_to_policies_only(monkeypatch):
    pol, reg = Recorder(), Recorder()
    monkeypatch.setattr("chock.toggles.policies_main", pol)
    monkeypatch.setattr("chock.registry.cli.main", reg)
    assert lifecycle.status_main(["--repo", "R"]) == 0
    assert pol.calls == [["--repo", "R"]]
    assert reg.calls == []


def test_status_registry_and_log_wiring(monkeypatch):
    reg, log = Recorder(), Recorder()
    monkeypatch.setattr("chock.registry.cli.main", reg)
    monkeypatch.setattr("chock.gatelog.main", log)
    assert lifecycle.status_main(["--repo", "R", "--only", "registry,log"]) == 0
    assert reg.calls == [["list", "--repo", "R"]]
    assert log.calls == [["--repo", "R"]]


def test_status_rejects_unknown_section(capsys):
    assert lifecycle.status_main(["--only", "vibes"]) == 2
    assert "Unknown section(s): vibes" in capsys.readouterr().err


@pytest.mark.parametrize("rc", [0, 4])
def test_status_propagates_rc(monkeypatch, rc):
    monkeypatch.setattr("chock.toggles.policies_main", Recorder(rc=rc))
    assert lifecycle.status_main(["--repo", "R"]) == rc
