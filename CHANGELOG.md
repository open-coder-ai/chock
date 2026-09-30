# Chock changelog

## Unreleased

- **Gate-log report fixes.** `--by rule` credited each rule with the record's total new findings,
  so two rules in one refusal were each shown every finding; each rule now counts its own. Ties in
  the top-files list are broken by path, so the report is the same on every run. `chock status`
  refuses `--json` and `--format md` unless `--only log` is the only section, since mixing the
  policy or registry text into them made the output unparseable. A markdown cell escapes `\`, `[`
  and `]`, so a log value can no longer render as a link, and the text report replaces control
  characters, so a log line cannot send escape sequences to the terminal. `--since` takes 1 or
  more days.
- **A findings refusal leads with the finding.** A script gate's refusal put the policy's long
  message first and the findings last, so an agent read the boilerplate before the `path:line:`
  that mattered. Findings now come first, then a one-line summary, then the policy message. A
  tool-use refusal (and the turn's end) carries the findings and one line on how a person
  customises the rules, with no policy text. At tool use and for an agent's commit, a sentence
  telling the reader to write `chock: allow` is replaced by "ask a person to review it; an agent
  cannot add the waiver", since an agent's waiver is never honoured; a person's commit and CI
  keep the sentence.
- **`chock status --only log` groups and reports.** `--by policy|rule|agent|event` counts blocked,
  asked, warned, `would_block` (its own column once a record carries it), new against baseline
  findings, agents and the top three files per group; `--format md` prints a paste-able markdown
  summary. The log is read locally and only ids, counts and the paths in `matches` are shown, never
  file contents. `chock status` now forwards `--policy`, `--since` and `--json` to the log, which
  only `python -m chock.gatelog` accepted. The runner records `agent` (the `agent_signal` marker,
  when one is set) on every git and script-hook outcome, and `rules` (rule id to count of new
  findings) when a script finding names its optional `rule`; older records group under "unknown".
- **Runtime bytecode stays out of git.** `.chock/bin/` holds Python the hooks import, so running a
  hook wrote `__pycache__` there, and the `!.chock/bin/**` rule that keeps the runtime tracked
  re-included it: every adopter saw untracked bytecode after the first hook ran. `chock sync` now
  appends ignores for `__pycache__/` and `*.pyc` under `.chock/bin/` and `.chock/compiled/`, after
  the negations, the way it already did for `.agents/policies/`.
- **A packaged skill's gate note states the gate's action.** Every Claude, Codex, Copilot, Cursor
  and Devin package with a tool-use gate said the policy "is enforced in this client", including a
  gate that only asks or warns. The note now reads "asks the person before the action proceeds" or
  "warns, and does not block" for those gates, and keeps "is enforced" for a gate that blocks.
- **SKILL.md footers say what chock actually enforces.** The footer was picked by artifact type
  alone, so a rule with a command guard, a git script or a gate still read "stays advisory even
  when compiled", and a hook whose gate only warns, or binds only at tool use, still read "becomes
  a git hook that exits non-zero". The footer now keeps "advisory" for the skill alone and names
  what `chock` compiles from the manifest: a guard or git script can refuse, a gate blocks, asks
  or warns, at the surfaces it declares.
- **Plugin keywords use a compliance entry's control id.** A dict-shaped `owasp_asi` entry such
  as `{control: ASI01, coverage: partial}` was stringified whole into `plugin.json` `keywords`.
  The keyword is now the control id, lowercased.
- **The MCP gateway judges a `content_regex` gate inside its scope.** The gateway matched every
  string argument of a tool call, so `pin-github-actions` (bounded to `.github/workflows/*` and
  `.github/actions/*`) refused a README written through an MCP filesystem tool for quoting
  `uses: a/b@v4`. The gateway spec now carries `applies_to.paths`. A call's write target is read
  from the same argument keys the session log uses (`file_path`, `filePath`, `path`,
  `notebook_path`, `target_file`, `TargetFile`). Content is judged only at an in-scope path,
  `forbidden_path_regex` applies to that path, and a path-bounded gate does not judge a call that
  names no path. Gates with no bound behave as before. `allowlist_pragma` stays unhonoured there:
  a waiver the agent writes into its own call must never lift the block.
- **The SKILL.md advisory line shows the gate's paths and no longer cuts a regex mid-pattern.**
  `paths=<applies_to globs>` follows the gate kind; a regex param (`*_regex`, `*_pattern`,
  `*_pragma`) longer than 60 characters renders as `<name>(regex)`, shorter ones in full.
- **`chock sync --check` compares committed agent-hook configs.** It compared only the compiled
  tree, so a vendor hook config still naming a guard script a later sync had replaced passed the
  check while the gate failed closed and denied every shell command. It now runs the real
  installers on a scratch copy of each wired vendor's committed config and reports `differs`
  where chock's own entries disagree; foreign entries and list order are ignored. The repo's own
  hook configs, coverage and `chock_session.py` runtime are regenerated.

## 0.15.2 — Script hashes skip Python bytecode

- **Script hashes skip Python bytecode.** A `.py` guard that imports a sibling package makes
  Python write `__pycache__` into `implementations/` the first time it runs. The registry scan
  and the determinism check hashed those `.pyc` files, so `chock registry scan` drifted as soon
  as `chock check --only evals` had run a guard. Both now hash only shipped files, through one
  predicate. The shellcheck sweep also leaves `*.py` guards out: their sh trampoline header made
  discovery by shebang hand their Python bodies to shellcheck.

## 0.15.1 — Plugins ship their guard's shared packages

- **Plugins ship their guard's shared packages.** The Claude, Codex, Copilot, Cursor and Devin
  plugins copied only `implementations/<id>.py`, so a guard that imports a sibling package such
  as `chock_shellparse` crashed with `ModuleNotFoundError` and asked instead of denying. Each
  plugin now also carries every directory under `implementations/` that has an `__init__.py`
  (its `.py` files, recursively, no `__pycache__`) beside the guard.

## 0.15.0 — Script gates judge only the findings a change introduces

- **Script gates judge only the findings a change introduces.** A `kind: script` gate that prints
  `{"findings": [{"key", "path", "line", "message"}]}` on stdout is run again on the baseline text
  (`"baseline": true`; HEAD at commit and Stop, the range base at push and ci, the disk before the
  write at PreToolUse), and only findings whose key the baseline lacks count, including a
  violation created by deleting a line. No new findings allows; otherwise the change-run's exit
  code decides and the reason lists just the new findings. A script that prints no findings
  document behaves as before. The two runs share the 30s budget. The gate log records
  `new_findings` and `baseline_findings`. Agent-event HEAD reads now resolve from `repo_root`, so
  a root below the git top-level finds its baseline (and a `content_regex` waiver already in
  HEAD). Vendored runner resynced; run `chock sync`.

## 0.14.0 — Gates on any tool call that can ask or warn, agent commits detected, and guards that run on any command

- **Eval cases can expect `ask` and `warn`.** `execute.expect` is now `allow | block | ask | warn`.
  At the agent events (`tool_use`, `stop`) the gate runner's exit 3 replays as `ask` and 4 as `warn`
  (a Stop `ask` warns, as it does live); at `commit` and `push` an `ask` gate's refusal reads as
  `ask`, not `block`, and a `warn` gate as `warn`; a `pre-commit`, `pre-push` or `commit-msg`
  script's exit 3 is `ask` and 4 is `warn`. A gate's declared `action` still caps a script's
  verdict. An `expect: block` case whose gate asks or warns now fails, saying so. The runner gains
  `judge()` (exit code and verdict); `run()` and every exit code are unchanged. Vendored runner
  resynced; run `chock sync`.
- **A `tool_call` script asks and warns too.** Exit `3` asks the person and exit `4` warns, as at
  every other event, and the gate's declared `action` caps the verdict and any refusal: a warn
  gate never denies a tool call, an ask gate never denies outright.
- **A gate can warn or ask instead of blocking.** `hook.gate.action` was documented as
  `block | verify | warn`, the schema accepted only `block`, and the runner ignored it. It is now
  `block` (default), `ask` or `warn`, and `verify` (a value of `enforcement`) is refused. `warn`
  never blocks: at commit, push and ci the reason is printed (a `::warning::` annotation in CI) and
  the exit is 0; in the agent Claude Code gets it as PreToolUse `additionalContext` (no
  `permissionDecision`, so its permission prompt is untouched), other vendors get stderr and the gate
  log, and at Stop it is a message, never a block. `ask` asks the person in the agent
  (`permissionDecision: ask` where the vendor honours one, a deny elsewhere); at commit and push it
  refuses unless `CHOCK_ALLOW=<policy-id>[,...]` is set on that command and it is not an agent commit;
  in CI and at Stop it is a warning; the mcp-gateway blocks it. A `script` gate chooses its own
  verdict by exit code (0 allow, 1 block, 3 ask, 4 warn) under its declared action; an exit 1 with no
  words or a crash signature is undecided and takes the declared action. Script-backed hooks read
  exit 3 as ask and 4 as warn, through the runner, which a script-only policy now vendors. The gate
  log records `warn` and `ask`, and `chock status --only log` counts them. A policy whose only
  mechanism warns is no longer credited as enforcing. Vendored runtimes and runner resynced; run
  `chock sync`.
- **An agent's commit is detected without opt-in.** `CLAUDECODE=1`, a non-empty `AI_AGENT` (both set
  by Claude Code's Bash tool and witnessed reaching a git hook), or any variable named under
  `agent_commit_env:` in `.chock/config.yaml` now marks a commit as an agent's, as `CHOCK_AGENT_COMMIT`
  always did. `CHOCK_AGENT_COMMIT=0` wins over every marker, for a person's git in an agent's
  terminal. Codex, Cursor and Copilot markers stay unverified. A person whose shell exports
  `CLAUDECODE` or `AI_AGENT` now sees their own waivers ignored until they set `CHOCK_AGENT_COMMIT=0`.
  Eval cases are judged as a person's commit whoever runs them.
- **Installing hooks no longer erases a guard's coverage.** `chock install-hooks` auto-compiled
  any hook policy without git-hook output, but a guard-only or `tool_use`-only policy has none by
  design, so the recompile rewrote its coverage as a git-hook-only view and every agent read
  `none`. A policy with any compiled surface is now left alone; a true drop-in still compiles.
- **A hook can carry both a `gate` and a `script`.** `hook` was exactly one of the two, so a
  policy with a pre-commit script could not also gate the write path. The schema now takes at
  least one; the git-hook emitter compiles both (the script's event shims plus the gate's
  `gate.json` and shims), the tool_use surfaces compile the gate, and coverage is credited per
  surface as before. DET-5 still pins `hook.script.on` to the scripts on disk. A gate and a script
  may not both run at the same git event (`manifest_script_events`): they would share one shim.
- **`test_integrity` honours its waiver at agent events the way `content_regex` does.** At
  `tool_use` and an agent's commit the `allowlist_pragma` was ignored outright; now a waiver counts
  only when that line is already in HEAD, and a waiver the agent adds still does not.
- **The eval runner resolves the command guard by name and replays more than commit and push.**
  The guard is `implementations/<id>.sh|.py` (else the legacy map), so helper modules and gate
  scripts are never taken for it, and a `.py` guard runs under Python. An `execute` case may set
  `event: tool_use` (`pre-tool-use`) or `stop` with `writes` (and `head_files`, `added`), replayed
  through the real gate runner at that event. It may also set `event: pre-commit`, `pre-push` or
  `commit-msg` to run the policy's event script in a staged throwaway repo (`files`, `message`,
  `stdin`); exit 0 allows, a refusal blocks, a crash is an error. These cases count as executable,
  not tier 3. Vendored runner resynced.
- **A gate can judge any tool call by its name.** `"on": [tool_call]` with `params.tools` (globs such
  as `mcp__Firecrawl__*`, `WebFetch`, `mcp__*`) runs a `content_regex` (over the JSON-serialised tool
  input) or `script` gate at PreToolUse; a script gets `{"event": "tool_call", "repo_root", "tool",
  "input", "session"}` and answers by exit code, allow or block. It is emitted for Claude Code, Codex
  CLI, Cursor, Gemini CLI and Copilot, the vendors whose vendor facts record a tool vocabulary;
  Antigravity, Devin, Grok, Tabnine and Windsurf get no entry and coverage credits them nothing for it.
  Run `chock sync` to pick it up; vendored runtimes resynced.
- **A gate can guard writes outside the repository.** A gate declaring `outside_repo: [<glob>]`
  (absolute, or starting with `~`, expanded per machine; Windows paths compare the Windows way)
  receives writes to matching absolute paths, e.g. `~/.claude/memory/*`; every other outside write is
  still ignored. Judged at PreToolUse only: Stop reads the worktree through git and cannot see them.
- **Script gates can ask what happened earlier in the session.** Hooks for a `tool_call` script gate
  append a record per tool call (tool, a path, command first line or URL without query, outcome) to
  `.chock/state/<session_id>.jsonl`, last 500 kept, files older than 7 days pruned, never file
  contents or environment values. Scripts receive `"session": {"id", "log_path", "tool_use_id"}` and can
  import the vendored stdlib helper `chock_session.py`. `chock sync` adds `.chock/state/` to
  `.gitignore`. Nothing leaves the machine; the format is in `spec/session-log.md`.

- **In-agent gates judge what changed, and honour committed waivers.** At `tool_use` (PreToolUse
  and Stop) a waiver already in HEAD is now honoured, so a line a human waived and committed no
  longer blocks the agent forever; a waiver the edit or turn adds is still ignored. At Stop the
  added lines are the diff of the file on disk against HEAD (a new file is all added), and a
  whole-file Write is diffed against the current disk file, so an old violation in a touched
  file no longer blocks every turn end. The baseline is the disk at PreToolUse and HEAD at Stop.
  `dependency_allowlist` and `test_integrity` now run at `tool_use` too, so a policy declaring
  `"on": [commit, tool_use]` for them gets in-agent gates. Commit, push and ci are unchanged.
  Vendored runner resynced.
- **A policy can carry a shell guard and a content gate together.** A policy with an
  `implementations/<id>.sh|.py` guard and a `hook.gate` whose `"on"` includes `tool_use` used to get
  only the guard at the write path; the gate was dropped. Both now compile, on the pre-tool-use
  surface for claude_code, cursor, codex and the other vendors with a recorded write vocabulary,
  and in the Copilot hooks file, each in its own fragment so neither overwrites the other. A policy
  reads as installed for an agent only when every compiled entry is present, so a missing gate entry
  no longer earns the credit the guard's entry alone used to. Run `chock sync` to pick it up.
- **A `rule` can carry a `hook.gate`.** The gate is the same control on a second surface, as
  `hook.script` already was: the rule text stays the ambient line and the INDEX entry, and the gate
  compiles to the git-hook, pre-tool-use, stop and ci surfaces as an `artifact: hook` gate does.
  A rule with a payload other than `rule` and one hook is still a `manifest_payload` error.
- **Script-backed hooks can run at `commit-msg`.** `hook.script.on` accepts `commit-msg`, backed by
  `implementations/<id>-commit-msg.{sh,py}`. `chock sync` installs a `commit-msg` dispatcher beside
  `pre-commit` and `pre-push`; git's message-file path arrives as `argv[1]` and the exit code is the
  verdict. `chock check` pins the declaration to the script both ways (DET-5), and the eval runner
  does not treat the script as a command guard.
- **A command guard now runs even when the command will not parse, and a crash is no longer read as a block.**
  A trailing backslash, an unbalanced quote or PowerShell quoting (`Remove-Item -Recurse C:\`) made
  `shlex.split` raise, which asked the user for every guard and never let a guard's raw-string branch
  run. The guard now always runs: argv is a whitespace split when `shlex` fails (`CHOCK_ARGV_FALLBACK=1`
  says so; the POSIX split is unchanged when it succeeds) and `CHOCK_RAW_COMMAND` is the exact command.
  Guards also get `CHOCK_TOOL` (`bash`, `powershell`, `shell` or `unknown`) from the hook payload's tool
  name. An exit 1 is a block only when the guard printed a reason: exit 1 with empty output, a Python
  traceback or a shell syntax error is a crash and asks, like any other non-zero exit. Guards that print
  a reason and `exit 1` still block. Vendored runtimes resynced; the contract is in
  `spec/script-backed-gates.md`.
- **`--no-registry-check` also skips script integrity.** DET-2 compares a policy's script hashes
  with the registry, so it is a registry check, but it ran even when the caller asked for none.
  That was already true of hook artifacts; since a rule's hook is now hashed too, a catalog
  validating its own source policies (which have no registry entry) was refused. The default
  still runs DET-2.

## 0.13.0 — Copilot gates the content an agent writes, and a policy reaches every clone

- **An agent's commit cannot waive its own refusal.** A `// chock: allow <rule>` waiver is a
  reviewer's decision, but at commit the gate honoured every waiver in the staged text, so an
  agent that ran `git commit` itself could add the waiver after a refusal and pass (seen with
  Copilot in VS Code). With `CHOCK_AGENT_COMMIT` set in the committing shell, the pre-commit gate
  now judges the commit at the event `agent-commit`, outside the waivable events: a waiver the
  commit adds is ignored, one already in HEAD still counts, and the refusal says so. Script
  gates receive `agent-commit` as `event`. Human commits are unchanged. No vendor environment
  variable is detected automatically, as none is verified to reach a git hook. Push and CI are
  unchanged. Vendored runner resynced.
- **A policy's `build/` folder now reaches every clone.** Policies install under
  `.agents/policies/`, and a policy can ship a Python package with a `build/` sub-package (the
  java-security policy does). Java and Gradle repos, and many global gitignores, ignore `build/`,
  so that folder was never committed and a fresh clone, CI checkout or Codex worktree crashed the
  gate with `ImportError: cannot import name 'build'` -- after which the hook refused every edit.
  `chock init` and `chock sync` now append `!.agents/policies/` and `!.agents/policies/**` to
  `.gitignore`, the same way they already keep `.chock/bin/` tracked. `__pycache__/` and `*.pyc`
  under the policies stay ignored, and your own top-level `build/` stays ignored too. Run
  `chock sync` once and commit the missing folder.
- **Copilot and VS Code get in-editor enforcement for content gates.** A policy whose gate judges
  the files a write leaves behind (the catalog's `java-security`, `pin-github-actions`) used to
  read `enforced-at-commit` for `copilot` and `vscode`, because chock's own `.github/hooks/chock.json`
  only carried shell-command guards. It now also carries, per content gate, a `PreToolUse` entry over
  `Edit|Write` (the tool names seen live: `Edit {path, old_str, new_str}`, `Write {path, file_text}`)
  and a `Stop` entry that re-reads what the turn left on disk, both in the same entry shape as the
  guard entries (`bash`, `command`, `powershell`, `windows`, `timeout`, `timeoutSec`) and both running
  the vendored `vscode_copilot` runtime in `--gate` mode. `chock sync` reports the grade the matrix earns
  once they are installed, and `enforced-at-commit` until then. `Stop` is registered alone: Copilot fires
  `agentStop` beside it, and registering both would run the gate twice.
- **The Copilot runtime answers in the top-level dialect it was seen honouring.** A `PreToolUse` deny
  now carries top-level `permissionDecision`/`permissionDecisionReason` (a top-level deny stopped an
  `Edit` in VS Code agent mode, 2026-09-28) beside agentseam's nested `hookSpecificOutput`, and a `Stop` block carries
  top-level `decision`/`reason` beside its nested one. Which of the two Stop forms Copilot reads is not
  yet isolated, so both are written; no other vendor's answer changes.
- **agentseam 0.3.5.** Its Copilot adapter reads a `Write` call's `file_text` as the file's
  content, parses the camelCase `agentStop` payload as a turn end rather than a tool call, and
  writes `bash` and `powershell` keys in the hook entries it generates. Vendored runtimes and
  their goldens are re-rendered; the next `chock sync` rewrites `.chock/bin`.

## 0.12.1 — Plugin hooks that start on Windows

- **A plugin's hook starts on Windows.** Every plugin package (claude, cursor, codex, copilot,
  devin) ran its runtime with a bare `python3`, which on Windows is often missing or the Store
  stub that exits 9009; the hook failed to start and Claude Code let the command run. Each
  package now ships `scripts/launch.sh` beside its runtime, and its hook runs it through git's
  own sh (`git -c "alias.chock-sh=!sh" chock-sh "<plugin root>/scripts/launch.sh" ...`), under
  bash, PowerShell or cmd.exe alike. The launcher starts the first of `python3`, `python` and
  `py` that actually runs Python 3.11+, or refuses with exit 2. The plugin descriptions now say
  it needs git and a Python 3.11+, not python3.

## 0.12.0 — Hooks that run on every machine and refuse when they cannot judge

- **Agent hooks run on every machine, not just the one that last ran `chock sync`.** Hook
  commands in committed agent configs named that machine's absolute Python (even a deleted
  temporary one), so on any other clone every hook failed to start -- and Claude Code and Codex
  treat that as non-blocking, so the gate silently did nothing. Every in-agent entry is now
  `git -c "alias.chock-hook=!sh .chock/bin/launch.sh" chock-hook .chock/bin/<agent>.py ...`,
  read identically by bash, PowerShell and cmd.exe; git runs it from the repository root, so a
  session started in a subdirectory is guarded too. The committed `.chock/bin/launch.sh` runs
  `git config chock.python` (written to the clone's local config by `chock sync`) or the first
  `python3`/`python`/`py` that actually runs Python 3.11+ (the recorded one is probed too: a venv
  whose base Python is gone still exists), and with none refuses (exit 2) with a fix-it message.
  With no launcher at git's top level (a nested repository, an unsynced clone) the command
  refuses the same way; bash-as-`sh` used to exit 127 there, which agents let through. Sync
  records its interpreter only when `--repo` is a repository's top level. Cursor's shell and pre-tool entries now set `failClosed`. Re-running
  `chock sync` elsewhere is a zero diff; entries in the old form are replaced at the next sync.
  `chock check` reports a missing or git-ignored launcher as a dangling hook target.

- **agentseam 0.3.4.** Claude Code's shell guards also match its `PowerShell` tool (Windows' default
  shell tool, where `Bash`-only guards never fired); Codex gets a pre-write gate on `apply_patch`;
  a policy handler's stray stdout can no longer turn a deny into an allow; Copilot CLI's camelCase
  payloads are read. A chock helper no longer shadows agentseam's Copilot input reader inside the
  single-file runtime (which made every Copilot guard allow), and a test now fails on any such clash.
  Copilot's PowerShell entries keep the hook's exit code, and refuse (exit 2) when no command ran at
  all: a bare `exit $LASTEXITCODE` exits 0 then, which is an allow.
- **A gate judges an absolute path as the repository file it names.** Claude Code and Cursor send
  `file_path` absolute; scoped gates matched repo-relative globs against it, so `pin-github-actions`
  allowed `actions/checkout@v4` written by the agent. Paths are made repo-relative first (drive
  letters, backslashes and case folded on Windows; a path outside the repo stays out of scope). A
  write through a symlinked folder is judged under its target's path as well as the one named.
- **A guard that cannot run asks instead of allowing.** No usable bash, or a command `shlex` cannot
  parse (`rm -rf / #'`), used to allow. Both now ask, naming what to install. Bash is found from
  `git` (Git for Windows' `bin\bash.exe` first, never System32's WSL launcher or a WindowsApps
  stub), found once per process, and runs with Git's `usr\bin` on PATH.
- **A hook naming a missing gate or guard refuses** and says to run `chock sync --repo .`, instead of
  allowing silently. A re-entered Stop is still let through so a refusal cannot trap the turn.
- **A gate never judges its own policy's files or the generated tree.** java-security refused the
  commit that adopted it (its own eval suite and setup page) and blocked every Stop until then. Each
  gate now skips `.agents/policies/<its id>/` and `.chock/compiled/<its id>/`, and nothing else: a file
  planted anywhere else under `.chock/` is judged like any other.
- **Git output is decoded as UTF-8 on every console**, so the Stop gate no longer skips non-ASCII
  paths on Windows, and a match printed to a cp1252 console no longer crashes the gate.
- **The PowerShell pre-commit probe no longer blocks the commit** when a candidate interpreter is
  missing or is the Store stub (PowerShell 5.1 made that a terminating error).
- **Sync fails when an agent's hooks could not be wired**, after wiring the rest, naming each agent
  and why. It used to print one warning and exit 0 with that agent ungated.
- **Sync says when an agent needs you to trust its hooks.** Codex (and grok) skip an untrusted
  project hook without a word; sync now prints an ACTION NEEDED line with the agent's own steps.
- **gemini_cli gets the write gate it was compiled.** Its fragment was never merged into
  `.gemini/settings.json`; only the turn-end check caught a bad `write_file` or `replace`.
- **Runtime bundling tolerates a reordered agentseam import block.** An exact-block anchor stopped
  matching agentseam 0.3.4's hoisted imports, and every runtime failed to render.
- **`chock check` is about 2.5x faster**: each YAML text is parsed once with the C loader, each bundled
  module is split once, and bash is probed once per process.
- **INDEX.md says where a gate runs.** The generated index headed its gates "enforced
  automatically at commit/push", so an agent reading it could expect nothing until a commit --
  while a gate compiled for tool use refuses the write in the turn. The heading now says gates
  run at commit/push and in the agent where noted, and each gate declared `on: tool_use` ends
  with "Also checked in the agent: before a write, or at the end of the turn, depending on the
  agent." Adopters pick it up on their next `chock sync`.

## 0.11.4 — An edit is judged as the file it would leave, and bytecode no longer fails a pack

- **An edit is judged before it lands, not only at the turn's end.** Claude Code changes an
  existing file with `Edit` or `MultiEdit`, whose payload carries only the text replaced and the
  text put in. The write gate judged that fragment alone, with no imports, class or neighbours
  around it, so a policy that reads whole files -- java-security's SQL rule, for one -- found
  nothing, and the edit went through; only the Stop hook refused it afterwards. The first real
  Claude Code run of the java-security agent kit showed exactly that: an edit adding
  `"... WHERE customer = '" + customer + "'"` was allowed at PreToolUse and refused at Stop.
  An edit is now judged as the file it would leave -- the file on disk with the call's
  replacements applied, in order, honouring `replace_all`, across CRLF files -- for Claude Code,
  and for the `oldString`/`newString` and `old_str`/`new_str` spellings other clients use. A
  kind that reads added lines still judges only the text the edit introduces, so a line already
  in the repository does not count as added. When the file cannot be rebuilt (the text to
  replace is not there, so the call itself will fail) the fragment is judged as before.
- **The write gate can read a Codex `apply_patch`.** Codex CLI writes with one tool whose only
  argument is the patch text, so the gate had no path and no content to judge. Each file the
  patch adds or updates is now rebuilt from disk, per Codex's documented patch format, and judged
  whole; `added_lines` sees only the lines it adds. Codex's hooks are not yet wired to call the
  gate before a write -- only at the turn's end -- so this is the runtime half of that.
- **Bytecode no longer makes an untouched pack fail `chock check`.** A script gate runs its
  implementation out of the pack directory, so the first gate run writes `__pycache__/` there --
  per interpreter version, and more of it as more rules are imported. The lockfile's pack hash
  counted those files, so after an agent's tool calls had run the gate, `chock check --only
  verify` reported the pack as changed (`java-security: hash mismatch`) with nobody having
  edited it; the first Copilot run of the java-security agent kit on Windows hit exactly that.
  The pack hash now leaves `__pycache__/`, `.pyc` and `.pyo` out, as plugin packaging already
  did. A lockfile written while bytecode sat in a pack is reported once; `chock sync` rewrites it.

## 0.11.3 — A global `bin/` ignore no longer takes the gate out of a repository

- **A global `bin/` ignore no longer takes the gate out of an adopter's repository.** The `bin/`
  rule in the Visual Studio, .NET and Java gitignore templates, common in a developer's global
  excludes file, matched `.chock/bin/`: `git add -A` never tracked the runtime every agent hook
  runs, and a clone, a CI checkout or a `git clean -x` left `.claude/settings.json`,
  `.cursor/hooks.json`, `.codex/hooks.json` and `.devin/hooks.json` naming a file that was not
  there. Claude Code reported `SessionStart:startup hook error ... can't open file
  '.chock/bin/claude_code.py'`, and no gate judged anything from then on: a hook whose script
  cannot start refuses every call with an unrelated error on a client that reads its exit code 2
  as a block, and lets every call through on one that treats a failed hook as non-blocking.
  `chock init` and `chock sync` now add `!.chock/bin/` and `!.chock/compiled/` (and `/**` under
  each) to the repository's .gitignore, which outranks a global excludes file.
  Existing adopters get the rules at their next `chock sync`; commit them with the files.
- **`chock check` names a hook target git would not keep.** The dangling-hook check caught only a
  runtime that was missing here. It now reports a runtime that git ignores, naming the rule and
  where it lives, and covers the compiled gate a hook hands the runtime as well as the runtime
  itself.

## 0.11.2 — The plugins page states each client's own crash answer

- **The plugins page states each client's own answer to a crashed guard.** Every tree's
  `PLUGINS.md` said a crashed guard "asks -- on Codex CLI, denies", naming Codex on the Cursor,
  Copilot and Devin pages alike. The sentence is now taken from the tested `honours_ask` claim for
  the tree's client: an ask where the client prompts (Claude Code, Cursor, VS Code Copilot), a
  refusal where it cannot (Codex CLI, Devin), and an untested ask where chock holds no tested claim.

## 0.11.1 — The plugins page tells a gate from a guard

- **The generated plugins page tells a gate from a guard.** `chock marketplace build` wrote one
  fixed paragraph per tree describing every enforcing package as a `PreToolUse` guard script
  that denies a shell command. Since 0.11.0 a package can carry a policy's gate instead, which
  judges what a turn writes rather than what it runs, so the published `PLUGINS.md` in every
  distribution repo misdescribed five of its fourteen enforcing packages -- and named
  `PreToolUse` even in the Cursor tree, whose guards hook `beforeShellExecution`. The paragraph
  is now derived from the hooks each package publishes: a `--guard` command makes a guard
  package, a `--gate` command a gate package, and each kind is described with the events its
  own hooks file wires, in that client's spelling. Where a client records no write-tool
  vocabulary the page says the gate runs at the turn's end only and the write itself is not
  judged. The page renderer moves to its own module, `chock.plugin.catalog_page`.
- **Documentation matches the code again.** A full audit of `README.md` and `docs/` against
  the source: the coverage-grade vocabulary (eight levels, and no agent reaches `enforced`),
  the adapter files `chock init` actually writes, a schema-valid example manifest, and the
  surface, vendor and format counts. `chock plugin build`'s summary line for the Cursor format
  now names its `preToolUse` and `stop` gate events beside `beforeShellExecution`.

## 0.11.0 — A policy's gate rides in its plugin, and Cursor gates a write and reports at the turn's end

- **Cursor gates a write and reports at the turn's end.** agentseam 0.3.3 records what a live
  probe of Cursor 3.21.18 showed: the generic `preToolUse` event fires for `Write` with the
  file's path and full content and honours a deny, and `stop` honours a `followup_message`
  that sends the agent back into the turn (a silent stop ends it, so that surface fails open).
  `chock sync` now compiles a Cursor write fragment and a Cursor stop fragment for a policy
  whose gate declares `tool_use`, and merges both into `.cursor/hooks.json` beside the shell
  guard, under their own event keys; Cursor's row gains the `stop` column. A flat Cursor entry
  carries no matcher, so the runtime answers every tool under `preToolUse` and judges only a
  write it recognises. A stop that already re-entered once (`loop_count`, Cursor's spelling of
  Claude Code's `stop_hook_active`) is not judged again. Pin: `agentseam==0.3.3`.
- **A policy's gate rides in its plugin, in every hook-carrying format.** A plugin installs at
  the agent, not in a repository, so it carried a command guard or nothing: a gate lived only
  where `chock sync` compiled it. `chock plugin build` now packages a policy whose gate declares
  `tool_use` -- the compiled `scripts/gate.json`, the runner beside it as `scripts/gate.py`,
  and for `kind: script` the policy's whole `implementations/` under `scripts/`, so a program
  that imports from beside itself still does -- wired to every surface agentseam records for
  the vendor and no other: Claude Code's package gates the recorded write tools at `PreToolUse`
  and the turn's end at `Stop`; Codex, Devin and Copilot record no write-tool vocabulary but
  block at the turn's end, so their packages carry the gate at `Stop` alone and say that the
  write itself is not judged; Cursor records `Write` at its generic `preToolUse` and a turn-end
  hook that hands a refusal back as a follow-up message, so its package gates the write and
  reports at `stop`, in Cursor's own flat entry shape. Each package states its posture (what is
  judged and when, refuses when it cannot decide, needs python3, the vendor's own caveat) and
  the skill claims its hooks. The bundled runtime looks for the runner beside the gate before
  the repository layout, and takes the repository from the event's working directory when the
  gate is packaged; a packaged script gate says `script_base: gate`, which the runner reads as
  "beside me" instead of "under the repository root". Runtime goldens regenerate (an emitter
  change, so a minor release).
- **A policy's own skill files.** A policy may carry a `skill/` folder: `skill/body.md` is
  appended to its rendered `SKILL.md` after the constraint block, and every other file there
  rides in the skill's directory in the Agent Plugins package and every store package -- a
  guided setup page beside the skill that opens it. `--check` sees a changed or removed file;
  every store now owns `skills/`, so a rebuild removes what the policy stopped shipping.

## 0.10.0 — A script gate's evals replay, and its ambient line names the script by file

- **A script gate's evals replay.** `chock check --only evals` runs a staged-files case against
  the compiled gate in a throwaway repository that holds only the case's own files -- whole
  for a declarative gate, whose JSON is the entire check, and empty-handed for a `kind: script`
  gate, whose program lives under the policy's `implementations/` and is resolved from the
  repository root. Every such case observed "not installed" and refused, so a suite could only
  pass by expecting `block`. The runner now copies the policy's `implementations/` to where the
  compiled gate names the script, as `chock sync` would have, before running the case.
- **A script gate's ambient line names the script, not its address.** The `on(...)` line an
  agent reads rendered the compiled `script` param, which is the file's path from the repository
  root and so differs between a catalog tree (`base/<id>/...`) and an adopter
  (`.agents/policies/<id>/...`). The packaged `SKILL.md` carries that line, so `chock plugin build
  --check` could not be clean in both places at once. The bare file name is rendered now, which is
  what the manifest declares; the `stability-script` golden moves with it (an emitter change, so
  this is a minor release under the stability rule).

## 0.9.3 — A `kind: script` gate that runs a policy's own program, and a native Devin plugin format and marketplace tree on agentseam 0.3.2

- **`kind: script` gate**: a `hook.gate` whose check is the policy's own program, for a check no
  declarative kind can hold -- a parser, a flow model over a method body, a rule table larger
  than `params`. The runner hands the script the same material every declarative kind reads
  (`{"event", "repo_root", "writes"}` on stdin: the staged blobs at commit and push, the write
  itself at tool use and at the turn's end) and carries back its exit code -- `0` allows, `1`
  refuses in the script's own words. A missing script, a crash or a timeout refuses in the
  runner's words, never allows. It is a write-path kind, so the existing emitters wire it to the
  write fragment and to `stop` unchanged: a script-backed policy now reaches every vendor a
  `content_regex` gate does. Until now a script could only be a shell guard (`--guard`,
  argv-shaped, never shown the file being written) or a git-event script (commit and push only);
  the gap a script-backed gate left was named in the catalog's own a11y changelog. `chock check`
  refuses a script name that is not a bare `.py` file name, and one the policy does not ship.
- **`devin` plugin format**: `chock plugin build --format devin` packages a policy as a native
  Devin plugin (`.devin-plugin/plugin.json` + `skills/<id>/SKILL.md` + a root-level `hooks.json`,
  not the nested `hooks/hooks.json` every other format uses). Same guard, same adapter,
  byte-identical to every other format -- only the envelope differs, and the hook command reaches
  its own bundled copies via a shell expansion of `$DEVIN_PLUGIN_ROOT`, the environment variable
  the vendor documents hook commands receive (agentseam records no `${...}` plugin-root token for
  Devin, unlike Codex or Cursor -- that expansion is chock's own inference, not a vendor-recorded
  token). Unlike every other hook format, the package claims no enforcement tier: the vendor's own
  docs call plugin hooks "currently best effort and fail open ... so don't rely on them for
  crucial guardrails yet," for local Devin sessions (the CLI and Devin Desktop) only, and the
  posture text says so instead of claiming a block.
- **`chock marketplace build --tree devin`**: Devin has no marketplace index file -- `devin
  plugins install` instead reads a repo's root `.devin-plugin/plugin.json` as a meta-plugin whose
  `optionalPlugins` point `git-subdir` entries at each built plugin, so `--tree devin` writes that
  root manifest in place of an index (a new `--url` is required; chock never reads `git remote`
  for it). `chock-market.lock` and `PLUGINS.md` cover the devin tree the same way they cover every
  other tree.
- **Pinned `agentseam==0.3.2`**, which records Devin's native plugin layout; the vendored runtime
  goldens moved with it (version stamp only, no handler change).

## 0.9.2 — `sync` no longer leaves a vendor's hook config pointing at a runtime it just deleted

- **Fixed: narrowing `supported_agents` on 0.9.1 left dangling hook entries behind (#151).**
  0.9.1 wired in-agent hooks only for the vendors `supported_agents` names and pruned a
  vendored runtime once its vendor fell out of that list, but neither step touched the
  vendor's own hook config file, which 0.9.0 had written for every vendor chock knew. An
  adopter who synced on 0.9.0 and then narrowed `supported_agents` on 0.9.1 (chock-example,
  chock-mise) ended up with `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`
  and four more config files still naming a `.chock/bin/<vendor>.py` that `sync` had just
  deleted -- a hook whose command failed on every tool call, in a client that reported no
  error, while both `chock sync --check` and `chock check` reported clean. `sync` now
  uninstalls chock's entries from every vendor it no longer wires before pruning that
  vendor's runtime, the same removal path the installers already take when a policy stops
  compiling (deleting a config file that held only chock's entries). A repo already broken
  by 0.9.1 -- whose runtime is already gone, and only the config entry says a vendor was
  ever wired -- self-heals on the next `sync` too, as this repo's own `.agents/hooks.json`
  did (dogfooding turned up a live instance of #151 here: `antigravity` left `supported_agents`
  under #150 and its runtime was pruned, but the stale entry was never removed until now).
- **`chock check` catches a dangling hook target.** A new repo check
  (`check_dangling_hook_targets()`) reads every hook config chock can write and reports an
  error on any chock-written entry naming a `.chock/bin/` path that does not exist, with
  `chock sync` as the fix -- the exact shape of drift #151 left silent.

## 0.9.1 — The suite passes on Windows, a policy-less repo keeps its runtime, a pull request may not weaken the policy set, and a pre-release review closes the boundary cases

- **Fixed: Windows.** The `v0.9.0` tag ran the full matrix and every Windows `validate` job
  failed at the test step, on fifteen tests, while Linux was green -- the release shipped on
  that evidence. Two were the engine's: the vendored runtime was written in text mode, so
  Windows got CRLF and `chock sync --check` reported every `.chock/bin/<vendor>.py` as
  differing (and `chock validate` failed on the same drift); the matrix skip note printed a
  Windows path. The rest were the tests': two searched JSON text for a backslash interpreter
  path, one stringified a `Path`, and two ran `bash`, which on a Windows runner resolves to
  System32's WSL launcher rather than Git Bash. `hooks/runtime_vendor.py` now writes LF on
  every platform (`tests/test_sessionstart_arm.py` pins it); `tests/conftest.py` locates Git
  Bash beside `git` on Windows.

- **`chock init` keeps the gate outcome log out of the adopter's commits.** Every git hook
  appends to `.chock/log/gate-events.jsonl`, and `init` never ignored it, so an adopter who
  ran `git add -A` after onboarding committed a per-machine log that then changed on every
  commit they made (chock-mise had 38 records committed). `init` now appends `.chock/log/` to
  `.gitignore` once, respecting any rule already there; `chock validate` warns when the log
  is tracked anyway and says how to untrack it (`check_gate_log_untracked()`).

- **Fixed: a repo with no policies lost the runtime its session-start hook runs.** `chock sync`
  installs the arm hook first, which vendors `.chock/bin/claude_code.py` and points
  `SessionStart` at it, then the pre-tool/stop installer for the same file found no fragments
  and unlinked the runtime -- leaving a fresh `chock init` (chock-quickstart) with a hook to
  nothing. The installer now keeps a runtime any entry under any event key still runs
  (`_runtime_referenced()` in `hooks/in_agent_merged.py`); the unlink stands when nothing
  references the file. Two tests in `tests/test_sessionstart_arm.py` pin both sides.

- **`chock check --only baseline --base <ref>`: a pull request may not weaken the policy set**
  (POL-4). `protect-agent-config` refuses the agent's *shell* edit of `.chock/config.yaml`,
  best-effort, and nothing refused the same edit committed through any other path -- a policy
  could be disabled in the PR that needed it gone. `validation/checks_baseline.py` reads the
  config at the base ref and at the head and errors on every policy the head disables,
  downgrades to advisory or narrows to fewer surfaces; a base with no config is every policy
  enabled; widening is never a finding. CI runs it against the pull request's base branch;
  bare `chock check` skips it with a note because it needs a ref. Modelled on
  chock-java-security's `check-baseline`.

- **`gateway/gates.py` and `gate/runner.py` are asked the same question.** #145 found the
  two `content_regex` evaluators disagreeing on the per-line waiver at tool-use, and nothing
  had put the same text to both. `tests/test_content_regex_evaluators_agree.py` runs one
  fixture through the gateway evaluator and through the runner at each agent event and
  asserts one verdict per case, waiver cases included.

- **chock dogfoods `pin-github-actions`.** Its workflows were SHA-pinned by discipline alone;
  the catalog's policy (0.0.3, with the `applies_to.paths` bound from chock-catalog#93) is
  now in `.agents/policies/`, compiled to the git hook, the write path and the turn-end
  backstop, and listed in `docs/baseline-policies.md` and `docs/agentic-risk-coverage.md`.
  The bound is what keeps it off `docs/installation.md` and `docs/reviewer-evidence.md`, which
  quote an unpinned `uses:` line on purpose.

- **`chock add` refuses what a catalog must not hand it.** `shutil.copytree` dereferenced
  symlinks, so a pack carrying `leak -> ~/.ssh/id_rsa` installed the adopter's private key as
  a regular file in their repo; a manifest whose `id` differed from its folder installed as
  two policies (the lock and compiled tree under one name, the config under the other);
  `--ref <sha>` failed (`git clone --branch` takes a branch or tag) and `--ref` with a local
  path was ignored; a path-like id was a traceback. `add` now refuses symlinks and foreign
  ids before hashing, fetches a commit id by name, honours `--ref` for a local checkout, and
  reports a bad id as an error (`scaffold/add.py`).

- **`chock check --only verify` attests every pack `sync` compiles.** An empty or missing
  `chock.lock` over installed packs verified clean -- nothing was compared -- and a pack nested
  under `.agents/policies/<group>/` was compiled but never locked, since `build_lock()` read one
  level and `discover_policy_dirs()` every level. Both are drift now (a nested pack records its
  `path`), and a lock that is not JSON is a named failure rather than a traceback (`lock.py`).

- **`chock review require` judges by the stricter of the base's policy and the head's.** It
  read `required_checks`, the check registry, `attestation_floor` and `unattestable_paths` from
  the pull request's own `.chock/config.yaml`, so the change being judged chose what it was
  judged on. The required set and unattestable paths are now the union of base and head, the
  floor the higher, and a check both define runs as the base defines it; a recorded failure is
  never merge-ready, required or not (`review/policy.py`, `docs/reviewer-evidence.md`).

- **The baseline check compares reach, not size.** `{git-hook, ci-gate} -> {git-hook,
  ambient-rule}` kept the surface count and lost a gate, and a strict-subset test passed it;
  a base ref that did not resolve read as "no config there", which is every policy enabled;
  a base config that was not YAML was a traceback. A head that lacks any base surface is a
  weakening; an unresolvable ref and unreadable YAML are errors (`checks_baseline.py`).

- **A config of the wrong shape neither crashes nor quietly widens.** `policies:` null,
  `disabled: scan-secrets` (iterated as letters), a null or string override and
  `surfaces: 5` each crashed the resolver or the baseline check; `validate` now names each
  (`policy_toggles`), the resolver treats a bare string as one id or surface, and POL-1 holds
  in `sync` too: a mandatory policy listed in `policies.disabled` is compiled in full.

- **`egress_allowlist` reads a URL the way a fetch library will.** `https:\\evil.io`,
  `https:/evil.io` and `https:///evil.io` yielded no host and passed; `example.com\@evil.io`
  is one host to a browser and another to curl; `evil.io%00.example.com` matched the
  allowlist's suffix. Backslashes and slash runs are normalised, a host outside the DNS and
  IP character set is refused as undecidable, and an international host is matched by its
  punycode name (`gateway/gates.py`).

- **A gate pattern that does not compile fails `validate`, not the first commit it guards.**
  `content_pattern: "("` passed schema validation and `sync`, then every commit died with a
  `re.error` traceback (`checks_gate_shape.py`).

- **`sync` wires in-agent hooks for `supported_agents` only.** `chock init . --agents claude`
  followed by `sync` wrote ten vendors' hook files (`.cursor/`, `.codex/`, `.windsurf/`,
  `.devin/`, ...) and vendored ten runtimes; the SessionStart arm hook was installed whether
  or not claude was named (`recompile.wired_vendors()`).

- **`agentseam` bumped to 0.3.1.** Its own `dispatch.handle()` now refuses a handler that
  raises in the vendor's dialect, instead of letting the exception escape; every vendored
  runtime's `main()` gains the matching `_decide()`/`_report()` wrapping, so a policy handler
  that raises is answered with a deny instead of an unhandled traceback. `dispatch.py.tmpl`'s
  own try/except in `gate/runtime_bundle.py` already refused on failure from the outside and
  is now redundant with agentseam's inner one for the vendored runtimes this repo emits; it
  stays for this release as defense in depth rather than being pulled the same cycle as the
  bump. 0.3.1 also writes `dump()` output as LF on every platform, which chock's own code
  paths never call. Every adopter's next `chock sync` rewrites `.chock/bin/*.py`.

## 0.9.0 — In-session enforcement for content policies: the write path, the `stop` backstop, and the waiver that could not be self-served

- **The vendored runtime refuses when it cannot decide.** `handle()` in every
  `.chock/bin/<agent>.py` now wraps the judge: an exception escaping it used to exit the hook
  with a traceback, which every client reads as a non-blocking error -- fail-open, with the
  reason on a stderr nobody watches. It now returns a deny that carries the exception's type
  and message, the same rule chock-java-security's four doors adopted. Runtime goldens
  regenerated; the diff is the wrap and nothing else. `tests/test_runtime_fail_closed.py`
  raises inside the rendered bundle and asserts the deny.

- **The composite action installs the release it ships with.** `action.yml` defaulted
  `version` to `0.1.0`, so `uses: open-coder-ai/chock@vX` with no `version:` installed a
  release eight versions old. The default now tracks `pyproject.toml`, as does the
  `docs/installation.md` example, and `tests/test_release_surfaces.py` fails the build when
  either drifts from the version being released.

- **The line waiver is honoured only where a human staged the text** (#145).
  `scan-secrets`' published message says the per-line pragma is *not* honoured at tool-use,
  where the scanned text is a live tool argument an appended token could neutralise. The
  mcp-gateway evaluator agreed and never read `allowlist_pragma`; `gate/runner.py`'s
  `_kind_content_regex` did not agree and honoured it at every event. Harmless while
  `tool_use` emitted nothing; the moment the write path and `stop` routed through the runner,
  an agent refused at the write path could append the pragma to the line it was refused on and
  pass. `WAIVABLE_EVENTS = {commit, push, ci}` now names the events where a human staged the
  text and the pragma is read nowhere else -- an allowlist, so a new event defaults to
  unwaivable. The blob-level waiver for a forbidden path follows the same rule. The test that
  pinned the wrong side is replaced by four that pin the right one; the same line is still
  waived at commit. Vendored runner resynced.

- **In-session enforcement for content policies: the write path, and a `stop` backstop
  behind it** (#144). `emit_pre_tool_use` looked for a bash guard script and returned `[]`
  for everything else, so a policy declaring `on: [commit, tool_use]` got the commit half and
  nothing in-session -- four catalog policies had asked for this since August. Two surfaces
  now emit, because one of them has a hard ceiling:
  - **Write path.** A pre-tool hook needs a *matcher*, and agentseam records a `tools.write`
    vocabulary for exactly two of ten wired vendors (`claude_code`, `gemini_cli`). Inventing
    one would gate a tool name nobody verified, so the other eight get no fragment and keep
    exactly the coverage they had (`vendors.write_matcher`, `_gate_fragments`,
    `pretooluse-write.json`; the claude installer glob widens to `pretooluse*.json`).
  - **`stop`, a new surface** (`Surface.STOP`), the end-of-turn hook: it is handed nothing and
    reads the worktree, so it sees what a pre-tool hook structurally cannot -- a heredoc or a
    redirect carries no file argument -- and takes no matcher, so it wires six vendors where
    the write path wires two. Membership is derived from `matrix.can_block(vendor, STOP)`
    (`levels.STOP_TODAY`, `vendors.stop_vendors`), never listed: cursor, grok and windsurf are
    `detect` and excluded; copilot/vscode can refuse a turn but are held back because their
    hooks live in chock's own `.github/hooks/chock.json` in a shape witnessed for the pre-tool
    key alone (`vendors.AGENT_HOOKS_VENDORS`, an install cap beside `repo_wirable`).
  - **`stop` is credited with no coverage**, enforced rather than promised: every tool call in
    the turn has already run by the time it fires, and a crash or a kill ends the turn without
    it. `UNCREDITED_SURFACES` holds it and `coverage_cell` subtracts it before grading; two
    parametrised tests assert adding `stop` moves no cell on any agent. `INSTALLED_SURFACES`,
    the coverage table, the README caveat and the fan-out figure all change together with the
    backstop wording attached.
  - The claude installer's settings file now takes two event keys, so `hooks/in_agent_merged.py`
    splits out of `in_agent_install.py` with a per-event `Wiring`; `docs/coverage-levels.md`
    splits out of `enforcement-surfaces.md` -- both at the 300-line budget. `Surface` moves to
    the leaf `compile/surface_kinds.py`, cutting the import cycle CodeQL found instead of
    deferring it; `test_no_import_cycles.py` restores both cut edges to prove the checker sees
    one. `gen_brand_assets.py` and `make_surfaces.py` derive their counts and rows from the
    package, so a ninth surface moved the picture and its alt text in the same commit.

- **The gate runner judges a write, at both agent events, and the vendored runtime can run a
  compiled gate** (#143). `WriteContext(GateContext)` answers `staged_paths`/`staged_blob`/
  `added_lines` from a `{"writes": {path: text}}` document on stdin instead of the index;
  `AGENT_EVENTS = ("pre-tool-use", "stop")` both map to the policy's own `tool_use` word;
  `WRITE_PATH_KINDS` names the one kind a write can answer (`content_regex`) and the runner
  refuses the rest at these events rather than reporting an allow it never made. The stdlib-only
  `gate/write_gate.py` is extracted into every per-agent runtime beside `guard_runner`: it finds
  the gate's runner by fixed depth (never by walking up into another repository's `.chock`),
  reads the tool call's own text at `pre_tool` and the worktree at `stop`, guards
  `stop_hook_active` re-entry, and refuses rather than allowing when the runner is missing or
  errors. Runtime goldens regenerated for all ten vendors; the diff is purely additive.

- **`applies_to.paths` bounds a compiled gate's reach** (#142). A policy's declared
  `applies_to.paths` rides into `gate.json` beside `params` as `paths`, and `GateContext`
  filters `staged_paths` through `fnmatch.fnmatchcase` (`*` crosses `/`, so
  `.github/workflows/*` covers nested files). A gate with no scope sees every changed file, as
  every gate did before. This is what keeps an in-session gate off files a policy was never
  about: a pattern for `uses: x@v1` must not refuse the README that documents how to pin an
  action.

- **Guards can ask.** A pre-tool guard that exits **3** holds the command for the user's
  confirmation, and its first output line is the prompt they see (`gate/guard_runner.py`,
  `GUARD_ASK_EXIT`). Until now a guard had two answers, exit 1 to refuse and exit 0 to stay
  silent, and every other exit was read as "the guard did not complete" and turned into an ask
  that says only "could not check". A policy whose table has a *confirm* column (rm -rf on a
  relative path, `git reset --hard`, `docker system prune`) had to refuse outright or stay
  quiet. The client outcome is unchanged on every vendor -- `escalate`, degraded as agentseam
  records -- so the crash path keeps its safety and only the reason text moves. The eval
  replayer observes it as `ask` and a case may `expect: ask` (`eval.schema.json`); the
  gate-events log records `"verdict": "ask"`. The runtime goldens are regenerated for the
  handler change. The fail-to-ask suite's crash fixture moves from exit 3 to exit 4.

- **Scaffold: the doc boundary `chock init` writes now matches this repo's own.** `4e85f97`
  renamed `never_read` to `read_on_demand` in this repo's `AGENTS.md` and in the per-agent
  wrapper text `scaffold/adapters.py` emits, but not in the `AGENTS.md` and `docs/README.md`
  templates `chock init` writes into an adopter's repo. One `init` therefore produced a
  `CLAUDE.md` saying "read `README.md` and `docs/` only when the task is to change them", an
  `AGENTS.md` saying `never_read`, and a `docs/README.md` saying "Agents must not read files
  here" -- and `AGENTS.md`, being the declared source of truth, is the one that wins. Both
  templates now carry the on-demand wording with the reason beside it, and the installed tree
  under `.agents/skills/` was regenerated with `chock install-skills .`.

- **CI/docs: launch prep -- smaller hero GIF, no star history, split workflows.**
  `docs/assets/demo.gif` recompressed with gifsicle (2.37 MB -> 955 KB) for mobile,
  verified legible at the 760px width the README renders at; the README's Star history
  section is removed for now (the owner restores it after launch). `render-demo.yml`
  is renamed to `demo-gif.yml` and gains a `push`-on-`docs/assets/demo.tape` trigger
  (any branch but `main`) that commits the regenerated GIF back to that branch, so a
  tape change carries its GIF into the same pull request; the `workflow_dispatch` path
  is unchanged. The `quickstart` job moves out of `ci.yml` into its own
  `.github/workflows/quickstart.yml`, which also generates and diff-checks the
  committed `docs/quickstart.sh` against the README's Quick start block.

- **Docs: rebuilt the README as a landing page.** Shared section order (Quick start · What you
  get · How it works · Author your own policy · Supported agents · For open-source maintainers ·
  Contributing · Part of open-coder-ai · Security · License), the Why/Roadmap/doc-index prose
  moved verbatim to `docs/why.md` and `docs/roadmap.md`, the hero GIF re-recorded as the
  `scan-secrets` demo, and the Quick start block now runs for real in CI
  (`tools/quickstart_block.py` + the `quickstart` job in `ci.yml`).

- **Added `chock plugin build --policy` and `--out`** (#12). `--policy <id>` (repeatable) builds
  only the named policies, matched by manifest `id` or directory name -- the same rule
  `toggles._find_policy_manifest` uses, not a third one -- instead of always rebuilding every
  policy under `--policies-dir`; an id that matches nothing exits non-zero naming it, rather than
  printing `Packaged 0 policies` and exiting 0. `--out <path>` writes that one policy's plugin
  directly to `<path>` instead of `<out-dir>/<format>/<id>/`; it is an argparse error with any
  count of `--policy` other than exactly one. Both flags are respected by `--check`. A
  `--policy`-narrowed build also no longer treats every other policy's package under `--out-dir`
  as stale and deletes it -- staleness can only be judged against the full policy set, so that
  cleanup pass now runs only on an unfiltered build.

- **Fixed: `chock sync` doubled `PreToolUse`/`SessionStart`/Cursor entries in a repo whose
  committed config predated the per-vendor `.chock/bin/` runtime split** (#84). Ownership of a
  hook entry was decided by matching the *current* runtime filename only
  (`.chock/bin/claude_code.py`, `.chock/bin/cursor.py`); an entry still pointing at
  `.chock/bin/pretooluse.py` or `.chock/bin/sessionstart.py` -- names chock wrote before that
  split -- was not recognised as chock's own, so it was kept and a fresh, current-named entry
  was appended beside it. `runtime_vendor.owned_markers()` now also matches every basename in
  the new `chock.hooks.data/legacy_runtime_basenames.json`, so a legacy entry is replaced in
  place instead of doubled. An explicit list, not a `.chock/bin/` prefix match, so a script an
  adopter happens to keep in that directory is never claimed as chock's. `in_agent_install.py`
  and `sessionstart_install.py` both use it. Added `tests/test_sync_legacy_runtime_names.py`.

- **Added `chock eval export --format context-report`**, moving chock's knowledge of its own
  policy format (which eval cases have no `execute` block, and how a policy's rule text renders
  for an agent) into chock as an exporter, so `open-coder-ai/context-report` can measure whether
  a policy's ambient rule changes agent behaviour without chock depending on it. Writes one
  `subjects/<id>.md` per policy via `chock.compile.emitters.advisory.advisory_lines` (the same
  function the ambient/plugin emitters use, never re-derived), one `claude plugin eval` case
  directory per tier-3 case tagged `rule:<id>`, and a `run.json` run manifest (`models`/`judge`
  left for the caller to fill in). A policy with no tier-3 cases is skipped with a one-line
  notice; the pre-`suite:` `eval_suite:`/`test_cases:` shape is a distinct, named error. See
  [`docs/cli-reference.md`](docs/cli-reference.md#eval-export--hand-tier-3-cases-to-context-report).

- **SEC-3 named a field/value pair the schema cannot express; corrected, and the class closed**
  (`chock-g1`). `spec/policy-spec.md` §10 required `gate.message` "for every hook with
  `action: block` or `action: verify`". `manifest.hook.json`'s `gate.action` is a `const: block` --
  it has never accepted `verify`. The `advise`/`verify`/`block` distinction belongs to
  `enforcement`, a different field (EFF-1), and no hook has ever used `verify` there either. The
  spec's conditional was also *weaker* than what is enforced: `message` sits in `gate.required`
  under `additionalProperties: false`, so it is required whenever a `gate` is declared, full stop.
  SEC-3 now says that. Adds `tests/test_spec_field_values.py`, which extracts every
  `` `field: value` `` the spec asserts and checks it against the schema that owns the field, so
  prose cannot again claim a value no artifact could carry. Found by
  `chock check --only mechanisms` (#112) while verifying SEC-3's mechanism, and recorded rather
  than fixed there because it changes what a check enforces.

- **CI now runs `mechanisms` and `conflicts`, and a test keeps that list honest** (`chock-g1`).
  `.github/workflows/ci.yml` runs each sub-check as its own `chock check --only <x>` step rather
  than the umbrella `chock check`, so the two most recently added checks -- `mechanisms` and
  `conflicts` (AMB-2) -- were in `lifecycle.py`'s `CHECKS` but had no CI step, and therefore
  gated nothing on a pull request. Added both steps, and
  `test_every_lifecycle_check_has_its_own_ci_step` so the next check added to `CHECKS` fails the
  suite until it is listed. The gap is the same shape as the one `mechanisms` itself was built to
  catch: a control that runs somewhere is not a control that runs where the ledger says it does.

- **Added `chock check --only mechanisms`, a matrix-vs-code check** (`chock-g1`). Three rows in
  `spec/enforcement-matrix.md` were found, in one day, whose claim outran its implementation --
  every one by accident, none by a standing check
  (`discovery/2026-09-04-enforcement-matrix-audit.md` in org-plan). The existing `matrix`
  sub-check only asserted that every invariant ID *appears*; presence is not the same as being
  real. `mechanisms` (`chock.validation.checks_matrix_mechanisms`) parses every row naming a
  `` `function()` `` mechanism and, via AST over `src/`, verifies: the function is defined; it is
  invoked on the `engine` (`chock validate`) or `lifecycle` (`chock check`-only sub-check) dispatch
  path -- both, since checking one only is how the audit produced its own false positives, e.g.
  `check_ambient_conflicts` is lifecycle-only and invisible from `engine.py` alone; and it can
  emit the severity the row claims, by walking the (transitive) call graph for literal
  `"error"`/`"warning"`/`"info"` findings, or treating a bare CLI entrypoint's nonzero exit as
  `error`-equivalent (it has no other vocabulary). A row that cannot be made true this way is not
  weakened to pass: it is marked `unautomated` (no code path) or `eval` (enforced by the eval
  suite instead), and the check skips it knowingly -- reported as an `info` finding, not silently.
  Wired into `chock check` beside `matrix` in `lifecycle.py`'s `CHECKS`.
  **Also repoints SEC-7** (a repointing, not a redesign -- the record's invariant, "the compiled
  ambient surface is what policies produce, nobody hand-edits it," was already enforced,
  blocking, by `chock check --only index` when `AGENTS.md` became a pointer; the row just named the
  wrong mechanism): SEC-7 now names `chock check --only index` (`cmd_refresh()`, on the `lifecycle`
  path) instead of `check_ambient_rule_blocks()`, which is a secondary, warning-level helper and
  was never a byte-match -- every one of its findings is `"warning"`, so it structurally could
  not fail a build. **Also fixes SEC-4, SEC-1, SEC-2, SEC-6, INT-1, INT-2** to name the real
  functions that enforce them (`_scan_text_surfaces`, `check_security_baseline`,
  `check_eval_first`, `validate_yaml_against_schema`) instead of prose with no `function()`
  the check could verify, and marks **TPL-1 and SCH-1 `unautomated`**: no code compares the
  template mirror or re-derives the installed schema copy, so their previous `warning`/`error`
  severities were claims nothing could ever produce. Every row now carries a `Dispatch` column
  (`engine`/`lifecycle`/`n/a`) recording which path enforces it, removing the ambiguity that
  produced the audit's own false positives. Also fixes an unescaped `|` in DET-1's Check column
  (`code|hybrid`, a pre-existing markdown-table bug this check's row parser exposed -- it split
  the row into a bogus extra column) and teaches the row parser to respect `\|`-escaped pipes
  already in use elsewhere in the file (e.g. EFF-1's `verify\|block`).
- **Added AMB-2, deterministic conflict detection over the compiled ambient rule surface**
  (`chock-g1`). `chock sync` compiles every enabled policy's rule into one attention surface
  (`.agents/policies/INDEX.md`, the file `AGENTS.md` points agents to read -- see the AMB-1
  correction below); nobody reviews those independently authored policies together, so a
  contradiction there is worse than a missing rule, because the agent silently picks one and
  neither is enforced. Arbiter ([arXiv:2603.08993](https://arxiv.org/abs/2603.08993)) finds
  that the agent that resolves instruction conflicts cannot be the agent that detects them --
  detection needs a different vantage point -- so this is not a model-based check: it is a new
  parser (`chock.validation.ambient_parser`) over the compiled key/value DSL, retaining which
  policy emitted each line, and a new check (`chock.validation.checks_conflicts`) doing set
  arithmetic over a closed, catalog-derived verb vocabulary (`never`/`block` vs.
  `prefer`/`require_approval`). Flags, as errors naming both policies and both lines: direct
  contradictions, modality conflicts, and scope overlaps (an `outer(paths): verb(target)` call
  flattened into per-path synthetic clauses, so a path claimed by two policies with opposing
  verdicts falls out of the same mechanism). Redundant or shadowed rules are a warning naming
  their token cost against the AMB-1 budget. A declared, reviewed override
  (`# chock: conflict-reviewed <key>` in a policy's `rule.text`) suppresses exactly that
  finding. New invariant AMB-2 in `spec/enforcement-matrix.md` and `spec/policy-spec.md` §16,
  and `chock check --only conflicts` for the authoring loop.
  **Also fixes an AMB-1 discrepancy**: the matrix and `spec/policy-spec.md` described AMB-1 as
  measuring `chock:rules` blocks inlined in `AGENTS.md`. That architecture no longer exists --
  `test_ambient_wiring.py::test_this_repo_carries_no_inlined_blocks` asserts `AGENTS.md` never
  carries per-policy blocks at all, only a pointer to `.agents/policies/INDEX.md`. The
  implementation (`check_ambient_token_budget()`, which reads `INDEX.md`) was already correct;
  the docs were stale. Corrected, not rearchitected.
- **Added `chock review require --base <ref>` and the `require-review-evidence` catalog policy**
  (`chock-g1`), closing the two holes left in `chock review`: a contributor could name a trivial
  subset of checks and have it verify cleanly (H1), and "evidence holds" was never the same claim
  as "the checks passed" (H2). `emit` now records a `command_set_hash` over the repository's
  `required_checks`, resolved to their actual registry commands; `require` recomputes that hash
  from repo config -- never from the evidence -- and rejects any mismatch, catching a shrunk set
  or a redefined check, not just an omission. New `chock.review.attestation_floor` and
  `applies_to` config. `require` runs as its own CI step via `action.yml`, not a compiled
  git-hook or ci-gate, because it depends on `chock.review` and the vendored gate runner must stay
  stdlib-only. Documents the branch-protection gap: `ci-gate`'s "un-bypassable" claim rests on a
  server-side required-status-check setting nothing in the repository can edit
  (`docs/adopting.md#the-branch-protection-gap`). Re-derives the mechanism *Proof-or-Stop: Don't
  Trust the Agent, Trust the Evidence* ([arXiv:2607.14890](https://arxiv.org/abs/2607.14890))
  already publishes, for chock's anonymous-fork threat model. Coverage row:
  `enforced-in-ci` -- re-derives claimed checks, does not deepen review.
- **Added the `test_integrity` gate kind, closing the `agentic-risk-coverage.md` row on an
  agent deleting tests or assertions to get green** (catalog policy `test-integrity`,
  `chock-g1`). Blocks a deleted test file, a net loss of assertions across the whole
  change, and a vacuous assertion (`assert True`, `expect(true)`) added in its place;
  `chock: test-removal-reviewed` on the removing line is the reviewed escape hatch.
  Declarative (`hook.gate` in `manifest.yaml`), `enforced-at-commit` with the `ci-gate`
  backstop so it holds for an inbound contributor whose agent never ran a local hook. The
  coverage row moves from `advisory` to `enforced-at-commit`.
- **Fixed a dead `import shutil` in every vendored runtime bundle except `claude_code`'s.**
  `chock.gate.runtime_bundle.render()` spliced its fixed `_chock_`-renamed stdlib import
  block into every agent's bundle regardless of which of those names the assembled handler
  actually used -- `shutil` is only referenced by `sessionstart`, extracted for
  `claude_code` alone, so every other vendor's `.chock/bin/<agent>.py` carried an unused
  import (flagged by CodeQL in every adopter that compiles the full vendor set, e.g.
  chock-catalog#56). `render()` now filters the import block per agent against what its
  handler source actually references. Runtime goldens regenerated; only the dead import
  line moved, confirmed by diff.

## 0.8.0 — Derive from agentseam's vendor config; externalize templates; adopt the Sonar/Checkstyle/FindBugs lint bar

- **Adopted the Sonar/Checkstyle/FindBugs-class ruff rule bar** (owner standard,
  `plan/coding-standards.md` §3) across `src/`: `C90 N PLR PLW PLC ERA T201 ARG RET SIM
  PIE FBT A B S BLE TRY RUF`, with mccabe max-complexity 10 and pylint max-args 5 /
  max-branches 12 / max-returns 6 / max-statements 50. Fixed the measured `src/` baseline
  category by category in bisectable commits -- mechanical/safe, magic values plus a new
  literal-duplication guard (`tools/check_literal_duplication.py`), exception hygiene,
  boolean traps (keyword-only, including the vendored gate runtime), unused arguments,
  asserts, subprocess hardening, 65 of 71 lazy imports hoisted to module top (6 kept lazy
  for documented reasons), and `print` centralized into a new `chock/output.py`
  `warn`/`error` surface for the 31 call sites that matched its convention (the ~183
  genuine CLI/render call sites are per-file-ignored). Complexity splits (37 findings
  across 21 functions) are deliberately deferred to a follow-up wave via scoped
  `TODO(lint-adoption)` per-file-ignores, never a blanket one. No behaviour change: full
  suite, `chock check`, `sync --check`, the acceptance suite, and a full before/after
  artifact diff all pass unchanged; the standard is recorded in `AGENTS.md`.
- **Emitted-artifact templates move out of Python source into template files, and the
  CLI command table becomes data** (owner standard `externalize, don't hardcode`,
  `plan/coding-standards.md` §2). Every non-Python template previously held as a Python
  string literal -- the CI-gate step and git-hook shim (`compile/emitters/ci.py`,
  `git_hook.py`), the in-agent bash/PowerShell one-liners (`in_agent.py`), the git-hook
  dispatcher and wrapper scripts (`hooks/installers.py`), the scaffolded CI workflow and
  config-file scaffolds (`scaffold/install_ci.py`, `templates.py`, `agents_md.py`), and
  the vendored-runtime Python-source fragments (`gate/runtime_bundle.py`, as `.py.tmpl`)
  -- now lives under each package's own `data/` directory, loaded via
  `chock.resources.package_data_dir` and rendered with `__TOKEN__` + `str.replace` (never
  `.format()`), so every template file is valid in its own language as committed and CI
  lints it that way (`shellcheck`, `actionlint`). Emitted bytes are unchanged: proven by
  the existing emitter-stability goldens, new token round-trip tests
  (`tests/test_template_tokens.py`), and this repo's own `chock sync --check` staying
  clean. `cli.py`'s `COMMANDS` table (name -> module/help/alias) moves to
  `data/commands.json`, read at import time; `chock --help` output is unchanged
  (`tests/test_commands_data.py` goldens it). New package-data and PyInstaller
  (`collect_data_files`) coverage tests guard every new `data/` directory. AGENTS.md
  gains a compact `externalized_text` hard rule recording the standard.

- **In-agent membership derives from agentseam's capability matrix, and the surface
  extends to seven new vendors** (design C3, `docs/design/derive-from-vendor-config.md`).
  `IN_AGENT_TODAY`, `SURFACE_AGENTS`, `RUNTIME_AGENTS` and `VENDORED_RUNTIMES` stop being
  hand lists: membership is `matrix.can_block(V, PRE_TOOL)` capped by what the repo-scoped
  installer may touch (a repo-relative JSON config), computed in `chock.vendors`.
  antigravity, codex_cli (repo-level, beside its existing plugin store), devin, gemini_cli,
  grok, tabnine and windsurf now get per-policy pre-tool fragments rendered by agentseam's
  own `hook_config` (`compile/emitters/in_agent.py`), one shape-agnostic config-merge
  installer (`hooks/in_agent_generic.py`: strip-ours/deep-merge keyed on the vendored
  runtime path, interpreter baking as before), and vendored runtimes from `bundle()`.
  junie and kimi_code can block per the matrix but their recorded hook configs are
  home-anchored (`~/.junie/...`, `~/.kimi-code/config.toml` -- TOML at that), outside what
  `chock sync --repo` may write, so they stay advisory-only; a pinned test fails the day
  upstream records repo-level JSON configs for them. junie (absent from chock entirely
  before) joins the alias table, advisory surfaces and both published matrices. Day-one
  coverage for every new vendor is the matrix word under its per-claim basis cap --
  `best-effort (vendor-docs|vendor-source|third-party-install|live-run-partial)`,
  `witnessed: false` everywhere (no live run exists) -- and the four previously enforced
  vendors' artifacts are byte-identical (before/after tree diff; only new-vendor
  coverage cells moved). New evidence: six `honours_ask` claim rows tested against the
  bundled runtimes (`block` and `exit-2` join the wire-verdict vocabulary for
  devin's spelling and windsurf's G5 exit-code grammar). New goldens: per-vendor fragment
  fixtures in the emitter-stability tree and frozen per-vendor runtime bytes
  (`tests/fixtures/runtime_goldens/`, regenerated only via `CHOCK_REGEN_GOLDENS=1`).
  Fragment commands for the new vendors use repo-relative paths -- no repo-root token is
  recorded upstream for them (the `${CLAUDE_PROJECT_DIR}` gap, filed) -- so the hooks
  resolve where the vendor runs them from the repo root, and installs stay unwitnessed
  best-effort claims until a real client run lands in the witness ledger.

- **Per-vendor wire facts are now reads of agentseam 0.2.0's vendor config, and the vendor
  emitters/installers collapse into one of each.** Config paths (`.claude/settings.json`,
  `.cursor/hooks.json`, the `.github/hooks/` directory), pre-tool event spellings
  (`PreToolUse`, `beforeShellExecution`), the cursor `version: 1` envelope, the SessionStart
  event name, and the Claude shell matcher (`Bash`, from `tools.shell`) come from
  `agentseam.vendor_config` / `agentseam.adapters` through `chock.vendors`, so those facts
  are recorded once, upstream. The two vendor emitters (`claude_pretooluse`, `agent_hooks`)
  become one `compile/emitters/in_agent.py`; the three installers (`pretooluse_install`,
  `cursor_install`, `agenthooks_install`) become one `hooks/in_agent_install.py` with the
  per-vendor differences reduced to a small wiring table; the plugin packagers render their
  hooks files through the same two shape builders. **Emitted bytes are unchanged** -- proven
  by a full before/after build of every artifact (compiled fragments, installed configs,
  vendored runtimes, all five plugin formats, marketplace index): 450/450 files sha256-equal.
  Three witnessed facts stay chock-recorded because agentseam 0.2.0 disagrees or records
  nothing: the agent-hooks `preToolUse` spelling and entry keys (live deny witnessed;
  upstream says `PreToolUse` + `{type, command, windows}`), the agent-hooks shell matcher,
  and the `${CLAUDE_PROJECT_DIR}` token (no schema field). `tests/test_vendor_wire_facts.py`
  binds each override to its witness row and to the upstream value it disagrees with, so the
  moment upstream ingests the witnessed shape the suite says "delete the override and
  derive". Cursor's `failClosed` stays unset: agentseam's accessor exists (`fail_closed`),
  but flipping it is an enforcement-behaviour change that needs an owner decision and a
  witnessed run, and a test now pins that no cursor wire byte carries the flag.

- **agentseam 0.2.0, and the claim table now separates wire words from semantics.** The
  dependency pin moves from 0.1.1 to 0.2.0 (the post-ACS release: canonical outcome
  `escalate`, `ask` kept only as a deprecated alias). Under 0.1.1 chock's claim table
  validated its `verdict` field against agentseam's canonical constants and derived the
  fail-to-ask lift by `verdict == ASK` -- correct only because canonical and wire words
  coincided. Each `src/chock/data/claims.json` row now records BOTH the word witnessed on
  the vendor's wire (`verdict`, validated against a chock-owned wire vocabulary that a
  live-runtime test recomputes from fixtures) and an explicit `honours` boolean; the lift
  derives from `honours` alone, and a mutation test pins that equality with any verdict
  constant fails. The vendored runtimes speak agentseam's canonical words
  (`guard_runner.VERDICT_ESCALATE`, `Decision.escalate`) and every runtime fixture runs
  with `-W error::DeprecationWarning`, so a deprecated spelling cannot ship silently.
  No behavior change: a crashed guard still asks where it asked and codex still gets its
  deny, and no coverage word moves.

- **Coverage cells now carry their evidence, and a witness ledger replaces hand-asserted
  posture prose.** Each `.chock/coverage.json` cell is `{level, basis, witnessed}` rather than
  a bare word, and every report prints the pair -- `best-effort (live-run)`. The level is
  `min(matrix word, cap(weakest basis the grade rests on))`, so a strong word can never sit on
  weak evidence: `vendor-docs` backs `best-effort` at most, `inherited` backs nothing
  reportable. **No day-one word changes** -- every basis chock grades on today clears its cap;
  the cap's bite is the future case. Evidence is a ceiling, never a source: capability is read
  from `agentseam.matrix` alone, so no evidence record can grant a gate a matrix row denies.
  chock's own live observations move out of the packagers' prose into
  `src/chock/data/witnesses.json` (`{agent, surface, client, date, method}`, partial rows
  refused at load), and the "witnessed blocking on ..." phrase in a package posture is now
  rendered from that row -- delete the row and the claim disappears with it. Cursor's posture
  therefore names the client and date it was witnessed on instead of "a real install".
  `tested` (our suite against our runtime, `src/chock/data/claims.json`) stays distinct from
  `witnessed`: the `fail-to-ask` lift now requires a TESTED honours-ask claim naming the
  fixture that proves it, which is also the table the runtime test parametrizes over, so a
  claim cannot be edited up without that test failing.

- **Runtime: a guard that RAN and could not decide now asks for confirmation instead of
  allowing silently.** `gate.guard_runner` had five "could not determine" paths and answered
  all five the same way -- allow, with a line on stderr the agent sees and the developer
  usually does not. Two of them are now an `ask`: the guard crashed (any exit code that is
  neither 0 nor 1) and the guard hit its 30-second timeout. Both mean the control was
  installed, reachable and runnable and still produced no answer, which is anomalous rather
  than routine.
  The other three still allow, deliberately: a command POSIX `shlex` will not tokenize is
  common and usually benign, an empty command has nothing to check, and a machine with no
  usable `bash` is uniform across every command rather than a fact about this one. Oversight
  capacity is finite, and a control that prompts on all five would train a developer to click
  through the prompts that matter.
  What an `ask` becomes is per-client and no client turns it into a silent allow: Claude Code
  and VS Code agent mode prompt (VS Code's `ask` overrides its own auto-approve), Cursor's
  `beforeShellExecution` honours `permission: "ask"`, and Codex CLI -- whose parser rejects
  `ask` outright and then fails open on the response it rejected -- gets a deny instead. The
  per-client evidence is cited to vendor source and vendor docs at named refs in
  `docs/enforcement-surfaces.md`.
  **No coverage grade moves.** A control is only as strong as its worst degradation and three
  paths still allow. The plugin descriptions, the marketplace README text and
  `docs/enforcement-surfaces.md` are corrected to state the split rather than a flat
  "fails open"; `gate.guard_runner.evaluate` now returns `(outcome, reason)` or `None`.

- **Fixed: a guard that timed out wrote the command it was gating -- credentials included
  -- to stderr.** `subprocess.TimeoutExpired.__str__` embeds the argv it was given, which
  for `gate.guard_runner.run_guard` is bash, the guard script, and every token of the
  command. Printing it reached the agent's own transcript, which is exactly what the same
  function's parse-failure branch and `log_outcome` both refuse to do, and for the same
  reason: commands routinely carry bearer tokens and passwords. The timeout branch now
  reports the timeout alone. `OSError` and `UnicodeError` keep their detail -- those name
  the interpreter and an offset, not the command.
- **Coverage taxonomy: a fourth in-agent level, `fail-to-ask`, and an ordering.** The
  vocabulary graded on one axis -- what the HOST does when our hook never runs -- so a
  control that degrades to silently allowing and one that degrades to prompting a human
  both read `best-effort`. Those are not the same promise, and a grading layer that cannot
  rank a control above ours is not measuring anything. The grade is now derived from two
  inputs: the host's block behaviour and fail mode (agentseam's matrix) and the control's
  own degradation (`compile.levels.CONTROL_DEGRADES_TO`). `compile.levels.level_rank`
  orders the in-agent ladder (`none` < `detect` < `best-effort` < `fail-to-ask` <
  `enforceable` < `enforced`) and deliberately refuses to rank `enforced-at-commit`,
  `advisory` and `disabled` against it -- different mechanisms, no honest common scale.
  **No existing grade changed**, and none moves with the ask above either: a mixed control
  is declared at its weakest path, and three of the guard's five undecided paths still
  allow, so `pre-tool-use` and `agent-hooks` stay at `best-effort`. The ladder carries a
  word for something chock does not fully do, which is the point.
- **Docs: stale enforcement grades corrected.** `docs/agentic-risk-coverage.md`,
  `docs/concepts.md`, `docs/architecture.md` and `docs/compatibility.md` still published
  `enforced` for an installed in-agent control and `unsupported` for the empty verdict --
  both superseded by 0.7.0's finer vocabulary and neither checked by anything. The level
  table in `docs/enforcement-surfaces.md` and its ordering are now bound to
  `compile.levels` by `tests/test_surface_doc_matches_code.py`, so this class of drift
  fails a test instead of aging in place.
- **Internal: the level vocabulary moved to `chock.compile.levels`.** `surfaces.py` says
  which surfaces exist per agent; how strong a control on one of them is, is a different
  question and now a different module.
- **Packaging: every published plugin package now carries its own `LICENSE`.** The
  distribution repos hold a licence at the root only, so a plugin directory copied out of one
  arrived with no terms attached. The notice is derived entirely from the policy's own
  `provenance` -- licence from `license`, holder from `author`, year from `created_at` (or
  `updated_at`) -- never from this project's own `LICENSE`, because `chock plugin build` runs
  on anybody's policies and stamping open-coder-ai's copyright into a third party's package
  would be a false claim in the one file where it matters. Nothing is written when the notice
  cannot be derived (a licence whose text chock does not ship, or no year): a missing
  `LICENSE` is a visible gap, an invented one is not. Emitted for `claude`, `codex`,
  `cursor`, `copilot`, and for `agent-plugins` when it builds into a distribution directory
  -- never for the in-place `agent-plugins` build, whose target is the adopter's own
  `.agents/policies/<id>/`.
- **Packaging: the Codex manifest gains its `interface` block.** `.codex-plugin/plugin.json`
  now carries `interface{displayName, shortDescription, composerIcon}`, which directory
  listings render and score. Every field is derived: `displayName` from the policy's own
  `name`, `shortDescription` from the first sentence of its description (the full ones run
  past 900 characters, and the manifest `description` additionally carries the posture
  suffix, which is an enforcement claim rather than a summary), and `composerIcon` from the
  icon this emitter now writes into the package at `assets/icon.svg`. No other field in the
  block has a source in a policy manifest, so none is emitted.
- **Packaging: the emitted icon ships as package data.** `chock/plugin/data/icon.svg`,
  byte-identical to `docs/assets/logo.svg` and 512x512 by its viewBox, pinned in both
  directions by tests -- against the logo it was copied from, and against the built wheel,
  because `docs/` is not in the wheel and package data that is not declared silently is not
  either.
- **Internal: `chock/plugin/listing.py`.** What a listing needs from a package (icon,
  licence, display metadata) is a different question from what a client needs to load it, and
  `build.py` and `codex.py` were both over the 300-line review budget with the two mixed.

## 0.7.0 — Migrate primitives-generation to agentseam

BREAKING-ISH: chock's file layout, coverage vocabulary, and vendored runtime bytes all
change. `agentseam==0.1.0` is a real dependency (staged, not yet published — CI on this
change stays red by design until go-live; see the PR). Every adopter's next `chock sync`
rewrites `.chock/bin/`, `.claude/settings.json`, `.cursor/hooks.json`, and most per-agent
instruction files; some previously-written instruction files (for agents that read
`AGENTS.md` natively) are deleted outright, and `coverage.json` re-grades several
enforcement claims to a more honest, finer-grained word. All five migration-map axes land
in this release (owner decision #7, "Option B"); the full accounting is in the wave's
report, `plan/spine-a/reports/w7.md` on `open-coder-ai/org-plan` (private).

- **Runtime: vendored PreToolUse/SessionStart runners are now agentseam's bundle, not a
  hand-written cross-vendor adapter.** `.chock/bin/pretooluse.py` and
  `.chock/bin/sessionstart.py` are gone, replaced by `.chock/bin/claude_code.py`,
  `.chock/bin/cursor.py`, and `.chock/bin/vscode_copilot.py` — one self-contained,
  stdlib-only file per agent (`agentseam.bundler.bundle()` plus chock's own guard-running
  handler spliced in, see `gate/runtime_bundle.py`), instead of one file that sniffed which
  vendor sent a payload by its shape. Claude Code's deny now rides entirely in the JSON
  response body on a clean exit rather than exit code 2 — a deliberate, verified
  improvement (avoids a PowerShell-wrapper exit-code collapse and a command-line leak into
  the UI on some vendors), not a regression. Plugin packages (`chock plugin build` for
  claude/cursor/copilot/codex) ship the matching per-agent runtime instead of a shared one.
- **Runtime: `installed_*_policy_ids` keeps its content-comparison identity, verified
  against agentseam's own new opt-in mode.** agentseam's `install()`/`installed()` gained a
  content-comparison mode this wave (built by a prior worker specifically so a
  multi-fragment consumer like chock would not have to keep re-deriving it). chock's own
  three `installed_*_policy_ids` functions keep their existing, already-correct
  content-comparison logic rather than delegating to it: agentseam's mode does an exact
  string compare with no hook for machine-independent normalization, and chock's committed
  `.claude/settings.json` must compare equal across machines with different baked
  interpreter paths — delegating would have reintroduced the exact cross-machine
  coverage-flip bug `_normalize_fragment` exists to prevent. The required behavior (a
  guard's compiled fragment changing drops its installed claim) is intact and tested.
- **Permissions: `claude_managed.py` is unchanged, on verified evidence.** Checked directly
  against Claude Code's own documentation (`code.claude.com/docs/en/permissions`, read
  2026-08-29): permission rules cannot match a tool's content field at all — the docs name
  this explicitly and say Claude Code rejects an attempt to do so at parse time — and a
  request for regex/content matching there was closed "not planned" upstream
  (`anthropics/claude-code#37509`). `scan-secrets`'s regex-based managed-setting fragment
  has no equivalent in `agentseam.permissions.plan()`'s model and none is being forced
  through; no protection changes.
- **Instructions: whole-file branded templates are gone, replaced by agentseam's
  marker-block / shared-file model (owner decision #8).** Most agents chock scaffolds for
  read `AGENTS.md` natively (`agentseam.instructions.reads_shared()`) and now get no
  dedicated file at all: `.cursor/rules/*.mdc`, `.cursorrules`, `.windsurf/rules/*.md`,
  `.windsurfrules`, `codex.md`, `.kimi-code/AGENTS.md`, `.github/copilot-instructions.md`,
  `.gemini/GEMINI.md`, and `.github/agents/*.agent.md` are no longer written — their
  content lives only in `AGENTS.md`'s own managed pointer block. Agents that do not read
  `AGENTS.md` natively (claude, aider, devin, grok, replit, tabnine, antigravity) get a
  marker-delimited block in their own file instead of a whole-file claim, so adopter
  content elsewhere in that file survives untouched — coexistence a whole-file template
  could never offer. Claude Code's own file moves from `.claude/CLAUDE.md` to `CLAUDE.md`
  at the repo root (agentseam's preferred path). Aider is the one exception: agentseam's
  model cannot express `.aider.conf.yml` (a real config file, not a marker-block target),
  so chock still ships it directly alongside the marker block it writes into
  `CONVENTIONS.md`.
- **Coverage: `coverage_level()` adopts agentseam's five-tier vocabulary for in-agent
  surfaces (owner decision #9).** `pre-tool-use`/`agent-hooks`, once installed, no longer
  read a flat `enforced` — they return whichever of `enforced`/`enforceable`/`best-effort`
  the mapped agent's own verified capability row earns
  (`agentseam.matrix.enforcement_level`). claude_code's PreToolUse is FAIL_OPEN, so it now
  reads `best-effort`, never `enforced`; cursor's is FAIL_CONFIGURABLE, so it reads
  `enforceable`. `enforced-at-commit` and `advisory` stay chock's own words for its
  git-hook/CI-gate and ambient-rule surfaces, which are outside agentseam's per-agent-hook
  model; `unsupported` is renamed `none`, agentseam's own word for the same claim. A
  companion `open-coder-ai/chock-catalog` PR re-renders the seven guard-shipping policies'
  docs and coverage matrix to the same honest wording (their own descriptions already said
  "best-effort"; only the machine-readable label was overclaiming).

## 0.6.0 — Agent-hooks `py` fallback and INT-3 verb list

MINOR: the agent-hooks emitter output changes, so an adopter's next `chock sync` /
`chock plugin build` rewrites `.github/hooks/*.json`. No credited enforcement surface
changes — the guard runs the same, just with one more way to find an interpreter.

- **Agent-hooks Bash resolver adds the `py` launcher fallback.** The Bash branch resolved
  `command -v python3 || command -v python`; the PowerShell branch already tried `py`. On a
  Windows checkout where only the `py` launcher is on PATH (no `python3`/`python`), the Bash
  hook exited "no python interpreter found" and the guard failed open. It now also tries
  `py`, matching the PowerShell branch, so the two agree about where enforcement holds.
- **INT-3 recognises `pin` as a verb.** `pin` was missing from the verb-prefix set, so a
  policy id like `pin-github-actions` drew a spurious "does not start with a verb" warning
  even though pinning is exactly what it does. Added `pin`; `block`/`protect`/`scan`/`verify`
  were already there.

## 0.5.0 — Managed-setting and SKILL honesty

MINOR: the Claude managed-setting emitter and the generated SKILL note change, so an
adopter's next `chock sync` / `chock plugin build` rewrites those artifacts. No credited
enforcement surface changes — both are non-credited/advisory outputs being brought into
line with what they can actually deliver (do-not-claim, applied to the emitter itself).

- **`protect-main-branch` managed-setting is now empty.** It previously emitted a
  branch-blind command-text deny (`commit.*\b(main|master)\b`) that missed a plain
  `git commit` on main and false-positived on "main" in a message. A static managed
  setting cannot resolve branch state, so the honest managed-setting for branch
  protection carries no deny — enforcement lives in its git-hook and ci-gate surfaces,
  which do read the branch.
- **`scan-secrets` managed-setting aligned to the gate.** Added `jks|keystore` to the
  credential-file pattern and more high-confidence credential prefixes (xoxb, sk/rk_live,
  sk-ant, AIza, npm_) so the in-session echo is less of a silent subset of the git-hook.
  Kept lookahead-free for cross-client regex-engine safety; the git-hook remains
  authoritative.
- **SKILL advisory note is conditional on artifact.** A `rule` (advise-tier) policy no
  longer claims it "becomes a git hook that exits non-zero" when compiled — it ships rule
  text and stays advisory. Only `hook` policies carry that line; guard-script policies
  still get the enforced note in the per-client plugin formats.

## 0.4.0 — Witnessed enforcement on Cursor and Codex

MINOR: plugin packaging output changes (spec fixes and three new formats), and the
vendored PreToolUse adapter changes -- the deny-dialect and payload-decoding fixes below
mean an adopter's next `chock sync` rewrites it. Every other compiled enforcement
surface is unchanged.

- **Per-vendor marketplace indexing**: `chock marketplace build --tree cursor|codex`
  indexes a vendor's own format tree with the index file its client actually reads --
  Cursor's `.cursor-plugin/marketplace.json` in Cursor's schema, and for Codex the
  legacy `.claude-plugin/marketplace.json` shape it was witnessed consuming from git
  marketplaces -- so each vendor-named distribution repo carries exactly one vendor's
  packages instead of every format tree. Default (`--tree claude`) is byte-unchanged.
- **`cursor` and `codex` plugin formats**: `chock plugin build --format cursor|codex`
  packages a policy for Cursor and OpenAI Codex, with the enforcing hook each vendor
  actually reads. Same guard, same adapter, byte-identical to every other format --
  only the envelope differs. `--format all` now emits five trees.
  - **Cursor** (`.cursor-plugin/plugin.json` + flat `hooks/hooks.json`) subscribes to
    `beforeShellExecution`, the shell-scoped event `chock sync` already installs, so a
    plugin install and a repo install run the identical hook. No `matcher` is emitted:
    under this event the matcher is a regex over the COMMAND TEXT, not a tool name, so
    the other formats' `"Bash"` would match almost nothing and silently disable the
    guard. Cursor ignores Agent Plugins hooks entirely, so this is the only format that
    enforces there.
  - **Codex** (`.codex-plugin/plugin.json` + nested `hooks/hooks.json`) subscribes to
    `PreToolUse` with matcher `Bash` -- Claude's protocol exactly. The legacy
    `.codex-plugin/` manifest is deliberate: Codex's loader DISCARDS hooks from an
    Agent-Plugins-format manifest (`codex-rs/core-plugins/src/loader.rs`), so shipping
    the Copilot package there would install a plugin whose enforcement is deleted at
    load time while its description still claimed it.
- **Codex packages claim witnessed enforcement -- via JSON deny, not exit codes.**
  Probed on a real Codex Desktop install (Windows 11): a trusted PreToolUse hook
  returning the documented exit-2 deny ran the command three times, because Codex wraps
  Windows hook commands in `powershell -Command`, which collapses exit 2 into 1 -- and
  Codex's parser treats that as a failed hook and FAILS OPEN (its only stdout-parsing
  arm is exit 0). With the deny carried in `hookSpecificOutput.permissionDecision` JSON
  on a clean exit, the same command was witnessed BLOCKED (2026-08-24). The adapter now
  speaks that dialect to Codex-shaped payloads (`turn_id` present); Claude Code keeps
  its witnessed exit-2 path. Conditions stated in the package posture: Codex hooks are
  UNTRUSTED on install until a human approves a per-hook trust review, that trust is
  bound to a hash of the hook command so a plugin update silently voids it until
  re-approved, and every hook failure fails open. The emitted hooks.json also carries no
  top-level `description`: Codex < 0.143.0 rejects the whole file over that one key and
  silently drops every hook in it (openai/codex#30397).
- **Cursor packages DO claim enforcement**, witnessed blocking on a real install after the
  two fixes below, with a benign command in the same session still allowed.
- **Two silent fail-opens fixed, both found by probing a real Cursor install** (neither
  is visible in any documentation, and each would have shipped a package that advertised
  enforcement and delivered none):
  - **Payload decoding.** Cursor prefixes its hook payload with a UTF-8 BOM, and
    `sys.stdin.read()` decoded those bytes with the platform locale (cp1252 on Windows),
    turning the BOM into three stray characters. `json.loads` then failed, the adapter
    reported "not checked", and returned 0 -- every command ALLOWED. The payload is now
    read as bytes and decoded `utf-8-sig`, which also stops non-ASCII paths being mangled.
  - **Deny signalling.** Cursor documents exit 2 as "equivalent to returning
    `permission: deny`". For plugin hooks that is false: a hook returning exit 2 with the
    reason on stderr was witnessed NOT blocking -- the command ran. The adapter now also
    emits Cursor's stdout response (`{"permission": "deny", "user_message",
    "agent_message"}`) for Cursor-shaped payloads only; Claude and Copilot still get
    exit 2 with an empty stdout, asserted by test.
  Witnessed blocking on a real Cursor install after both fixes, with a benign command in
  the same session still allowed.
- **A silent guard can no longer become a silent allow**: the PreToolUse adapter now
  guarantees a reason on stderr for every deny. Codex records exit 2 with an empty
  stderr as a FAILED hook ("did not write a blocking reason to stderr",
  `codex-rs/hooks/src/events/pre_tool_use.rs`) and lets the command run, so a guard that
  denied without explaining itself would have enforced nothing there while every other
  client showed a deny. Harmless elsewhere; load-bearing on Codex.
- The marketplace lockfile test now derives its expected tree set from `FORMATS` rather
  than an enumerated list -- the same under-coverage a hand-written list caused once
  before, where a newly added tree escaped the check while it still read as complete.

- **Bundled authoring skills use the same flat metadata**: the five shipped skills
  (chock-init, eval, optimize, policy-init, validate) carried the nested `chock:`
  object the packaged-policy fix removed — two metadata dialects in one project.
  Their frontmatter is now the same flat string map (lists comma-joined, booleans
  as "true"/"false"), and manifest ingestion decodes the typed fields; the derived
  manifests are proven identical. Old nested frontmatter still loads, so
  third-party skills are unaffected.
- **SKILL.md `metadata` spec fix**: the Agent Skills spec (which Agent Plugins 1.0
  defers to for SKILL.md) requires `metadata` to map string keys to string values;
  the packaged skills nested a `chock:` object there, which awesome-copilot's `vally`
  linter rejected ("Metadata values must be strings"). Now a flat map with dotted
  keys (`chock.artifact`, `chock.enforcement`, `chock.coverage_without_chock`) —
  same facts, spec-conformant shape. A parsed-not-substring test pins the constraint.
- **Posture-aware skill frontmatter**: a hook-carrying package's SKILL.md used to
  state `coverage_without_chock: advisory` next to the very hook that enforces —
  one package stating and refuting a claim at once. The frontmatter now swaps the
  advisory claim for the shipped hook's path (`chock.hooks`), the same substitution
  the hook emitters already made in plugin.json and the closing note.
- **`copilot` plugin format**: `chock plugin build --format copilot` emits the Agent
  Plugins 1.0 layout — root `plugin.json`, `skills/` — with the enforcing PreToolUse
  hook under `com.github.copilot/hooks/hooks.json`, the namespace directory VS Code
  documents for Agent Plugins hook bundles and non-Copilot clients must ignore. This
  is the shape spec-validating marketplaces (awesome-copilot) accept; the Claude
  layout, which Copilot also reads, keeps its manifest in `.claude-plugin/` and fails
  their intake. Hook command, adapter and guard are byte-identical to the Claude
  package's (asserted in tests): two formats, one enforcement system. The posture is
  scoped to this format's audience — generic Agent Plugins clients are required to
  ignore `com.github.copilot`, so the description names where the hook enforces
  (documented for VS Code agent mode) and that a namespace-ignoring client gets the
  advisory skill only. Hook-carrying packages replace the `coverage_without_chock`
  extension claim with the hook's location, and the dangling `manifest: manifest.yaml`
  pointer (a file this out-of-place format never ships) is dropped — each package
  carries only claims that are true of it. `--format all` now emits three trees.

## 0.3.0 — Native pre-tool-use for Copilot CLI and VS Code

- **`agent-hooks` enforcement surface**: `chock sync` now writes `.github/hooks/chock.json`,
  the native pre-tool-use hook read by **Copilot CLI and VS Code agent mode**. Both honour
  exit 2 as deny (witnessed blocking on both). The hook resolves its interpreter at run time
  — skipping the Windows Store `python3` alias stub that made hooks error — and finds the
  repo root with `git rev-parse`, so the committed file is portable with no baked path. One
  adapter now parses all three payload shapes (Claude, Cursor, Copilot/VS Code). Coverage is
  credited `enforced` for copilot/vscode only when the file is verifiably installed. Guards
  are bash-oriented, so on Windows PowerShell they catch bash-syntax commands but not
  PowerShell-native destructive syntax until a PowerShell guard ships (documented caveat).

## 0.2.0 — First release with an external contribution

MINOR: new features and adapters; compiled output for existing policies is unchanged
(golden-suite verified), but new surfaces exist.

- **Antigravity CLI adapter** — contributed by @alexsmolya, the project's first external
  contribution: `.agents/rules/chock.md` workspace rule, ambient/git-hook/CI surfaces
  (deliberately not pre-tool-use: no installer exists, so no claim is made).
- **Claude-format plugin emitter**: `chock plugin build --format claude|all --out-dir`
  renders each policy into Claude Code's plugin layout (read natively by Claude Code,
  Copilot CLI, VS Code and Grok Build), with the fail posture stated verbatim in every
  emitted description and per-format subtrees so no package has to lie for another
  client. Stale-output reconciliation, duplicate-id refusal.
- **`chock marketplace build`**: derives the marketplace index, a content-addressed
  `chock-market.lock` (sha256 per published plugin directory), and a generated
  `PLUGINS.md` catalog page from the built packages — never hand-listed, drift-checked.
- **Hook interpreter honesty**: the emitted hook command stays a single `python3`
  invocation -- a review of the proposed `python3 || python` fallback proved a chain
  can erase a deny verdict (a deny exit followed by a missing-interpreter exit reads
  as an error, and the first leg consumes stdin), so it was rejected with
  measurements. Instead every emitted description now states the per-client fail
  posture: fail-open clients allow silently without `python3` and a usable bash;
  fail-closed clients (VS Code) refuse matched commands; Windows needs the
  Microsoft Store `python3` alias disabled or Python installed.
- **Supply chain**: the Marketplace action no longer interpolates workflow inputs
  into shell (two HIGH template-injection alerts, fixed by env indirection); GitHub
  Releases are created by the runner's own `gh` CLI instead of a third-party action;
  the semgrep scanner installs hash-pinned via compiled requirements; Dependabot
  gets a 7-day cooldown.
- **CI pressure testing**: zizmor, actionlint, ShellCheck, and Semgrep (with custom
  rules encoding this project's own incidents) run as required checks; all three
  public repos are at zero open code-scanning alerts.
- **Fix**: `chock remove` refuses when a policy's manifest cannot be read — an
  unreadable manifest previously read as "not mandatory" and allowed deletion.
- **Fix**: `frontier_ingest` no longer prints and exits at import time; frontier
  validation shares one `STANDARDS_DIR` with ingestion.
- **Tests**: 755 (from 736); statement coverage 83%; new suites for the plugin
  emitter, marketplace, `chock remove`, and the frontier validation modes.


## 0.1.1 — Hardening and governance PATCH

Compiled output is byte-identical to 0.1.0 (golden-suite enforced); everything here is
validation, supply chain, documentation, and tests.

- **Fix**: policy-id validation now uses `fullmatch` — an id with a trailing newline
  was accepted by Python's `$`-before-newline matching. Found by the new
  property-based suite.
- **Supply chain**: every GitHub Action pinned to a commit SHA; least-privilege
  `permissions:` on all workflows; pip installs hash-pinned via compiled requirements;
  release artifacts now carry build provenance attestations; weekly coverage-guided
  fuzzing (atheris) of the id and selection parsers.
- **Governance docs**: GOVERNANCE.md (decision-making, roles, access continuity) and a
  public roadmap index; SECURITY.md gains advisory URL and response timelines.
- **Tests**: property-based suite for id validation and agent selection; unit suites
  for the lifecycle umbrellas and frontier ingestion (statement coverage 78% → 81%).
- **Marketplace**: the GitHub Action is listed as "Chock Governance Check" with branding.

## 0.1.0 — First public release

Everything below is the launch surface; `0.0.1a0` was a name-claiming pre-release, so this
is the first version with real contents.

- **Policies as code**: versioned policy manifests committed to the repo, compiled by
  `chock sync` to every enforcement surface each agent supports.
- **Enforcement surfaces**: pre-tool-use guards (Claude Code and Cursor), git hooks,
  a CI gate (`chock sync --ci` + commit-range mode), and ambient rules for
  instruction-file agents.
- **Coverage honesty**: per-agent, per-policy claims at three levels — `enforced`,
  `enforced-at-commit`, `advisory` — raised only when the installed mechanism is
  witnessed for that agent.
- **Arm-on-clone**: cloned repos re-arm through an ambient rule plus a consented
  SessionStart hook; git never clones hooks and Chock does not fight that boundary.
- **Catalog adoption**: `chock add <id>` installs hash-pinned policies from any
  catalog, public or private; every published policy ships with replayed evals.
- **Compliance frameworks built in**: OWASP Agentic Security Top-10, MITRE ATLAS,
  NIST AI RMF, EU AI Act — manifests claim framework coverage, `chock check` reports it.
- **Versioning contract**: PATCH releases never change compiled output (enforced by a
  golden-file suite); MINOR releases may.

## 0.0.1a0 — Name-claiming pre-release

Not a feature release. PyPI has no name-reservation mechanism — a project name is claimed only
by uploading a distribution — so this exists to claim `chock`, and to exercise the
release pipeline once on a disposable version before it matters.

Published as a pre-release rather than as `0.0.1` because PyPI versions are immutable: a
`0.0.1` uploaded now could never be replaced by the real one.

Contents are `0.0.1` as described below, plus Agent Plugins packaging. Treat it as early
access — the CLI surface, the manifest schema and the compiled output may all change before
`0.0.1`.

## 0.0.1 — Initial public baseline

First published baseline of the agent-neutral policy-engineering framework:

- Neutral policy spec with traced invariants (`spec/enforcement-matrix.md`), JSON schemas, and methodology.
- Meta-skills: `policy-init`, `validate`, `eval`, `optimize`, `chock-init` — all at lifecycle `review`, trust tier `community`.
- Deterministic tooling: validator, registry with script-integrity hashes, and dispatcher-based git hooks.
- Security posture: ambient-context integrity (SEC-1..7), deterministic-first execution (DET-1..4), effects/approval gating (EFF-1).
- Thin adapters for 13 agent surfaces with `AGENTS.md` as the single source of truth.
- The reference repo validates at 0 errors, 0 warnings, 0 infos under its own tooling.

Packaging and layout:

- Tooling ships as an installable `chock` package (`src/chock/`) with one
  CLI and activity-named subpackages: `validation/`, `registry/`, `hooks/`, `authoring/`.
- CLI subcommands: `validate`, `registry`, `install-hooks`, `check-matrix`.
- Taxonomy is agent-only: deliverables are skill, rule, hook, command, and subagent; no worker or headless orchestrator runtime.
- Every file in the repo respects the 300-line review budget, enforced by `tests/test_repo_standards.py`.
- Single owner handle `open-coder-ai` across provenance, reviews, and CODEOWNERS.

Pre-release iteration history (internal versions 0.2.x–0.6.x) is preserved in git log.
