"""`chock add <id>` -- fetch one artifact from a catalog and wire it in.

The framework ships no policies, so before this existed the only way to adopt one was to
clone a catalog by hand, copy a folder, and remember to recompile. That is four operations
and one of them is easy to forget, which is a poor first experience for the step that turns
an inert repo into a governed one.

Transport is `git clone --depth 1`, deliberately. It inherits whatever credentials the
adopter already has -- a private catalog works with no token handling in our code, and
there is no bespoke HTTP client to get wrong. A local path is accepted too, which is what
CI and offline installs use.

**Trust model.** A catalog policy is not inert data. `implementations/*.sh` becomes a git
hook that runs on every commit and a guard consulted before an agent runs a command, so
`add` installs executable content from a remote repository. Without a ref it resolves the
catalog's default branch -- whatever that branch points at today.

That is trust-on-first-use, and the job here is to make it evident rather than to imply
otherwise: the resolved commit is printed and recorded in `chock.lock`, `--ref` pins,
and `--verify-sha` refuses content whose hash is not the expected one. The hash is checked
*before* anything is written, so an unexpected guard script never reaches the disk.
Signature verification is the next step up and is not implemented; `SECURITY.md` says so
plainly rather than leaving it to be discovered.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chock.lock import compute_pack_hash, read_lock, write_lock


class IntegrityError(RuntimeError):
    """Fetched content did not match the hash the caller required."""


#: The base catalog. Overridable per call so private and domain catalogs are first-class.
DEFAULT_CATALOG = "https://github.com/open-coder-ai/chock-catalog"

#: Where an artifact lands, by the catalog directory it came from. Policies and skills are
#: different trees in an adopter's repo, so the source directory decides the destination
#: rather than the adopter having to say.
_AREAS = {
    "base": Path(".agents") / "policies",
    "policies": Path(".agents") / "policies",
    "skills": Path(".agents") / "skills",
}


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd) if cwd else None, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def fetch_catalog(source: str, ref: str | None, into: Path) -> tuple[Path, str | None]:
    """Make the catalog available locally. Returns (root, resolved commit or None).

    The commit is what makes an install reproducible: `--ref main` still means "whatever
    main pointed at when you ran it", so the answer has to be recorded rather than the
    request. A local path has no commit to resolve and reports None.
    """
    local = Path(source).expanduser()
    if local.exists():
        return local.resolve(), None

    args = ["git", "clone", "--quiet", "--depth", "1"]
    if ref:
        args += ["--branch", ref]
    args += [source, str(into)]
    result = _run(args)
    if result.returncode != 0:
        raise RuntimeError(f"could not fetch catalog {source}:\n{result.stderr.strip()}")

    resolved = _run(["git", "rev-parse", "HEAD"], cwd=into)
    return into, (resolved.stdout.strip() or None) if resolved.returncode == 0 else None


def _reject_unsafe_id(artifact_id: str) -> None:
    """Refuse an artifact id that is anything but a single path component.

    `artifact_id` becomes `repo_root / area / artifact_id`, and with `--force` that
    destination is `shutil.rmtree`d before the copy. `chock add ../../foo --force` would
    otherwise delete a directory outside the repo. A bare name cannot traverse.
    """
    if artifact_id in ("", ".", "..") or "/" in artifact_id or "\\" in artifact_id or Path(artifact_id).is_absolute():
        raise ValueError(f"invalid artifact id {artifact_id!r}: expected a single name, not a path")


def locate(catalog_root: Path, artifact_id: str) -> tuple[Path, Path]:
    """Find `artifact_id` in the catalog. Returns (source dir, destination area).

    The catalog's registry.yaml is consulted first: it maps every published id to its
    path, whatever tree it lives in. The hardcoded _AREAS scan is only the fallback for
    catalogs without a registry -- it silently missed every tree added after it was
    written (`agentic-security/` shipped 13 policies that `add` could not find).
    """
    _reject_unsafe_id(artifact_id)
    catalog_resolved = catalog_root.resolve()

    registry = catalog_root / "registry.yaml"
    if registry.exists():
        import yaml

        data = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
        for entry in data.get("policies", []) or []:
            if entry.get("id") == artifact_id and entry.get("path"):
                candidate = catalog_root / entry["path"]
                # A registry is catalog-authored data, not a trusted instruction: a `path`
                # of `../../etc` or an absolute path would otherwise make the "catalog
                # artifact" any directory on the machine that holds a manifest.yaml.
                if not candidate.resolve().is_relative_to(catalog_resolved):
                    continue
                if (candidate / "manifest.yaml").exists() or (candidate / "SKILL.md").exists():
                    dest = _AREAS["skills"] if entry["path"].startswith("skills/") else _AREAS["base"]
                    return candidate, dest

    for area, dest in _AREAS.items():
        candidate = catalog_root / area / artifact_id
        if (candidate / "manifest.yaml").exists() or (candidate / "SKILL.md").exists():
            return candidate, dest

    searched = ", ".join(f"{a}/" for a in _AREAS)
    raise FileNotFoundError(f"{artifact_id!r} is not in this catalog (checked registry.yaml and {searched})")


@dataclass
class Added:
    """Where an artifact landed, and the provenance worth recording about it."""

    path: Path
    sha256: str
    commit: str | None = None


def add(
    repo_root: Path,
    artifact_id: str,
    source: str,
    ref: str | None,
    force: bool,
    verify_sha: str | None = None,
) -> Added:
    """Copy one artifact into the repo. Returns where it landed and what it hashed to."""
    with tempfile.TemporaryDirectory(prefix="chock-add-") as tmp:
        catalog, commit = fetch_catalog(source, ref, Path(tmp) / "catalog")
        src, area = locate(catalog, artifact_id)

        # Hashed and checked while the content is still in the temp clone. Verifying after
        # the copy would mean an unexpected guard script had already been written to a repo
        # whose next commit runs it.
        digest = compute_pack_hash(src)
        if verify_sha and digest != verify_sha:
            raise IntegrityError(f"{artifact_id}: expected sha256 {verify_sha}, got {digest}. Nothing was installed.")

        dest = repo_root / area / artifact_id
        if dest.exists() and not force:
            # Never silently replace something the adopter may have edited: once installed,
            # the content is theirs. Refusing is the whole reason policies are not bundled.
            raise FileExistsError(f"{area.as_posix()}/{artifact_id} already exists; use --force to replace it")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        return Added(path=dest, sha256=digest, commit=commit)


def record_provenance(repo_root: Path, artifact_id: str, source: str, ref: str | None, added: Added) -> None:
    """Write where a pack came from into chock.lock.

    `recompile` rebuilds the lockfile from what is on disk, which can say what the bytes are
    but not where they came from. Without this an installed pack was indistinguishable from
    one written by hand, so "which catalog, at which commit" was unanswerable the moment the
    terminal scrolled.
    """
    lock = read_lock(repo_root)
    for entry in lock.get("packs", []):
        if entry.get("id") != artifact_id:
            continue
        entry["source"] = source
        entry["source_commit"] = added.commit
        if ref:
            entry["source_ref"] = ref
        write_lock(lock, repo_root)
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chock add", description="Install a policy or skill from a catalog and compile it"
    )
    parser.add_argument("artifact_id", help="Policy or skill id, e.g. protect-main-branch")
    parser.add_argument("--repo", default=".", help="Target repo root")
    parser.add_argument("--from", dest="source", default=DEFAULT_CATALOG, help="Catalog URL or local path")
    parser.add_argument("--ref", default=None, help="Catalog branch or tag")
    parser.add_argument("--force", action="store_true", help="Replace an artifact that is already installed")
    parser.add_argument("--skip-compile", action="store_true", help="Copy only; do not compile or install hooks")
    parser.add_argument(
        "--verify-sha",
        default=None,
        metavar="SHA256",
        help="Refuse to install unless the fetched artifact hashes to this value",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    try:
        added = add(repo_root, args.artifact_id, args.source, args.ref, args.force, args.verify_sha)
    except (RuntimeError, FileNotFoundError, FileExistsError) as exc:
        print(f"chock add: {exc}", file=sys.stderr)
        return 1

    rel = added.path.relative_to(repo_root).as_posix()
    print(f"Added {args.artifact_id} to {rel}")

    # Printed, not merely stored. A catalog policy can carry guard scripts that run on every
    # commit, so the adopter should be able to see which commit they just trusted without
    # opening a lockfile.
    if added.commit:
        print(f"  from {args.source} at {added.commit}")
    print(f"  sha256 {added.sha256}")
    if not args.ref and added.commit:
        print(f"  (unpinned: this was the default branch. Pin with --ref, or --verify-sha {added.sha256})")

    if args.skip_compile:
        print("Run `chock sync --repo .` to compile it.")
        return 0

    # Compiling here is the point of the command. `recompile` also reconciles the index,
    # registry and lockfile, so the repo is left in a state that validates and commits.
    from chock.config import agents_from_config as _agents_from_config
    from chock.scaffold.recompile import BookkeepingError, recompile

    try:
        agents = _agents_from_config(repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        recompile(repo_root, agents, skip_hooks=True)
    except BookkeepingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    # After recompile, so it is not overwritten by the lockfile rebuild.
    record_provenance(repo_root, args.artifact_id, args.source, args.ref, added)
    print("Compiled. Run `chock sync --repo .` to activate commit-time enforcement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
