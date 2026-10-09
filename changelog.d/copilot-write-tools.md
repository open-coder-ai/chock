- **Copilot CLI: the write gate and the toggle-file guard now judge `create` and `apply_patch` before the write.**
  Copilot runs a plugin's `PreToolUse` hook on `Write|Edit` for its `create`, `edit`, `str_replace_editor` and
  `apply_patch` tools, but passes the tool's own arguments: `create` carries `file_text`, and `apply_patch`
  carries the patch as the bare `tool_input` string (or under `input`/`patch`). The runtime read neither, so in
  the Copilot witness run (2026-10-08) an unpinned workflow and a write of `{}` to `.chock/guardrails.json`
  landed and were refused only at turn end. Both are now read, and the turn-end check stays. `edit`
  (`old_str`/`new_str`) was already judged. An `apply_patch` that deletes a file is still not refused at
  write time; a deletion that loosens a toggle is refused at turn end. Copilot keeps its "turn end only" label
  until a witness re-run.
