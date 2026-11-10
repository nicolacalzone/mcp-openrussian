from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openrussian_mcp import __version__
from openrussian_mcp.domain.normalization import form_keys, normalize_lookup
from openrussian_mcp.pipeline.patches import apply_patches
from openrussian_mcp.sources.directory import read_rows
from openrussian_mcp.sources.manifest import verify_snapshot, write_json
from openrussian_mcp.storage.schema import SCHEMA_VERSION, create_indexes, create_schema

logger = logging.getLogger(__name__)
BATCH_SIZE = 10_000


def integer(value: str | None) -> int | None:
    return int(value) if value is not None and value != "" else None


def flag(value: str | None) -> int | None:
    result = integer(value)
    if result not in (None, 0, 1):
        raise ValueError(f"Invalid boolean value: {value!r}")
    return result


def _chunks(values: Iterable[tuple[Any, ...]]) -> Iterator[list[tuple[Any, ...]]]:
    batch = []
    for item in values:
        batch.append(item)
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _insert(
    connection: sqlite3.Connection,
    sql: str,
    values: Iterable[tuple[Any, ...]],
) -> int:
    total = 0
    for batch in _chunks(values):
        connection.executemany(sql, batch)
        total += len(batch)
    return total


def _rows(directory: Path, table: str, mapper: Callable[[dict[str, str]], tuple[Any, ...]]):
    for row in read_rows(directory, table):
        yield mapper(row)


