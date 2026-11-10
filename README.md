# OpenRussian MCP

A local, read-only dictionary server for MCP clients. It serves a manually
downloaded OpenRussian CSV snapshot through SQLite. The data export is kept
separate from the Python package.

## Install

Requires Python 3.12 or newer. The recommended reproducible install uses
`uv` and the committed `uv.lock`:

```text
uv sync --locked
```

If you do not use `uv`, from this directory:

```text
python -m venv .venv
.venv/Scripts/python -m pip install -e .
```

On macOS/Linux, use `.venv/bin/python` in place of `.venv/Scripts/python`.

## First dataset build

Download the current CSV tables from the TogetherDB link on
[OpenRussian's data page](https://en.openrussian.org/dictionary-data). Keep the
original filenames. This server needs the 13 tables listed in
`src/openrussian_mcp/sources/contract.py`; `scenarios.csv` is optional and not
ingested. Place the exports in a local directory, then run:

```text
openrussian-data inspect --input . --date 2026-09-21
openrussian-data snapshot --input . --date 2026-09-21
openrussian-data build --snapshot 2026-09-21
openrussian-data validate --build 2026-09-21
openrussian-data activate --build 2026-09-21
openrussian-data lookup стол
openrussian-data analyze "Я вчера ходил в магазин"
```

Replace the date with the date of your export. `openrussian-data refresh
--input DIRECTORY --date YYYY-MM-DD` combines snapshot, build, validation,
and activation. Validation failures leave the active database unchanged.
The snapshot command rejects an already-used date; use the actual date of
each new export and do not edit a snapshot in place. A build directory is
named after its snapshot date. To rebuild the same snapshot (for example after
upgrading this package), pass a new name with `--build-id`:

```text
openrussian-data build --snapshot 2026-09-21 --build-id 2026-09-21-v2
openrussian-data activate --build 2026-09-21-v2
```

Version 0.2 uses database schema 2. Databases built by 0.1 are rejected with a
message asking for a rebuild.

The default data directory is `./data`. Set `OPENRUSSIAN_DATA_DIR` to an
absolute path if you launch the MCP server from another working directory.
The active pointer (`data/active/manifest.json`) stores the database path
relative to the data directory, so the whole directory can be moved, or shared
between Windows and WSL, without reactivating.
Full source CSVs and generated databases are ignored by Git. Keep the
snapshot and previous validated build for rollback.

## MCP client

Configure your local MCP client to launch `openrussian-mcp` from the virtual
environment and set `OPENRUSSIAN_DATA_DIR` to this project's absolute `data`
directory. All tools are read-only:

| Tool | Use it for |
| --- | --- |
| `analyze_text` | Check every Russian word of a text in one call: possible lemmas, grammatical reading of each form, and the words found nowhere in the dictionary (`unknown`). The starting point for correcting a message. |
| `lookup_entries` | A Russian word in any form. Returns every matching entry and says which grammatical forms the query is. |
| `search_entries` | Russian words for an English or German meaning, or by Russian spelling. |
| `get_entry` | One entry in full: inflection tables, translations with government notes, aspect partners, related words, examples. |
| `browse_entries` | Word lists by frequency rank, CEFR level and part of speech. |
| `find_examples` | Tatoeba sentences using a word, or exactly one form of it, optionally up to a CEFR level. |

Stress is returned as a combining acute accent (U+0301), e.g. `ко́т`. Words
typed without ё match ё spellings (`идет` finds `идёт`). The dictionary checks
words, not syntax: agreement and word order are left to the client model.
Dataset, licensing, and grammatical form labels are available as MCP
resources. For a Windows client whose configuration uses a JSON command
object, substitute your absolute paths in this example:

```json
{
  "command": "C:\\path\\to\\MCP_open_russian\\.venv\\Scripts\\openrussian-mcp.exe",
  "args": [],
  "env": {
    "OPENRUSSIAN_DATA_DIR": "C:\\path\\to\\MCP_open_russian\\data"
  }
}
```

On macOS/Linux, the executable is `.venv/bin/openrussian-mcp`. Restart the
client after activating a new database. The server never accesses TogetherDB
or the network for a request; returned audio URLs and Tatoeba links are
external references only.

## Monthly refresh

Download a new complete set of CSVs manually and run `refresh` with a new
date. Restart your MCP client after activating the new build. There is no
automatic TogetherDB extraction. A future acquisition provider can produce
the same raw snapshot without changing the builder or server.

To roll back, run `openrussian-data activate --build OLD_DATE` against a
previously validated build, then restart the client. Do not remove that
build while a server process is using it.

## Development

```text
uv sync --locked --extra dev
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked mypy src tests
```

Code CI runs these checks against tiny synthetic CSV fixtures on Windows and
Linux; it does not fetch or refresh dictionary data. The September 2026 full
export builds into a roughly 730 MiB SQLite file in about one and a half
minutes.
Build duration and size will vary by machine and export.

The implementation design and release gates are in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Data rights

Source data is from OpenRussian.org under CC BY-SA 4.0. Example sentences are
from Tatoeba under CC BY 2.0 FR. See [NOTICE](NOTICE). This application does
not download or distribute audio files.
