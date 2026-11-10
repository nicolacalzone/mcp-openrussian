from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entries (
    entry_id INTEGER PRIMARY KEY,
    bare TEXT NOT NULL,
    accented TEXT NOT NULL,
    normalized TEXT NOT NULL,
    normalized_yo TEXT NOT NULL,
    pos TEXT,
    rank INTEGER,
    level TEXT,
    disabled INTEGER NOT NULL CHECK(disabled IN (0,1)),
    audio_url TEXT,
    usage_en TEXT,
    usage_de TEXT,
    derived_from_entry_id INTEGER REFERENCES entries(entry_id),
    gender TEXT,
    animate INTEGER,
    indeclinable INTEGER,
    sg_only INTEGER,
    pl_only INTEGER,
    aspect TEXT,
    partner TEXT,
    incomparable INTEGER
);
CREATE TABLE translations (
    translation_id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    lang TEXT NOT NULL CHECK(lang IN ('en','de')),
    position INTEGER,
    text TEXT NOT NULL,
    example_ru TEXT,
    example_translation TEXT,
    info TEXT,
    UNIQUE(entry_id, lang, position, text)
);
CREATE TABLE forms (
    form_id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    form_type TEXT NOT NULL,
    position INTEGER,
    form TEXT NOT NULL,
    form_bare TEXT NOT NULL,
    UNIQUE(entry_id, form_type, position, form)
);
-- One form cell can hold several spellings; each gets its own lookup key.
CREATE TABLE form_keys (
    form_id INTEGER NOT NULL REFERENCES forms(form_id),
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    normalized TEXT NOT NULL,
    normalized_yo TEXT NOT NULL,
    PRIMARY KEY (form_id, normalized)
) WITHOUT ROWID;
CREATE TABLE examples (
    sentence_id INTEGER PRIMARY KEY,
    ru TEXT NOT NULL,
    en TEXT,
    de TEXT,
    tatoeba_key TEXT NOT NULL UNIQUE,
    disabled INTEGER NOT NULL CHECK(disabled IN (0,1)),
    level TEXT
);
CREATE TABLE entry_examples (
    link_id INTEGER PRIMARY KEY,
    sentence_id INTEGER NOT NULL REFERENCES examples(sentence_id),
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    start INTEGER NOT NULL,
    length INTEGER NOT NULL,
    form_type TEXT
);
CREATE TABLE relations (
    relation_id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    related_entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    relation TEXT NOT NULL
);
CREATE TABLE expression_members (
    link_id INTEGER PRIMARY KEY,
    expression_id INTEGER NOT NULL REFERENCES entries(entry_id),
    referenced_entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    start INTEGER NOT NULL,
    length INTEGER NOT NULL
);
CREATE TABLE tags (
    tag_id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    name_en TEXT,
    name_ru TEXT,
    name_de TEXT
);
CREATE TABLE entry_tags (
    link_id INTEGER PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id),
    entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
    translation_id INTEGER REFERENCES translations(translation_id),
    tag_text TEXT
);
CREATE TABLE search_documents (
    entry_id INTEGER PRIMARY KEY REFERENCES entries(entry_id),
    lemma TEXT NOT NULL,
    lemma_yo TEXT NOT NULL,
    translations TEXT NOT NULL
);
CREATE VIRTUAL TABLE search_fts USING fts5(
    lemma, lemma_yo, translations,
    content='search_documents', content_rowid='entry_id', tokenize='unicode61'
);
"""

INDEXES = """
CREATE INDEX idx_entries_normalized ON entries(normalized, disabled, rank);
CREATE INDEX idx_entries_yo ON entries(normalized_yo, disabled, rank);
CREATE INDEX idx_entries_pos ON entries(pos, disabled);
CREATE INDEX idx_entries_rank ON entries(disabled, rank);
CREATE INDEX idx_translations_entry ON translations(entry_id, lang, position, translation_id);
CREATE INDEX idx_forms_entry ON forms(entry_id, form_type, position, form_id);
CREATE INDEX idx_form_keys_normalized ON form_keys(normalized, entry_id);
CREATE INDEX idx_form_keys_yo ON form_keys(normalized_yo, entry_id);
CREATE INDEX idx_entry_examples_entry ON entry_examples(entry_id, sentence_id);
CREATE INDEX idx_relations_entry ON relations(entry_id, relation);
CREATE INDEX idx_expression_members_expression ON expression_members(expression_id);
CREATE INDEX idx_expression_members_word ON expression_members(referenced_entry_id);
CREATE INDEX idx_entry_tags_entry ON entry_tags(entry_id);
"""


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(INDEXES)
