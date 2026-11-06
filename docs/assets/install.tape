# Chock — install clip
#
# A real run: install chock from PyPI, build chock.sh's Git hygiene preset for Claude Code
# from its builder share code, then run the built plugin's own PreToolUse hook on a
# `git commit --no-verify` payload. No Claude Code runs here, so the clip says the plugin's
# hook refuses, not that Claude Code does.
#
# Inputs come from install_clip.py, never typed: the version from pyproject.toml and the
# share code from chock.sh/data/site.json, encoded as the builder encodes it.
#
# Prerequisites: pipx, jq, network to PyPI, chock.sh and GitHub, and VHS
#   (https://github.com/charmbracelet/vhs). Run from the repo root.
# Render:
#   vhs docs/assets/install.tape     # writes docs/assets/install.gif

Output docs/assets/install.gif

Set Shell "bash"
Set FontSize 16
Set Width 1400
Set Height 760
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 24

# --- hidden setup: pipx's bin first on PATH; version and share code from install_clip.py.
# Plain assignments keep each exit status, so a failure skips `clear` and stays on screen. ---
Hide
Type `export PATH="$HOME/.local/bin:$PATH" && V="$(python3 docs/assets/install_clip.py version)" && CODE="$(python3 docs/assets/install_clip.py code)" && clear`
Enter
Sleep 3s
Show

# --- 1. Install chock from PyPI ---
Type "# 1. install chock from PyPI"
Enter
Type `pipx install "chock==$V"`
Enter
Wait@240s
Sleep 1s

# --- 2. Build the Git hygiene preset for Claude Code (no --apply: Claude Code is not here) ---
Type "# 2. build chock.sh's Git hygiene preset as a Claude Code plugin"
Enter
Type `chock install --selection "$CODE" --client claude-code 2>&1 | cut -c1-120 | sed -n '1,16p'`
Enter
Wait@240s
Sleep 4s

# --- 3. The plugin's own hook, run as its hooks.json declares it, in a scratch repo ---
Hide
Type "clear"
Enter
Show
Type "# 3. the plugin's hook refuses git commit --no-verify (its PreToolUse hook, no live Claude Code)"
Enter
Type `cd "$(mktemp -d)" && git init -q && PLUGIN=~/.chock/marketplace/claude-code/claude/chock-guardrails`
Enter
Type `HOOK=$(jq -r '.hooks.PreToolUse[].hooks[].command | select(contains("--member block-no-verify "))' "$PLUGIN/hooks/hooks.json")`
Enter
Type `echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git commit --no-verify -m wip"},"cwd":"'"$PWD"'"}' | CLAUDE_PLUGIN_ROOT="$PLUGIN" sh -c "$HOOK"`
Enter
Wait@60s
Sleep 6s
