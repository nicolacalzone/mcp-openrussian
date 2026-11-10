"""Compute reference answers for group G (frequency / level questions) from the dictionary.

Usage: python tests/eval/tools/ground_truth_g.py [DATA_DIR] > tests/eval/ground_truth_G.md

Judges cannot verify group G from memory, so they get these numbers instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openrussian_mcp.pipeline.publish import active_database
from openrussian_mcp.service.dictionary import DictionaryService


def main() -> None:
    root = Path(
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPENRUSSIAN_DATA_DIR", "data")
    )
    service = DictionaryService(active_database(root / "active"))

    def entry(word: str, pos: str | None = None) -> dict | None:
        found = service.lookup_entries(word, part_of_speech=pos)["entries"]
        return found[0] if found else None

    def show(word: str) -> str:
        e = entry(word)
        if e is None:
            return f"{word}: not in the dictionary"
        shared = " (rank shared with a homograph)" if e["rank_shared"] else ""
        return f"{e['stressed']}: rank {e['rank']}{shared}, level {e['level'] or 'none'}"

    def words(**kwargs) -> str:
        rows = service.browse_entries(**kwargs)["results"]
        return "; ".join(f"{r['stressed']} (rank {r['rank']}, {r['level']})" for r in rows)

    print("# Group G reference data (computed from the active dictionary)\n")
    print(f"Dataset date: {service.dataset_date}\n")
    print("G01 top 10 nouns (ambiguous homograph ranks skipped):")
    print(words(part_of_speech="noun", limit=10), "\n")
    print("G02 B1 verbs, first 15 by frequency:")
    print(words(level="B1", part_of_speech="verb", limit=15), "\n")
    print("G03 ответственность:", show("ответственность"), "\n")
    print("G04 видеть:", show("видеть"), "| смотреть:", show("смотреть"), "\n")
    print(
        "G05/G07/G09: the dictionary has no topic tags; any theme is the answerer's own choice.\n"
    )
    print("G06 авось:", show("авось"), "\n")
    print("G08 чайник:", show("чайник"), "\n")
    print("G10 C1 band:", words(level="C1", limit=5), "...")
    top = service.browse_entries(level="C1", limit=100)["results"]
    print(f"C1 entries with rank: {top[0]['rank']} to {top[-1]['rank']} (first 100)")
    print("Register-tagged entries exist only for colloquial / archaic / formal (~350 entries).")
    print(words(register="formal", limit=10))


if __name__ == "__main__":
    main()
