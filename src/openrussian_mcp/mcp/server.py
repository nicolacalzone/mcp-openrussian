from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from openrussian_mcp import __version__
from openrussian_mcp.config import data_root
from openrussian_mcp.mcp.schemas import (
    AnalysisResponse,
    BrowseResponse,
    DisplayLanguage,
    EntryResponse,
    ExamplesResponse,
    Level,
    LookupResponse,
    PartOfSpeech,
    Register,
    SearchResponse,
    TranslationLanguage,
)
from openrussian_mcp.pipeline.publish import active_database
from openrussian_mcp.service.dictionary import DictionaryService

INSTRUCTIONS = """\
Offline Russian dictionary (OpenRussian.org, ~90k entries) with stress marks, full inflection
tables, aspect pairs, government notes (e.g. "за + instrumental"), frequency rank, CEFR level,
and Tatoeba example sentences.

Notation: stress is a combining acute accent (U+0301) after the stressed vowel, e.g. ко́т.
Remove it when writing ordinary Russian text. Inflection tables use sg/pl,
nom/gen/dat/acc/inst/prep, m/f/n, and sg1..pl3.

Workflows:
- Checking or correcting Russian text: call analyze_text once on the whole text. Look at words in
  `unknown` (possible misspellings, or names and rare words) and at which grammatical forms each
  word can be. Then call get_entry for the words whose case, gender, aspect or government you need
  to confirm. The dictionary checks words, not syntax: agreement and word order are up to you.
- Meaning of a Russian word (any inflected form): lookup_entries.
- Russian word for an English or German meaning: search_entries with language set.
- Study: browse_entries for frequency- or level-based word lists; find_examples for real sentences.

Limits to keep in mind (state them briefly when they affect an answer, without narrating
tool calls):
- A word is "known" if it is a valid form in isolation. Wrong agreement (три годов, в пять
  часа) and wrong government are not detected. Unknown words come with spelling suggestions;
  they are guesses, so check them against the sentence.
- Words mixing Latin and Cyrillic letters are reported in `mixed_script`.
- Frequency ranks belong to the written word; homographs share them (`rank_shared`).
- CEFR levels exist for about 5k entries and may look odd. Register tags exist for only ~350
  entries and there are no topic tags: build themed lists with search_entries.
- find_examples handles a phrase only if Tatoeba has it; it returns nothing for rare phrases.
- Stress and glosses come from OpenRussian and can differ from other references: when the
  dictionary and your own knowledge disagree, say so in one line.
"""

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def _result(model: BaseModel) -> CallToolResult:
    """Compact JSON text for the model, full typed data as structured content."""
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    model.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        ],
        structured_content=model.model_dump(mode="json"),
    )


