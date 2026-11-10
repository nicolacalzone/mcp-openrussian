from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openrussian_mcp.domain.normalization import lookup_key, normalize_lookup, search_tokens
from openrussian_mcp.domain.vocabulary import LEVELS
from openrussian_mcp.storage.schema import SCHEMA_VERSION

_LEVEL_ORDER = (
    "CASE {col} "
    + " ".join(f"WHEN '{level}' THEN {rank}" for rank, level in enumerate(LEVELS, 1))
    + f" ELSE {len(LEVELS) + 1} END"
)
# English first by default, then source order.
_TRANSLATION_ORDER = "CASE lang WHEN 'en' THEN 0 ELSE 1 END, position, translation_id"
# OpenRussian gives one frequency rank per written word, so homographs share it. The two
# flags say how far the rank can be trusted for this particular entry.
_RANK_SHARED = (
    "EXISTS(SELECT 1 FROM entries o WHERE o.normalized=entries.normalized AND o.disabled=0"
    " AND o.rank=entries.rank AND o.entry_id<>entries.entry_id)"
)
_RANK_AMBIGUOUS = (
    "EXISTS(SELECT 1 FROM entries o WHERE o.normalized=entries.normalized AND o.disabled=0"
    " AND o.rank=entries.rank AND o.entry_id<>entries.entry_id AND o.pos IS NOT entries.pos)"
)
_SUMMARY_FIELDS = f"entry_id,bare,accented,pos,rank,level,aspect,{_RANK_SHARED} AS rank_shared"


