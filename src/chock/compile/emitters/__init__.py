"""Emitters that translate policy manifests into target-surface enforcement artifacts."""

from chock.resources import package_data_dir

#: Shared template/data directory for every emitter in this package.
DATA_DIR = package_data_dir("chock.compile.emitters", "data")
