"""Closed value sets shared by the storage, service and MCP layers.

The Literal types are the single source of truth; the tuples are derived from them for
runtime validation, so the two can never drift apart.
"""

from __future__ import annotations

from typing import Literal, get_args

Register = Literal["colloquial", "archaic", "formal"]
PartOfSpeech = Literal["noun", "verb", "adjective", "adverb", "expression", "pronoun", "other"]
TranslationLanguage = Literal["en", "de"]
DisplayLanguage = Literal["en", "de", "both"]
Level = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

REGISTERS: tuple[str, ...] = get_args(Register)
PARTS_OF_SPEECH: tuple[str, ...] = get_args(PartOfSpeech)
LANGUAGES: tuple[str, ...] = get_args(TranslationLanguage)
DISPLAY_LANGUAGES: tuple[str, ...] = get_args(DisplayLanguage)
LEVELS: tuple[str, ...] = get_args(Level)
