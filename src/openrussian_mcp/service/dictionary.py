from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openrussian_mcp.domain.grammar import (
    GENDERS,
    describe_form_type,
    display_form,
    form_sort_key,
    paradigm,
)
from openrussian_mcp.domain.normalization import (
    mixed_script_words,
    normalize_lookup,
    repair_mixed_script,
    russian_tokens,
    stress,
)
from openrussian_mcp.domain.spelling import spelling_cost
from openrussian_mcp.domain.vocabulary import (
    DISPLAY_LANGUAGES,
    LANGUAGES,
    LEVELS,
    PARTS_OF_SPEECH,
    REGISTERS,
)
from openrussian_mcp.storage.repository import (
    DictionaryRepository,
    Match,
    Queries,
)

TATOEBA_SOURCE = "Tatoeba (CC BY 2.0 FR)"
MAX_TEXT_LENGTH = 4000
MAX_TEXT_TOKENS = 300
MAX_SUGGESTED_WORDS = 15
SUGGESTIONS_PER_WORD = 3
# One plain edit or two common confusions. Larger distances mostly return noise.
SUGGESTION_MAX_COST = 1.0
_RELATION_CAP = 10
_GLOSS_PREFIX = re.compile(r"^(?:to|a|an|the)\s+")
_PARENTHESES = re.compile(r"\([^)]*\)")
_ACUTE = "\u0301"


def _bounded_text(value: str, *, name: str, maximum: int = 120) -> str:
    value = value.strip()
    if not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} must contain 1 to {maximum} characters")
    return value


def _bounded(value: int, minimum: int, maximum: int, *, name: str = "limit") -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _choice(value: str | None, allowed: Sequence[str], name: str) -> str | None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _langs(language: str) -> tuple[str, ...]:
    return LANGUAGES if language == "both" else (language,)


def _pick(rows: list[dict], language: str) -> list[dict]:
    """Rows in the requested language, or the other language if there are none."""
    if language == "both":
        return rows
    chosen = [row for row in rows if row["lang"] == language]
    return chosen or rows


def _stress_query(value: str) -> str | None:
    """The query with its stress mark kept, or None if the user gave no stress mark."""
    text = unicodedata.normalize("NFC", value.strip()).casefold()
    return text if _ACUTE in unicodedata.normalize("NFD", text) else None


def _same_stress(query: str, candidate: str) -> bool:
    folded = unicodedata.normalize("NFC", candidate.strip()).casefold()
    return folded == query


def _entry_has_stress(query: str, entry: dict) -> bool:
    """Does the entry spell the query, stress included, as its headword or one of its forms?"""
    match = entry.get("match") or {}
    candidates: list[str] = []
    if match.get("headword") and entry.get("stressed"):
        candidates.append(entry["stressed"])
    for form in match.get("forms", []):
        candidates.extend(form["form"].split(" / "))
    return any(_same_stress(query, candidate) for candidate in candidates)


def _diversify(rows: list[dict], limit: int) -> list[dict]:
    """Pick up to `limit` sentences that show different forms and different sentence frames.

    Rows arrive easiest and shortest first. Sentences that differ from an already chosen one
    in a single word ("Возьми мой." / "Возьми мою.", "Я ходил." / "Том ходил.") are treated
    as repeats and used only to fill up. The rest are taken round-robin across the forms of
    the word, so a query for ходить shows ходил, ходила and ходили.
    """
    forms: dict[str, list[dict]] = {}
    for row in rows:
        forms.setdefault(normalize_lookup(row.get("span") or "", fold_yo=True), []).append(row)
    chosen: list[dict] = []
    frames: list[list[str]] = []
    repeats: list[dict] = []

    def is_repeat(tokens: list[str]) -> bool:
        return any(
            len(tokens) == len(other)
            and sum(a != b for a, b in zip(tokens, other, strict=True)) <= 1
            for other in frames
        )

    queues = [list(group) for group in forms.values()]
    while queues and len(chosen) < limit:
        for queue in list(queues):
            while queue:
                row = queue.pop(0)
                tokens = [normalize_lookup(t, fold_yo=True) for t in russian_tokens(row["ru"])]
                if is_repeat(tokens):
                    repeats.append(row)
                    continue
                chosen.append(row)
                frames.append(tokens)
                break
            if not queue:
                queues.remove(queue)
            if len(chosen) == limit:
                break
    return chosen + repeats[: max(0, limit - len(chosen))]


