"""Decode OpenRussian form labels (``ru_noun_sg_gen`` ...) into readable grammar."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from openrussian_mcp.domain.normalization import stress

CASES = {
    "nom": "nominative",
    "gen": "genitive",
    "dat": "dative",
    "acc": "accusative",
    "inst": "instrumental",
    "prep": "prepositional",
}
GENDERS = {"m": "masculine", "f": "feminine", "n": "neuter", "pl": "plural"}
NUMBERS = {"sg": "singular", "pl": "plural"}
PERSONS = {
    "sg1": "1st person singular",
    "sg2": "2nd person singular",
    "sg3": "3rd person singular",
    "pl1": "1st person plural",
    "pl2": "2nd person plural",
    "pl3": "3rd person plural",
}
_ORDER = {
    key: index
    for index, key in enumerate(
        [
            *CASES,
            "sg",
            "m",
            "f",
            "n",
            "pl",
            *PERSONS,
            "presfut",
            "present",
            "past",
            "imperative",
            "participle",
            "gerund",
            "active",
            "passive",
        ]
    )
}
_DISPLAY_SEPARATOR = re.compile(r"\s*/+\s*")


def tense_name(aspect: str | None) -> str:
    """OpenRussian's ``presfut`` is present tense for imperfective verbs, future for perfective."""
    if aspect == "imperfective":
        return "present"
    if aspect == "perfective":
        return "future"
    return "present_future"


def describe_form_type(label: str, aspect: str | None = None, pos: str | None = None) -> str:
    parts = label.split("_")
    if label == "ru_base":
        return "dictionary form"
    if len(parts) < 3 or parts[0] != "ru":
        return label
    family, rest = parts[1], parts[2:]
    if family == "noun" and len(rest) == 2:
        return f"noun {CASES.get(rest[1], rest[1])} {NUMBERS.get(rest[0], rest[0])}"
    if family == "adj":
        if rest[0] == "short" and len(rest) == 2:
            return f"short form {GENDERS.get(rest[1], rest[1])}"
        if len(rest) == 2:
            # OpenRussian stores pronoun declensions under adjective labels.
            kind = "pronoun" if pos == "pronoun" else "adjective"
            return f"{kind} {GENDERS.get(rest[0], rest[0])} {CASES.get(rest[1], rest[1])}"
        return rest[0]
    if family == "verb":
        kind = rest[0]
        if kind == "presfut" and len(rest) == 2:
            return f"{tense_name(aspect).replace('_', '/')} {PERSONS.get(rest[1], rest[1])}"
        if kind == "past" and len(rest) == 2:
            return f"past {GENDERS.get(rest[1], rest[1])}"
        if kind == "imperative" and len(rest) == 2:
            return f"imperative {NUMBERS.get(rest[1], rest[1])}"
        if kind == "participle" and len(rest) == 3:
            return f"{rest[1]} {rest[2]} participle"
        if kind == "gerund" and len(rest) == 2:
            return f"{rest[1]} gerund"
    return " ".join(rest)


def display_form(form: str) -> str:
    return _DISPLAY_SEPARATOR.sub(" / ", stress(form) or form)


def _slot(label: str, aspect: str | None) -> tuple[str, list[str]]:
    """Family and nested key path for a form label."""
    parts = label.split("_")
    if label == "ru_base" or len(parts) < 3:
        return "base", []
    family, rest = parts[1], parts[2:]
    if family == "noun":
        return "noun", rest
    if family == "adj":
        if rest[0] in ("comparative", "superlative"):
            return "adjective", [rest[0]]
        return "adjective", rest
    if family == "verb":
        kind, tail = rest[0], rest[1:]
        group = {
            "presfut": tense_name(aspect),
            "participle": "participles",
            "gerund": "gerunds",
        }.get(kind, kind)
        return "verb", [group, "_".join(tail)] if tail else [group]
    return "other", [label]


def form_sort_key(label: str) -> tuple[int, ...]:
    """Paradigm order: singular before plural, nominative before genitive, and so on."""
    return tuple(_ORDER.get(part, 99) for part in label.split("_")[2:])


def paradigm(rows: Iterable[dict[str, Any]], aspect: str | None = None) -> dict[str, Any]:
    """Group form rows into nested tables, e.g. ``{"sg": {"nom": "ко́т", ...}, "pl": {...}}``.

    Several spellings for one slot are joined with " / ". If an entry has forms from more
    than one family (noun, adjective, verb), the tables are nested under the family name.
    """
    values: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for row in sorted(rows, key=lambda r: (form_sort_key(r["form_type"]), r["position"] or 0)):
        family, path = _slot(row["form_type"], aspect)
        bucket = values.setdefault((family, tuple(path)), [])
        text = display_form(row["form"])
        if text not in bucket:
            bucket.append(text)
    families: dict[str, Any] = {}
    for (family, keys), forms in values.items():
        text = " / ".join(forms)
        if not keys:
            families[family] = text
            continue
        node = families.setdefault(family, {})
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = text
    if len(families) == 1:
        only = next(iter(families.values()))
        return only if isinstance(only, dict) else {"base": only}
    return families
