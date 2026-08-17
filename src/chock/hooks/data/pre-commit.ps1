# Chock deterministic validation hook for Windows PowerShell.
# Installed by: chock sync
$ErrorActionPreference = "Stop"

$repoRoot = git rev-parse --show-toplevel

# The interpreter that installed this hook is tried first; see the bash variant for why a
# bare `python` is wrong. chock normally lives in a virtualenv, and PATH usually
# points somewhere else.
$py = $null
foreach ($candidate in @("@CHOCK_PYTHON@", "python", "python3", "py")) {
    if (-not $candidate) { continue }
    & $candidate -c "import chock" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $candidate; break }
}

# Fail open, loudly: a missing interpreter means the check did not happen, which is not the
# same as a policy violation.
if (-not $py) {
    Write-Host "chock: no interpreter found that can import chock; validation skipped."
    Write-Host "chock: install it, then re-run 'chock sync'."
    exit 0
}

# --event commit: drift the staged diff never touched warns instead of blocking the
# commit that did not cause it. Plain `validate` and CI stay strict.
& $py -m chock check --only validate --repo "$repoRoot" --event commit
exit $LASTEXITCODE
