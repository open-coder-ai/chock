# Chock — hero demo GIF: five agent mistakes, five refused commits
#
# Adopt five enforced-at-commit security guards from the catalog, then replay the
# mistakes a coding agent actually makes -- a hard-coded cloud key, an MCP server at
# @latest, a wildcard IAM grant, model output piped into os.system, a Trojan Source bidi
# override -- and watch each commit get refused. The last scene is the fix committing
# cleanly. Every line of output is the real gate's, captured by running the commands.
#
# Prerequisites: `chock` on PATH (pip install -e .) and VHS
#   (https://github.com/charmbracelet/vhs):  brew install vhs
# Render:
#   vhs docs/assets/demo.tape        # writes docs/assets/demo.gif

Output docs/assets/demo.gif

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 16
Set LineHeight 1.3
Set Width 1200
Set Height 680
Set Padding 36
Set WindowBar Colorful
Set BorderRadius 10
Set TypingSpeed 25ms
Set WaitPattern /❯/
Set WaitTimeout 60s
Set Theme { "name": "chock", "background": "#0D1626", "foreground": "#E8EEF6", "selection": "#1F3254", "cursor": "#D9B45C", "black": "#0A1220", "red": "#F29B8A", "green": "#9ED3A6", "yellow": "#D9B45C", "blue": "#7FB8F0", "magenta": "#C9A8F0", "cyan": "#86D3DB", "white": "#C9D4E2", "brightBlack": "#5A6B80", "brightRed": "#F7B3A6", "brightGreen": "#B8E3BE", "brightYellow": "#F0CF7D", "brightBlue": "#9ECBF5", "brightMagenta": "#DAC2F5", "brightCyan": "#A6E1E7", "brightWhite": "#FFFFFF" }

# --- hidden setup: a throwaway repo on an (unborn) main branch at a fixed path, onboarded
# with `chock init`, a gold prompt, and a person's shell rather than an agent's, so the
# output reads the same wherever the tape is rendered. EXAMPLE_KEY is AWS's documented
# example key, assembled here so this file carries no key-shaped literal. ---
Hide
Sleep 1s
Type `G=$(printf '\342\235\257'); X=$(printf '\342\234\227')`
Enter
Sleep 300ms
Type `PROMPT_COMMAND='if [ $? = 0 ]; then PS1="\[\e[33m\]$G\[\e[0m\] "; else PS1="\[\e[1;31m\]$X commit refused (exit 1)\[\e[0m\]\n\[\e[33m\]$G\[\e[0m\] "; fi'`
Enter
Sleep 500ms
Type `export EXAMPLE_KEY="AKIA$(printf 'IOSFODNN7%s' EXAMPLE)"`
Enter
Sleep 300ms
Type "unset CLAUDECODE AI_AGENT; rm -rf /work/demo && git -c init.defaultBranch=main init -q /work/demo && cd /work/demo"
Enter
Wait
Type "git config user.email demo@example.com && git config user.name Demo && chock init . >/dev/null"
Enter
Wait@30s
Type "clear"
Enter
Wait
Show

# --- 1. Adopt five guards from the catalog ---
Type "# adopt five security guards from the catalog, compile them into git hooks"
Enter
Type "chock add scan-secrets >/dev/null"
Enter
Wait@60s
Hide
Type `for g in block-unpinned-agent-components block-wildcard-iam block-unsafe-code-execution block-invisible-unicode; do chock add $g >/dev/null; done`
Enter
Wait@120s
Type "clear"
Enter
Wait
Show
Type "chock sync --repo . >/dev/null && git add -A && git commit -qm 'adopt guards' && ls .agents/policies/"
Enter
Wait@60s
Sleep 2500ms
Hide
Type "clear"
Enter
Wait
Show

# --- 2. A hard-coded cloud key -> refused ---
Type "# 1/5  the agent hard-codes a cloud key (AWS's documented example key)"
Enter
Type `echo "AWS_KEY=$EXAMPLE_KEY" > config.py && git add . && git commit -qm config`
Enter
Wait
Sleep 2800ms
Hide
Type "git reset -q && rm -f config.py && clear"
Enter
Wait
Show

# --- 3. An MCP server at @latest -> refused ---
Type "# 2/5  the agent wires an MCP server at @latest"
Enter
Type `echo '{"mcpServers":{"gh":{"command":"npx","args":["github-mcp@latest"]}}}' > .mcp.json` # pragma: allowlist unpinned -- the scene exists to show the gate refusing it
Enter
Wait
Type "git add . && git commit -qm mcp"
Enter
Wait
Sleep 2800ms
Hide
Type "git reset -q && rm -f .mcp.json && clear"
Enter
Wait
Show

# --- 4. A wildcard IAM grant -> refused ---
Type "# 3/5  the agent grants itself Action * on Resource *"
Enter
Type `echo '{"Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}' > iam.json` # pragma: allowlist broad-privilege -- the scene exists to show the gate refusing it
Enter
Wait
Type "git add . && git commit -qm iam"
Enter
Wait
Sleep 2800ms
Hide
Type "git reset -q && rm -f iam.json && clear"
Enter
Wait
Show

# --- 5. Model output into os.system -> refused ---
Type "# 4/5  the agent pipes model output into os.system"
Enter
Type `printf 'import os\nos.system(llm_reply)\n' > tool.py && git add . && git commit -qm tool` # pragma: allowlist exec -- the scene exists to show the gate refusing it
Enter
Wait
Sleep 2800ms
Hide
Type "git reset -q && rm -f tool.py && clear"
Enter
Wait
Show

# --- 6. A Trojan Source bidi override -> refused ---
Type "# 5/5  a pasted snippet hides a bidi override (Trojan Source, CVE-2021-42574)"
Enter
Type `printf 'role = "user\342\200\256"  # admin\n' > auth.py && git add . && git commit -qm auth`
Enter
Wait
Sleep 2800ms
Hide
Type "git reset -q && rm -f auth.py && clear"
Enter
Wait
Show

# --- 7. The fix commits cleanly ---
Type "# the fix: read the key from the environment"
Enter
Type `echo 'AWS_KEY = os.environ["AWS_KEY"]' > config.py && git add . && git commit -qm 'read key from env'`
Enter
Wait
Type "git log --oneline -1"
Enter
Wait
Sleep 3500ms
