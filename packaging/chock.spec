# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a one-file chock executable.

Build:
    pip install -e '.[build]'
    pyinstaller packaging/chock.spec

The resulting dist/chock (or dist/chock.exe on Windows) bundles the
CLI, all data files (packs, schemas, hooks), and can run `chock init .` in a
fresh directory with no Python on PATH.
"""

from PyInstaller.building.build_main import Analysis, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


block_cipher = None

# Ship every data file under src/chock: packs, schemas, hook scripts, etc.
datas = collect_data_files("chock")
# agentseam >= 0.2.0 loads data/vendors/*.json at import; without these the frozen
# binary dies in `chock init` with FileNotFoundError from agentseam._data.load().
datas += collect_data_files("agentseam")
# Make importlib.metadata.version('chock') work in the frozen binary.
datas += copy_metadata("chock")
# Fallback for version lookup: the root pyproject.toml travels with the binary.
datas += [("../pyproject.toml", ".")]
# `gate/runner.py` is vendored into consumer repos as .chock/bin/gate.py, so it must
# exist on disk as READABLE SOURCE at runtime — not just as compiled bytecode inside the
# binary. collect_data_files() skips .py by design, so add it explicitly or `chock
# init` fails with FileNotFoundError from vendor_runner().
datas += [("../src/chock/gate/runner.py", "chock/gate")]

# The CLI imports subcommand modules by string; make sure PyInstaller includes them.
hiddenimports = collect_submodules("chock")


a = Analysis(
    ["../src/chock/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="chock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
