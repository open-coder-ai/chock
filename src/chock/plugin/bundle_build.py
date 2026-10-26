"""Package a bundle per client as one merged plugin: `chock install --selection` is the only bundle route.

Merging reuses each member's own builder: a member's files come from the same `*_plugin_files` a
stand-alone package uses, and are only placed under the bundle -- skills stay under the member's
name, its scripts move under `scripts/<member>/`, its hook commands are re-pointed there and the
hook documents are concatenated. The client's runtime and launcher are chock's own and identical
in every member, so they are shared, and two members that disagree about a shared file are an error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from chock.guardrails import plugin as guardrails
from chock.hooks import heartbeat, stop_check
from chock.plugin import bundle_grade, bundles, claude, hook_dir
from chock.plugin.clients import CLIENTS, Client
from chock.plugin.listing import LICENSE_REL, license_text
from chock.plugin.store import SCRIPTS_TEMPLATE

SCRIPTS_DIR = "scripts/"

FilesFn = Callable[[Path, dict[str, Any], Path], dict[Path, str]]


class MergeCollisionError(bundles.BundleError):
    """Two members would write different bytes to one path of a merged bundle."""


@dataclass(frozen=True)
class Member:
    """One policy a bundle names, as the packager is given it."""

    policy_dir: Path
    manifest: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.manifest.get("id") or self.policy_dir.name)


def _synthetic_manifest(bundle: dict[str, Any], members: list[Member], description: str, grade: int) -> dict[str, Any]:
    """The policy-manifest shape the client builders read, for the bundle itself."""
    provenance: dict[str, Any] = {}
    for key in ("license", "source_repo", "author"):
        values = {str((m.manifest.get("provenance") or {}).get(key)) for m in members} - {"None", ""}
        if len(values) == 1:
            provenance[key] = values.pop()
    if {"license", "author"} <= provenance.keys():
        # One licence and one holder across the members: the bundle's notice dates from its oldest.
        years = sorted(str((m.manifest.get("provenance") or {}).get("created_at") or "")[:4] for m in members)
        if years and all(y.isdigit() for y in years):
            provenance["created_at"] = years[0]
    return {
        "id": bundle["id"],
        "name": bundle.get("name") or bundle["id"],
        "version": bundle["version"],
        "description": description,
        "artifact": "bundle",
        "enforcement": bundle_grade.enforcement_keyword(grade),
        "provenance": provenance,
    }


def _member_packages(
    client: Client, members: list[Member], repo_root: Path, hooks_rel: str
) -> list[tuple[Member, dict[Path, str], int, str]]:
    out = []
    for member in members:
        files = client.files(member.policy_dir, member.manifest, repo_root)
        grade, what = bundle_grade.grade_of_files(files, hooks_rel, client.agent)
        out.append((member, files, grade, what))
    return out


def member_grades(
    client_name: str, members: list[Member], repo_root: Path, *, write_judged: bool = True
) -> list[tuple[Member, int, str]]:
    """(member, grade, what it does) for each member, read from the hooks its own package in `client_name` ships."""
    client = CLIENTS[client_name]
    hooks_rel = client.layout()[1]
    out = []
    for member in members:
        files = client.files(member.policy_dir, member.manifest, repo_root)
        grade, what = bundle_grade.grade_of_files(files, hooks_rel, client.agent, write_judged=write_judged)
        out.append((member, grade, what))
    return out


#: Devin's own docs call plugin hooks best-effort and fail-open, so no member line may say it "refuses" flatly.
_QUALIFIER = {"devin": "best-effort, and a hook error lets the action through: "}


def _describe(client: Client, bundle: dict[str, Any], packages: list, note: str) -> tuple[str, int]:
    """The bundle's per-member statement, and the weakest member's grade -- the bundle-level claim."""
    qualifier = _QUALIFIER.get(client.package_agent, "")
    lines = [(m.id, what if g == bundle_grade.ADVISORY else f"{qualifier}{what}") for m, _f, g, what in packages]
    text = bundles.bundle_description(bundle["description"], lines)
    return f"{text} {note}".strip(), min(grade for _m, _f, grade, _w in packages)


def _weakest_flags(packages: list, grade: int, hooks_rel: Path) -> tuple[bool, bool, bool]:
    """(enforced, gate, guard) of the first member at the weakest grade: what the client's posture keys on."""
    member_files = next(files for _m, files, g, _w in packages if g == grade)
    gated = Path(SCRIPTS_TEMPLATE.format(name="gate.json")) in member_files
    guarded = bundle_grade.carries_guard(member_files.get(hooks_rel))
    return grade != bundle_grade.ADVISORY, gated, guarded


