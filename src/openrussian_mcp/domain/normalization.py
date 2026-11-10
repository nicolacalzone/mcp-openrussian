from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "´": "'"})
_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
# OpenRussian marks stress with an ASCII apostrophe after the stressed vowel.
_STRESS = re.compile(f"([{_VOWELS}])'")
_VARIANT_SEPARATOR = re.compile(r"\s*/+\s*")
_RUSSIAN_WORD = re.compile(r"[а-яё\u0301']+(?:-[а-яё\u0301']+)*", re.IGNORECASE)
# Prepositions OpenRussian prints in front of some prepositional-case forms ("о ле'се").
_FORM_PREPOSITIONS = {"в", "во", "на", "о", "об", "обо"}


def normalize_display(value: str) -> str:
    return unicodedata.normalize("NFC", _SPACES.sub(" ", value.strip()))


def normalize_lookup(value: str, *, fold_yo: bool = False) -> str:
    text = normalize_display(value).translate(_APOSTROPHES).casefold()
    text = "".join(char for char in unicodedata.normalize("NFD", text) if char != "\u0301")
    text = unicodedata.normalize("NFC", text).replace("'", "")
    return text.replace("ё", "е") if fold_yo else text


def lookup_key(value: str) -> tuple[str, bool]:
    """Return a lookup key and whether it must match the ё-folded column.

    Written Russian usually replaces ё with е, so input without ё matches both spellings.
    Input that contains ё was written deliberately and only matches ё spellings.
    """
    normalized = normalize_lookup(value)
    return normalized, "ё" not in normalized


def stress(value: str | None) -> str | None:
    """Convert OpenRussian apostrophe stress marks to combining acute accents (U+0301)."""
    if value is None:
        return None
    return unicodedata.normalize("NFC", _STRESS.sub("\\1\u0301", value))


def form_keys(form_bare: str, form_type: str) -> list[str]:
    """Normalized lookup keys for one OpenRussian form string.

    The source packs several spellings into one cell: variants separated by ``/`` or ``//``
    ("новы / новы", "выброси//выбрось"), archaic variants in parentheses ("(должною)"),
    and prepositional forms printed with a preposition ("о лесе"). Truncated stems such
    as "приподним-" are not words and get no key.
    """
    keys: list[str] = []
    for part in _VARIANT_SEPARATOR.split(form_bare):
        part = part.strip().strip("()").strip()
        if not part or part.startswith("-") or part.endswith("-"):
            continue
        candidates = [part]
        words = part.split()
        if len(words) > 1 and form_type != "ru_base":
            if words[0].casefold() in _FORM_PREPOSITIONS:
                candidates.append(" ".join(words[1:]))
            elif form_type.startswith("ru_adj_") and not form_type.endswith(
                ("superlative", "comparative")
            ):
                # Rare space-separated variants: "неадекватной неадекватною".
                candidates.extend(words)
        for candidate in candidates:
            key = normalize_lookup(candidate)
            if key and key not in keys:
                keys.append(key)
    return keys


def russian_tokens(text: str) -> list[str]:
    """Russian words in text order, keeping hyphenated words and stress marks together."""
    return _RUSSIAN_WORD.findall(normalize_display(text).translate(_APOSTROPHES))


def search_tokens(value: str) -> list[str]:
    """Words for safe FTS queries; no user FTS operators pass through."""
    text = normalize_lookup(value, fold_yo=True)
    return re.findall(r"[^\W_]+", text, re.UNICODE)[:8]


_MIXED_CANDIDATE = re.compile(r"[A-Za-zА-Яа-яЁё\u0301]+(?:-[A-Za-zА-Яа-яЁё\u0301]+)*")
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# Latin letters that look like a Cyrillic letter; typing one inside a Russian word is a typo
# that no visual proofreading catches.
_HOMOGLYPHS = str.maketrans("AaBCcEeHKMOoPpTXxy", "АаВСсЕеНКМОоРрТХху")


def repair_homoglyphs(word: str) -> str:
    """Replace look-alike Latin letters with Cyrillic ones."""
    return word.translate(_HOMOGLYPHS)


def mixed_script_words(text: str) -> list[dict]:
    """Words that mix Latin and Cyrillic letters, with the likely intended spelling.

    Pure-Latin words ("iPhone") and pure-Cyrillic words are not reported.
    """
    found: list[dict] = []
    for match in _MIXED_CANDIDATE.finditer(normalize_display(text)):
        word = match.group()
        if not (_LATIN.search(word) and _CYRILLIC.search(word)):
            continue
        suggestion = repair_homoglyphs(word)
        found.append(
            {
                "word": word,
                "suggestion": None if _LATIN.search(suggestion) else suggestion,
                "latin_letters": [
                    {"letter": char, "position": index}
                    for index, char in enumerate(word)
                    if _LATIN.fullmatch(char)
                ],
            }
        )
    return found


def repair_mixed_script(text: str) -> str:
    """Text with homoglyphs fixed inside words that also contain Cyrillic letters."""

    def fix(match: re.Match) -> str:
        word = match.group()
        if _LATIN.search(word) and _CYRILLIC.search(word):
            return repair_homoglyphs(word)
        return word

    return _MIXED_CANDIDATE.sub(fix, normalize_display(text))
