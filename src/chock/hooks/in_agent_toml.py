"""TOML in-agent install (mistral_vibe): chock's rules as one owned block in the vendor's own file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentseam import adapters
from agentseam.install_config import ConfigUnreadableError, block_bounds, read_text, remove_block, write_block

from chock import vendors
from chock.compile.emitters.in_agent_hooks import generic_pre_tool_config
from chock.hooks import multi_wiring

#: The block owner: `# >>> agentseam >>> chock` ... `# <<< agentseam <<< chock`, beside any other owner's.
OWNER = "chock"


def _read(path: Path) -> str:
    """The file's text; one that is not readable text is refused, never overwritten."""
    try:
        return str(read_text(str(path)))
    except (OSError, ConfigUnreadableError):
        msg = f"{path} is not readable text; leaving it untouched"
        raise ValueError(msg) from None


def _rules(fragment: Any) -> list[dict[str, Any]]:
    return [rule for rule in fragment if isinstance(rule, dict)] if isinstance(fragment, list) else []


_PRE_TOOL = "pre_tool"
_ANY_TOOL = "*"


def _renamed(vendor: str) -> Any:
    """A folded rule with the name agentseam derives from its command, as a rule for that command would carry."""

    def rename(rule: dict[str, Any], command: str) -> dict[str, Any]:
        matcher = None if rule.get("match") == _ANY_TOOL else rule.get("match")
        return {**rule, **generic_pre_tool_config(vendor, command, matcher)[0]}

    return rename


def folded_rules(repo_root: Path, vendor: str, rules: list[dict[str, Any]], kept: set[str], *, write: bool) -> list:
    """`rules` with the pre-tool ones folded into one rule per matcher; every other rule stays as it was."""
    return multi_wiring.collapse_list(
        repo_root,
        vendor,
        _PRE_TOOL,
        rules,
        kept,
        rename=_renamed(vendor),
        write=write,
        eligible=lambda rule: rule.get("type") == _PRE_TOOL,
    )


def _render(vendor: str, rules: list[dict[str, Any]]) -> str:
    return str(adapters.get(vendor).render_config(rules))


def _owned_block(path: Path) -> str:
    """Our block's text in `path`, or "" where the file or the block is absent."""
    if not path.is_file():
        return ""
    text = _read(path)
    bounds = block_bounds(text, OWNER)
    return text[bounds[0] : bounds[1]] if bounds else ""


def install_toml(repo_root: Path, vendor: str, fragments: list[tuple[str, Any]]) -> list[str]:
    """Write every fragment's rules as our one block; with none, remove the block (and a file left empty)."""
    path = Path(repo_root) / vendors.config_path(vendor)
    rules = [rule for _policy_id, fragment in fragments for rule in _rules(fragment)]
    kept: set[str] = set()
    rules = folded_rules(repo_root, vendor, rules, kept, write=True)
    multi_wiring.prune(repo_root, vendor, kept)
    if not rules:
        if _owned_block(path):
            remove_block(str(path), OWNER)
            if not _read(path).strip():
                path.unlink()
        return []
    if path.exists():
        _read(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_block(str(path), _render(vendor, rules), OWNER)
    return [policy_id for policy_id, fragment in fragments if _rules(fragment)]


def installed_toml_ids(repo_root: Path, vendor: str, fragments: list[tuple[str, Any]]) -> set[str]:
    """Policy ids whose every rule is rendered inside our block."""
    try:
        block = _owned_block(Path(repo_root) / vendors.config_path(vendor))
    except ValueError:
        return set()
    every = [rule for _policy_id, fragment in fragments for rule in _rules(fragment)]
    folded = folded_rules(Path(repo_root), vendor, every, set(), write=False)
    if not all(_render(vendor, [rule]).strip() in block for rule in folded):
        return set()
    return {policy_id for policy_id, fragment in fragments if _rules(fragment)}
