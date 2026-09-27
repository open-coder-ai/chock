#!/bin/sh
# chock hook launcher. Every agent hook chock writes runs:
#   git -c "alias.chock-hook=!sh .chock/bin/launch.sh" chock-hook <runtime.py> [args...]
# git runs the alias from the repository's top level under its own sh (bash, PowerShell
# and cmd.exe all pass that string through unchanged), so relative paths resolve and no
# absolute interpreter path is ever committed. This script picks the first Python that
# actually runs: `chock.python` (written into .git/config by `chock sync`), then PATH.
# A candidate must execute, not merely exist: Windows' python3.exe Store alias exists and
# exits 9009. With no working Python it refuses (exit 2) and says why -- never allows.
runtime="$1"
shift
configured="$(git config --get chock.python 2>/dev/null)"
if [ -n "$configured" ] && [ -f "$configured" ]; then
    exec "$configured" -X utf8 "$runtime" "$@"
fi
for candidate in python3 python py; do
    if "$candidate" -c 'import sys; sys.exit(sys.version_info < (__MIN_PYTHON__,))' </dev/null >/dev/null 2>&1; then
        exec "$candidate" -X utf8 "$runtime" "$@"
    fi
done
echo "chock: no working Python __MIN_PYTHON_TEXT__+ found (tried chock.python, python3, python, py), so this hook cannot check anything. Install Python, or point chock at one: git config chock.python /path/to/python" >&2
exit 2
