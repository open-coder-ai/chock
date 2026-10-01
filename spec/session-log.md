# Session log

A small, local, per-session record of the tool calls an agent made, appended to by chock's
in-agent runtime so a policy script can ask "was this file read before", "did a `WebFetch` of this
URL fail earlier", "how many times was this command retried".

## When it is written

Only for a policy whose gate is `kind: script` and declares `"on": [tool_call]` (see
[`gate-dsl.md`](gate-dsl.md)). Its hooks are installed without a matcher so they see every tool:

| hook | logs | vendors |
|------|------|---------|
| the gate's PreToolUse hook | a `pre` record, after the verdict (so the script reads prior calls only) | Claude Code, Codex CLI, Cursor, Gemini CLI, Copilot |
| PostToolUse recorder | a `post` record, `outcome` `ok` or `error` | Claude Code, Codex CLI, Cursor, Gemini CLI |
| PostToolUseFailure recorder | a `post` record, `outcome` `error` (Claude Code fires this instead of PostToolUse when a tool fails) | Claude Code, Cursor |

Copilot's own hooks file has no witnessed `PostToolUse`, so Copilot sessions carry `pre` records
only. A vendor with no `tool_call` entry writes no log. A `content_regex` gate reads no session and
writes none. Any `script` gate (at `tool_use` or `tool_call`) is handed the session handle; the log
exists only while some `tool_call` script policy is installed.

## File

`.chock/state/<session_id>.jsonl`, relative to the repository root. `<session_id>` is the vendor's
session id with everything but letters, digits, `.`, `_` and `-` removed (`unknown` when the
payload has none). `chock sync` adds `.chock/state/` to `.gitignore`.

- **Bounded.** The last 500 records are kept; older ones are dropped as new ones arrive.
- **Pruned.** A log file untouched for 7 days is deleted the next time any hook writes one.
- **Best effort.** A failure to write is swallowed; the log never changes a verdict.
- **Deduplicated.** Two policies' hooks logging one call write one record (same `phase` and
  `tool_use_id`; with no id, the same second, tool and input).

## Record

One JSON object per line, keys sorted:

```json
{"input": {"url": "https://example.com/a"}, "outcome": null, "phase": "pre", "session_id": "s1", "tool": "WebFetch", "tool_use_id": "toolu_01", "ts": "2026-09-29T10:15:00Z"}
```

| key | type | notes |
|-----|------|-------|
| `ts` | string | UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `session_id` | string | as in the file name |
| `phase` | string | `pre` (before the call) or `post` (after it ran) |
| `tool` | string | the vendor's tool name, e.g. `Bash`, `Read`, `mcp__Firecrawl__firecrawl_scrape` |
| `input` | object | a summary with any of `path`, `command`, `url`; each at most 300 characters |
| `outcome` | string or null | `null` before the call; `blocked` on a `pre` record the gate refused; `ok` or `error` on `post` |
| `tool_use_id` | string or null | the vendor's id for the call, when it sends one |

`input` is never the tool's arguments as sent. `path` is the file path as the tool named it.
`command` is the first line only, with the value of every `NAME=value` word replaced by `***`.
`url` has its userinfo, query and fragment removed. File contents, edit text, environment values
and tool output are never recorded. `outcome: "error"` is read from the payload
(`tool_response.is_error` / `success: false` / non-zero `exit_code` / an `error` field) or from a
failure event.

## Reading it

A script gate receives `"session": {"id", "log_path", "tool_use_id"}` on stdin. Hooks of one call
can run concurrently, so the log may already hold the current call's own `pre` record;
`tool_use_id` names it so a script can leave it out.

`chock sync` vendors a stdlib helper, `chock_session.py`, beside the per-agent runtimes (source:
`src/chock/gate/session_reader.py`), while a `tool_call` script gate is installed. Import it, or copy it:

```python
import json, os, sys

payload = json.load(sys.stdin)
sys.path.insert(0, os.path.join(payload["repo_root"], ".chock", "bin"))
import chock_session as log

prior = log.prior(payload["session"])          # records of earlier calls
url = payload["input"].get("url", "")
if log.failed(prior, tool=payload["tool"], url=url):
    sys.exit("this URL already failed in this session; try another source")
if log.count(prior, tool="Bash", phase=log.PRE, command="make test") >= 3:
    sys.exit("make test already ran 3 times; stop retrying and read the failure")
```

`entries(session_or_path)` returns every readable record, oldest first (a missing or damaged log
yields none); `prior(session)` drops the current call; `matching(records, tool=, phase=,
outcome=, path=, command=, url=)` filters; `count` and `failed` are built on it. A script may also
read the JSON lines directly.

## Stop ledger

A separate file, `.chock/state/<session_id>.stop.jsonl`, counts a turn's Stops so a client that
re-enters its Stop hook is refused at most 3 times while findings remain, then warned (see
`gate-dsl.md`). Every Stop gate writes one record per Stop, whatever policies are installed; it is
not part of the tool-call log above, and `chock_session.py` does not read it. Bounded and pruned
like the tool-call log (500 records, 7 days).

```json
{"anchor": false, "findings": ["3f2a9c0d1e4b5a67"], "phase": "stop", "policy": "scan-secrets", "reentry": 1, "session_id": "s1", "ts": "2026-09-29T10:15:00Z", "turn": "t1", "verdict": "block"}
```

| key | type | notes |
|-----|------|-------|
| `ts`, `session_id` | string | as above |
| `phase` | string | `stop` |
| `policy` | string | the Stop gate's policy id |
| `turn` | string or null | the vendor's turn id: Codex `turn_id`, Cursor `generation_id`; records of other turns are ignored |
| `reentry` | integer | `0` for a turn's first Stop, then one more per re-entry |
| `anchor` | boolean | on a re-entry: the count restarted here because the earlier records were missing or damaged |
| `findings` | list of strings | one 16-hex digest per flagged file, of its path and content; never either one |
| `verdict` | string | `block`, `allow` or `warn` |

A re-entry counts only an unbroken run of well-formed records of this session and policy (and
turn) back to a `reentry: 0` or `anchor` record. Anything else is `untracked`: refused again and
anchored, or, when the ledger cannot be written and the client sends no count of its own, the turn
ends at once with the warning. Cursor's `loop_count` is believed over the ledger.

The warning goes out as `systemMessage` (Claude Code, Codex, VS Code Copilot) and on stderr (every
vendor). Each re-entry is a gate-log record under surface `stop-reentry`, `kind: reentry`, with
`reentry` (its index), `verdict` (`block`, `allow`, `warn`) and `reentry_verdict` (`refused`,
`clean`, `cap-reached`, `untracked`). The warn is held (`would_block: true`, `would_action:
block`), so it is written even with `CHOCK_GATE_LOG=0`.

### A Stop whose payload cannot be read

No session id is readable then, so `unreadable-stop.jsonl` beside the session files in `.chock/state/` counts the repository's refusals
instead: records `{"phase": "unreadable-stop", "verdict", "at" (epoch seconds), "reentry"}`. Refusals
inside a 600 second window count; 3 are refused, the next ends the turn with a `systemMessage` and
stderr warning and a held `warn` record (`reentry_verdict: unreadable`), until the oldest refusal
ages out. A record that does not parse counts as none, and a ledger that cannot be written keeps refusing.

## Privacy

Nothing leaves the machine: the log is a local file in the repository's own `.chock/state/`,
ignored by git, written and read only by chock's vendored runtime and the policy's own script. No
chock component uploads it, and a script's own network use is bound by SEC-2 like any other.
