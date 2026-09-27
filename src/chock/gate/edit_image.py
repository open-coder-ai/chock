"""The file an edit call would leave behind, for a gate that judges whole files.

A write call carries the file; an edit call carries only the text it replaces and the text it
puts in. Extracted into the vendored per-agent runtime beside write_gate, so it is stdlib-only
and may not import chock.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The (old, new) spellings an edit call uses: Claude Code, Gemini CLI, Kimi and Grok write
#: snake_case, VS Code's replace tools camelCase, the memory tool's str_replace `_str`.
_EDIT_KEYS = (("old_string", "new_string"), ("oldString", "newString"), ("old_str", "new_str"))
#: A batched edit (Claude Code's MultiEdit) lists its replacements, applied in order.
_EDIT_LIST = "edits"
_CRLF = "\r\n"


def _tool_input(event):
    raw = getattr(event, "raw", None)
    tool_input = raw.get("tool_input") if isinstance(raw, dict) else None
    if isinstance(tool_input, str) and tool_input[:1] == "{":
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            return {}
    return tool_input if isinstance(tool_input, dict) else {}


def _pair(item):
    if not isinstance(item, dict):
        return None
    for old, new in _EDIT_KEYS:
        if isinstance(item.get(old), str) and isinstance(item.get(new), str):
            return item[old], item[new], item.get("replace_all") is True
    return None


def edit_replacements(event):
    """The (old, new, replace_all) replacements an edit call applies, in order; None if not an edit."""
    tool_input = _tool_input(event)
    listed = tool_input.get(_EDIT_LIST)
    found = [_pair(item) for item in (listed if isinstance(listed, list) else [tool_input])]
    if not found or None in found:
        return None
    return found


def _replace(text, old, new, every):
    """`text` with the replacement applied, or None when `old` is not there to replace.

    The file is read with universal newlines, so a CRLF file (a Windows checkout) arrives as
    LF; the call's strings are brought to LF too, whichever ending the client sent them with,
    rather than calling a real edit a failure over line endings.
    """
    old, new = old.replace(_CRLF, "\n"), new.replace(_CRLF, "\n")
    if old == "":
        return new if text == "" else None
    if old not in text:
        return None
    return text.replace(old, new) if every else text.replace(old, new, 1)


def edited_text(event, root=None):
    """The file an edit call would leave behind, or None when it is not an edit or cannot be rebuilt."""
    replacements = edit_replacements(event)
    path = getattr(event, "path", None)
    if replacements is None or not path:
        return None
    target = Path(path)
    if not target.is_absolute():
        target = Path(root if root is not None else Path.cwd()) / target
    try:
        text = target.read_text(encoding="utf-8") if target.exists() else ""
    except (OSError, UnicodeDecodeError):
        return None
    for old, new, every in replacements:
        text = _replace(text, old, new, every)
        if text is None:
            return None
    return text


def added_from_event(event):
    """What an edit call introduces -- what `added_lines` means for it -- or {} for any other call."""
    replacements = edit_replacements(event)
    path = getattr(event, "path", None)
    if replacements is None or not path:
        return {}
    return {str(path): "\n".join(new for _, new, _ in replacements)}
