from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, TextContent

from openrussian_mcp.domain.grammar import describe_form_type, paradigm
from openrussian_mcp.domain.normalization import (
    form_keys,
    lookup_key,
    normalize_lookup,
    russian_tokens,
    search_tokens,
    stress,
)
from openrussian_mcp.mcp.server import create_server
from openrussian_mcp.pipeline.build import build_database
from openrussian_mcp.pipeline.publish import activate, active_database, prune, validate_build
from openrussian_mcp.service.dictionary import DictionaryService
from openrussian_mcp.sources import release, togetherdb
from openrussian_mcp.sources.contract import TABLES, filename
from openrussian_mcp.sources.manifest import create_snapshot, inspect_directory, verify_snapshot
from openrussian_mcp.storage.repository import DictionaryRepository
from openrussian_mcp.storage.schema import SCHEMA_VERSION

ACUTE = "́"


def _source(directory: Path, table: str, rows: list[dict[str, str]]) -> None:
    headers = list(TABLES[table])
    for row in rows:
        headers.extend(column for column in row if column not in headers)
    with (directory / filename(table)).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _word(id_: int, bare: str, accented: str, type_: str, rank: str, disabled: str = "0") -> dict:
    return {
        "id": str(id_),
        "bare": bare,
        "accented": accented,
        "type": type_,
        "rank": rank,
        "disabled": disabled,
    }


def _tl(id_: int, word: int, lang: str, position: int, text: str, **extra: str) -> dict:
    return {
        "id": str(id_),
        "word_id": str(word),
        "lang": lang,
        "position": str(position),
        "tl": text,
        **extra,
    }


def _form(id_: int, word: int, form_type: str, form: str, position: int = 1) -> dict:
    return {
        "id": str(id_),
        "word_id": str(word),
        "form_type": form_type,
        "position": str(position),
        "form": form,
        "form_bare": form.replace("'", ""),
    }


def _noun(word: int, gender: str) -> dict:
    return {
        "word_id": str(word),
        "gender": gender,
        "partner": "",
        "animate": "1",
        "indeclinable": "0",
        "sg_only": "0",
        "pl_only": "0",
    }


def _sentence(id_: int, ru: str, level: str, disabled: str = "0") -> dict:
    return {
        "id": str(id_),
        "ru": ru,
        "tatoeba_key": str(122 + id_),
        "disabled": disabled,
        "level": level,
    }


def _link(id_: int, sentence: int, word: int, start: int, length: int) -> dict:
    return {
        "id": str(id_),
        "sentence_id": str(sentence),
        "word_id": str(word),
        "start": str(start),
        "length": str(length),
        "form_type": "",
    }