def _bundle_manifest(
    client: Client, bundle: dict[str, Any], packages: list, *, carries_hooks: bool, note: str = ""
) -> dict[str, Any]:
    """The client's own manifest for the bundle, its posture sentence the weakest member's."""
    text, grade = _describe(client, bundle, packages, note)
    hooks_rel = Path(client.layout()[1])
    weak_enforced, weak_gate, weak_guard = _weakest_flags(packages, grade, hooks_rel)
    synthetic = _synthetic_manifest(bundle, [m for m, *_ in packages], text, grade)
    assert client.manifest is not None and client.posture is not None  # noqa: S101 -- callers skip manifest-less formats
    manifest = client.manifest(synthetic, Path(bundle["id"]), enforced=carries_hooks, gate=weak_gate, guard=weak_guard)
    posture = client.posture(enforced=weak_enforced, gate=weak_gate, guard=weak_guard)
    manifest["description"] = f"{text} [{posture}]"
    return manifest


def _per_member(manifest: dict[str, Any], client: Client, bundle: dict[str, Any], packages: list) -> dict[str, Any]:
    """`manifest` labelling each member only: no weakest-member posture suffix or enforcement keyword."""
    text, grade = _describe(client, bundle, packages, "")
    if "keywords" not in manifest:  # a closed manifest schema (antigravity) refuses a key it does not name
        return {**manifest, "description": text}
    keywords = [k for k in manifest["keywords"] if k != bundle_grade.enforcement_keyword(grade)]
    return {**manifest, "description": text, "keywords": keywords}


def _with_licence(files: dict[Path, str], bundle: dict[str, Any], members: list[Member]) -> dict[Path, str]:
    """The bundle's own LICENSE, written only when every member shares one licence and holder.

    A member's LICENSE is never carried over: it would claim to cover the other members' files.
    """
    files.pop(LICENSE_REL, None)
    licence = license_text(_synthetic_manifest(bundle, members, "", bundle_grade.ADVISORY))
    if licence:
        files[LICENSE_REL] = licence
    return files


def _merge_docs(into: Any, other: Any, where: str = "hooks") -> Any:
    """Concatenate lists, merge dicts, and require agreement on everything else."""
    if isinstance(into, dict) and isinstance(other, dict):
        for key, value in other.items():
            into[key] = _merge_docs(into[key], value, f"{where}.{key}") if key in into else value
        return into
    if isinstance(into, list) and isinstance(other, list):
        return into + other
    if into != other:
        msg = f"members disagree at {where}: {into!r} vs {other!r}"
        raise MergeCollisionError(msg)
    return into


def _merge_into(into: Any, other: Any) -> Any:
    """`other` merged into the hooks gathered so far; the first document starts them."""
    return other if into is None else _merge_docs(into, other)


def _repoint(doc: Any, moved: dict[str, str]) -> Any:
    """`doc` with every hook command's member-owned script path moved under the member's directory."""
    if isinstance(doc, dict):
        return {
            k: _repoint_command(v, moved) if k == "command" and isinstance(v, str) else _repoint(v, moved)
            for k, v in doc.items()
        }
    return [_repoint(v, moved) for v in doc] if isinstance(doc, list) else doc


def _repoint_command(command: str, moved: dict[str, str]) -> str:
    changed = command
    for old in sorted(moved, key=len, reverse=True):
        changed = re.sub(rf"(?<![\w.-]){re.escape(old)}(?![\w.-])", moved[old], changed)
    if changed == command:
        msg = f"hook command references no member-owned script, so it cannot be namespaced: {command!r}"
        raise MergeCollisionError(msg)
    return changed


def _place(into: dict[Path, str], rel: Path, content: str) -> None:
    if rel in into and into[rel] != content:
        msg = f"two members write different bytes to {rel.as_posix()}"
        raise MergeCollisionError(msg)
    into[rel] = content


