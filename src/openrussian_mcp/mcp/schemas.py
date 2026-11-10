from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from openrussian_mcp.domain.vocabulary import (
    DisplayLanguage,
    Level,
    PartOfSpeech,
    Register,
    TranslationLanguage,
)

__all__ = ["DisplayLanguage", "Level", "PartOfSpeech", "Register", "TranslationLanguage"]


class WordRef(BaseModel):
    entry_id: int
    word: str = Field(description="Stressed headword")


class TranslationExample(BaseModel):
    ru: str
    translation: str | None = None


class Translation(BaseModel):
    lang: str
    text: str
    info: str | None = Field(
        default=None, description="Usage or government note, e.g. 'за + instrumental'"
    )
    example: TranslationExample | None = None


class Example(BaseModel):
    ru: str = Field(description="Tatoeba sentence with stress marks")
    word: str | None = Field(default=None, description="The linked word as it appears")
    en: str | None = None
    de: str | None = None
    level: str | None = None
    source_url: str
    entry_id: int | None = None


class FormMatch(BaseModel):
    form: str = Field(description="Stressed form")
    grammar: list[str] = Field(description="Readable descriptions, e.g. 'noun genitive singular'")


class MatchInfo(BaseModel):
    headword: bool = Field(description="The query is this entry's dictionary form")
    forms: list[FormMatch] = Field(description="Inflected forms of this entry equal to the query")


class Grammar(BaseModel):
    gender: str | None = None
    animate: bool | None = None
    indeclinable: bool | None = None
    singular_only: bool | None = None
    plural_only: bool | None = None
    incomparable: bool | None = None
    aspect: str | None = None
    aspect_partners: list[str] | None = None
    partners: list[str] | None = None


class Entry(BaseModel):
    entry_id: int
    headword: str
    stressed: str | None = Field(description="Headword with U+0301 stress marks")
    pos: str | None
    rank: int | None = Field(description="Frequency rank; 1 is most frequent")
    rank_shared: bool = Field(
        default=False,
        description="The rank belongs to the written word and is shared with a homograph entry",
    )
    level: str | None = Field(description="CEFR level from OpenRussian, if any")
    grammar: Grammar
    usage: str | None = None
    translations: list[Translation]
    forms: dict[str, Any] | None = Field(
        default=None, description="Inflection tables, e.g. {'sg': {'nom': ..., 'gen': ...}}"
    )
    relations: dict[str, list[WordRef]] | None = None
    derived_from: WordRef | None = None
    in_expressions: list[WordRef] | None = None
    expression_parts: list[WordRef] | None = None
    tags: list[str] | None = None
    examples: list[Example] | None = None
    audio_url: str | None = None
    match: MatchInfo | None = None
    stress_match: bool | None = Field(
        default=None,
        description="Only when the query had a stress mark: this entry spells it that way",
    )


class Summary(BaseModel):
    entry_id: int
    headword: str
    stressed: str | None
    pos: str | None
    rank: int | None
    rank_shared: bool = False
    level: str | None
    aspect: str | None = None
    registers: list[str] | None = Field(
        default=None, description="Register tags from the dictionary: colloquial, archaic, formal"
    )
    translations: list[str]
    match_reason: str | None = None
    matched_translation: str | None = None


class LookupResponse(BaseModel):
    query: str
    found: bool
    count: int = Field(ge=0)
    entries: list[Entry]
    stress_filtered: int | None = Field(
        default=None,
        description="Homograph entries dropped because their stress differs from the query",
    )
    dataset_date: str


class SearchResponse(BaseModel):
    query: str
    count: int = Field(ge=0)
    results: list[Summary]
    dataset_date: str


class EntryResponse(BaseModel):
    found: bool
    entry_id: int = Field(gt=0)
    entry: Entry | None
    dataset_date: str


class Candidate(BaseModel):
    entry_id: int
    lemma: str | None
    pos: str | None
    rank: int | None
    rank_shared: bool = False
    gloss: str | None
    headword: bool
    forms: list[FormMatch]


class SpellingSuggestion(BaseModel):
    word: str = Field(description="Suggested spelling, stressed")
    lemma: str | None
    pos: str | None
    gloss: str | None
    cost: float = Field(description="Edit cost; 0.5 is a single common confusion (о/а, и/ы)")


class WordAnalysis(BaseModel):
    word: str
    count: int
    known: bool
    candidates: list[Candidate]
    suggestions: list[SpellingSuggestion] = Field(
        default_factory=list,
        description="For unknown words: likely intended spellings, best first. These are "
        "guesses by edit distance; check them against the sentence.",
    )


class LatinLetter(BaseModel):
    letter: str
    position: int = Field(description="0-based index inside the word")


class MixedScriptWord(BaseModel):
    word: str = Field(description="The word as typed, mixing Latin and Cyrillic letters")
    suggestion: str | None = Field(description="The word with look-alike Latin letters replaced")
    latin_letters: list[LatinLetter]


class AnalysisResponse(BaseModel):
    token_count: int
    unique_words: int
    unknown: list[str] = Field(description="Words with no headword or form in the dictionary")
    mixed_script: list[MixedScriptWord] = Field(
        description="Words that mix Latin and Cyrillic letters; these are certain typos. "
        "They were looked up in their repaired spelling."
    )
    words: list[WordAnalysis]
    dataset_date: str


class BrowseResponse(BaseModel):
    count: int
    offset: int
    next_offset: int | None
    results: list[Summary]
    note: str | None = None
    dataset_date: str


class ExamplesResponse(BaseModel):
    query: str
    found: bool
    entries: list[WordRef]
    exact_form: bool
    examples: list[Example]
    source: str
    dataset_date: str
