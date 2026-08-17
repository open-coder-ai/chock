# Chock — hero demo GIF
#
# Renders the killer 15-second loop: onboard a repo, get blocked committing to
# main, then succeed on a feature branch.
#
# Prerequisites: `chock` on PATH (pip install -e .) and VHS
#   (https://github.com/charmbracelet/vhs):  brew install vhs
# Render:
#   vhs docs/assets/demo.tape        # writes docs/assets/demo.gif

Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 20
Set Width 1100
Set Height 660
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

# --- hidden setup: a throwaway repo on an (unborn) main branch ---
Hide
Type "cd $(mktemp -d)"
Enter
Type "git -c init.defaultBranch=main init -q demo && cd demo && clear"
Enter
Show

# --- 1. Onboard the repo, then adopt a guardrail from the catalog ---
# init is wiring-only (the framework ships no policies), so the blocked commit
# below only happens after `add` + `sync` — the same 3-command flow the README shows.
Type "chock init ."
Sleep 600ms
Enter
Sleep 3s
Type "chock add protect-main-branch"
Sleep 500ms
Enter
Sleep 2500ms
Type "chock sync --repo ."
Sleep 500ms
Enter
Sleep 2500ms

# --- 2. Try to commit straight to main → BLOCKED ---
Type "echo 'oops' > hotfix.txt && git add hotfix.txt"
Enter
Sleep 800ms
Type 'git commit -m "quick fix straight to main"'
Sleep 500ms
Enter
Sleep 3500ms

# --- 3. Do it right on a feature branch → allowed ---
Type "git checkout -b feature/x"
Sleep 300ms
Enter
Sleep 1s
Type 'git commit -m "safe on a feature branch"'
Sleep 500ms
Enter
Sleep 3500ms
