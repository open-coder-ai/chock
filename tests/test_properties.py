"""Property-based tests for the two parsers whose outputs become shell tokens and paths."""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chock.compile.surfaces import parse_agent_selection
from chock.policy_id import POLICY_ID_RE, InvalidPolicyId, validate_policy_id

SAFE_CHARS = set(string.ascii_lowercase + string.digits + "-")

valid_ids = st.from_regex(POLICY_ID_RE, fullmatch=True)

VOCAB = {name: object() for name in ("alpha", "beta", "gamma", "delta")}
vocab_names = st.sampled_from(sorted(VOCAB))


@given(valid_ids)
def test_accepted_ids_contain_only_shell_and_path_safe_chars(policy_id: str) -> None:
    validate_policy_id(policy_id, policy_id)
    assert set(policy_id) <= SAFE_CHARS
    assert not policy_id.startswith("-")


@given(st.text(min_size=1, max_size=80))
def test_validator_agrees_with_the_published_pattern(candidate: str) -> None:
    if POLICY_ID_RE.fullmatch(candidate):
        validate_policy_id(candidate, candidate)
    else:
        with pytest.raises(InvalidPolicyId):
            validate_policy_id(candidate, candidate)


@given(valid_ids, st.sampled_from(list('";$`|&<>()/\\ \n\t')))
def test_one_hot_byte_anywhere_is_rejected(policy_id: str, hot: str) -> None:
    for pos in (0, len(policy_id) // 2, len(policy_id)):
        poisoned = policy_id[:pos] + hot + policy_id[pos:]
        with pytest.raises(InvalidPolicyId):
            validate_policy_id(poisoned, poisoned)


@given(valid_ids, valid_ids)
def test_id_must_equal_folder(policy_id: str, folder: str) -> None:
    if policy_id == folder:
        validate_policy_id(policy_id, folder)
    else:
        with pytest.raises(InvalidPolicyId):
            validate_policy_id(policy_id, folder)


@given(st.lists(vocab_names, min_size=1, max_size=8))
def test_selection_is_deduped_and_order_preserving(names: list[str]) -> None:
    result = parse_agent_selection(names, valid=VOCAB)
    assert len(result) == len(set(result))
    first_seen = list(dict.fromkeys(names))
    assert result == first_seen


@given(st.lists(vocab_names, min_size=1, max_size=8))
def test_comma_and_space_forms_are_equivalent(names: list[str]) -> None:
    assert parse_agent_selection([",".join(names)], valid=VOCAB) == parse_agent_selection(names, valid=VOCAB)


@given(st.lists(vocab_names, min_size=1, max_size=8))
def test_parsing_is_idempotent(names: list[str]) -> None:
    once = parse_agent_selection(names, valid=VOCAB)
    assert parse_agent_selection(once, valid=VOCAB) == once


@given(st.lists(vocab_names, min_size=0, max_size=4), st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12))
def test_any_unknown_name_stops_the_run(known: list[str], stranger: str) -> None:
    if stranger in VOCAB:
        return
    with pytest.raises(ValueError, match="unknown agent"):
        parse_agent_selection([*known, stranger], valid=VOCAB)
