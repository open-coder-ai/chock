"""`hook_command` joins no word a shell would read into the command line."""

from __future__ import annotations

import pytest

from chock.hooks.launch import hook_command


@pytest.mark.parametrize(
    "word",
    [
        'x"; touch pwned; "',
        "a b",
        "$(id)",
        "`id`",
        "a;b",
        "a|b",
        "a&b",
        "a\\b",
        "a'b",
        "a>b",
        'a"b/c',
        "a$b/c",
        "a`b`/c",
        "a\\b/c",
        "a\nb/c",
    ],
)
def test_hook_command_refuses_a_word_a_shell_would_read(word: str) -> None:
    with pytest.raises(ValueError, match="hook command"):
        hook_command(".chock/bin/x.py", "--gate", word)
    with pytest.raises(ValueError, match="hook command"):
        hook_command(f".chock/bin/{word}")


def test_hook_command_keeps_a_path_with_a_space_quoted() -> None:
    assert hook_command(".chock/bin/x.py", "--guard", "a b/c.py").endswith('--guard "a b/c.py"')


def test_hook_command_keeps_plain_words_as_they_were() -> None:
    assert hook_command(".chock/bin/x.py", "--gate", "p/gate.json", "plain-id_1").endswith(
        '.chock/bin/x.py --gate "p/gate.json" plain-id_1'
    )
