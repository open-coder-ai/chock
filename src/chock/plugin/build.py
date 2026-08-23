"""Emit an Agent Plugins 1.0.0 package from a policy directory.

Agent Plugins (agent-plugins.org, published 2026-08-06) standardises a directory layout for
shipping agent extensions: `plugin.json` at the root, skills under `skills/<name>/SKILL.md`,
and reverse-domain namespace directories for anything client-specific. Its v1 covers skills
and MCP servers only -- hooks, commands and rules are explicitly deferred "until their
formats converge" -- and it defines no trust, provenance or distribution semantics at all.

That is why this lives outside `compile/`. The tempting implementation is a
`Surface.AGENT_PLUGIN` registered next to `git-hook` and `ambient-rule`, and it would be
wrong in the one way this project cannot afford. `Surface` is not a list of output formats;
it is the input to `coverage_level()`, which answers what a policy actually *enforces*. A
plugin skill is text a conformant client reads, with exactly the reach of an ambient rule:
advisory. Registering it as a surface would either add a 13-agent matrix column for something
that enforces nothing, or inflate a coverage verdict -- the failure `INSTALLED_SURFACES` was
rewritten to make structurally impossible.

So: packaging here, enforcement there, and `test_agent_plugin.py` asserts the separation so
it cannot be quietly undone.

`manifest.yaml` stays canonical. `plugin.json` is generated from it and never hand-authored,
because two hand-maintained manifests disagree eventually and the disagreement is silent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chock.compile.emitters.advisory import advisory_lines
from chock.emit import write_generated

#: The schema's `$schema` property is a `const`, so this string is not a default -- any other
#: value makes the manifest invalid. Pinned to 1.0.0 deliberately: a client selects its
#: supported schema from this field, and silently tracking "latest" would change what we
#: claim conformance to without anyone reviewing the change.
SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

#: Spec section 8: "A client SHOULD base its namespace on a domain name it controls." We do
#: not own chock.dev; we do control the GitHub org, so this is accurate today. It is
#: also permanent in practice -- anything reading the namespace breaks if it moves -- so
#: registering a domain later is not on its own a reason to change it.
NAMESPACE = "io.github.open-coder-ai"

#: From schemas/1.0.0/plugin.schema.json. Reproduced rather than fetched: emitting a manifest
#: is offline work, and a network dependency in the compile path would be a worse trade than
#: a constant that a conformance test re-checks against the vendored schema.
_NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_NAME_MAX = 64

#: `additionalProperties: false`, so an unrecognised key is not ignored -- it invalidates the
#: whole manifest. Ordered as the schema declares them for a stable diff.
MANIFEST_KEYS = (
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
)


class PluginNameError(ValueError):
    """A policy id that cannot be a conformant plugin name."""


def plugin_name(policy_id: str) -> str:
    """Validate a policy id as an Agent Plugins `name`.

    Deliberately raises instead of sanitising. A silently rewritten id would make the plugin
    name and the policy id disagree, and the policy id is what every other surface -- the
    lockfile, coverage.json, the gate -- is keyed by. Better to refuse to package than to
    ship a package that identifies itself as something else.
    """
    if len(policy_id) > _NAME_MAX or not _NAME_PATTERN.match(policy_id):
        raise PluginNameError(
            f"policy id {policy_id!r} is not a valid Agent Plugins name: "
            f"lowercase alphanumerics, dots and hyphens, no leading/trailing separator, "
            f"no '--' or '..', max {_NAME_MAX} chars"
        )
    return policy_id


def _one_line(text: Any) -> str:
    """Collapse a folded YAML block to a single line."""
    return " ".join(str(text or "").split())


def _keywords(manifest: dict[str, Any]) -> list[str]:
    """Discovery terms drawn from the manifest, never invented.

    Order is fixed rather than sorted so the emitted array reads most-specific-first and does
    not reshuffle when a compliance tag is added.
    """
    words = ["chock", "policy-as-code"]
    for key in ("artifact", "enforcement"):
        value = manifest.get(key)
        if value:
            words.append(str(value))
    for tag in (manifest.get("compliance") or {}).get("owasp_asi") or []:
        words.append(str(tag).lower())
    seen: set[str] = set()
    return [w for w in words if not (w in seen or seen.add(w))]


def _author(provenance: dict[str, Any]) -> dict[str, str] | None:
    """`author` is an object with `additionalProperties: false`, so only name/email/url.

    Omitted entirely when there is no author, rather than emitted as `{}`: an empty object is
    a claim that we looked and found nothing, and a missing key is the truth.
    """
    name = _one_line(provenance.get("author"))
    return {"name": name} if name else None


def build_manifest(manifest: dict[str, Any], policy_dir: Path) -> dict[str, Any]:
    """Derive a conformant `plugin.json` from a policy manifest."""
    policy_id = manifest.get("id") or Path(policy_dir).name
    provenance = manifest.get("provenance") or {}

    data: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "name": plugin_name(str(policy_id)),
        "description": _one_line(manifest.get("description")),
        "keywords": _keywords(manifest),
        # Spec section 8.1: a client MUST ignore namespaces it does not implement. This is the
        # sanctioned way to ship enforcement metadata through a format that has no concept of
        # enforcement -- everyone else sees a valid plugin with one advisory skill.
        "extensions": {
            NAMESPACE: {
                "manifest": "manifest.yaml",
                "artifact": manifest.get("artifact"),
                "enforcement": manifest.get("enforcement"),
                # Named for the limitation rather than the capability. A client that ignores
                # our namespace gets advisory text and nothing else, and that is what this
                # field says out loud instead of leaving the reader to infer it.
                "coverage_without_chock": "advisory",
            }
        },
    }
    if manifest.get("version"):
        data["version"] = str(manifest["version"])
    if provenance.get("license"):
        data["license"] = str(provenance["license"])
    if provenance.get("source_repo"):
        data["repository"] = str(provenance["source_repo"])
    author = _author(provenance)
    if author:
        data["author"] = author

    return {key: data[key] for key in MANIFEST_KEYS if key in data}


#: Printed in every generated skill. A conformant client has no mechanism to enforce anything
#: -- the standard defines none -- so a policy distributed this way reaches exactly as far as
#: an ambient rule. Stating that in our own output costs nothing and is the whole reason the
#: coverage taxonomy is believed elsewhere.
_ADVISORY_NOTE = (
    "This skill is advisory: the client reading it has no mechanism to enforce it. "
    "The same policy compiled by `chock` becomes a git hook that exits non-zero. "
    "See https://github.com/open-coder-ai/chock"
)


def build_skill(policy_dir: Path, manifest: dict[str, Any], repo_root: Path, hooks: str | None = None) -> str:
    """Render `SKILL.md` for a policy.

    The body comes from `advisory_lines` -- the same function that renders the AGENTS.md
    ambient block -- so the plugin and the ambient rule cannot drift, and neither can
    contradict the resolved gate. That function reads the *resolved* gate spec, which is why
    a policy whose protected branches come from config renders the branches actually
    enforced rather than the manifest's defaults.

    `hooks` is the package-relative path of a hook shipped BESIDE this skill, or None.
    The frontmatter coverage claim must match the package it ships in: a hookless package
    is advisory without chock, and says so; a hook-carrying package enforces without chock
    in clients that read the hook, so it names the hook instead -- the same substitution
    the hook emitters make in plugin.json. Leaving the advisory claim in a hooked package
    made one file contradict its own directory.
    """
    policy_id = manifest.get("id") or Path(policy_dir).name
    description = _one_line(manifest.get("description")) or f"Chock policy {policy_id}"

    lines = advisory_lines(Path(policy_dir), manifest, Path(repo_root))
    body = "\n".join(lines) if lines else f"see .agents/policies/{policy_id}/"

    # Frontmatter is hand-rendered rather than yaml.dump'd: the description is a single
    # already-collapsed line and the quoting rules for it are trivial, while yaml.dump would
    # reflow long values and reorder nothing usefully. Deterministic bytes matter more here.
    #
    # `metadata` is a flat string-to-string map because the Agent Skills spec (which Agent
    # Plugins 1.0 defers to for SKILL.md) requires exactly that -- string keys to string
    # values. The original nested `chock:` object was a spec violation that awesome-copilot's
    # `vally` linter rejected ("Metadata values must be strings"). Dotted keys keep the
    # namespacing the nesting used to provide.
    coverage_line = f"  chock.hooks: {hooks}\n" if hooks else "  chock.coverage_without_chock: advisory\n"
    return (
        "---\n"
        f"name: {policy_id}\n"
        f"description: {json.dumps(description)}\n"
        "metadata:\n"
        f"  chock.artifact: {manifest.get('artifact') or 'rule'}\n"
        f"  chock.enforcement: {manifest.get('enforcement') or 'advise'}\n"
        f"{coverage_line}"
        "---\n"
        "\n"
        f"# {manifest.get('name') or policy_id}\n"
        "\n"
        f"{description}\n"
        "\n"
        "```\n"
        f"{body}\n"
        "```\n"
        "\n"
        f"{_ADVISORY_NOTE}\n"
    )


def plugin_files(policy_dir: Path, manifest: dict[str, Any], repo_root: Path) -> dict[Path, str]:
    """Return the plugin's files as {relative path: content}, writing nothing.

    Separating rendering from writing is what lets `--check` compare against the tree without
    touching it. `recompile --check` once wrote into the very tree it was measuring, so the
    check could not fail; keeping the pure function pure is how that stays fixed here.
    """
    policy_id = manifest.get("id") or Path(policy_dir).name
    name = plugin_name(str(policy_id))
    return {
        Path("plugin.json"): json.dumps(build_manifest(manifest, policy_dir), indent=2) + "\n",
        Path("skills") / name / "SKILL.md": build_skill(policy_dir, manifest, repo_root),
    }


def build_plugin(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, out_dir: Path | None = None
) -> list[Path]:
    """Write the Agent Plugins package for one policy. Defaults to in place.

    In place is the spec authors' own migration advice ("add portability first: create
    plugin.json without removing legacy files"): the policy folder gains `plugin.json` and
    `skills/`, and `manifest.yaml` and `evals/` stay exactly where every other command
    expects them.
    """
    target = Path(out_dir) if out_dir else Path(policy_dir)
    written: list[Path] = []
    for rel, content in plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
        written.append(dest)
    return written


def plugin_differences(
    policy_dir: Path, manifest: dict[str, Any], repo_root: Path, target: Path | None = None
) -> list[str]:
    """Report where the on-disk plugin disagrees with what the manifest would produce.

    `target` mirrors `build_plugin`'s `out_dir`: in place by default, a distribution
    directory when packaging into one -- so check and build always judge the same tree.
    """
    policy_id = manifest.get("id") or Path(policy_dir).name
    differences: list[str] = []
    for rel, content in plugin_files(Path(policy_dir), manifest, Path(repo_root)).items():
        dest = Path(target if target is not None else policy_dir) / rel
        if not dest.exists():
            differences.append(f"missing: {policy_id}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            differences.append(f"differs: {policy_id}/{rel.as_posix()}")
    return differences