def _marks(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


@dataclass
class Match:
    """Why an entry matched a word: as its headword and/or as inflected forms."""

    headword: bool = False
    forms: list[tuple[str, str]] = field(default_factory=list)  # (form_type, form)


class Queries:
    """All read queries, bound to one connection for the duration of a service call."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, tuple(params)).fetchall()

    def form_types(self) -> list[dict]:
        return [
            dict(row)
            for row in self._all(
                "SELECT form_type,COUNT(*) AS count FROM forms "
                "GROUP BY form_type ORDER BY form_type"
            )
        ]

    def matches(
        self, words: Iterable[str], pos: str | None = None, limit_per_word: int = 20
    ) -> dict[str, dict[int, Match]]:
        """Resolve words to entries by headword and by every inflected form, in one batch.

        Returns ``{word: {entry_id: Match}}`` with entries ordered by frequency rank.
        Words without ё also match ё spellings ("идет" finds "идёт").
        """
        keys = {word: lookup_key(word) for word in words}
        folded = sorted({key for key, fold in keys.values() if fold and key})
        exact = sorted({key for key, fold in keys.values() if not fold and key})
        pos_sql = " AND e.pos=?" if pos else ""
        pos_params = [pos] if pos else []
        found: dict[tuple[str, bool], dict[int, Match]] = {}
        ranks: dict[int, tuple[int, int]] = {}

        def record(row: sqlite3.Row, key: str, fold: bool, form: tuple[str, str] | None) -> None:
            bucket = found.setdefault((key, fold), {})
            match = bucket.setdefault(row["entry_id"], Match())
            ranks[row["entry_id"]] = (row["rank"] is None, row["rank"] or 0)
            if form is None:
                match.headword = True
            elif form not in match.forms:
                match.forms.append(form)

        for column, values, fold in (("normalized_yo", folded, True), ("normalized", exact, False)):
            if not values:
                continue
            for row in self._all(
                f"""SELECT e.entry_id,e.rank,e.{column} AS key FROM entries e
                WHERE e.disabled=0 AND e.{column} IN ({_marks(values)}){pos_sql}""",
                [*values, *pos_params],
            ):
                record(row, row["key"], fold, None)
            for row in self._all(
                f"""SELECT f.entry_id,e.rank,k.{column} AS key,f.form_type,f.form
                FROM form_keys k JOIN forms f ON f.form_id=k.form_id
                JOIN entries e ON e.entry_id=f.entry_id
                WHERE e.disabled=0 AND k.{column} IN ({_marks(values)}){pos_sql}
                ORDER BY f.form_type,f.position""",
                [*values, *pos_params],
            ):
                record(row, row["key"], fold, (row["form_type"], row["form"]))

        result: dict[str, dict[int, Match]] = {}
        for word, (key, fold) in keys.items():
            bucket = found.get((key, fold), {})
            ordered = sorted(
                bucket.items(),
                key=lambda item: (not item[1].headword, ranks[item[0]], item[0]),
            )
            result[word] = dict(ordered[:limit_per_word])
        return result

    def spelling_pool(self, word_yo: str, max_length_gap: int = 2) -> list[str]:
        """Known spellings (ё folded) that start with the same letter and have a similar length.

        Typos in the first letter are not recovered.
        """
        low, high = word_yo[:1], chr(ord(word_yo[:1]) + 1)
        n = len(word_yo)
        params = [low, high, n - max_length_gap, n + max_length_gap]
        keys = {
            row[0]
            for table in ("form_keys", "entries")
            for row in self.connection.execute(
                f"""SELECT DISTINCT normalized_yo FROM {table}
                WHERE normalized_yo>=? AND normalized_yo<?
                  AND length(normalized_yo) BETWEEN ? AND ?""",
                params,
            )
        }
        return list(keys)

    def key_ranks(self, keys: Sequence[str]) -> dict[str, int | None]:
        """Best frequency rank among active entries for each ё-folded spelling."""
        ranks: dict[str, int | None] = {key: None for key in keys}
        if not keys:
            return ranks
        for sql in (
            f"""SELECT k.normalized_yo AS key,MIN(e.rank) AS rank FROM form_keys k
            JOIN entries e ON e.entry_id=k.entry_id
            WHERE e.disabled=0 AND k.normalized_yo IN ({_marks(keys)}) GROUP BY k.normalized_yo""",
            f"""SELECT normalized_yo AS key,MIN(rank) AS rank FROM entries
            WHERE disabled=0 AND normalized_yo IN ({_marks(keys)}) GROUP BY normalized_yo""",
        ):
            for row in self._all(sql, keys):
                current = ranks[row["key"]]
                if row["rank"] is not None and (current is None or row["rank"] < current):
                    ranks[row["key"]] = row["rank"]
        return ranks

    def translations(
        self, entry_ids: Sequence[int], langs: Sequence[str], per_entry: int | None = None
    ) -> dict[int, list[dict]]:
        result: dict[int, list[dict]] = {entry_id: [] for entry_id in entry_ids}
        if not entry_ids:
            return result
        for row in self._all(
            f"""SELECT entry_id,lang,text,info,example_ru,example_translation FROM translations
            WHERE entry_id IN ({_marks(entry_ids)}) AND lang IN ({_marks(langs)})
            ORDER BY entry_id,{_TRANSLATION_ORDER}""",
            [*entry_ids, *langs],
        ):
            bucket = result[row["entry_id"]]
            if per_entry is None or len(bucket) < per_entry:
                bucket.append(dict(row))
        return result

    def summaries(self, entry_ids: Sequence[int]) -> dict[int, dict]:
        if not entry_ids:
            return {}
        return {
            row["entry_id"]: dict(row)
            for row in self._all(
                f"""SELECT {_SUMMARY_FIELDS} FROM entries
                WHERE disabled=0 AND entry_id IN ({_marks(entry_ids)})""",
                entry_ids,
            )
        }

    def translation_candidates(
        self, needle: str, lang: str | None, pos: str | None, cap: int = 2000
    ) -> list[sqlite3.Row]:
        """Translations containing the needle as a substring (ranked later in Python)."""
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self._all(
            f"""SELECT t.entry_id,t.lang,t.position,t.text,e.rank
            FROM translations t JOIN entries e ON e.entry_id=t.entry_id
            WHERE e.disabled=0 AND t.text LIKE ? ESCAPE '\\'
              AND (? IS NULL OR t.lang=?) AND (? IS NULL OR e.pos=?)
            ORDER BY e.rank IS NULL,e.rank,e.entry_id,{_TRANSLATION_ORDER} LIMIT ?""",
            [f"%{escaped}%", lang, lang, pos, pos, cap],
        )

    def fts_ids(self, query: str, lang: str | None, pos: str | None, limit: int) -> list[int]:
        tokens = search_tokens(query)
        if not tokens:
            return []
        # Tokens contain only Unicode word characters and are quoted; only the last one
        # is a prefix, so "cat" does not drag in every "category".
        parts = [f'"{token}"' for token in tokens[:-1]]
        parts.append(f'"{tokens[-1]}"*' if len(tokens[-1]) >= 3 else f'"{tokens[-1]}"')
        return [
            row["entry_id"]
            for row in self._all(
                """SELECT e.entry_id FROM search_fts JOIN entries e ON e.entry_id=search_fts.rowid
                WHERE search_fts MATCH ? AND e.disabled=0 AND (? IS NULL OR e.pos=?)
                  AND (? IS NULL OR EXISTS (
                    SELECT 1 FROM translations t WHERE t.entry_id=e.entry_id AND t.lang=?))
                ORDER BY bm25(search_fts, 4.0, 2.0, 1.0),e.rank IS NULL,e.rank,e.entry_id
                LIMIT ?""",
                [" AND ".join(parts), pos, pos, lang, lang, limit],
            )
        ]

    def browse(
        self,
        level: str | None,
        pos: str | None,
        min_rank: int | None,
        max_rank: int | None,
        limit: int,
        offset: int,
        *,
        skip_ambiguous_rank: bool = False,
        register: str | None = None,
    ) -> list[int]:
        ambiguous_sql = f" AND NOT {_RANK_AMBIGUOUS}" if skip_ambiguous_rank else ""
        register_sql = (
            " AND EXISTS(SELECT 1 FROM entry_tags et JOIN tags t ON t.tag_id=et.tag_id"
            " WHERE et.entry_id=entries.entry_id AND t.uid=?)"
            if register
            else ""
        )
        return [
            row["entry_id"]
            for row in self._all(
                f"""SELECT entry_id FROM entries WHERE disabled=0
                  AND (? IS NULL OR level=?) AND (? IS NULL OR pos=?)
                  AND (? IS NULL OR rank>=?) AND (? IS NULL OR rank<=?){ambiguous_sql}{register_sql}
                ORDER BY rank IS NULL,rank,entry_id LIMIT ? OFFSET ?""",
                [
                    level,
                    level,
                    pos,
                    pos,
                    min_rank,
                    min_rank,
                    max_rank,
                    max_rank,
                    *([register] if register else []),
                    limit,
                    offset,
                ],
            )
        ]

    def examples(
        self,
        entry_ids: Sequence[int],
        limit: int,
        *,
        max_level: str | None = None,
        prefer_lang: str = "en",
        form_keys: set[str] | None = None,
        candidates: int | None = None,
    ) -> list[dict]:
        """Example sentences, easiest and shortest first.

        With ``form_keys``, only sentences where the linked word is spelled as one of those
        normalized forms are returned (e.g. sentences using "иду" rather than any form of идти).
        """
        if not entry_ids or limit <= 0:
            return []
        allowed = LEVELS[: LEVELS.index(max_level) + 1] if max_level else None
        level_sql = f" AND x.level IN ({_marks(allowed)})" if allowed else ""
        lang_col = "x.de" if prefer_lang == "de" else "x.en"
        candidate_limit = (
            max(limit, candidates or 0) if form_keys is None else max(limit * 50, 5000)
        )
        rows = self._all(
            f"""SELECT link.entry_id,link.start,link.length,x.sentence_id,x.ru,x.en,x.de,
              x.tatoeba_key,x.level
            FROM entry_examples link JOIN examples x ON x.sentence_id=link.sentence_id
            WHERE link.entry_id IN ({_marks(entry_ids)}) AND x.disabled=0{level_sql}
            ORDER BY {lang_col} IS NULL,{_LEVEL_ORDER.format(col="x.level")},
              length(x.ru),x.sentence_id
            LIMIT ?""",
            [*entry_ids, *(allowed or []), candidate_limit],
        )
        result: list[dict] = []
        seen: set[int] = set()
        for row in rows:
            if row["sentence_id"] in seen:
                continue
            span = row["ru"][row["start"] : row["start"] + row["length"]]
            if form_keys is not None and normalize_lookup(span, fold_yo=True) not in form_keys:
                continue
            seen.add(row["sentence_id"])
            result.append(dict(row, span=span))
            if len(result) == max(limit, candidates or 0):
                break
        return result

    def form_key_set(self, entry_ids: Sequence[int], cap: int = 600) -> set[str]:
        """Every ё-folded spelling (headword and forms) of the given entries."""
        if not entry_ids:
            return set()
        keys = {
            row[0]
            for row in self.connection.execute(
                f"SELECT normalized_yo FROM entries WHERE entry_id IN ({_marks(entry_ids)})",
                tuple(entry_ids),
            )
        }
        for row in self.connection.execute(
            f"SELECT DISTINCT normalized_yo FROM form_keys WHERE entry_id IN ({_marks(entry_ids)})"
            f" LIMIT {int(cap)}",
            tuple(entry_ids),
        ):
            keys.add(row[0])
        return keys

    def link_count(self, entry_ids: Sequence[int]) -> int:
        if not entry_ids:
            return 0
        return self.connection.execute(
            f"SELECT COUNT(*) FROM entry_examples WHERE entry_id IN ({_marks(entry_ids)})",
            tuple(entry_ids),
        ).fetchone()[0]

    def sentences_with(
        self, entry_ids: Sequence[int], max_level: str | None = None, cap: int = 20000
    ) -> list[dict]:
        """Sentences linked to any of the entries, easiest and shortest first."""
        allowed = LEVELS[: LEVELS.index(max_level) + 1] if max_level else None
        level_sql = f" AND x.level IN ({_marks(allowed)})" if allowed else ""
        return [
            dict(row)
            for row in self._all(
                f"""SELECT DISTINCT x.sentence_id,x.ru,x.en,x.de,x.tatoeba_key,x.level
                FROM entry_examples link JOIN examples x ON x.sentence_id=link.sentence_id
                WHERE link.entry_id IN ({_marks(entry_ids)}) AND x.disabled=0{level_sql}
                ORDER BY {_LEVEL_ORDER.format(col="x.level")},length(x.ru),x.sentence_id
                LIMIT ?""",
                [*entry_ids, *(allowed or []), cap],
            )
        ]

    def entry_row(self, entry_id: int) -> dict | None:
        row = self.connection.execute(
            f"""SELECT entry_id,bare,accented,pos,rank,level,audio_url,usage_en,usage_de,
              derived_from_entry_id,gender,animate,indeclinable,sg_only,pl_only,aspect,partner,
              incomparable,{_RANK_SHARED} AS rank_shared
            FROM entries WHERE entry_id=? AND disabled=0""",
            (entry_id,),
        ).fetchone()
        return dict(row) if row else None

    def forms(self, entry_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._all(
                "SELECT form_type,position,form FROM forms WHERE entry_id=? "
                "ORDER BY form_type,position,form_id LIMIT 300",
                (entry_id,),
            )
        ]

    def relations(self, entry_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._all(
                """SELECT r.relation,r.related_entry_id AS entry_id,e.accented
                FROM relations r JOIN entries e ON e.entry_id=r.related_entry_id
                WHERE r.entry_id=? AND e.disabled=0
                ORDER BY r.relation,e.rank IS NULL,e.rank,r.related_entry_id LIMIT 60""",
                (entry_id,),
            )
        ]

    def expressions_with(self, entry_id: int, limit: int = 10) -> list[dict]:
        return [
            dict(row)
            for row in self._all(
                """SELECT DISTINCT e.entry_id,e.accented FROM expression_members m
                JOIN entries e ON e.entry_id=m.expression_id
                WHERE m.referenced_entry_id=? AND e.disabled=0
                ORDER BY e.rank IS NULL,e.rank,e.entry_id LIMIT ?""",
                (entry_id, limit),
            )
        ]

    def expression_members(self, entry_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self._all(
                """SELECT e.entry_id,e.accented FROM expression_members m
                JOIN entries e ON e.entry_id=m.referenced_entry_id
                WHERE m.expression_id=? AND e.disabled=0 ORDER BY m.start""",
                (entry_id,),
            )
        ]

    def tags(self, entry_id: int) -> list[str]:
        return [
            row["name_en"] or row["uid"]
            for row in self._all(
                """SELECT DISTINCT t.uid,t.name_en FROM entry_tags et
                JOIN tags t ON t.tag_id=et.tag_id WHERE et.entry_id=? ORDER BY t.uid LIMIT 30""",
                (entry_id,),
            )
        ]

    def tags_for(self, entry_ids: Sequence[int]) -> dict[int, list[str]]:
        result: dict[int, list[str]] = {entry_id: [] for entry_id in entry_ids}
        if entry_ids:
            for row in self._all(
                f"""SELECT DISTINCT et.entry_id,t.uid FROM entry_tags et
                JOIN tags t ON t.tag_id=et.tag_id
                WHERE et.entry_id IN ({_marks(entry_ids)}) ORDER BY t.uid""",
                entry_ids,
            ):
                result[row["entry_id"]].append(row["uid"])
        return result

    def entry_heads(self, entry_ids: Sequence[int]) -> dict[int, str]:
        if not entry_ids:
            return {}
        return {
            row["entry_id"]: row["accented"]
            for row in self._all(
                f"SELECT entry_id,accented FROM entries WHERE entry_id IN ({_marks(entry_ids)})",
                entry_ids,
            )
        }


class DictionaryRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        with self.session() as queries:
            version = queries.connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"{self.db_path} has schema version {version}; this server needs "
                f"{SCHEMA_VERSION}. Rebuild with `openrussian-data build` and activate it."
            )

    @contextmanager
    def session(self) -> Iterator[Queries]:
        connection = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=2000")
        try:
            yield Queries(connection)
        finally:
            connection.close()

    def metadata(self) -> dict:
        with self.session() as queries:
            metadata = {
                row["key"]: row["value"]
                for row in queries.connection.execute("SELECT key,value FROM metadata")
            }
            metadata["active_entries"] = queries.connection.execute(
                "SELECT COUNT(*) FROM entries WHERE disabled=0"
            ).fetchone()[0]
        report_path = self.db_path.parent / "report.json"
        manifest_path = self.db_path.parent / "manifest.json"
        if report_path.is_file() and manifest_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata["counts"] = report["database_rows"]
            metadata["source_sha256"] = {
                table: source["sha256"]
                for table, source in manifest["source_manifest"]["files"].items()
            }
            metadata["database_bytes"] = self.db_path.stat().st_size
        return metadata