@pytest.fixture
def incoming(tmp_path: Path) -> Path:
    source = tmp_path / "incoming"
    source.mkdir()
    content: dict[str, list[dict[str, str]]] = {
        "words": [
            _word(1, "кот", "ко'т", "noun", "1"),
            _word(2, "кот", "ко'т", "noun", "2"),
            _word(3, "ёж", "ё'ж", "", "3"),
            _word(4, "тайный", "тайный", "adjective", "", disabled="1"),
            _word(5, "идти", "идти'", "verb", "4"),
            _word(6, "лес", "ле'с", "noun", "5"),
            _word(7, "новый", "но'вый", "adjective", "6"),
            _word(8, "кошка", "ко'шка", "noun", "7"),
            _word(9, "кошки", "ко'шки", "noun", "8"),
            _word(10, "бежать", "бежа'ть", "verb", "50"),
            _word(11, "провести", "провести'", "verb", "10"),
            _word(12, "мой", "мо'й", "pronoun", "9"),
            _word(13, "мыть", "мы'ть", "verb", "20"),
        ],
        "translations": [
            _tl(1, 1, "en", 1, "cat"),
            _tl(2, 1, "en", 1, "cat"),
            _tl(13, 1, "de", 1, "Kater"),
            _tl(3, 2, "de", 1, "Kater"),
            _tl(4, 3, "en", 1, "hedgehog"),
            _tl(5, 5, "en", 1, "to go"),
            _tl(6, 5, "de", 1, "gehen"),
            _tl(7, 10, "en", 1, "to run"),
            _tl(8, 11, "en", 1, "to conduct"),
            _tl(9, 11, "en", 6, "run, lay"),
            _tl(10, 8, "en", 1, "cat (female)"),
            _tl(11, 12, "en", 1, "my"),
            _tl(12, 13, "en", 1, "to wash"),
            _tl(14, 6, "en", 1, "forest", info="в + prepositional: в лесу'"),
        ],
        "words_forms": [
            _form(1, 1, "ru_noun_sg_gen", "кота'"),
            {**_form(2, 1, "ru_noun_sg_dat", ""), "form_bare": ""},
            _form(3, 5, "ru_verb_presfut_sg3", "идёт"),
            _form(4, 5, "ru_verb_presfut_sg1", "иду'"),
            _form(5, 6, "ru_noun_sg_prep", "о ле'се", 1),
            _form(6, 6, "ru_noun_sg_prep", "в лесу'", 2),
            _form(7, 7, "ru_adj_short_pl", "но'вы / новы'"),
            _form(8, 8, "ru_noun_sg_gen", "ко'шки"),
            _form(9, 8, "ru_noun_pl_nom", "ко'шки"),
            _form(10, 12, "ru_adj_m_nom", "мо'й"),
            _form(11, 13, "ru_verb_imperative_sg", "мо'й"),
            _form(12, 1, "ru_noun_sg_nom", "ко'т"),
            _form(13, 5, "ru_verb_imperative_sg", "приподним-//иди'"),
        ],
        "sentences": [
            _sentence(1, "Э'то ко'т.", "A1"),
            _sentence(2, "Тайный кот.", "A1", disabled="1"),
            _sentence(3, "Он идёт домо'й.", "A2"),
            _sentence(4, "Я иду'.", "A1"),
        ],
        "sentences_translations": [
            {"sentence_id": "1", "tl_en": "This is a cat.", "tl_de": ""},
            {"sentence_id": "2", "tl_en": "Secret cat.", "tl_de": ""},
            {"sentence_id": "3", "tl_en": "He is going home.", "tl_de": "Er geht nach Hause."},
            {"sentence_id": "4", "tl_en": "I am going.", "tl_de": ""},
        ],
        "sentences_words": [
            _link(1, 1, 1, 5, 4),
            _link(2, 2, 1, 7, 3),
            _link(3, 3, 5, 3, 4),
            _link(4, 4, 5, 2, 4),
        ],
        "nouns": [
            _noun(1, "m"),
            _noun(2, "m"),
            _noun(3, "m"),
            _noun(6, "m"),
            _noun(8, "f"),
            _noun(9, "pl"),
        ],
        "verbs": [
            {"word_id": "5", "aspect": "imperfective", "partner": "пойти'"},
            {"word_id": "10", "aspect": "imperfective", "partner": ""},
            {"word_id": "11", "aspect": "perfective", "partner": ""},
            {"word_id": "13", "aspect": "imperfective", "partner": ""},
        ],
        "adjectives": [
            {"word_id": "4", "incomparable": "0"},
            {"word_id": "7", "incomparable": "0"},
        ],
        "words_rels": [{"id": "1", "word_id": "1", "rel_word_id": "2", "relation": "related"}],
        "expressions_words": [],
        "tags": [
            {"id": "1", "uid": "test", "name_en": "Test", "name_ru": "Тест", "name_de": "Test"}
        ],
        "tags_words": [
            {"id": "1", "tag_id": "1", "word_id": "1", "translation_id": "1", "tag_text": ""}
        ],
    }
    for table, rows in content.items():
        _source(source, table, rows)
    return source


@pytest.fixture
def built(incoming: Path, tmp_path: Path) -> tuple[Path, DictionaryService]:
    snapshot = create_snapshot(incoming, tmp_path / "snapshots", "2026-09-21")
    build = build_database(snapshot, tmp_path / "builds")
    db = activate(build, tmp_path / "active")
    return build, DictionaryService(db)


def _ids(response: dict) -> list[int]:
    return [entry["entry_id"] for entry in response["entries"]]


