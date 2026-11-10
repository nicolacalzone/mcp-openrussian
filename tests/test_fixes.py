"""Regression tests for problems found by the 100-item MCP A/B evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_pipeline import ACUTE, _form, _link, _noun, _sentence, _source, _tl, _word

from openrussian_mcp.domain.normalization import (
    mixed_script_words,
    repair_mixed_script,
    russian_tokens,
)
from openrussian_mcp.pipeline.build import build_database
from openrussian_mcp.pipeline.publish import activate
from openrussian_mcp.service.dictionary import DictionaryService
from openrussian_mcp.sources.contract import TABLES
from openrussian_mcp.sources.manifest import create_snapshot

LATIN_A = "a"  # U+0061


@pytest.fixture
def homograph_service(tmp_path: Path) -> DictionaryService:
    source = tmp_path / "incoming"
    source.mkdir()
    content: dict[str, list[dict]] = {
        "words": [
            _word(1, "мука", "му'ка", "noun", "30"),  # torment, mis-glossed as flour
            _word(2, "мука", "мука'", "noun", "30"),  # flour
            _word(3, "стать", "стать", "noun", "40"),  # the noun "article"
            _word(4, "стать", "стать", "verb", "40"),  # to become: the real owner of rank 40
            _word(5, "столяр", "столя'р", "noun", "60"),
            _word(6, "год", "год", "noun", "10"),
            _word(7, "дом", "до'м", "noun", "20"),
        ],
        "translations": [
            _tl(1, 1, "en", 1, "flour"),
            _tl(2, 1, "de", 1, "Qual, Plage, Pein, Leiden"),
            _tl(3, 2, "en", 1, "flour, meal"),
            _tl(4, 3, "en", 1, "article"),
            _tl(5, 4, "en", 1, "to become"),
            _tl(6, 5, "en", 1, "joiner"),
            _tl(7, 6, "en", 1, "year"),
            _tl(8, 7, "en", 1, "house"),
        ],
        "words_forms": [
            _form(1, 1, "ru_noun_sg_nom", "му'ка"),
            _form(2, 2, "ru_noun_sg_nom", "мука'"),
            _form(3, 6, "ru_noun_sg_gen", "го'да"),
        ],
        "sentences": [],
        "sentences_translations": [],
        "sentences_words": [],
        "nouns": [_noun(1, "f"), _noun(2, "f"), _noun(3, "f"), _noun(5, "m"), _noun(6, "m")]
        + [{**_noun(7, "m"), "animate": "0"}],
        "verbs": [{"word_id": "4", "aspect": "perfective", "partner": ""}],
        "adjectives": [],
        "words_rels": [],
        "expressions_words": [],
        "tags": [],
        "tags_words": [],
    }
    # столяр is flagged inanimate in the export
    content["nouns"][3] = {**_noun(5, "m"), "animate": "0"}
    for table in TABLES:
        _source(source, table, content.get(table, []))
    snapshot = create_snapshot(source, tmp_path / "snapshots", "2026-09-21")
    build = build_database(snapshot, tmp_path / "builds")
    return DictionaryService(activate(build, tmp_path / "active"))


def test_homoglyph_is_detected_and_repaired() -> None:
    word = f"год{LATIN_A}"
    found = mixed_script_words(f"Я учу русский язык уже три {word}.")
    assert found == [
        {
            "word": word,
            "suggestion": "года",
            "latin_letters": [{"letter": LATIN_A, "position": 3}],
        }
    ]
    assert russian_tokens(repair_mixed_script(f"три {word}")) == ["три", "года"]


def test_pure_scripts_are_not_reported() -> None:
    assert mixed_script_words("Я купил iPhone и новый ноутбук.") == []


def test_unfixable_latin_letter_has_no_suggestion() -> None:
    (item,) = mixed_script_words("приdет")
    assert item["suggestion"] is None
    assert item["latin_letters"] == [{"letter": "d", "position": 3}]


def test_analyze_text_reports_mixed_script(homograph_service: DictionaryService) -> None:
    result = homograph_service.analyze_text(f"три год{LATIN_A}")
    assert [m["word"] for m in result["mixed_script"]] == [f"год{LATIN_A}"]
    words = {w["word"]: w for w in result["words"]}
    assert words["года"]["known"] is True  # looked up in the repaired spelling
    assert homograph_service.analyze_text("три года")["mixed_script"] == []


def test_rank_shared_flag(homograph_service: DictionaryService) -> None:
    entries = {e["entry_id"]: e for e in homograph_service.lookup_entries("стать")["entries"]}
    assert entries[3]["rank_shared"] and entries[4]["rank_shared"]
    assert homograph_service.lookup_entries("год")["entries"][0]["rank_shared"] is False


def test_browse_skips_cross_pos_shared_ranks_when_filtered(
    homograph_service: DictionaryService,
) -> None:
    nouns = homograph_service.browse_entries(part_of_speech="noun")
    assert 3 not in [r["entry_id"] for r in nouns["results"]]  # noun "стать" rank is the verb's
    assert nouns["note"]
    # Same-POS homographs keep their rank (flagged), and unfiltered browsing is unchanged.
    assert {1, 2} <= {r["entry_id"] for r in nouns["results"]}
    everything = homograph_service.browse_entries()
    assert {3, 4} <= {r["entry_id"] for r in everything["results"]}
    assert everything["note"] is None
    forced = homograph_service.browse_entries(part_of_speech="noun", include_ambiguous_rank=True)
    assert 3 in [r["entry_id"] for r in forced["results"]]


def test_stress_in_query_selects_homograph(homograph_service: DictionaryService) -> None:
    both = homograph_service.lookup_entries("мука")
    assert both["stress_filtered"] is None
    assert all("stress_match" not in e for e in both["entries"])

    torment = homograph_service.lookup_entries(f"му{ACUTE}ка")
    assert [e["entry_id"] for e in torment["entries"]] == [1]
    assert torment["entries"][0]["stress_match"] is True
    assert torment["stress_filtered"] == 1

    flour = homograph_service.lookup_entries(f"мука{ACUTE}")
    assert [e["entry_id"] for e in flour["entries"]] == [2]

    # A stress the dictionary does not have: nothing is dropped, nothing matches.
    wrong = homograph_service.lookup_entries(f"дом{ACUTE}")
    assert wrong["entries"][0]["stress_match"] is False
    assert wrong["stress_filtered"] is None


def test_known_export_errors_are_patched(homograph_service: DictionaryService) -> None:
    torment = homograph_service.get_entry(1)["entry"]
    assert torment["translations"][0]["text"].startswith("torment")
    assert homograph_service.get_entry(2)["entry"]["translations"][0]["text"] == "flour, meal"
    assert homograph_service.get_entry(5)["entry"]["grammar"]["animate"] is True


def test_patches_are_reported(homograph_service: DictionaryService) -> None:
    import json

    report = json.loads(
        (homograph_service.repository.db_path.parent / "report.json").read_text(encoding="utf-8")
    )
    status = {p["key"]: p["status"] for p in report["patches"]}
    assert status == {"muka-torment-gloss": "applied", "stolyar-animate": "applied"}


def _build(tmp_path: Path, content: dict[str, list[dict]]) -> DictionaryService:
    source = tmp_path / "incoming"
    source.mkdir()
    for table in TABLES:
        _source(source, table, content.get(table, []))
    snapshot = create_snapshot(source, tmp_path / "snapshots", "2026-09-21")
    build = build_database(snapshot, tmp_path / "builds")
    return DictionaryService(activate(build, tmp_path / "active"))


def _sentences(items: list[tuple[str, str]]) -> dict[str, list[dict]]:
    return {
        "sentences": [_sentence(i, ru, "A1") for i, (ru, _) in enumerate(items, 1)],
        "sentences_translations": [
            {"sentence_id": str(i), "tl_en": en, "tl_de": ""} for i, (_, en) in enumerate(items, 1)
        ],
    }


def _links(*spans: tuple[int, int, str, str]) -> list[dict]:
    """(sentence, word, sentence text, linked word as written) -> link rows."""
    return [
        _link(i, sentence, word, text.index(written), len(written))
        for i, (sentence, word, text, written) in enumerate(spans, 1)
    ]


@pytest.fixture
def phrase_service(tmp_path: Path) -> DictionaryService:
    texts = [
        ("Я скучаю по тебе.", "I miss you."),
        ("Мы скучали по дому.", "We missed home."),
        ("Он скучает.", "He is bored."),
        ("Я иду по улице.", "I walk along the street."),
        ("Я ходил.", "I went."),
        ("Том ходил.", "Tom went."),
        ("Она ходила домой.", "She went home."),
    ]
    content: dict[str, list[dict]] = {
        "words": [
            _word(1, "скучать", "скуча'ть", "verb", "10"),
            _word(2, "по", "по", "", "1"),
            _word(3, "идти", "идти'", "verb", "5"),
            _word(4, "ходить", "ходи'ть", "verb", "6"),
        ],
        "translations": [
            _tl(1, 1, "en", 1, "to miss"),
            _tl(2, 2, "en", 1, "along"),
            _tl(3, 3, "en", 1, "to go"),
            _tl(4, 4, "en", 1, "to walk"),
        ],
        "words_forms": [
            _form(1, 1, "ru_verb_presfut_sg1", "скуча'ю"),
            _form(2, 1, "ru_verb_past_m", "скуча'л"),
            _form(3, 1, "ru_verb_past_pl", "скуча'ли"),
            _form(4, 1, "ru_verb_presfut_sg3", "скуча'ет"),
            _form(5, 3, "ru_verb_presfut_sg1", "иду'"),
            _form(6, 4, "ru_verb_past_m", "ходи'л"),
            _form(7, 4, "ru_verb_past_f", "ходи'ла"),
        ],
        **_sentences(texts),
        "sentences_words": _links(
            (1, 1, texts[0][0], "скучаю"),
            (1, 2, texts[0][0], "по"),
            (2, 1, texts[1][0], "скучали"),
            (2, 2, texts[1][0], "по"),
            (3, 1, texts[2][0], "скучает"),
            (4, 3, texts[3][0], "иду"),
            (4, 2, texts[3][0], "по"),
            (5, 4, texts[4][0], "ходил"),
            (6, 4, texts[5][0], "ходил"),
            (7, 4, texts[6][0], "ходила"),
        ),
        "verbs": [{"word_id": str(i), "aspect": "imperfective", "partner": ""} for i in (1, 3, 4)],
        "nouns": [],
        "adjectives": [],
    }
    return _build(tmp_path, content)


def test_phrase_examples_follow_word_order_and_inflection(
    phrase_service: DictionaryService,
) -> None:
    result = phrase_service.find_examples("скучать по")
    sentences = [x["ru"].replace(ACUTE, "") for x in result["examples"]]
    assert sentences == ["Я скучаю по тебе.", "Мы скучали по дому."]
    assert result["exact_form"] is False
    # Words out of order, or a different word in between, do not match.
    assert phrase_service.find_examples("по скучать")["found"] is False
    assert phrase_service.find_examples("идти по")["examples"][0]["ru"].startswith("Я иду")


def test_inflected_phrase_matches_only_that_form(phrase_service: DictionaryService) -> None:
    result = phrase_service.find_examples("скучали по")
    assert result["exact_form"] is True
    assert [x["ru"].replace(ACUTE, "") for x in result["examples"]] == ["Мы скучали по дому."]


def test_examples_are_diversified_across_forms(phrase_service: DictionaryService) -> None:
    plain = phrase_service.find_examples("ходить", limit=2, diverse=False)
    assert [x["ru"].replace(ACUTE, "") for x in plain["examples"]] == ["Я ходил.", "Том ходил."]
    varied = phrase_service.find_examples("ходить", limit=2)
    assert [x["ru"].replace(ACUTE, "") for x in varied["examples"]] == [
        "Я ходил.",
        "Она ходила домой.",
    ]
    # With room to spare the near-duplicate is still returned, after the varied ones.
    assert len(phrase_service.find_examples("ходить", limit=3)["examples"]) == 3


def test_spelling_suggestions_for_unknown_words(tmp_path: Path) -> None:
    content: dict[str, list[dict]] = {
        "words": [
            _word(1, "хотеть", "хоте'ть", "verb", "10"),
            _word(2, "машина", "маши'на", "noun", "20"),
            _word(3, "ресторан", "рестора'н", "noun", "30"),
            _word(4, "москва", "москва'", "noun", "40"),
            _word(5, "мост", "мост", "noun", "50"),
        ],
        "translations": [
            _tl(1, 1, "en", 1, "to want"),
            _tl(2, 2, "en", 1, "car"),
            _tl(3, 3, "en", 1, "restaurant"),
            _tl(4, 4, "en", 1, "Moscow"),
            _tl(5, 5, "en", 1, "bridge"),
        ],
        "words_forms": [
            _form(1, 1, "ru_verb_presfut_sg1", "хочу'"),
            _form(2, 2, "ru_noun_sg_acc", "маши'ну"),
            _form(3, 3, "ru_noun_sg_prep", "рестора'не"),
            _form(4, 4, "ru_noun_sg_prep", "москве'"),
        ],
        "nouns": [_noun(2, "f"), _noun(3, "m"), _noun(4, "f"), _noun(5, "m")],
        "verbs": [{"word_id": "1", "aspect": "imperfective", "partner": ""}],
    }
    service = _build(tmp_path, content)
    result = service.analyze_text("Я хачу машыну в рестаране. Масскве.")
    suggestions = {
        w["word"]: [s["word"].replace(ACUTE, "") for s in w["suggestions"]]
        for w in result["words"]
        if not w["known"]
    }
    assert suggestions["хачу"] == ["хочу"]
    assert suggestions["машыну"] == ["машину"]
    assert suggestions["рестаране"] == ["ресторане"]
    assert suggestions["Масскве"] == ["москве"]
    known = [w for w in result["words"] if w["known"]]
    assert all(w["suggestions"] == [] for w in known)
    assert result["words"][0]["suggestions"] == []  # «Я» is not an unknown word


def test_browse_by_register_and_summary_tags(tmp_path: Path) -> None:
    content: dict[str, list[dict]] = {
        "words": [
            _word(1, "дом", "до'м", "noun", "10"),
            _word(2, "ночлежка", "ночле'жка", "noun", "20"),
            _word(3, "ныне", "ны'не", "", "30"),
        ],
        "translations": [
            _tl(1, 1, "en", 1, "house"),
            _tl(2, 2, "en", 1, "dosshouse"),
            _tl(3, 3, "en", 1, "now"),
        ],
        "nouns": [_noun(1, "m"), _noun(2, "f")],
        "tags": [
            {"id": "1", "uid": "colloquial", "name_en": "Colloquial", "name_ru": "", "name_de": ""},
            {"id": "2", "uid": "archaic", "name_en": "Archaic", "name_ru": "", "name_de": ""},
        ],
        "tags_words": [
            {"id": "1", "tag_id": "1", "word_id": "2", "translation_id": "", "tag_text": ""},
            {"id": "2", "tag_id": "2", "word_id": "3", "translation_id": "", "tag_text": ""},
        ],
    }
    service = _build(tmp_path, content)
    colloquial = service.browse_entries(register="colloquial")
    assert [r["entry_id"] for r in colloquial["results"]] == [2]
    assert colloquial["results"][0]["registers"] == ["colloquial"]
    assert [r["entry_id"] for r in service.browse_entries(register="archaic")["results"]] == [3]
    assert len(service.browse_entries()["results"]) == 3
    with pytest.raises(ValueError):
        service.browse_entries(register="slang")
