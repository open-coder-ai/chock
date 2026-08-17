# Packaging

Local builds for wheels and the frozen single-file binary.

## Wheel

```bash
pip install -e '.[build]'
python -m build
```

Inspect the wheel to confirm data files are present:

```bash
unzip -l dist/*.whl | grep -E '_skills|schemas/'
```

## Single binary

```bash
pyinstaller packaging/chock.spec
```

Produces `dist/chock` (Linux/macOS) or `dist/chock.exe` (Windows).

Smoke test in a clean directory:

```bash
mkdir -p /tmp/ac-smoke && cd /tmp/ac-smoke
git init --quiet
/path/to/dist/chock init . --skip-hooks
```

This proves the frozen bundles include `packs/`, `validation/schemas/`, and
`hooks/data/`, and that `init` can run without a Python interpreter on PATH.