def create_server(database: Path) -> MCPServer:
    service = DictionaryService(database)
    server = MCPServer("openrussian-dictionary", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def analyze_text(
        text: Annotated[str, Field(min_length=1, max_length=4000)],
        language: DisplayLanguage = "en",
        max_candidates: Annotated[int, Field(ge=1, le=10)] = 4,
    ) -> Annotated[CallToolResult, AnalysisResponse]:
        """Check every Russian word in a text in one call.

        For each distinct word it returns the dictionary entries it can belong to, with the
        grammatical reading of the form (e.g. "кота́: noun genitive singular, noun accusative
        singular") and a short gloss. Words that match nothing are listed in `unknown`: they
        may be misspellings, but also names, slang or rare words. Words that mix Latin and
        Cyrillic letters (a Latin "a" in «годa») are listed in `mixed_script`: always a typo.
        Words without ё match ё spellings. A word counts as known if it is a valid form in
        isolation, so wrong agreement (три годов, в пять часа) is not detected. Unknown words get
        `suggestions`: likely intended spellings by edit distance, best first (a wrong first
        letter is not recovered). This checks words only, not agreement or word order.
        """
        return _result(
            AnalysisResponse.model_validate(service.analyze_text(text, language, max_candidates))
        )

    @server.tool(annotations=READ_ONLY)
    def lookup_entries(
        lemma: Annotated[str, Field(min_length=1, max_length=120)],
        part_of_speech: PartOfSpeech | None = None,
        include_forms: bool = False,
        example_limit: Annotated[int, Field(ge=0, le=10)] = 0,
        language: DisplayLanguage = "en",
    ) -> Annotated[CallToolResult, LookupResponse]:
        """Look up a Russian word, either in its dictionary form or any inflected form.

        Returns every matching entry (homonyms and words whose forms coincide, e.g. "мой" is
        both the pronoun and the imperative of мыть). Each entry's `match` says whether the
        query is its headword and which grammatical forms it is. The entry also has
        translations, grammar (gender, animacy, aspect and aspect partners) and related words.
        Set include_forms for full inflection tables. If the query carries a stress mark
        (му́ка vs мука́), entries spelled that way are returned first with `stress_match`;
        when none matches, every entry has stress_match=false: that stress is not in the
        dictionary. Stress follows OpenRussian, which can differ from other orthoepic
        references for variable words.
        """
        return _result(
            LookupResponse.model_validate(
                service.lookup_entries(
                    lemma, part_of_speech, include_forms, example_limit, language
                )
            )
        )

    @server.tool(annotations=READ_ONLY)
    def search_entries(
        query: Annotated[str, Field(min_length=1, max_length=120)],
        language: TranslationLanguage | None = None,
        part_of_speech: PartOfSpeech | None = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> Annotated[CallToolResult, SearchResponse]:
        """Find Russian words by English or German meaning, or by Russian spelling.

        Translation matches are ranked by how well a sense matches ("run" → бежа́ть before
        "run away"), then by frequency. `language` restricts matching and display to English
        or German. Results are summaries; use get_entry for details.
        """
        return _result(
            SearchResponse.model_validate(
                service.search_entries(query, language, part_of_speech, limit)
            )
        )

    @server.tool(annotations=READ_ONLY)
    def get_entry(
        entry_id: Annotated[int, Field(gt=0)],
        example_limit: Annotated[int, Field(ge=0, le=10)] = 5,
        include_forms: bool = True,
        language: DisplayLanguage = "en",
    ) -> Annotated[CallToolResult, EntryResponse]:
        """Get one entry in full.

        Includes stressed inflection tables, translations with government notes and usage,
        aspect partners, synonyms/antonyms/related words, expressions that contain the word,
        and Tatoeba example sentences (easiest first).
        """
        return _result(
            EntryResponse.model_validate(
                service.get_entry(entry_id, example_limit, include_forms, language)
            )
        )

    @server.tool(annotations=READ_ONLY)
    def browse_entries(
        level: Level | None = None,
        part_of_speech: PartOfSpeech | None = None,
        min_rank: Annotated[int | None, Field(ge=1)] = None,
        max_rank: Annotated[int | None, Field(ge=1)] = None,
        language: DisplayLanguage = "en",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        offset: Annotated[int, Field(ge=0, le=100_000)] = 0,
        include_ambiguous_rank: bool = False,
        register: Register | None = None,
    ) -> Annotated[CallToolResult, BrowseResponse]:
        """List words by frequency for vocabulary study, most frequent first.

        Filter by CEFR level (only about 5k entries have a level), part of speech, or a
        frequency-rank range (e.g. max_rank=500 for the 500 most common words). Page with
        offset and next_offset. OpenRussian ranks written words, so homographs share a rank
        (`rank_shared`); with part_of_speech set, entries that share their rank with a
        homograph of another part of speech are skipped unless include_ambiguous_rank is
        true. `register` keeps only entries tagged colloquial, archaic or formal (only about
        350 entries carry such a tag). Levels are incomplete and the dictionary has no topic
        tags: for a themed list (food, family) use search_entries with several English words.
        """
        return _result(
            BrowseResponse.model_validate(
                service.browse_entries(
                    level,
                    part_of_speech,
                    min_rank,
                    max_rank,
                    language,
                    limit,
                    offset,
                    include_ambiguous_rank,
                    register,
                )
            )
        )

    @server.tool(annotations=READ_ONLY)
    def find_examples(
        word: Annotated[str, Field(min_length=1, max_length=120)],
        max_level: Level | None = None,
        exact_form: bool | None = None,
        language: DisplayLanguage = "en",
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        diverse: bool = True,
    ) -> Annotated[CallToolResult, ExamplesResponse]:
        """Find real Tatoeba sentences with translations that use a Russian word.

        Easiest and shortest sentences come first. max_level restricts to sentences at or below
        a CEFR level. exact_form=true only returns sentences using exactly the given form (e.g.
        "иду"); by default this is on for inflected forms and off for dictionary forms.
        A phrase such as «скучать по» finds sentences with those words in that order; a
        dictionary form stands for all its forms. A phrase that is not in the corpus returns
        nothing: then search its main word. By default (`diverse`) the sentences show
        different forms and different frames instead of near-identical ones.
        """
        return _result(
            ExamplesResponse.model_validate(
                service.find_examples(word, max_level, exact_form, language, limit, diverse)
            )
        )

    @server.resource("openrussian://dataset/info")
    def dataset_info() -> str:
        """Dataset date, licence, source, and builder version."""
        return json.dumps(service.info(), ensure_ascii=False)

    @server.resource("openrussian://dataset/license")
    def dataset_license() -> str:
        """Attribution and licence information for dictionary and sentence data."""
        return (
            "OpenRussian.org dictionary data: CC BY-SA 4.0, "
            "https://en.openrussian.org/dictionary-data. "
            "Tatoeba sentence text: CC BY 2.0 FR, https://tatoeba.org. "
            "This server creates an indexed local snapshot. Audio is linked, not bundled."
        )

    @server.resource("openrussian://grammar/form-types")
    def grammar_form_types() -> str:
        """Source form labels, their meaning, and the abbreviations used in inflection tables."""
        return json.dumps(service.form_types(), ensure_ascii=False)

    return server


def main() -> None:
    server = create_server(active_database(data_root() / "active"))
    server.run()


if __name__ == "__main__":
    main()
