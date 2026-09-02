"""Coverage-guided fuzzing (atheris) of the parsers whose outputs become shell tokens.

The invariant under test is the same one the Hypothesis suite states example-free:
anything `validate_policy_id` ACCEPTS must be safe to splice into bash and filesystem
paths, and `parse_agent_selection` must either return known names or raise — never
silently shrink a selection. The property suite already caught `.match` blessing a
trailing newline; this harness walks the input space with coverage feedback instead
of random generation.

Linux-only (atheris ships manylinux wheels); run by .github/workflows/fuzz.yml.
Local run:  pip install -r requirements/fuzz.txt && python fuzz/fuzz_policy_id.py
"""

from __future__ import annotations

import string
import sys

import atheris

with atheris.instrument_imports():
    from chock.compile.surfaces import parse_agent_selection
    from chock.policy_id import InvalidPolicyIdError, validate_policy_id

SAFE = set(string.ascii_lowercase + string.digits + "-")
VOCAB = {"alpha": 0, "beta": 0, "gamma": 0}


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    candidate = fdp.ConsumeUnicodeNoSurrogates(64)

    try:
        validate_policy_id(candidate, candidate)
    except InvalidPolicyIdError:
        pass
    else:
        # Acceptance implies shell/path safety -- the project's core id invariant.
        assert candidate and set(candidate) <= SAFE, f"unsafe id accepted: {candidate!r}"
        assert not candidate.startswith("-"), f"flag-shaped id accepted: {candidate!r}"

    groups = [fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 4))]
    try:
        result = parse_agent_selection(groups, valid=VOCAB)
    except ValueError:
        pass
    else:
        # Whatever comes back is known, deduped, and stable under re-parsing.
        assert all(name in VOCAB for name in result), f"unknown name returned: {result!r}"
        assert len(result) == len(set(result)), f"duplicates returned: {result!r}"
        assert parse_agent_selection(result, valid=VOCAB) == result


def main() -> None:
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
