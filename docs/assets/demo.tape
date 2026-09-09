# Chock — hero demo GIF
#
# Renders the secrets-demo loop: onboard a repo, adopt scan-secrets, get blocked
# committing a credential, then commit cleanly once the secret reads from the
# environment instead.
#
# Prerequisites: `chock` on PATH (pip install -e .) and VHS
#   (https://github.com/charmbracelet/vhs):  brew install vhs
# Render:
#   vhs docs/assets/demo.tape        # writes docs/assets/demo.gif

Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 640
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 24

# --- hidden setup: a throwaway repo on an (unborn) main branch. A fixed real path
# (not `mktemp -d`) so `chock init`'s own printed paths are stable and reviewable,
# never a per-run container temp path. ---
Hide
Type "rm -rf /work/demo && git -c init.defaultBranch=main init -q /work/demo && cd /work/demo"
Enter
Type "git config user.email demo@example.com && git config user.name Demo && clear"
Enter
Show

# --- 1. Onboard the repo, then adopt scan-secrets from the catalog ---
Type "chock init ."
Enter
Sleep 300ms
Type "chock add scan-secrets"
Enter
Sleep 300ms
Type "chock sync --repo ."
Enter
Sleep 300ms

# --- 2. Commit a credential → BLOCKED (hold 3.5s) ---
Type "echo 'AWS_KEY=AKIAIOSFODNN7EXAMPLE' > config.py && git add config.py" # pragma: allowlist secret -- AWS's own documented example key, never a real one
Enter
Sleep 150ms
Type 'git commit -m "add config"'
Enter
Sleep 3500ms

# --- 3. Read the key from the environment instead → passes (hold 3s) ---
Type `echo 'AWS_KEY = os.environ["AWS_KEY"]' > config.py && git add config.py`
Enter
Sleep 150ms
Type 'git commit -m "read key from env"'
Enter
Sleep 3000ms