def _gloss_text(text: str) -> str:
    return _GLOSS_PREFIX.sub("", _PARENTHESES.sub("", text).strip().casefold()).strip()


def _gloss_rank(query: str, text: str, position: int | None) -> tuple[int, int, int] | None:
    """How well a translation answers an English/German query; lower is better.

    Tier 0: one comma-separated sense equals the query ("to run" for "run").
    Tier 1: a sense starts with the query as a phrase ("run away").
    Tier 2: the query is a whole word inside a sense.
    """
    items = [_gloss_text(item) for item in re.split(r"[,;]", text)]
    best: tuple[int, int, int] | None = None
    for index, item in enumerate(items):
        if item == query:
            tier = 0
        elif item.startswith(query + " "):
            tier = 1
        elif re.search(rf"(?<!\w){re.escape(query)}(?!\w)", item):
            tier = 2
        else:
            continue
        candidate = (tier, position or 99, index)
        if best is None or candidate < best:
            best = candidate
    return best


class DictionaryService:
    def __init__(self, database: Path):
        self.repository = DictionaryRepository(database)
        self._info = self.repository.metadata()

    def info(self) -> dict:
        return self._info.copy()

    @property
    def dataset_date(self) -> str:
        return self._info["snapshot_date"]

    def form_types(self) -> dict:
        with self.repository.session() as queries:
            labels = queries.form_types()
        for label in labels:
            label["meaning"] = describe_form_type(label["form_type"])
        return {
            "labels": labels,
            "note": (
                "get_entry groups forms into tables keyed by these abbreviations: "
                "sg/pl = singular/plural; nom, gen, dat, acc, inst, prep = cases; "
                "m/f/n = gender; sg1..pl3 = person and number. The verb table 'present' "
                "(imperfective) or 'future' (perfective) comes from OpenRussian's presfut forms."
            ),
        }

    # ----- formatting -------------------------------------------------------------------

    @staticmethod
    def _summary(
        row: dict, translations: list[dict], language: str, tags: list[str] | None = None
    ) -> dict:
        primary = "en" if language == "both" else language
        return {
            "entry_id": row["entry_id"],
            "headword": row["bare"],
            "stressed": stress(row["accented"]),
            "pos": row["pos"],
            "rank": row["rank"],
            "rank_shared": bool(row.get("rank_shared")),
            "level": row["level"],
            "aspect": row.get("aspect"),
            "registers": tags or None,
            "translations": [
                t["text"] if t["lang"] == primary else f"{t['lang']}: {t['text']}"
                for t in _pick(translations, language)[:4]
            ],
        }

    @staticmethod
    def _example(row: dict, langs: tuple[str, ...], with_entry: bool = False) -> dict:
        example: dict[str, Any] = {
            "ru": stress(row["ru"]),
            "word": stress(row["span"]),
            "level": row["level"],
            "source_url": f"https://tatoeba.org/en/sentences/show/{row['tatoeba_key']}",
        }
        present = [lang for lang in langs if row[lang]] or [
            lang for lang in LANGUAGES if row[lang]
        ][:1]
        for lang in present:
            example[lang] = row[lang]
        if with_entry:
            example["entry_id"] = row["entry_id"]
        return example

    @staticmethod
    def _match(match: Match, aspect: str | None, pos: str | None = None) -> dict:
        grouped: dict[str, list[str]] = {}
        for form_type, form in sorted(match.forms, key=lambda f: form_sort_key(f[0])):
            grammar = grouped.setdefault(display_form(form), [])
            description = describe_form_type(form_type, aspect, pos)
            if description not in grammar:
                grammar.append(description)
        return {
            "headword": match.headword,
            "forms": [{"form": form, "grammar": grammar} for form, grammar in grouped.items()],
        }

    def _entry(
        self,
        queries: Queries,
        entry_id: int,
        *,
        include_forms: bool,
        example_limit: int,
        language: str,
    ) -> dict | None:
        row = queries.entry_row(entry_id)
        if row is None:
            return None
        langs = _langs(language)
        translations = _pick(queries.translations([entry_id], LANGUAGES)[entry_id], language)
        grammar: dict[str, Any] = {}
        if row["gender"]:
            grammar["gender"] = GENDERS.get(row["gender"], row["gender"])
        if row["animate"] is not None:
            grammar["animate"] = bool(row["animate"])
        for column, name in (
            ("indeclinable", "indeclinable"),
            ("sg_only", "singular_only"),
            ("pl_only", "plural_only"),
            ("incomparable", "incomparable"),
        ):
            if row[column]:
                grammar[name] = True
        if row["aspect"]:
            grammar["aspect"] = row["aspect"]
        if row["partner"]:
            partners = [stress(p.strip()) for p in row["partner"].split(";") if p.strip()]
            grammar["aspect_partners" if row["pos"] == "verb" else "partners"] = partners
        usage = row["usage_de"] if language == "de" else row["usage_en"]
        usage = usage or row["usage_en"] or row["usage_de"]

        relations: dict[str, list[dict]] = {}
        for relation in queries.relations(entry_id):
            bucket = relations.setdefault(relation["relation"], [])
            if len(bucket) < _RELATION_CAP:
                word = stress(relation["accented"])
                bucket.append({"entry_id": relation["entry_id"], "word": word})

        derived = row["derived_from_entry_id"]
        derived_word = queries.entry_heads([derived]).get(derived) if derived else None
        entry: dict[str, Any] = {
            "entry_id": entry_id,
            "headword": row["bare"],
            "stressed": stress(row["accented"]),
            "pos": row["pos"],
            "rank": row["rank"],
            "rank_shared": bool(row["rank_shared"]),
            "level": row["level"],
            "grammar": grammar,
            "usage": usage.replace("\\n", "\n") if usage else None,
            "translations": [
                {
                    "lang": t["lang"],
                    "text": t["text"],
                    "info": t["info"],
                    "example": (
                        {"ru": stress(t["example_ru"]), "translation": t["example_translation"]}
                        if t["example_ru"]
                        else None
                    ),
                }
                for t in translations[:40]
            ],
            "forms": paradigm(queries.forms(entry_id), row["aspect"]) if include_forms else None,
            "relations": relations or None,
            "derived_from": (
                {"entry_id": derived, "word": stress(derived_word)} if derived_word else None
            ),
            "in_expressions": [
                {"entry_id": e["entry_id"], "word": stress(e["accented"])}
                for e in queries.expressions_with(entry_id)
            ]
            or None,
            "expression_parts": (
                [
                    {"entry_id": e["entry_id"], "word": stress(e["accented"])}
                    for e in queries.expression_members(entry_id)
                ]
                or None
            )
            if row["pos"] == "expression"
            else None,
            "tags": queries.tags(entry_id) or None,
            "examples": [
                self._example(x, langs)
                for x in queries.examples([entry_id], example_limit, prefer_lang=langs[0])
            ]
            if example_limit
            else None,
            "audio_url": row["audio_url"],
        }
        return entry

    # ----- tools ------------------------------------------------------------------------

    def lookup_entries(
        self,
        lemma: str,
        part_of_speech: str | None = None,
        include_forms: bool = False,
        example_limit: int = 0,
        language: str = "en",
    ) -> dict:
        lemma = _bounded_text(lemma, name="lemma")
        _choice(part_of_speech, PARTS_OF_SPEECH, "part_of_speech")
        _choice(language, DISPLAY_LANGUAGES, "language")
        example_limit = _bounded(example_limit, 0, 10, name="example_limit")
        with self.repository.session() as queries:
            matches = queries.matches([lemma], part_of_speech, limit_per_word=20)[lemma]
            entries = []
            for entry_id, match in matches.items():
                entry = self._entry(
                    queries,
                    entry_id,
                    include_forms=include_forms,
                    example_limit=example_limit,
                    language=language,
                )
                if entry is not None:
                    aspect = entry["grammar"].get("aspect")
                    entry["match"] = self._match(match, aspect, entry["pos"])
                    entries.append(entry)
        stress_filtered = None
        wanted = _stress_query(lemma)
        if wanted is not None:
            # The query carried a stress mark: say which entries spell it that way, and when
            # at least one does, drop the homographs stressed differently (му́ка vs мука́).
            for entry in entries:
                entry["stress_match"] = _entry_has_stress(wanted, entry)
            if any(entry["stress_match"] for entry in entries):
                stress_filtered = sum(not entry["stress_match"] for entry in entries)
                entries = [entry for entry in entries if entry["stress_match"]]
        return {
            "query": lemma,
            "found": bool(entries),
            "count": len(entries),
            "entries": entries,
            "stress_filtered": stress_filtered,
            "dataset_date": self.dataset_date,
        }

    def search_entries(
        self,
        query: str,
        language: str | None = None,
        part_of_speech: str | None = None,
        limit: int = 10,
    ) -> dict:
        query = _bounded_text(query, name="query")
        _choice(language, LANGUAGES, "language")
        _choice(part_of_speech, PARTS_OF_SPEECH, "part_of_speech")
        limit = _bounded(limit, 1, 30)
        found: list[int] = []
        reasons: dict[int, str] = {}
        matched: dict[int, str] = {}

        def add(entry_id: int, reason: str) -> None:
            if entry_id not in reasons and len(found) < limit:
                found.append(entry_id)
                reasons[entry_id] = reason

        with self.repository.session() as queries:
            for entry_id, match in queries.matches([query], part_of_speech, limit)[query].items():
                add(entry_id, "headword" if match.headword else "inflected_form")

            needle = _gloss_text(query)
            if len(found) < limit and len(needle) >= 2:
                best: dict[int, tuple[tuple[int, int, int], tuple[bool, int], str]] = {}
                for row in queries.translation_candidates(needle, language, part_of_speech):
                    score = _gloss_rank(needle, row["text"], row["position"])
                    if score is None:
                        continue
                    rank = (row["rank"] is None, row["rank"] or 0)
                    current = best.get(row["entry_id"])
                    if current is None or score < current[0]:
                        best[row["entry_id"]] = (score, rank, row["text"])
                # Match quality first, then primary sense before secondary senses, then
                # frequency: "run" ranks бежать ("to run", sense 1) above провести
                # ("run, lay", sense 6).
                ordered = sorted(
                    best.items(),
                    key=lambda item: (
                        item[1][0][0],
                        item[1][0][1] > 1,
                        item[1][1],
                        item[1][0][1:],
                        item[0],
                    ),
                )
                for entry_id, (_, _, text) in ordered:
                    add(entry_id, "translation")
                    if reasons.get(entry_id) == "translation":
                        matched.setdefault(entry_id, text)

            if len(found) < limit:
                for entry_id in queries.fts_ids(query, language, part_of_speech, limit * 2):
                    add(entry_id, "full_text")

            rows = queries.summaries(found)
            translations = queries.translations(found, LANGUAGES)
            tags = queries.tags_for(found)
        display = language or "en"
        results = []
        for entry_id in found:
            if entry_id not in rows:
                continue
            summary = self._summary(
                rows[entry_id], translations[entry_id], display, tags.get(entry_id)
            )
            summary["match_reason"] = reasons[entry_id]
            summary["matched_translation"] = matched.get(entry_id)
            results.append(summary)
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "dataset_date": self.dataset_date,
        }

    def get_entry(
        self,
        entry_id: int,
        example_limit: int = 5,
        include_forms: bool = True,
        language: str = "en",
    ) -> dict:
        if entry_id <= 0:
            raise ValueError("entry_id must be positive")
        example_limit = _bounded(example_limit, 0, 10, name="example_limit")
        _choice(language, DISPLAY_LANGUAGES, "language")
        with self.repository.session() as queries:
            entry = self._entry(
                queries,
                entry_id,
                include_forms=include_forms,
                example_limit=example_limit,
                language=language,
            )
        return {
            "found": entry is not None,
            "entry_id": entry_id,
            "entry": entry,
            "dataset_date": self.dataset_date,
        }

    def _suggestions(self, queries: Queries, surface: str, language: str) -> list[dict]:
        """Likely intended spellings of an unknown word, most plausible first."""
        typed = normalize_lookup(surface, fold_yo=True)
        if len(typed) < 3 or "-" in typed:
            return []
        near = []
        # Within two edits one of three disjoint parts of the typed word survives intact, so a
        # substring test discards almost every candidate before the slower distance check.
        third = max(1, len(typed) // 3)
        parts = [typed[i : i + third] for i in range(0, third * 3, third)]
        for key in queries.spelling_pool(typed):
            if not any(part in key for part in parts):
                continue
            cost = spelling_cost(typed, key, SUGGESTION_MAX_COST)
            if cost is not None and key != typed:
                near.append((cost, key))
        ranks = queries.key_ranks([key for _, key in near])
        scored = sorted((cost, ranks[key] is None, ranks[key] or 0, key) for cost, key in near)
        picked = scored[:SUGGESTIONS_PER_WORD]
        if not picked:
            return []
        matches = queries.matches([key for *_, key in picked], limit_per_word=1)
        ids = [entry_id for found in matches.values() for entry_id in found]
        rows = queries.summaries(ids)
        translations = queries.translations(ids, LANGUAGES)
        result = []
        for cost, _, _, key in picked:
            for entry_id, match in matches.get(key, {}).items():
                row = rows.get(entry_id)
                if row is None:
                    continue
                described = self._match(match, row["aspect"], row["pos"])
                form = described["forms"][0]["form"] if described["forms"] else None
                gloss = _pick(translations[entry_id], language)
                result.append(
                    {
                        "word": form or stress(row["accented"]),
                        "lemma": stress(row["accented"]),
                        "pos": row["pos"],
                        "gloss": gloss[0]["text"] if gloss else None,
                        "cost": round(cost, 2),
                    }
                )
        return result

    def analyze_text(self, text: str, language: str = "en", max_candidates: int = 4) -> dict:
        text = _bounded_text(text, name="text", maximum=MAX_TEXT_LENGTH)
        _choice(language, DISPLAY_LANGUAGES, "language")
        max_candidates = _bounded(max_candidates, 1, 10, name="max_candidates")
        mixed = mixed_script_words(text)
        tokens = russian_tokens(repair_mixed_script(text))
        if len(tokens) > MAX_TEXT_TOKENS:
            raise ValueError(f"text contains more than {MAX_TEXT_TOKENS} Russian words")
        surfaces: dict[str, str] = {}
        counts: dict[str, int] = {}
        for token in tokens:
            key = normalize_lookup(token)
            surfaces.setdefault(key, token)
            counts[key] = counts.get(key, 0) + 1
        with self.repository.session() as queries:
            matches = queries.matches(surfaces.values(), limit_per_word=max_candidates)
            ids = sorted({entry_id for found in matches.values() for entry_id in found})
            rows = queries.summaries(ids)
            translations = queries.translations(ids, LANGUAGES)
        words = []
        unknown = []
        with self.repository.session() as queries:
            suggestions = {
                surface: self._suggestions(queries, surface, language)
                for surface in [
                    surface
                    for surface in surfaces.values()
                    if not any(rows.get(i) for i in matches[surface])
                ][:MAX_SUGGESTED_WORDS]
            }
        for key, surface in surfaces.items():
            candidates = []
            for entry_id, match in matches[surface].items():
                row = rows.get(entry_id)
                if row is None:
                    continue
                gloss = _pick(translations[entry_id], language)
                described = self._match(match, row["aspect"], row["pos"])
                candidates.append(
                    {
                        "entry_id": entry_id,
                        "lemma": stress(row["accented"]),
                        "pos": row["pos"],
                        "rank": row["rank"],
                        "rank_shared": bool(row.get("rank_shared")),
                        "gloss": gloss[0]["text"] if gloss else None,
                        "headword": described["headword"],
                        "forms": described["forms"],
                    }
                )
            if not candidates:
                unknown.append(surface)
            words.append(
                {
                    "word": surface,
                    "count": counts[key],
                    "known": bool(candidates),
                    "candidates": candidates,
                    "suggestions": suggestions.get(surface, []),
                }
            )
        return {
            "token_count": len(tokens),
            "unique_words": len(words),
            "unknown": unknown,
            "mixed_script": mixed,
            "words": words,
            "dataset_date": self.dataset_date,
        }

    def browse_entries(
        self,
        level: str | None = None,
        part_of_speech: str | None = None,
        min_rank: int | None = None,
        max_rank: int | None = None,
        language: str = "en",
        limit: int = 20,
        offset: int = 0,
        include_ambiguous_rank: bool = False,
        register: str | None = None,
    ) -> dict:
        _choice(level, LEVELS, "level")
        _choice(register, REGISTERS, "register")
        _choice(part_of_speech, PARTS_OF_SPEECH, "part_of_speech")
        _choice(language, DISPLAY_LANGUAGES, "language")
        limit = _bounded(limit, 1, 100)
        offset = _bounded(offset, 0, 100_000, name="offset")
        with self.repository.session() as queries:
            # With a part-of-speech filter, a rank that the entry shares with a homograph of
            # another part of speech belongs to the other word (мочь the noun "might" is not
            # the 24th most frequent noun), so those entries are skipped unless asked for.
            skipped = bool(part_of_speech) and not include_ambiguous_rank
            ids = queries.browse(
                level,
                part_of_speech,
                min_rank,
                max_rank,
                limit,
                offset,
                skip_ambiguous_rank=skipped,
                register=register,
            )
            rows = queries.summaries(ids)
            translations = queries.translations(ids, LANGUAGES)
            tags = queries.tags_for(ids)
        results = [
            self._summary(rows[i], translations[i], language, tags.get(i)) for i in ids if i in rows
        ]
        return {
            "count": len(results),
            "offset": offset,
            "next_offset": offset + len(results) if len(results) == limit else None,
            "results": results,
            "note": (
                "Entries whose frequency rank is shared with a homograph of another part of "
                "speech were left out; set include_ambiguous_rank to see them."
                if skipped
                else None
            ),
            "dataset_date": self.dataset_date,
        }

    def _phrase_examples(
        self,
        queries: Queries,
        tokens: list[str],
        max_level: str | None,
        langs: tuple[str, ...],
        limit: int,
        diverse: bool,
    ) -> dict:
        """Sentences containing the words in this order.

        A token typed as a dictionary form stands for all its inflected forms («скучать по»
        finds «скучаю по тебе»); a token typed as an inflected form matches only itself.
        """
        key_sets: list[set[str]] = []
        entry_ids: list[list[int]] = []
        expanded = False
        for token in tokens:
            matches = queries.matches([token], limit_per_word=5)[token]
            headwords = [i for i, m in matches.items() if m.headword]
            keys = {normalize_lookup(token, fold_yo=True)}
            if headwords:
                keys |= queries.form_key_set(headwords)
                expanded = expanded or len(keys) > 1
            key_sets.append(keys)
            entry_ids.append(list(matches))
        linked = [(queries.link_count(ids), ids) for ids in entry_ids if ids]
        rarest = min(linked, key=lambda item: item[0])[1] if linked else []
        found: list[dict] = []
        if rarest:
            for row in queries.sentences_with(rarest, max_level):
                words = [normalize_lookup(w, fold_yo=True) for w in russian_tokens(row["ru"])]
                for start in range(len(words) - len(tokens) + 1):
                    if all(words[start + i] in key_sets[i] for i in range(len(tokens))):
                        found.append(dict(row, span=" ".join(tokens), entry_id=None))
                        break
        if diverse:
            found = _diversify(found, limit)
        found = found[:limit]
        heads = queries.entry_heads([ids[0] for ids in entry_ids if ids])
        return {
            "query": " ".join(tokens),
            "found": bool(found),
            "entries": [{"entry_id": i, "word": stress(h)} for i, h in heads.items()],
            "exact_form": not expanded,
            "examples": [self._example(row, langs, with_entry=True) for row in found],
            "source": TATOEBA_SOURCE,
            "dataset_date": self.dataset_date,
        }

    def find_examples(
        self,
        word: str,
        max_level: str | None = None,
        exact_form: bool | None = None,
        language: str = "en",
        limit: int = 5,
        diverse: bool = True,
    ) -> dict:
        word = _bounded_text(word, name="word")
        _choice(max_level, LEVELS, "max_level")
        _choice(language, DISPLAY_LANGUAGES, "language")
        limit = _bounded(limit, 1, 20)
        langs = _langs(language)
        phrase = russian_tokens(word)
        if len(phrase) > 1:
            with self.repository.session() as queries:
                return self._phrase_examples(queries, phrase, max_level, langs, limit, diverse)
        with self.repository.session() as queries:
            matches = queries.matches([word], limit_per_word=5)[word]
            if exact_form is None:
                # A dictionary form asks for the word in general; an inflected form asks
                # for sentences that use exactly that form.
                exact_form = not any(match.headword for match in matches.values())
            heads = queries.entry_heads(list(matches))
            rows = queries.examples(
                list(matches),
                limit,
                max_level=max_level,
                prefer_lang=langs[0],
                form_keys={normalize_lookup(word, fold_yo=True)} if exact_form else None,
                candidates=max(limit * 100, 1000) if diverse else None,
            )
        if diverse:
            rows = _diversify(rows, limit)
        rows = rows[:limit]
        return {
            "query": word,
            "found": bool(rows),
            "entries": [{"entry_id": i, "word": stress(heads[i])} for i in matches if i in heads],
            "exact_form": exact_form,
            "examples": [self._example(row, langs, with_entry=True) for row in rows],
            "source": TATOEBA_SOURCE,
            "dataset_date": self.dataset_date,
        }
