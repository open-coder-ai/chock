"""README.md stays within its word-count budget once tables and code are stripped."""

from __future__ import annotations

import check_readme_wordcount


def test_readme_word_count_is_in_budget() -> None:
    text = (check_readme_wordcount.Path(__file__).resolve().parents[1] / "README.md").read_text()
    count = check_readme_wordcount.stripped_words(text)
    assert check_readme_wordcount.LOW <= count <= check_readme_wordcount.HIGH, count
