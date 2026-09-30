"""`chock plugin build` for bundles: write or check each bundle's package per format, and the bundle index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chock.compile.compiler import _load_manifest
from chock.emit import write_generated
from chock.plugin import bundle_build, bundle_index, bundles, store
from chock.plugin.build import plugin_name


@dataclass(frozen=True)
class BundleRun:
    """What a bundle build reads and where it writes."""

    by_id: dict[str, tuple[Path, dict[str, Any]]]
    formats: list[str]
    repo_root: Path
    out_root: Path


def _members(bundle: dict[str, Any], by_id: dict[str, tuple[Path, dict[str, Any]]]) -> list[bundle_build.Member]:
    return [bundle_build.Member(by_id[m][0], by_id[m][1]) for m in bundle["members"]]


def package_bundles(bundle_list: list[dict[str, Any]], run: BundleRun, *, check: bool) -> list[str]:
    """Differences (when `check`) or nothing; otherwise the bundles are written under `out_root/<format>/<id>/`."""
    bundles.check_members(bundle_list, set(run.by_id))
    differences: list[str] = []
    for bundle in bundle_list:
        name = plugin_name(bundle["id"])
        members = _members(bundle, run.by_id)
        for fmt in run.formats:
            target = run.out_root / fmt / name
            files_fn = _files_fn(fmt, bundle, members)
            if fmt == bundle_build.AGENT_PLUGINS:
                differences.extend(_plain(files_fn, name, target, run.repo_root, check=check))
                continue
            args = (fmt, files_fn, Path(name), {"id": name}, run.repo_root, target)
            if check:
                differences.extend(store.store_plugin_differences(*args))
            else:
                store.build_store_plugin(*args)
    differences.extend(_index(bundle_list, run.out_root, check=check))
    return differences


def _files_fn(fmt: str, bundle: dict[str, Any], members: list[bundle_build.Member]) -> Any:
    def files_fn(_dir: Path, _manifest: dict[str, Any], root: Path) -> dict[Path, str]:
        return bundle_build.bundle_files(fmt, bundle, members, root)

    return files_fn


def _plain(files_fn: Any, name: str, target: Path, repo_root: Path, *, check: bool) -> list[str]:
    """The generic format has no store record of what it owns, so it is only written or compared."""
    found: list[str] = []
    for rel, content in files_fn(target, {}, repo_root).items():
        dest = target / rel
        if not check:
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_generated(dest, content)
        elif not dest.exists():
            found.append(f"missing: {name}/{rel.as_posix()}")
        elif dest.read_text(encoding="utf-8") != content:
            found.append(f"differs: {name}/{rel.as_posix()}")
    return found


def _index(bundle_list: list[dict[str, Any]], out_root: Path, *, check: bool) -> list[str]:
    """`chock-bundles.json`: written, compared, or removed when no bundle is built."""
    dest = out_root / bundle_index.BUNDLES_INDEX
    content = bundle_index.bundles_index(bundle_list) if bundle_list else None
    if check:
        if content is None:
            return [f"stale: {bundle_index.BUNDLES_INDEX} (no bundle produces it)"] if dest.exists() else []
        if not dest.exists():
            return [f"missing: {bundle_index.BUNDLES_INDEX}"]
        return [] if dest.read_text(encoding="utf-8") == content else [f"differs: {bundle_index.BUNDLES_INDEX}"]
    if content is None:
        dest.unlink(missing_ok=True)
    else:
        out_root.mkdir(parents=True, exist_ok=True)
        write_generated(dest, content)
    return []


def bundle_step(
    repo_root: Path, bundles_arg: str | None, policy_dirs: list[Path], run_args: tuple[list[str], Path], *, check: bool
) -> tuple[list[str], set[str]]:
    """Package the repo's bundles over its full policy set: (differences, bundle ids produced)."""
    formats, out_root = run_args
    path = Path(bundles_arg) if bundles_arg else repo_root / bundles.BUNDLES_FILE
    bundle_list = bundles.load_bundles(path) if path.is_file() else []
    by_id = {}
    for policy_dir in policy_dirs:
        manifest = _load_manifest(policy_dir)
        if manifest:
            by_id[str(manifest.get("id") or policy_dir.name)] = (policy_dir, manifest)
    run = BundleRun(by_id, formats, repo_root, out_root)
    return package_bundles(bundle_list, run, check=check), {b["id"] for b in bundle_list}