def _load_entries(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    sql = """INSERT INTO entries
      (entry_id,bare,accented,normalized,normalized_yo,pos,rank,level,disabled,
       audio_url,usage_en,usage_de,derived_from_entry_id)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""

    def values(row: dict[str, str]) -> tuple[Any, ...]:
        bare = row["bare"]
        if not bare:
            raise ValueError(f"words.id={row['id']}: empty headword")
        return (
            int(row["id"]),
            bare,
            row["accented"] or bare,
            normalize_lookup(bare),
            normalize_lookup(bare, fold_yo=True),
            row["type"] or None,
            integer(row["rank"]),
            row.get("level") or None,
            flag(row["disabled"]),
            row.get("audio") or None,
            row.get("usage_en") or None,
            row.get("usage_de") or None,
            integer(row.get("derived_from_word_id")),
        )

    report["source_rows"]["words"] = _insert(connection, sql, _rows(directory, "words", values))
    entry_positions = {
        row[0]: row[1] for row in connection.execute("SELECT entry_id,pos FROM entries")
    }

    for table, update in (
        ("nouns", "gender=?, partner=?, animate=?, indeclinable=?, sg_only=?, pl_only=?"),
        ("verbs", "aspect=?, partner=?"),
        ("adjectives", "incomparable=?"),
    ):
        source = list(read_rows(directory, table))
        expected_pos = table[:-1] if table != "adjectives" else "adjective"
        classified = connection.execute(
            "SELECT COUNT(*) FROM entries WHERE pos=?", (expected_pos,)
        ).fetchone()[0]
        if len(source) != classified:
            report["warnings"].append(
                f"{table}: {len(source)} side-table rows versus {classified} entries of that POS"
            )
        seen: set[int] = set()
        for row in source:
            word_id = int(row["word_id"])
            if word_id in seen:
                raise ValueError(f"{table}: duplicate word_id={word_id}")
            seen.add(word_id)
            if word_id not in entry_positions:
                raise ValueError(f"{table}: orphan word_id={word_id}")
            prior_pos = entry_positions[word_id]
            if prior_pos not in (None, expected_pos):
                raise ValueError(
                    f"{table}: word_id={word_id} has conflicting words.type={prior_pos!r}"
                )
            entry_positions[word_id] = expected_pos
        if table == "nouns":
            params: list[tuple[Any, ...]] = [
                (
                    r["gender"] or None,
                    r["partner"] or None,
                    flag(r["animate"]),
                    flag(r["indeclinable"]),
                    flag(r["sg_only"]),
                    flag(r["pl_only"]),
                    int(r["word_id"]),
                )
                for r in source
            ]
        elif table == "verbs":
            params = [
                (r["aspect"] or None, r["partner"] or None, int(r["word_id"])) for r in source
            ]
        else:
            params = [(flag(r["incomparable"]), int(r["word_id"])) for r in source]
        connection.executemany(f"UPDATE entries SET {update} WHERE entry_id=?", params)
        connection.executemany(
            "UPDATE entries SET pos=? WHERE entry_id=? AND (pos IS NULL OR pos='')",
            [(expected_pos, int(r["word_id"])) for r in source],
        )
        report["source_rows"][table] = len(source)


def _load_translations(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    sql = """INSERT OR IGNORE INTO translations
      (translation_id,entry_id,lang,position,text,example_ru,example_translation,info)
      VALUES (?,?,?,?,?,?,?,?)"""
    total = empty = 0

    def values() -> Iterator[tuple[Any, ...]]:
        nonlocal total, empty
        for row in read_rows(directory, "translations"):
            total += 1
            if not row["tl"]:
                empty += 1
                continue
            yield (
                int(row["id"]),
                int(row["word_id"]),
                row["lang"],
                integer(row["position"]),
                row["tl"],
                row.get("example_ru") or None,
                row.get("example_tl") or None,
                row.get("info") or None,
            )

    attempted = _insert(connection, sql, values())
    stored = connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    report["source_rows"]["translations"] = total
    report["omitted"]["empty_translations"] = empty
    report["omitted"]["duplicate_translations"] = attempted - stored


def _load_forms(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    sql = """INSERT OR IGNORE INTO forms
      (form_id,entry_id,form_type,position,form,form_bare)
      VALUES (?,?,?,?,?,?)"""
    total = empty = 0

    def values() -> Iterator[tuple[Any, ...]]:
        nonlocal total, empty
        for row in read_rows(directory, "words_forms"):
            total += 1
            if not row["form"]:
                empty += 1
                continue
            yield (
                int(row["id"]),
                int(row["word_id"]),
                row["form_type"],
                integer(row["position"]),
                row["form"],
                row["form_bare"] or row["form"],
            )

    _insert(connection, sql, values())
    report["source_rows"]["words_forms"] = total
    report["omitted"]["empty_forms"] = empty
    report["omitted"]["duplicate_forms"] = (
        total - empty - connection.execute("SELECT COUNT(*) FROM forms").fetchone()[0]
    )

    def keys() -> Iterator[tuple[Any, ...]]:
        rows = connection.execute("SELECT form_id,entry_id,form_type,form_bare FROM forms")
        for form_id, entry_id, form_type, form_bare in rows:
            for key in form_keys(form_bare, form_type):
                yield form_id, entry_id, key, key.replace("ё", "е")

    # Streaming is safe: rows are read from `forms` while inserts go to another table.
    _insert(
        connection,
        "INSERT INTO form_keys(form_id,entry_id,normalized,normalized_yo) VALUES (?,?,?,?)",
        keys(),
    )
    report["omitted"]["forms_without_lookup_key"] = connection.execute(
        "SELECT COUNT(*) FROM forms f WHERE NOT EXISTS "
        "(SELECT 1 FROM form_keys k WHERE k.form_id=f.form_id)"
    ).fetchone()[0]


def _load_examples(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    sql = """INSERT INTO examples(sentence_id,ru,tatoeba_key,disabled,level)
      VALUES (?,?,?,?,?)"""
    report["source_rows"]["sentences"] = _insert(
        connection,
        sql,
        _rows(
            directory,
            "sentences",
            lambda r: (
                int(r["id"]),
                r["ru"],
                r["tatoeba_key"],
                flag(r["disabled"]),
                r["level"] or None,
            ),
        ),
    )
    sql = "UPDATE examples SET en=?, de=? WHERE sentence_id=?"
    sentence_ids = {row[0] for row in connection.execute("SELECT sentence_id FROM examples")}

    def sentence_translation_values():
        seen: set[int] = set()
        for row in read_rows(directory, "sentences_translations"):
            sentence_id = int(row["sentence_id"])
            if sentence_id in seen:
                raise ValueError(f"Duplicate sentence translation for sentence_id={sentence_id}")
            if sentence_id not in sentence_ids:
                raise ValueError(f"Orphan sentence translation for sentence_id={sentence_id}")
            seen.add(sentence_id)
            yield row["tl_en"] or None, row["tl_de"] or None, sentence_id

    report["source_rows"]["sentences_translations"] = _insert(
        connection,
        sql,
        sentence_translation_values(),
    )
    if report["source_rows"]["sentences_translations"] != len(sentence_ids):
        raise ValueError("Sentence translations do not cover every sentence")
    sql = """INSERT INTO entry_examples
      (link_id,sentence_id,entry_id,start,length,form_type) VALUES (?,?,?,?,?,?)"""
    report["source_rows"]["sentences_words"] = _insert(
        connection,
        sql,
        _rows(
            directory,
            "sentences_words",
            lambda r: (
                int(r["id"]),
                int(r["sentence_id"]),
                int(r["word_id"]),
                int(r["start"]),
                int(r["length"]),
                r["form_type"] or None,
            ),
        ),
    )


def _load_misc(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    specs = (
        (
            "words_rels",
            "INSERT INTO relations VALUES (?,?,?,?)",
            lambda r: (int(r["id"]), int(r["word_id"]), int(r["rel_word_id"]), r["relation"]),
        ),
        (
            "expressions_words",
            "INSERT INTO expression_members VALUES (?,?,?,?,?)",
            lambda r: (
                int(r["id"]),
                int(r["expression_id"]),
                int(r["referenced_word_id"]),
                int(r["start"]),
                int(r["length"]),
            ),
        ),
        (
            "tags",
            "INSERT INTO tags VALUES (?,?,?,?,?)",
            lambda r: (int(r["id"]), r["uid"], r["name_en"], r["name_ru"], r["name_de"]),
        ),
        (
            "tags_words",
            "INSERT INTO entry_tags VALUES (?,?,?,?,?)",
            lambda r: (
                int(r["id"]),
                int(r["tag_id"]),
                int(r["word_id"]),
                integer(r["translation_id"]),
                r["tag_text"] or None,
            ),
        ),
    )
    for table, sql, mapper in specs:
        report["source_rows"][table] = _insert(connection, sql, _rows(directory, table, mapper))


def _apply_patches(connection: sqlite3.Connection, directory: Path, report: dict) -> None:
    report["patches"] = apply_patches(connection)


def _build_search(connection: sqlite3.Connection) -> None:
    # A sorted subquery gives stable translation concatenation across rebuilds.
    connection.execute("""INSERT INTO search_documents(entry_id,lemma,lemma_yo,translations)
      SELECT e.entry_id,e.normalized,e.normalized_yo,
        COALESCE((SELECT group_concat(x.text,' ')
          FROM (SELECT text FROM translations t WHERE t.entry_id=e.entry_id
            ORDER BY t.lang,t.position,t.translation_id) x),'')
      FROM entries e WHERE e.disabled=0""")
    connection.execute("INSERT INTO search_fts(search_fts) VALUES ('rebuild')")


def validate_database(connection: sqlite3.Connection, report: dict) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"SQLite integrity_check failed: {integrity}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchmany(10)
    if violations:
        raise ValueError(f"Foreign key violations: {violations}")
    counts = {}
    for table in (
        "entries",
        "translations",
        "forms",
        "form_keys",
        "examples",
        "entry_examples",
        "relations",
        "expression_members",
        "tags",
        "entry_tags",
        "search_documents",
    ):
        counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    report["database_rows"] = counts
    if counts["entries"] != report["source_rows"]["words"]:
        raise ValueError("Entry count does not match source words")
    if counts["examples"] != report["source_rows"]["sentences"]:
        raise ValueError("Sentence count does not match source sentences")
    span_errors = connection.execute("""SELECT COUNT(*) FROM entry_examples link
      JOIN examples x ON x.sentence_id=link.sentence_id
      WHERE link.start<0 OR link.length<=0 OR link.start+link.length>length(x.ru)""").fetchone()[0]
    if span_errors:
        raise ValueError(f"Invalid sentence spans: {span_errors}")
    active = connection.execute("SELECT COUNT(*) FROM entries WHERE disabled=0").fetchone()[0]
    if counts["search_documents"] != active:
        raise ValueError("Search document count does not match active entries")
    report["active_entries"] = active
    report["warnings"].extend(
        f"{n} active entries without {lang} translations"
        for lang, n in (
            (
                lang,
                connection.execute(
                    """SELECT COUNT(*) FROM entries e WHERE e.disabled=0
              AND NOT EXISTS (SELECT 1 FROM translations t WHERE t.entry_id=e.entry_id
              AND t.lang=?)""",
                    (lang,),
                ).fetchone()[0],
            )
            for lang in ("en", "de")
        )
        if n
    )
    # FTS integrity check detects a stale external-content index.
    connection.execute("INSERT INTO search_fts(search_fts) VALUES ('integrity-check')")


def build_database(snapshot: Path, builds: Path, build_id: str | None = None) -> Path:
    manifest = verify_snapshot(snapshot)
    snapshot_id = manifest["snapshot_date"]
    build_id = build_id or snapshot_id
    if not build_id.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"Invalid build id: {build_id!r}")
    target_dir = builds / build_id
    if target_dir.exists():
        raise FileExistsError(f"Build already exists: {target_dir}")
    target_dir.mkdir(parents=True)
    db_path = target_dir / "openrussian.db"
    report: dict[str, Any] = {
        "build_id": build_id,
        "snapshot_date": snapshot_id,
        "builder_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "started_at": datetime.now(UTC).isoformat(),
        "source_rows": {},
        "database_rows": {},
        "omitted": {},
        "warnings": [],
        "status": "building",
    }
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        create_schema(connection)
        stages = (
            ("entries", _load_entries),
            ("translations", _load_translations),
            ("forms", _load_forms),
            ("examples", _load_examples),
            ("misc", _load_misc),
            ("patches", _apply_patches),
        )
        for name, stage in stages:
            logger.info("Building %s", name)
            stage(connection, snapshot, report)
            connection.commit()
        create_indexes(connection)
        logger.info("Building search index")
        _build_search(connection)
        connection.execute("INSERT INTO metadata VALUES (?,?)", ("snapshot_date", snapshot_id))
        connection.execute("INSERT INTO metadata VALUES (?,?)", ("builder_version", __version__))
        connection.execute(
            "INSERT INTO metadata VALUES (?,?)", ("source_url", manifest["source_url"])
        )
        connection.execute(
            "INSERT INTO metadata VALUES (?,?)", ("source_license", manifest["source_license"])
        )
        connection.commit()
        connection.execute("ANALYZE")
        connection.commit()
        logger.info("Validating database")
        validate_database(connection, report)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.commit()
        report["status"] = "validated"
        report["completed_at"] = datetime.now(UTC).isoformat()
        report["database_bytes"] = db_path.stat().st_size
        write_json(target_dir / "report.json", report)
        write_json(
            target_dir / "manifest.json",
            {
                "build_id": build_id,
                "snapshot_date": snapshot_id,
                "builder_version": __version__,
                "schema_version": SCHEMA_VERSION,
                "database_file": db_path.name,
                "source_manifest": manifest,
                "database_bytes": db_path.stat().st_size,
            },
        )
        return target_dir
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        write_json(target_dir / "report.json", report)
        raise
    finally:
        connection.close()