def test_normalization() -> None:
    assert normalize_lookup("  Ко'т  ") == "кот"
    assert normalize_lookup("ко́т") == "кот"
    assert normalize_lookup("Ёж", fold_yo=True) == "еж"
    assert search_tokens('cat OR "hedgehog"*') == ["cat", "or", "hedgehog"]
    assert lookup_key("Идет") == ("идет", True)
    assert lookup_key("идёт") == ("идёт", False)
    assert stress("ко'т") == f"ко{ACUTE}т"
    assert stress("don't") == "don't"
    assert russian_tokens("Я иду́ в по-русски, ok!") == ["Я", f"иду{ACUTE}", "в", "по-русски"]


def test_form_keys_split_composite_cells() -> None:
    assert form_keys("новы / новы", "ru_adj_short_pl") == ["новы"]
    assert form_keys("выброси//выбрось", "ru_verb_imperative_sg") == ["выброси", "выбрось"]
    assert form_keys("(должною)", "ru_adj_f_inst") == ["должною"]
    assert form_keys("о лесе", "ru_noun_sg_prep") == ["о лесе", "лесе"]
    assert form_keys("приподним-//подыми", "ru_verb_imperative_sg") == ["подыми"]
    assert form_keys("-", "ru_adj_short_m") == []
    assert form_keys("в порядке исключения", "ru_base") == ["в порядке исключения"]


def test_grammar_labels_and_paradigm() -> None:
    assert describe_form_type("ru_noun_sg_gen") == "noun genitive singular"
    assert describe_form_type("ru_verb_presfut_sg3", "perfective") == "future 3rd person singular"
    assert describe_form_type("ru_adj_short_f") == "short form feminine"
    table = paradigm(
        [
            {"form_type": "ru_noun_pl_nom", "position": 1, "form": "ко'шки"},
            {"form_type": "ru_noun_sg_gen", "position": 1, "form": "ко'шки"},
            {"form_type": "ru_noun_sg_nom", "position": 1, "form": "ко'шка"},
        ]
    )
    assert table == {
        "sg": {"nom": f"ко{ACUTE}шка", "gen": f"ко{ACUTE}шки"},
        "pl": {"nom": f"ко{ACUTE}шки"},
    }
    assert list(table["sg"]) == ["nom", "gen"]


def test_missing_table_fails(incoming: Path) -> None:
    (incoming / filename("tags")).unlink()
    with pytest.raises(ValueError, match="Missing source table"):
        inspect_directory(incoming, "2026-09-21")


