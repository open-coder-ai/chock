"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Finding:
    path: str
    check: str
    severity: str
    message: str


@dataclass
class Report:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    infos: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        if finding.severity == "error":
            self.errors.append(finding)
        elif finding.severity == "warning":
            self.warnings.append(finding)
        else:
            self.infos.append(finding)

    def is_clean(self) -> bool:
        return not self.errors


def emit(report: Report, use_json: bool) -> None:
    if use_json:
        print(
            json.dumps(
                {
                    "valid": report.is_clean(),
                    "errors": [f.__dict__ for f in report.errors],
                    "warnings": [f.__dict__ for f in report.warnings],
                    "infos": [f.__dict__ for f in report.infos],
                },
                indent=2,
            )
        )
        return

    if report.is_clean() and not report.warnings:
        print("[PASS] All checks passed.")
    elif report.is_clean():
        print("[PASS] Passed with warnings.")
    else:
        print("[FAIL] Validation failed.")

    for finding in report.errors:
        print(f"  [ERROR] {finding.path} :: {finding.check}: {finding.message}")
    for finding in report.warnings:
        print(f"  [WARN]  {finding.path} :: {finding.check}: {finding.message}")
    for finding in report.infos:
        print(f"  [INFO]  {finding.path} :: {finding.check}: {finding.message}")
