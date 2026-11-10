"""Weighted edit distance tuned for typical Russian misspellings."""

from __future__ import annotations

# Substitutions that are cheap because they are the usual spelling mistakes: unstressed
# vowel reduction, и/ы after hard consonants, ё/е, and voiced/voiceless pairs.
_CHEAP_PAIRS = {
    frozenset(pair)
    for pair in (
        "оа",
        "еи",
        "иы",
        "её",
        "эе",
        "яе",
        "яи",
        "юу",
        "зс",
        "бп",
        "дт",
        "гк",
        "вф",
        "жш",
    )
}
_SUBSTITUTION_CHEAP = 0.5
_SOFT_SIGNS = "ьъ"
MAX_COST = 2.0


def _substitution(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return _SUBSTITUTION_CHEAP if frozenset((a, b)) in _CHEAP_PAIRS else 1.0


def _insertion(previous: str | None, char: str) -> float:
    if char in _SOFT_SIGNS:
        return 0.7
    return 0.5 if previous == char else 1.0  # a doubled or missing double letter


def spelling_cost(typed: str, candidate: str, bound: float = MAX_COST) -> float | None:
    """Edit cost to turn `typed` into `candidate`, or None if it exceeds `bound`.

    Insertions and deletions cost 1 (0.5 for a doubled letter, 0.7 for ь/ъ); substitutions
    cost 0.5 for common confusions (о/а, е/и, и/ы, ...) and 1 otherwise.
    """
    if abs(len(typed) - len(candidate)) > bound:
        return None
    previous_row = [0.0]
    for j, char in enumerate(candidate, 1):
        before = candidate[j - 2] if j > 1 else None
        previous_row.append(previous_row[-1] + _insertion(before, char))
    for i, a in enumerate(typed, 1):
        row = [previous_row[0] + _insertion(typed[i - 2] if i > 1 else None, a)]
        for j, b in enumerate(candidate, 1):
            row.append(
                min(
                    previous_row[j - 1] + _substitution(a, b),
                    previous_row[j] + _insertion(typed[i - 2] if i > 1 else None, a),
                    row[j - 1] + _insertion(candidate[j - 2] if j > 1 else None, b),
                )
            )
        if min(row) > bound:
            return None
        previous_row = row
    cost = previous_row[-1]
    return cost if cost <= bound else None
