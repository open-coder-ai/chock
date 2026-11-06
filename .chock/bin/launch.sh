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
# A candidate must also answer the probe's token, so a program that merely exits 0 (`true`) is not taken for Python.
#
# On POSIX the probe is the runtime itself: its first statements (plain Python 3) exit unless Python is >= the
# minimum, then write a start marker to fd 9 (CHOCK_START_FD), which this shell reads back. A candidate with no
# marker (not found, 9009 or 127, a stub, Python too old, a SyntaxError) passes to the next; one that wrote it and
# then failed keeps its own exit. Windows (OS or MSYSTEM set) and `-m` keep the probe.
legacy=
case "${OS:-}|${MSYSTEM:-}" in *Windows_NT*|*"|"?*) legacy=1 ;; esac
[ "$runtime" = "-m" ] && legacy=1
# Only the marker path sets it (to 9); everywhere else an inherited value is cleared, so it never names an fd.
[ -n "$legacy" ] && { CHOCK_START_FD=; export CHOCK_START_FD; }
for candidate in "$configured" python3 python py; do
    [ -n "$candidate" ] || continue
    if [ -n "$legacy" ]; then
        if probed="$("$candidate" -c 'import sys; print("chock-python"); sys.exit(sys.version_info < (3, 11,))' </dev/null 2>/dev/null)" && [ "$probed" = "chock-python" ]; then
            exec "$candidate" -X utf8 "$runtime" "$@"
        fi
    elif command -v "$candidate" >/dev/null 2>&1; then
        exec 3>&1
        marker="$(CHOCK_START_FD=9 "$candidate" -X utf8 "$runtime" "$@" 9>&1 1>&3 3>&-)"
        status=$?
        exec 3>&-
        [ "$marker" = "chock-python" ] && exit "$status"
    fi
done
echo "chock: no working Python 3.11+ found (tried chock.python, python3, python, py), so this hook cannot check anything. Install Python, or point chock at one: git config chock.python /path/to/python" >&2
exit 2
