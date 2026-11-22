# Gate event `prompt_submit`

`"on": [prompt_submit]` runs the gate when a prompt is submitted, before the model reads it. Only
`content_regex` and `script` can judge one; `chock check` refuses the others. No `params.tools`.
A gate's `action` is a ceiling, as in [Actions](gate-dsl.md#actions); a client that cannot prompt at this
event turns an `ask` into a refusal.

| kind | reads | verdict |
|------|-------|---------|
| `content_regex` | `content_pattern` searched in the prompt text. No waiver applies: the prompt is live text | a match blocks, with the gate's `message` |
| `script` | JSON on stdin: `{"event": "prompt_submit", "repo_root": "...", "prompt": "<text>", "session": {"id", "log_path", "tool_use_id"}}` | exit `0` allows, `1` blocks, `3` asks, `4` warns; a crash, timeout or missing script takes the declared `action` |

The refusal is the client's own way of rejecting a prompt (agentseam's rendering for that client),
carrying the gate's `message`. It never carries the prompt or the text that matched: a script's own words (stdout or stderr) are not
shown at this event. A script's refusal is the gate's `message`; a crash, timeout or missing script is a fixed
engine message naming the policy and the cause (exited N, timed out, not installed). And the decision log records the
policy and the verdict, never the prompt. A prompt the client did not send as text is refused, not allowed.

The hook is written only for clients agentseam grades able to refuse a prompt (`can_block` at
`prompt_submit`) whose hook config chock may write in the repository: Claude Code, Codex CLI,
Cursor, Devin, Factory Droid, Gemini CLI, OpenHands, Tabnine and Windsurf. Cline, Goose and Grok
are graded detect: they can notice a prompt, never refuse one, so they get no entry and `chock sync`
says so. Junie and Kimi Code keep their hook config in the user's home, and Copilot has no witnessed
prompt key in chock's own hooks file, so none is written there either. Every grade is agentseam's
word for the client and is **untested** here until a live refusal is witnessed.

`file_changed` is not a gate event: agentseam grades it `detect` for Claude Code, Cursor and Goose,
so a hook can notice a change after the write but never refuse it; use `tool_use` to refuse a write.

