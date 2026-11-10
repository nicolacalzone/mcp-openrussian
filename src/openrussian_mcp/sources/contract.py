from __future__ import annotations

PREFIX = "openrussian_public - "
SCHEMA_VERSION = 1
SOURCE_URL = "https://en.openrussian.org/dictionary-data"
SOURCE_LICENSE = "CC BY-SA 4.0"

# Required source columns. Extra columns are preserved at the raw boundary and
# reported, so an additive upstream change does not break the build.
TABLES: dict[str, tuple[str, ...]] = {
    "words": ("id", "bare", "accented", "type", "rank", "disabled"),
    "translations": ("id", "word_id", "lang", "position", "tl"),
    "words_forms": ("id", "word_id", "form_type", "position", "form", "form_bare"),
    "sentences": ("id", "ru", "tatoeba_key", "disabled", "level"),
    "sentences_translations": ("sentence_id", "tl_en", "tl_de"),
    "sentences_words": ("id", "sentence_id", "word_id", "start", "length", "form_type"),
    "nouns": ("word_id", "gender", "partner", "animate", "indeclinable", "sg_only", "pl_only"),
    "verbs": ("word_id", "aspect", "partner"),
    "adjectives": ("word_id", "incomparable"),
    "words_rels": ("id", "word_id", "rel_word_id", "relation"),
    "expressions_words": ("id", "expression_id", "referenced_word_id", "start", "length"),
    "tags": ("id", "uid", "name_en", "name_ru", "name_de"),
    "tags_words": ("id", "tag_id", "word_id", "translation_id", "tag_text"),
}


def filename(table: str) -> str:
    return f"{PREFIX}{table}.csv"
