"""Release gate G1, GT-2 docs: every sentence of `docs/floor.md` and of the `--floor` help that states a behaviour
names the test that proves it, as test_managed_emit_deploy_text.py does for deploy.json. A new sentence fails here
until it names its proof; a proof that no longer exists fails too."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from chock.validation import floor_cli

ROOT = Path(__file__).resolve().parents[1]
SUITE = Path(__file__).parent
#: A sentence that states no behaviour of the floor (a disclaimer or a note on testing), so no test can prove it.
NO_BEHAVIOUR = "states no behaviour"

#: docs/floor.md, by each sentence's opening words (bold markers dropped, whitespace collapsed).
DOC_PROOF = {
    "`chock check --floor --base <base> --head <merge result>` judges": "test_a_head_rewrite_of_the_gate_does_not_stop_the_base_gate, test_head_cannot_lower_rollout",
    "It is a preview, and it holds only": "test_docs_every_run_says_it_is_a_preview_and_states_its_conditions",
    "Judge what will land. The base must be an ancestor": "test_head_not_descendant_of_base_is_undecided, test_a_stale_branch_is_undecided_and_its_merge_result_passes",
    "Everything comes from the tree diff": "test_renaming_or_moving_a_test_file_is_refused_as_a_deletion, test_docs_external_diff_and_textconv_never_reach_the_floor, test_a_secret_added_then_removed_is_found_by_the_history_pass",
    "Every git call reads attributes from the base": "test_attributes_come_from_the_base, test_a_git_that_ignores_attr_source_is_undecided",
    "Control plane. A change (add, edit, delete, mode)": "test_mode_and_deletion_changes_are_listed, test_d1_agent_config_at_any_depth_is_refused_and_named",
    "A path that a commit in the range changed": "test_a_guardrail_changed_and_changed_back_is_named",
    "These files define the guardrails": "test_docs_a_listing_says_the_floor_does_not_judge_safety_and_a_person_decides",
    "A person decides.": "test_docs_a_listing_says_the_floor_does_not_judge_safety_and_a_person_decides",
    "Links. Every symbolic link at, inside or above": "test_a_link_above_a_nested_agent_folder_is_undecided, test_a_chain_of_symlinks_is_followed",
    "If it opens a path that is itself control plane, or nothing": "test_a_link_to_another_control_plane_folder_carries_on, test_a_dangling_control_plane_link_carries_on_until_the_head_fills_it, test_a_non_control_plane_hop_is_listed_when_retargeted",
    "Otherwise the run is undecided (exit 2), naming the link": "test_a_dangling_control_plane_link_carries_on_until_the_head_fills_it, test_a_link_above_a_nested_agent_folder_is_undecided",
    "So is a loop, an absolute target": "test_a_control_plane_link_that_cannot_resolve_is_undecided, test_symlinked_agent_folder_into_a_submodule_bump_is_named",
    "The fix: put the target on": "test_a_base_link_whose_target_the_base_adds_to_the_plane_lists_the_target, test_a_link_above_a_nested_agent_folder_is_undecided",
    "A base whose `.chock` is a link or a submodule": "test_symlinked_chock_folder_at_base_is_not_first_adoption, test_docs_a_base_whose_chock_is_a_submodule_is_undecided",
    "Everything else is judged by the base's compiled ci gates and rollout": "test_a_head_rewrite_of_the_gate_does_not_stop_the_base_gate, test_head_cannot_lower_rollout, test_a_base_observe_rollout_softens_history_and_a_warn_gate_never_refuses",
    "No file from the head executes.": "test_no_head_file_is_executed, test_no_head_file_runs",
    "`ask` refuses.": "test_ask_counts_as_a_refusal",
    "A gate that crashes, times out or cannot be read": "test_a_crashing_base_script_gate_is_undecided_whatever_the_rollout, test_docs_a_gate_that_times_out_is_undecided_whatever_the_rollout, test_invalid_json_gate_at_base",
    "A waiver counts only on a line present and unchanged": "test_a_base_waiver_on_a_line_the_pull_request_removes_is_not_honoured, test_a_waiver_the_pull_request_adds_is_not_honoured, test_a_content_waiver_on_an_unchanged_line_still_counts",
    "History. The base's content gates read every blob": "test_a_secret_added_then_removed_is_found_by_the_history_pass, test_control_plane_change_and_revert_secret_in_history",
    "Exit codes: 0 clean, 1 refused, 2 undecided.": "test_e4_text_and_sarif_agree_and_sarif_never_changes_the_exit",
    "`--sarif <file>` writes a log on every run": "test_e4_text_and_sarif_agree_and_sarif_never_changes_the_exit, test_an_undecided_run_replaces_a_stale_sarif",
    "default: exit 1 on any listed path.": "test_d1_agent_config_at_any_depth_is_refused_and_named",
    "`listed`: exit 0, paths still listed": "test_e2_listed_mode_is_clean_and_lists_first",
    "`name/` or `name/**` is the folder and all in it": "test_e1_added_entries",
    "must name a default pattern exactly": "test_d5_removing_the_old_style_pattern_is_undecided_and_names_the_one_to_write, test_a_removal_that_names_no_default_pattern_is_undecided",
    "Each run prints the mode, the number of patterns": "test_mode_and_size_are_stated_when_nothing_is_listed, test_d6_removing_the_any_depth_pattern_lets_the_change_through_and_says_so",
    "An added entry that matches no path at base or head": "test_add_folder_forms",
    "A required status check the pull request cannot redefine. The floor holds only as one.": "test_docs_every_run_says_it_is_a_preview_and_states_its_conditions",
    "That is the repository's own setting, and chock does not verify it.": "test_docs_every_run_says_it_is_a_preview_and_states_its_conditions, test_no_coverage_tier_is_credited_for_the_floor",
    "Committed content only.": "test_docs_only_committed_content_is_judged, test_no_head_file_reaches_the_working_tree",
    "Under `refuse`, every guardrail change needs a privileged merge": "test_ok_add_policy_hook_lock_unrelated, test_an_action_bump_in_the_floor_workflow_is_a_control_plane_change",
    "Under `listed`, you rely on code-owner review": "test_listed_mode_content_gap_is_stated",
    "The content inside them is not judged.": "test_listed_mode_content_gap_is_stated",
    "The list is what chock knows about, not a proof": NO_BEHAVIOUR,
    "If your workflow installs chock from a file": "test_docs_a_file_the_workflow_installs_chock_from_can_be_put_on_the_list",
    "Renames. Renaming or moving a test file": "test_renaming_or_moving_a_test_file_is_refused_as_a_deletion",
    "Windows short names. The 8.3 alias": "test_docs_paths_the_list_does_not_cover",
    "This is untested on Windows.": NO_BEHAVIOUR,
    "`*.code-workspace` files. They are not on the list": "test_docs_paths_the_list_does_not_cover",
    "Submodule content. Only the pointer is seen.": "test_docs_only_a_submodule_pointer_is_seen",
    "A pointer at or inside a control-plane folder is listed": "test_a_gitlink_inside_a_control_plane_folder_is_listed, test_gitlink_at_a_vendor_folder_is_named, test_docs_only_a_submodule_pointer_is_seen",
    "What the history pass does not see:": "test_docs_the_history_pass_does_not_see_other_encodings_commit_messages_or_file_names",
    "Back-merges. A path is named from history": "test_a_guardrail_changed_and_changed_back_is_named, test_a_pull_request_merge_of_a_behind_branch_names_nothing_from_the_base",
    "A branch that merged an older base": "test_docs_a_branch_that_merged_an_older_base_is_named_for_a_later_base_change",
}

#: The `--floor` help, by each clause's opening words (clauses split at `; ` and `. ` outside parentheses).
HELP_PROOF = {
    "Preview: judge base..head": "test_head_not_descendant_of_base_is_undecided, test_a_head_rewrite_of_the_gate_does_not_stop_the_base_gate",
    "a changed guardrail path is listed and, by default, refused": "test_d1_agent_config_at_any_depth_is_refused_and_named, test_the_floor_runs_alone_and_needs_a_base",
    "It holds only as a required check": "test_docs_every_run_says_it_is_a_preview_and_states_its_conditions, test_docs_only_committed_content_is_judged",
    "under `listed` you rely on code-owner review": "test_listed_mode_content_gap_is_stated",
    "The list is what chock knows about": "test_docs_a_file_the_workflow_installs_chock_from_can_be_put_on_the_list",
    "a symlink at, inside or above the list must open a listed path or nothing": "test_a_link_to_another_control_plane_folder_carries_on, test_a_dangling_control_plane_link_carries_on_until_the_head_fills_it, test_a_link_above_a_nested_agent_folder_is_undecided",
    "a renamed or moved test file reads as a deletion": "test_renaming_or_moving_a_test_file_is_refused_as_a_deletion",
}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?<!/)\*\*", "", text)).strip()  # bold markers, not `name/**`


def doc_sentences() -> list[str]:
    """Every sentence of docs/floor.md outside headings, with each YAML comment in its code block as one sentence."""
    blocks, fence, current = [], False, []
    for line in (ROOT / "docs/floor.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
        elif fence and "#" in line:
            blocks.append(line.split("#", 1)[1].strip())
        elif not fence and (line.startswith(("#", "- ")) or not line.strip()):
            blocks.append(" ".join(current))
            current = [line[2:]] if line.startswith("- ") else []
        elif not fence:
            current.append(line)
    blocks.append(" ".join(current))
    found: list[str] = []
    for block in blocks:
        start = len(found)
        for part in re.split(r"(?<=\.|\*)\s+(?=[A-Z`*])", re.sub(r"\s+", " ", block).strip()):
            # A bold lead ("**Renames.**") opens the sentence after it rather than standing alone.
            joined = found.pop() + " " + part if len(found) > start and found[-1].endswith(".**") else part
            found.append(joined)
    return [_flat(sentence) for sentence in found if sentence]


def help_clauses() -> list[str]:
    parser = argparse.ArgumentParser()
    floor_cli.add_arguments(parser)
    [text] = [a.help for a in parser._actions if "--floor" in a.option_strings]
    clauses, depth, current = [], 0, ""
    for i, char in enumerate(text):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char in ";." and depth == 0 and text[i + 1 : i + 2] in (" ", ""):
            clauses.append(current.strip())
            current = ""
        else:
            current += char
    return [c for c in [*clauses, current.strip()] if c]


def _proof_for(sentence: str, proofs: dict[str, str]) -> str:
    owned = [proof for opening, proof in proofs.items() if sentence.startswith(opening)]
    assert len(owned) == 1, f"{len(owned)} proofs for: {sentence}"
    return owned[0]


def _sources() -> str:
    return "".join(path.read_text(encoding="utf-8") for path in sorted(SUITE.glob("test_floor_*.py")))


@pytest.mark.parametrize(
    ("source", "proofs"), [(doc_sentences, DOC_PROOF), (help_clauses, HELP_PROOF)], ids=["docs", "help"]
)
def test_every_behaviour_sentence_has_a_proof_that_exists(source, proofs):
    sources, used = _sources(), set()
    for sentence in source():
        proof = _proof_for(sentence, proofs)
        used.add(proof)
        for name in (part.strip() for part in proof.split(",") if proof != NO_BEHAVIOUR):
            assert f"def {name}(" in sources, (sentence, name)
    stale = [
        opening
        for opening, proof in proofs.items()
        if proof not in used or not any(s.startswith(opening) for s in source())
    ]
    assert not stale, f"no sentence opens with: {stale}"


def test_the_splitters_see_every_sentence():
    """The maps are only as good as the split: the docs give 46 sentences and the help 7 clauses."""
    assert (len(doc_sentences()), len(help_clauses())) == (len(DOC_PROOF), len(HELP_PROOF))
