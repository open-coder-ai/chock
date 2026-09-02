"""Facade: single import surface for this activity package."""

import yaml

from chock.registry.cli import (
    cmd_get,
    cmd_init,
    cmd_list,
    cmd_resolve,
    cmd_scan,
    main,
)
from chock.registry.core import (
    REGISTRY_DIR,
    REGISTRY_FILE,
    REGISTRY_FORMAT_VERSION,
    RegistryEntry,
    SkippedManifest,
    _hash_file,
    compute_script_hashes,
    discover_manifests,
    ensure_registry_dir,
    entry_from_manifest,
    extract_dependencies,
    load_registry,
    registry_path,
    repo_root,
    resolve,
    save_registry,
    scan,
)
