#!/bin/sh
# chock hook launcher. Every agent hook chock writes runs:
#   git -c "alias.chock-hook=!test -f <this> || { ...; exit 2; }; sh <this>" chock-hook <runtime.py> [args...]
# git runs the alias from the repository's top level under its own sh (bash, PowerShell
# and cmd.exe all pass that string through unchanged), so relative paths resolve and no
# absolute interpreter path is ever committed. This script picks the first Python that
# actually runs: `chock.python` (written into .git/config by `chock sync`), then PATH.
# A candidate must execute, not merely exist: Windows' python3.exe Store alias exists and
# exits 9009. With no working Python it refuses (exit 2) and says why -- never allows.
runtime="$1"
shift
configured="$(git config --get chock.python 2>/dev/null)"
# The recorded interpreter is probed like the rest: a venv whose base Python was removed
# still exists, and exec'ing it exits non-zero without a verdict, which agents let through.
for candidate in "$configured" python3 python py; do
    if [ -n "$candidate" ] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11,))' </dev/null >/dev/null 2>&1; then
        exec "$candidate" -X utf8 "$runtime" "$@"
    fi
done
echo "chock: no working Python 3.11+ found (tried chock.python, python3, python, py), so this hook cannot check anything. Install Python, or point chock at one: git config chock.python /path/to/python" >&2
exit 2
