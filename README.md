<p align="center">
  <a href="https://en.openrussian.org/">
    <img src="https://en.openrussian.org/img/polandball-russia.png" alt="OpenRussian logo" width="160">
  </a>
</p>

# Unofficial OpenRussian MCP

> **Unofficial community project.** The dictionary, its data and its logo
> belong to [OpenRussian.org](https://en.openrussian.org/). I am **not** part
> of the OpenRussian team or board in any way. I am an Italian guy who studies/speaks 
> Russian and built this tool for other students who use AI assistants and find 
> that AI often gets Russian grammar wrong (stress, cases, aspect, verb government). 
> Giving the assistant a real dictionary to check, fixes a lot of that (but spends more tokens).

## Support OpenRussian

This project exists only because of the work of the OpenRussian volunteers.
If it is useful to you, please support the original:

- Visit and use the dictionary: <https://en.openrussian.org/>
- Send feedback or corrections to the team via the
  [contact page](https://en.openrussian.org/contact).
- Consider a [Pro Account](https://en.openrussian.org/pro-account), if it
  suits you, to support the site.
- Learn more on the [About page](https://en.openrussian.org/about) and the
  [data page](https://en.openrussian.org/dictionary-data).

## Contribute to this MCP

Bug reports and pull requests to this MCP server are welcome: better lookups,
new tools, tests, docs, or support for more MCP clients. See
[Development](#development) for how to run the checks, then open a PR at
<https://github.com/nicolacalzone/mcp-openrussian>.

## About

A local, read-only dictionary server for MCP clients. It serves an OpenRussian
CSV snapshot through SQLite. The data is kept separate from the Python package.
A monthly GitHub Actions job publishes fresh CSVs, and `openrussian-data pull`
turns the latest release into the local database (see
[Monthly refresh](#monthly-refresh)). You can also build from CSVs you
download yourself.

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

The examples below call `openrussian-data` directly. Either activate the
virtual environment first, or prefix each command with `uv run --locked`.

## First dataset build

If your repository already has a monthly release, skip to
[Monthly refresh](#monthly-refresh) and run `openrussian-data pull`. Otherwise,
build from CSVs you download yourself.

Download the CSV tables into a directory of your own (not inside `data/`):

```text
openrussian-data download --output raw
```

This fetches all 14 tables from TogetherDB under their original filenames.
Alternatively, export them by hand from the TogetherDB link on
[OpenRussian's data page](https://en.openrussian.org/dictionary-data) and keep
the original filenames. This server needs the 13 tables listed in
`src/openrussian_mcp/sources/contract.py`; `scenarios.csv` is optional and not
ingested. Then run, using the directory that holds the CSVs as `--input`:

```text
openrussian-data inspect --input raw --date 2026-09-21
openrussian-data snapshot --input raw --date 2026-09-21
openrussian-data build --snapshot 2026-09-21
openrussian-data validate --build 2026-09-21
openrussian-data activate --build 2026-09-21
openrussian-data lookup стол
openrussian-data analyze "Я вчера ходил в магазин"
```

Replace the date with the date of your export. `openrussian-data refresh
--input raw --date YYYY-MM-DD` combines snapshot, build, validation,
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

The default data directory is `./data`, relative to the directory you run the
command from. For the CLI, pass `--data-dir PATH` before the subcommand
(`openrussian-data --data-dir work refresh ...`). For the MCP server, set
`OPENRUSSIAN_DATA_DIR` to an absolute path, since it may be launched from
another working directory.
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
  "command": "C:\\path\\to\\russian-mcp\\.venv\\Scripts\\openrussian-mcp.exe",
  "args": [],
  "env": {
    "OPENRUSSIAN_DATA_DIR": "C:\\path\\to\\russian-mcp\\data"
  }
}
```

On macOS/Linux, the executable is `.venv/bin/openrussian-mcp`. Restart the
client after activating a new database. The server never accesses TogetherDB
or the network for a request; returned audio URLs and Tatoeba links are
external references only.

## Monthly refresh

### 1. Publish (GitHub)

[openrussian-monthly.yml](.github/workflows/openrussian-monthly.yml) runs on the
1st of each month at 03:17 UTC, and on demand from the Actions tab
(`workflow_dispatch`). It:

1. downloads all 14 tables from TogetherDB (`openrussian-data download`);
2. runs a full snapshot, build and validation on the result, and stops if it fails;
3. publishes `openrussian-csv.zip` and `openrussian-csv.zip.sha256` as a release
   tagged `dump-YYYY-MM-DD`.

To set it up, push this repository to GitHub. The workflow uses the built-in
`GITHUB_TOKEN`, so no secrets are needed. GitHub disables scheduled workflows
after 60 days without repository activity; `pull` warns when the latest release
is more than 40 days old. The download uses TogetherDB's undocumented export
API, which may change without notice. If the workflow starts failing, check the
Actions log, or fall back to a manual `refresh`.

### 2. Pull (your machine)

```text
export OPENRUSSIAN_RELEASE_REPO=you/russian-mcp   # PowerShell: $env:OPENRUSSIAN_RELEASE_REPO="..."
export GITHUB_TOKEN=...                           # only for a private repository
openrussian-data pull
```

`pull` reads the latest release, downloads the zip, checks its SHA-256, and
accepts only the expected CSV names. It then runs the usual snapshot, build,
validate and activate steps and prints the new build ID. Restart your MCP
client afterwards; the server picks the database at startup and never uses the
network itself.

- Running `pull` again reports `up to date` when the active dataset is the same
  or newer than the latest release.
- `--force` rebuilds from the stored snapshot under a new build ID
  (`DATE-v2`, ...) and activates it.
- `--repo OWNER/NAME` overrides `OPENRUSSIAN_RELEASE_REPO`.
- Snapshots from `pull` record `togetherdb_export_github_release` as their
  acquisition method.

### 3. Pruning

After each `pull`, old data is deleted. `--keep N` (default 2) keeps the active
build plus the newest other validated builds, up to N in total. It also removes
failed or incomplete builds and snapshots no kept build uses. It never deletes
the active build or `data/verified_builds/`.

```text
openrussian-data prune --dry-run     # preview
openrussian-data prune --keep 3
```

Because of pruning, you can only roll back to a kept build. A running server
keeps working during a `pull` because its database is the previous build, which
is kept.

### 4. Schedule (optional, Linux or WSL)

Edit the paths and repository in [deploy/systemd](deploy/systemd), then:

```text
mkdir -p ~/.config/systemd/user
cp deploy/systemd/openrussian-pull.* ~/.config/systemd/user/
systemctl --user enable --now openrussian-pull.timer
```

The timer runs on the 2nd of each month at 07:00, and `Persistent=true` runs a
missed pull the next time the machine starts. For a private repository, follow the
comment in the service file to add an `EnvironmentFile` containing `GITHUB_TOKEN=...`.

### Manual refresh and rollback

Refreshing from CSVs you exported yourself still works with `refresh`.

To roll back, run `openrussian-data activate --build OLD_ID` against a
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
Linux. Tests mock all HTTP, so CI never touches the network or the real
dictionary; only the monthly workflow downloads data. The September 2026 full
export builds into a roughly 730 MiB SQLite file in about one and a half
minutes.
Build duration and size will vary by machine and export.

## Data rights

Source data is from OpenRussian.org under CC BY-SA 4.0. Example sentences are
from Tatoeba under CC BY 2.0 FR. See [NOTICE](NOTICE). This application does
not download or distribute audio files. The monthly release redistributes the
CSV tables with attribution, which CC BY-SA allows; if the repository is public,
so is the zip.
