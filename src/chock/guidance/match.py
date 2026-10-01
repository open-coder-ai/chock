"""Deterministic plan-to-rule matching: rarity-weighted word overlap, gated by path globs. No model."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_WORD = re.compile(r"[a-z0-9]+")
_MIN_WORD = 3
_MIN_STEM = 3
_ES_ENDINGS = ("sses", "xes", "ches", "shes", "zes")
_KEEP_S = ("ss", "us", "is")
_KEEP_DOUBLE = ("ss", "ll")


def stem(word: str) -> str:
    """A crude, stable stem: enough that file/files and upload/uploading meet."""
    if word.endswith(_ES_ENDINGS):
        return word[:-2]
    if word.endswith("ies") and len(word) > _MIN_STEM + 2:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(_KEEP_S) and len(word) > _MIN_STEM + 1:
        return word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            base = word[: -len(suffix)]
            return base[:-1] if base[-1] == base[-2] and base[-2:] not in _KEEP_DOUBLE else base
    return word


def words(text: str, stopwords: frozenset[str]) -> set[str]:
    """Distinct stemmed words of a text, camelCase split, stopwords and short words dropped."""
    found = _WORD.findall(_CAMEL.sub(r"\1 \2", text).lower())
    return {stem(w) for w in found if len(w) >= _MIN_WORD and w not in stopwords}


@dataclass(frozen=True)
class RuleInfo:
    """What the matcher needs of one catalog rule."""

    id: str
    pack: str
    title: str
    constraint: str
    cwe: tuple[str, ...]
    names: frozenset[str]
    body: frozenset[str]


@dataclass(frozen=True)
class Hit:
    rule: RuleInfo
    score: float


def path_matches(path: str, globs: Iterable[str]) -> bool:
    """Whether a repo-relative posix path matches any right-anchored glob."""
    pure = PurePosixPath(path)
    return any(pure.match(glob) for glob in globs)


def expand(query: set[str], synonyms: Mapping[str, list[str]], stopwords: frozenset[str]) -> set[str]:
    """The plan's words plus what each one implies, from the data map."""
    extra: set[str] = set()
    for word in query:
        for implied in synonyms.get(word, ()):
            extra |= words(implied, stopwords)
    return query | extra


def weights(rules: Iterable[RuleInfo], generic_share: float) -> dict[str, float]:
    """Rarity weight per word across the catalog; words in too many rules carry none."""
    rules = list(rules)
    counts: dict[str, int] = {}
    for rule in rules:
        for word in rule.names | rule.body:
            counts[word] = counts.get(word, 0) + 1
    total = len(rules)
    return {w: math.log(1 + total / n) for w, n in counts.items() if n / total <= generic_share}


def score(rule: RuleInfo, query: set[str], weight: Mapping[str, float], body_share: float) -> float:
    """Rarity-weighted overlap; a word in the rule's name counts in full, one in its body in part."""
    named = sum(weight[w] for w in query & rule.names if w in weight)
    body = sum(weight[w] for w in query & (rule.body - rule.names) if w in weight)
    return named + body_share * body


def rank(
    rules: Iterable[RuleInfo],
    query: set[str],
    limits: Mapping[str, float],
    weight: Mapping[str, float],
) -> list[Hit]:
    """Rules whose name and body the query reaches with enough rare words, best first, ties by id."""
    hits = []
    for rule in rules:
        if len(query & (rule.names | rule.body)) < limits["min_words"]:
            continue
        score_ = score(rule, query, weight, limits["body_share"])
        if score_ >= limits["min_score"]:
            hits.append(Hit(rule, round(score_, 6)))
    return sorted(hits, key=lambda h: (-h.score, h.rule.id))
