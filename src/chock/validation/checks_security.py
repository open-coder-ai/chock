"""Chock module (auto-organized from the original monolith)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from chock.manifest import CANONICAL_MANIFEST, CONTENT_INSTRUCTIONS_KEY
from chock.validation.loading import (
    find_manifest,
)
from chock.validation.patterns import (
    INJECTION_PATTERNS,
)
from chock.validation.report import Finding, Report


def _is_script_file(path: Path) -> bool:
    """Return True for files that are intended to be executable code."""
    code_suffixes = {".py", ".sh", ".ps1", ".js", ".ts", ".rb", ".go", ".java", ".rs"}
    return path.is_file() and path.suffix in code_suffixes


def _split_eval_suite(path: Path) -> tuple[str, list[str]] | None:
    """Split an eval suite into (non-adversarial remainder, adversarial case texts)."""
    if path.name not in ("suite.yaml", "suite.yml"):
        return None
    if "evals" not in path.parts:
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(doc, dict):
        return None
    suite = doc.get("eval_suite", doc.get("suite", {}))
    if not isinstance(suite, dict):
        return None
    cases_key = "cases" if "cases" in suite else "test_cases"
    cases = suite.get(cases_key, [])
    if not isinstance(cases, list):
        return None
    if not cases:
        return None
    case_texts = [yaml.safe_dump(case, sort_keys=False) for case in cases]
    remainder_doc = dict(doc)
    remainder_suite = dict(suite)
    remainder_suite[cases_key] = []
    remainder_doc["eval_suite" if "eval_suite" in doc else "suite"] = remainder_suite
    return yaml.safe_dump(remainder_doc, sort_keys=False), case_texts


def _scan_text_surfaces(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Scan every text surface in the artifact folder for prompt-injection tripwires (SEC-4)."""
    text_suffixes = {".md", ".yaml", ".yml", ".txt"}
    for path in artifact_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in text_suffixes:
            continue
        rel_parts = path.relative_to(artifact_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        split = _split_eval_suite(path)
        if split is not None:
            remainder, adversarial_cases = split
            surfaces = [(remainder, "error", "")] + [
                (case_text, "info", " in an eval case") for case_text in adversarial_cases
            ]
        else:
            surfaces = [(text, "error", "")]
        for surface_text, severity, where in surfaces:
            for pattern in INJECTION_PATTERNS:
                if re.search(pattern, surface_text, re.IGNORECASE):
                    report.add(
                        Finding(
                            str(path),
                            "security",
                            severity,
                            f"Prompt-injection-like pattern matched in {path.name}{where}: '{pattern}' (SEC-4).",
                        )
                    )


def check_security_baseline(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Lightweight deterministic security checks (no LLM)."""
    manifest_path = find_manifest(artifact_dir, artifact_type)
    manifest_ref = str(manifest_path or artifact_dir / CANONICAL_MANIFEST)

    security = manifest.get("security", {})
    if security.get(CONTENT_INSTRUCTIONS_KEY) != "never-obey":
        report.add(
            Finding(manifest_ref, "security", "error", "security.content_instructions must be 'never-obey' (SEC-1).")
        )

    skill_type = (manifest.get("skill") or {}).get("skill_type") or manifest.get("skill_type")
    script_dirs: list[Path] = []
    if artifact_type == "skill" and skill_type in {"code", "hybrid"}:
        script_dirs.append(artifact_dir / "scripts")
    if artifact_type == "hook":
        script_dirs.append(artifact_dir / "implementations")

    for scripts_dir in (d for d in script_dirs if d.exists()):
        for script in scripts_dir.rglob("*"):
            if not _is_script_file(script):
                continue
            text = script.read_text(encoding="utf-8", errors="ignore").lower()
            if re.search(r"\b(openai|anthropic)\b", text) or re.search(r"\bllm\b", text) or "chat.completions" in text:
                report.add(
                    Finding(
                        str(script),
                        "security",
                        "error",
                        "Deterministic script appears to call an LLM. Code/hybrid scripts must be deterministic (SEC-2).",
                    )
                )
            if re.search(r"\b(requests\.get|requests\.post|urllib)\b", text):
                report.add(
                    Finding(
                        str(script),
                        "security",
                        "warning",
                        "Deterministic script contains network calls; ensure runtime.network_access is true and justified (SEC-2).",
                    )
                )

    _scan_text_surfaces(artifact_dir, manifest, artifact_type, report)


def _resolve_effects_and_approval(manifest: dict[str, Any], artifact_type: str) -> tuple[list[str], dict[str, Any]]:
    """Return the active effects and approval for the artifact type."""
    if artifact_type == "skill":
        skill = manifest.get("skill") or {}
        return skill.get("effects") or manifest.get("effects") or ["none"], skill.get("approval") or manifest.get(
            "approval"
        ) or {}
    if artifact_type == "workflow":
        workflow = manifest.get("workflow") or {}
        return workflow.get("effects") or manifest.get("effects") or ["none"], workflow.get("approval") or manifest.get(
            "approval"
        ) or {}
    return manifest.get("effects") or ["none"], manifest.get("approval") or {}


def check_effects_and_approval(
    artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report
) -> None:
    """Check EFF-1: writes_external/irreversible effects require verify/block enforcement and approval."""
    if artifact_type == "rule":
        return

    effects, approval = _resolve_effects_and_approval(manifest, artifact_type)
    if not effects:
        effects = ["none"]

    manifest_path = find_manifest(artifact_dir, artifact_type) or (artifact_dir / CANONICAL_MANIFEST)

    if "none" in effects and effects != ["none"]:
        report.add(
            Finding(
                str(manifest_path), "effects", "error", "effects cannot mix 'none' with other effect types (EFF-1)."
            )
        )
        return

    gated = {e for e in effects if e in {"writes_external", "irreversible"}}
    if not gated:
        return

    enforcement = manifest.get("enforcement")
    if enforcement not in {"verify", "block"}:
        report.add(
            Finding(
                str(manifest_path),
                "effects",
                "error",
                f"Effects {sorted(gated)} require enforcement 'verify' or 'block' (EFF-1).",
            )
        )

    if not approval.get("required"):
        report.add(
            Finding(
                str(manifest_path),
                "effects",
                "error",
                f"Effects {sorted(gated)} require approval: {{required: true}} (EFF-1).",
            )
        )


def check_ambient_tier(artifact_dir: Path, manifest: dict[str, Any], artifact_type: str, report: Report) -> None:
    """Check SEC-5: rules wired into ambient context require community+ tier or explicit override."""
    if artifact_type != "rule":
        return

    provenance = manifest.get("provenance", {})
    trust_tier = provenance.get("trust_tier", "sandbox")
    if trust_tier in {"community", "verified", "certified"}:
        return

    ambient_override = manifest.get("ambient_override", False)
    if not ambient_override:
        manifest_path = find_manifest(artifact_dir, artifact_type) or (artifact_dir / CANONICAL_MANIFEST)
        report.add(
            Finding(
                str(manifest_path),
                "ambient_tier",
                "error",
                "Rule is wired into ambient context (SEC-5). sandbox is the scaffold default and is fine "
                "while drafting; before the rule ships, either set provenance.trust_tier >= community "
                "(it has been reviewed) or ambient_override: true with a documented rationale "
                "(it is trusted without review, and the manifest says why).",
            )
        )