def _merge_member(
    client: Client, member_id: str, member_files: dict[Path, str], files: dict[Path, str], special: tuple[Path, ...]
) -> dict[str, Any] | None:
    """Place one member's files in `files`, its scripts under `scripts/<member>/`; return its repointed hooks."""
    shared = set(claude._runtime_files(client.agent))
    moved = {
        rel.as_posix(): f"{SCRIPTS_DIR}{member_id}/{rel.relative_to(SCRIPTS_DIR).as_posix()}"
        for rel in member_files
        if rel.as_posix().startswith(SCRIPTS_DIR) and rel not in shared
    }
    doc = None
    for rel, content in member_files.items():
        if rel in (*special[1:], LICENSE_REL):
            continue
        if rel == special[0]:
            doc = _repoint(stop_check.without(json.loads(content)), moved)
        elif rel.as_posix() in moved:
            _place(files, Path(moved[rel.as_posix()]), content)
        else:
            _place(files, rel, content)
    return doc


def _scripts_only(member_files: dict[Path, str], hooks_rel: Path) -> dict[Path, str]:
    """The built-in protection's hooks and scripts: no skill, manifest or licence of its own."""
    return {rel: c for rel, c in member_files.items() if rel == hooks_rel or rel.as_posix().startswith(SCRIPTS_DIR)}


def _rows(client: Client, bundle: dict[str, Any], packages: list) -> list[tuple[str, str]]:
    """(policy id, label) per member: the install's own labels when given, else what its hooks do here."""
    given = bundle.get("labels") or {}
    qualifier = _QUALIFIER.get(client.package_agent, "")
    return [
        (m.id, given.get(m.id) or (what if g == bundle_grade.ADVISORY else f"{qualifier}{what}"))
        for m, _f, g, what in packages
    ]


def merged_files(
    client_name: str, bundle: dict[str, Any], members: list[Member], repo_root: Path, *, aggregate: bool = True
) -> dict[Path, str]:
    """One plugin carrying every member's skills, hooks, scripts and packages; `aggregate=False` drops the bundle claim."""
    client = CLIENTS[client_name]
    manifest_name, hooks_name, skill_rel = client.layout()
    hooks_rel = Path(hooks_name)
    manifest_rel = Path(manifest_name) if manifest_name else None
    special = (hooks_rel,) if manifest_rel is None else (hooks_rel, manifest_rel)
    packages = _member_packages(client, members, repo_root, hooks_rel.as_posix())
    files: dict[Path, str] = {}
    hooks: Any = None  # a map of events, or (kimi) a flat list of rules
    for member, member_files, _grade, _what in packages:
        doc = _merge_member(client, member.id, member_files, files, special)
        if doc is not None:
            hooks = _merge_into(hooks, guardrails.wrap_doc(doc, client.agent, bundle["id"], member.id))
    protect = Member(guardrails.protect_dir(), guardrails.protect_manifest())
    protect_files = client.files(protect.policy_dir, protect.manifest, repo_root)
    protect_doc = _merge_member(client, protect.id, _scripts_only(protect_files, hooks_rel), files, (hooks_rel,))
    hooks = _merge_into(hooks, guardrails.verify_at_stop(protect_doc, client.agent))
    beat = heartbeat.plugin_doc(client.agent, hooks)
    if beat is not None:  # one session_start line per session, from the runtime the protection already ships
        beat = guardrails.at_session_start(beat, client.agent)
        hooks = _merge_into(hooks, hook_dir.store_timeout(client.own_layout, beat) if client.own_layout else beat)
    stop = stop_check.plugin_doc(client.agent, hooks, generic=client.generic)  # `chock stop`: every tool, never toggled
    hooks = _merge_into(hooks, hook_dir.store_timeout(client.own_layout, stop) if client.own_layout else stop)
    for rel, content in guardrails.files(bundle["id"], _rows(client, bundle, packages), skill_rel).items():
        _place(files, rel, content)
    if manifest_rel is not None:
        manifest = _bundle_manifest(client, bundle, packages, carries_hooks=bool(hooks))
        if not aggregate:
            manifest = _per_member(manifest, client, bundle, packages)
        files[manifest_rel] = json.dumps(manifest, indent=2) + "\n"
    if hooks:
        files[hooks_rel] = json.dumps(hooks, indent=2) + "\n"
    return dict(sorted(_with_licence(files, bundle, members).items()))
