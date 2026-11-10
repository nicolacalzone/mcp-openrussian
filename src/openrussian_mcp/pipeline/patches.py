"""Known errors in the OpenRussian export, corrected while building the database.

Each patch names the entry by headword and stress (the apostrophe notation used in the
export), so it keeps working when entry ids change between snapshots. A patch that matches
no row is recorded as skipped in the build report. It is never an error, because the export
may fix the problem itself.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Patch:
    key: str
    bare: str
    accented: str
    reason: str
    english: str | None = None  # replaces the first English translation
    animate: int | None = None


PATCHES: tuple[Patch, ...] = (
    Patch(
        key="muka-torment-gloss",
        bare="мука",
        accented="му'ка",
        english="torment, suffering, pain, anguish",
        reason="The English gloss says 'flour' (copied from мука́); the German gloss "
        "'Qual, Plage, Pein, Leiden' is correct.",
    ),
    Patch(
        key="stolyar-animate",
        bare="столяр",
        accented="столя'р",
        animate=1,
        reason="A joiner is a person; the export flags the noun as inanimate, which gives "
        "the wrong accusative.",
    ),
)


def apply_patches(connection: sqlite3.Connection) -> list[dict]:
    results = []
    for patch in PATCHES:
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT entry_id FROM entries WHERE bare=? AND accented=? AND disabled=0",
                (patch.bare, patch.accented),
            )
        ]
        changed = 0
        for entry_id in ids:
            if patch.english is not None:
                cursor = connection.execute(
                    """UPDATE translations SET text=? WHERE translation_id=(
                         SELECT translation_id FROM translations
                         WHERE entry_id=? AND lang='en'
                         ORDER BY position,translation_id LIMIT 1)
                       AND text<>?""",
                    (patch.english, entry_id, patch.english),
                )
                changed += cursor.rowcount
            if patch.animate is not None:
                cursor = connection.execute(
                    "UPDATE entries SET animate=? WHERE entry_id=? AND animate IS NOT ?",
                    (patch.animate, entry_id, patch.animate),
                )
                changed += cursor.rowcount
        results.append(
            {
                "key": patch.key,
                "entries": ids,
                "status": "applied" if changed else "skipped",
                "reason": patch.reason,
            }
        )
    return results