def test_snapshot_build_query_and_activation(incoming: Path, tmp_path: Path) -> None:
    snapshot = create_snapshot(incoming, tmp_path / "snapshots", "2026-09-21")
    assert verify_snapshot(snapshot)["files"]["words"]["rows"] == 13
    build = build_database(snapshot, tmp_path / "builds")
    assert validate_build(build)["schema_version"] == SCHEMA_VERSION
    db = activate(build, tmp_path / "active")
    assert active_database(tmp_path / "active") == db
    manifest = json.loads((tmp_path / "active" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database_path"] == "builds/2026-09-21/openrussian.db"

    service = DictionaryService(db)
    assert service.info()["active_entries"] == 12
    assert service.info()["counts"]["entries"] == 13
    assert _ids(service.lookup_entries("кот")) == [1, 2]
    assert _ids(service.lookup_entries("еж")) == [3]
    assert service.lookup_entries("тайный")["found"] is False
    assert _ids(service.lookup_entries("кота")) == [1]
    assert service.lookup_entries("кота", part_of_speech="verb")["found"] is False

    hedgehog = service.search_entries("hedgehog")["results"][0]
    assert hedgehog["entry_id"] == 3
    assert hedgehog["matched_translation"] == "hedgehog"
    assert service.search_entries("cat")["results"][0]["entry_id"] == 1
    assert service.search_entries("кота")["results"][0]["match_reason"] == "inflected_form"

    entry = service.get_entry(1)["entry"]
    assert entry is not None
    assert entry["stressed"] == f"ко{ACUTE}т"
    assert [t["text"] for t in entry["translations"]] == ["cat"]
    assert entry["forms"] == {"sg": {"nom": f"ко{ACUTE}т", "gen": f"кота{ACUTE}"}}
    assert entry["grammar"] == {"gender": "masculine", "animate": True}
    assert entry["relations"] == {"related": [{"entry_id": 2, "word": f"ко{ACUTE}т"}]}
    assert len(entry["examples"]) == 1
    assert entry["examples"][0]["source_url"].endswith("/123")
    assert entry["examples"][0]["word"] == f"ко{ACUTE}т"
    assert "normalized" not in entry and "disabled" not in entry

    report = json.loads((build / "report.json").read_text(encoding="utf-8"))
    assert report["omitted"]["duplicate_translations"] == 1
    assert report["omitted"]["empty_forms"] == 1
    assert report["source_rows"]["translations"] == 14

    async def check_mcp() -> None:
        server = create_server(db)
        direct = await server.call_tool("lookup_entries", {"lemma": "кот"})
        assert isinstance(direct, CallToolResult)
        assert direct.is_error is False
        assert isinstance(direct.content[0], TextContent)
        text = direct.content[0].text
        assert json.loads(text)["count"] == 2
        assert "null" not in text and "\n" not in text
        assert direct.structured_content is not None
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert set(tools) == {
            "analyze_text",
            "lookup_entries",
            "search_entries",
            "get_entry",
            "browse_entries",
            "find_examples",
        }
        annotations = tools["analyze_text"].annotations
        assert annotations is not None and annotations.read_only_hint is True
        assert tools["lookup_entries"].output_schema is not None
        resources = await server.list_resources()
        assert "openrussian://grammar/form-types" in [str(item.uri) for item in resources]

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "openrussian_mcp.mcp.server"],
            env={**os.environ, "OPENRUSSIAN_DATA_DIR": str(tmp_path)},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("search_entries", {"query": "hedgehog"})
                assert isinstance(result, CallToolResult)
                assert result.is_error is False
                assert isinstance(result.content[0], TextContent)
                assert json.loads(result.content[0].text)["results"][0]["entry_id"] == 3
                analysis = await session.call_tool("analyze_text", {"text": "Он идет в лесу"})
                assert isinstance(analysis.content[0], TextContent)
                words = json.loads(analysis.content[0].text)["words"]
                assert [w["known"] for w in words] == [False, True, False, True]

    asyncio.run(check_mcp())


def test_lookup_without_yo_matches_yo_forms(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    result = service.lookup_entries("идет")
    assert _ids(result) == [5]
    assert result["entries"][0]["match"] == {
        "headword": False,
        "forms": [{"form": "идёт", "grammar": ["present 3rd person singular"]}],
    }
    assert _ids(service.lookup_entries("идёт")) == [5]
    # A deliberate ё does not match plain е.
    assert service.lookup_entries("кёт")["found"] is False


def test_headword_does_not_hide_form_matches(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    koshki = service.lookup_entries("кошки")
    assert _ids(koshki) == [9, 8]
    assert koshki["entries"][0]["match"]["headword"] is True
    assert koshki["entries"][1]["match"]["forms"] == [
        {"form": f"ко{ACUTE}шки", "grammar": ["noun genitive singular", "noun nominative plural"]}
    ]
    moy = service.lookup_entries("мой")
    assert _ids(moy) == [12, 13]
    assert moy["entries"][0]["match"]["forms"][0]["grammar"] == ["pronoun masculine nominative"]
    assert moy["entries"][1]["match"]["forms"][0]["grammar"] == ["imperative singular"]


def test_composite_and_prepositional_forms(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    assert _ids(service.lookup_entries("новы")) == [7]
    assert _ids(service.lookup_entries("лесе")) == [6]
    assert _ids(service.lookup_entries("лесу")) == [6]
    assert _ids(service.lookup_entries("иди")) == [5]
    assert service.lookup_entries("приподним")["found"] is False
    forms = service.get_entry(6)["entry"]["forms"]
    assert forms == {"sg": {"prep": f"о ле{ACUTE}се / в лесу{ACUTE}"}}


def test_translation_search_ranking(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    run = service.search_entries("run", language="en")["results"]
    assert [r["entry_id"] for r in run[:2]] == [10, 11]
    assert run[0]["matched_translation"] == "to run"
    assert service.search_entries("go", language="en")["results"][0]["entry_id"] == 5
    assert service.search_entries("gehen", language="de")["results"][0]["entry_id"] == 5
    cat = service.search_entries("cat")["results"]
    assert cat[0]["entry_id"] == 1
    assert cat[0]["translations"][0] == "cat"
    assert service.get_entry(1, language="both")["entry"]["translations"][0]["lang"] == "en"
    # Entries with only German translations fall back to German.
    assert service.get_entry(2)["entry"]["translations"][0]["text"] == "Kater"


def test_analyze_text(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    result = service.analyze_text("Кот идет. Кот и кошки!")
    assert result["token_count"] == 5
    assert result["unknown"] == ["и"]
    words = {w["word"]: w for w in result["words"]}
    assert words["Кот"]["count"] == 2
    assert [c["entry_id"] for c in words["Кот"]["candidates"]] == [1, 2]
    assert words["идет"]["candidates"][0]["lemma"] == f"идти{ACUTE}"
    assert words["идет"]["candidates"][0]["gloss"] == "to go"
    assert [c["entry_id"] for c in words["кошки"]["candidates"]] == [9, 8]


def test_browse_and_examples(built: tuple[Path, DictionaryService]) -> None:
    _, service = built
    browse = service.browse_entries(max_rank=5)
    assert [r["entry_id"] for r in browse["results"]] == [1, 2, 3, 5, 6]
    assert service.browse_entries(part_of_speech="verb", limit=2)["next_offset"] == 2

    exact = service.find_examples("иду")
    assert exact["exact_form"] is True
    assert [x["source_url"][-3:] for x in exact["examples"]] == ["126"]
    general = service.find_examples("идти")
    assert general["exact_form"] is False
    assert [x["source_url"][-3:] for x in general["examples"]] == ["126", "125"]
    assert general["examples"][1]["en"] == "He is going home."
    assert service.find_examples("идти", max_level="A1")["examples"][0]["word"] == f"иду{ACUTE}"
    german = service.find_examples("идти", language="de")["examples"]
    assert german[0]["de"] == "Er geht nach Hause."  # sentences with German first
    assert german[1]["en"] == "I am going."  # falls back to English


def test_rebuild_with_build_id_and_move_data_dir(incoming: Path, tmp_path: Path) -> None:
    snapshot = create_snapshot(incoming, tmp_path / "data" / "snapshots", "2026-09-21")
    build_database(snapshot, tmp_path / "data" / "builds")
    with pytest.raises(FileExistsError):
        build_database(snapshot, tmp_path / "data" / "builds")
    second = build_database(snapshot, tmp_path / "data" / "builds", "2026-09-21-v2")
    assert json.loads((second / "manifest.json").read_text())["build_id"] == "2026-09-21-v2"
    activate(second, tmp_path / "data" / "active")
    shutil.move(tmp_path / "data", tmp_path / "moved")
    assert active_database(tmp_path / "moved" / "active") == (
        tmp_path / "moved" / "builds" / "2026-09-21-v2" / "openrussian.db"
    )


def test_old_schema_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(ValueError, match="schema version 1"):
        DictionaryRepository(db)


def test_tampered_snapshot_cannot_build(incoming: Path, tmp_path: Path) -> None:
    snapshot = create_snapshot(incoming, tmp_path / "snapshots", "2026-09-21")
    with (snapshot / filename("words")).open("a", encoding="utf-8") as stream:
        stream.write("changed")
    with pytest.raises(ValueError, match="mismatch|changed"):
        build_database(snapshot, tmp_path / "builds")


def test_orphan_side_table_fails_without_publishing(incoming: Path, tmp_path: Path) -> None:
    with (incoming / filename("nouns")).open("a", encoding="utf-8", newline="") as stream:
        stream.write("999,m,,1,0,0,0\n")
    snapshot = create_snapshot(incoming, tmp_path / "snapshots", "2026-09-21")
    with pytest.raises(ValueError, match="orphan word_id=999"):
        build_database(snapshot, tmp_path / "builds")
    failed_build = tmp_path / "builds" / "2026-09-21"
    report = json.loads((failed_build / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    with pytest.raises(ValueError, match="Incomplete database build"):
        activate(failed_build, tmp_path / "active")
    assert not (tmp_path / "active" / "manifest.json").exists()


def test_active_database_detects_tampering(incoming: Path, tmp_path: Path) -> None:
    snapshot = create_snapshot(incoming, tmp_path / "snapshots", "2026-09-21")
    build = build_database(snapshot, tmp_path / "builds")
    db = activate(build, tmp_path / "active")
    with db.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        active_database(tmp_path / "active")


# --- acquisition: download, pull, prune (no network: HTTP layers are monkeypatched) ---


def _release_zip(incoming: Path, archive: Path, extra: dict[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(archive, "w") as bundle:
        for table in TABLES:
            bundle.write(incoming / filename(table), filename(table))
        bundle.writestr("NOTICE", "attribution")
        for name, data in (extra or {}).items():
            bundle.writestr(name, data)


def _fake_release(
    monkeypatch: pytest.MonkeyPatch, archive: Path, tag: str = "dump-2026-11-01", sha: str = ""
) -> list[str]:
    downloads: list[str] = []
    digest = sha or hashlib.sha256(archive.read_bytes()).hexdigest()

    def fetch_json(url: str) -> dict[str, Any]:
        assert url.endswith("/repos/owner/repo/releases/latest")
        return {
            "tag_name": tag,
            "assets": [
                {"name": release.ASSET_NAME, "url": "asset:zip"},
                {"name": release.HASH_NAME, "url": "asset:hash"},
            ],
        }

    def fetch_file(url: str, destination: Path) -> None:
        downloads.append(url)
        if url == "asset:zip":
            shutil.copyfile(archive, destination)
        else:
            destination.write_text(f"{digest}  {release.ASSET_NAME}\n", encoding="utf-8")

    monkeypatch.setattr(release, "fetch_json", fetch_json)
    monkeypatch.setattr(release, "fetch_file", fetch_file)
    return downloads


def test_pull_builds_activates_and_is_idempotent(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "release.zip"
    _release_zip(incoming, archive)
    downloads = _fake_release(monkeypatch, archive)
    root = tmp_path / "data"
    result = release.pull(root, "owner/repo")
    assert result["status"] == "updated"
    assert result["build_id"] == "2026-11-01"
    manifest = json.loads((root / "snapshots" / "2026-11-01" / "manifest.json").read_text())
    assert manifest["acquisition_method"] == "togetherdb_export_github_release"
    active = json.loads((root / "active" / "manifest.json").read_text())
    assert active["snapshot_date"] == "2026-11-01"
    assert DictionaryService(active_database(root / "active")).info()
    assert len(downloads) == 2
    again = release.pull(root, "owner/repo")
    assert again["status"] == "up to date"
    assert len(downloads) == 2
    forced = release.pull(root, "owner/repo", force=True)
    assert forced["build_id"] == "2026-11-01-v2"
    assert len(downloads) == 2  # reuses the verified snapshot


def test_pull_rejects_hash_mismatch(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "release.zip"
    _release_zip(incoming, archive)
    _fake_release(monkeypatch, archive, sha="0" * 64)
    root = tmp_path / "data"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        release.pull(root, "owner/repo")
    assert not (root / "snapshots").exists()
    assert not (root / "active").exists()


@pytest.mark.parametrize("name", ["../evil.csv", "payload.sh", "sub/openrussian_public - x.csv"])
def test_pull_rejects_unexpected_zip_entry(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    archive = tmp_path / "release.zip"
    _release_zip(incoming, archive, {name: b"x"})
    _fake_release(monkeypatch, archive)
    with pytest.raises(ValueError, match="Unexpected entry"):
        release.pull(tmp_path / "data", "owner/repo")
    assert not (tmp_path / "evil.csv").exists()
    assert not (tmp_path / "data" / "snapshots").exists()


def test_pull_rejects_bad_tag(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "release.zip"
    _release_zip(incoming, archive)
    _fake_release(monkeypatch, archive, tag="v1.0")
    with pytest.raises(ValueError, match="Unexpected release tag"):
        release.pull(tmp_path / "data", "owner/repo")


def _three_builds(incoming: Path, root: Path) -> None:
    for day in ("2026-01-01", "2026-02-01", "2026-03-01"):
        snapshot = create_snapshot(incoming, root / "snapshots", day)
        build_database(snapshot, root / "builds")


def test_prune_keeps_active_and_newest_other(incoming: Path, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _three_builds(incoming, root)
    activate(root / "builds" / "2026-03-01", root / "active")
    (root / "builds" / "broken").mkdir()
    (root / "verified_builds").mkdir()
    preview = prune(root, keep=2, dry_run=True)
    assert preview["deleted_builds"] == ["2026-01-01", "broken"]
    assert (root / "builds" / "2026-01-01").exists()
    result = prune(root, keep=2)
    assert result["kept_builds"] == ["2026-02-01", "2026-03-01"]
    assert sorted(p.name for p in (root / "builds").iterdir()) == ["2026-02-01", "2026-03-01"]
    assert sorted(p.name for p in (root / "snapshots").iterdir()) == ["2026-02-01", "2026-03-01"]
    assert (root / "verified_builds").exists()
    assert active_database(root / "active").is_file()


def test_prune_never_deletes_older_active_build(incoming: Path, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _three_builds(incoming, root)
    activate(root / "builds" / "2026-01-01", root / "active")
    result = prune(root, keep=2)
    assert result["kept_builds"] == ["2026-01-01", "2026-03-01"]
    assert active_database(root / "active").is_file()
    with pytest.raises(ValueError, match="at least 1"):
        prune(root, keep=0)


def _fake_togetherdb(
    monkeypatch: pytest.MonkeyPatch,
    incoming: Path,
    tables: list[str],
    fail_first_download: bool = False,
    body: bytes | None = None,
) -> None:
    state = {"failed": False}
    keys = {f"key-{table}": table for table in tables}

    def payload(table: str) -> bytes:
        path = incoming / filename(table)
        return path.read_bytes() if path.exists() else b"id,name\n1,x\n"

    def fake_open(url: str, method: str = "GET", timeout: int = 120) -> io.BytesIO:
        if url.endswith("/structure"):
            return io.BytesIO(
                json.dumps({"result": {"tables": [{"name": t} for t in tables]}}).encode()
            )
        if method == "POST":
            table = url.split("/tables/")[1].split("/export")[0]
            return io.BytesIO(json.dumps({"result": {"exportKey": f"key-{table}"}}).encode())
        if fail_first_download and not state["failed"]:
            state["failed"] = True
            raise ConnectionResetError("dropped")
        return io.BytesIO(body if body is not None else payload(keys[url.rsplit("/", 1)[1]]))

    monkeypatch.setattr(togetherdb, "_open", fake_open)
    monkeypatch.setattr(togetherdb, "_pause", lambda: None)
    monkeypatch.setattr(togetherdb, "_backoff", lambda attempt: None)


def test_download_writes_contract_filenames_and_retries(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_togetherdb(monkeypatch, incoming, [*TABLES, "scenarios"], fail_first_download=True)
    output = togetherdb.download(tmp_path / "raw")
    assert sorted(p.name for p in output.iterdir()) == sorted(
        [filename(t) for t in TABLES] + [filename("scenarios")]
    )
    assert not list(output.glob("*.part"))
    assert not (tmp_path / "raw.partial").exists()
    assert inspect_directory(output, "2026-11-01")["files"]["words"]["rows"] == 13


def test_download_fails_cleanly_on_missing_table(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_togetherdb(monkeypatch, incoming, [t for t in TABLES if t != "tags"])
    with pytest.raises(RuntimeError, match="lacks required tables"):
        togetherdb.download(tmp_path / "raw")
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "raw.partial").exists()


@pytest.mark.parametrize("body", [b"", b"\x00\x01binary"])
def test_download_rejects_empty_or_non_csv(
    incoming: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    _fake_togetherdb(monkeypatch, incoming, list(TABLES), body=body)
    with pytest.raises(RuntimeError, match="failed after 4 tries"):
        togetherdb.download(tmp_path / "raw")
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "raw.partial").exists()
