"""Download the OpenRussian public database from TogetherDB as raw CSV files.

This uses TogetherDB's internal (undocumented) web API, the same calls the "Export"
button makes, so it may change without notice. Standard library only.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import shutil
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openrussian_mcp.sources.contract import TABLES, filename

logger = logging.getLogger(__name__)

CONNECTION = "fwoedz5fvtwvq03v"
DATABASE = "openrussian_public"
BASE = f"https://worker.togetherdb.com/connections/{CONNECTION}/databases/{DATABASE}"
EXPORTS = "https://worker.togetherdb.com/exports"
HEADERS = {"User-Agent": "openrussian-monthly-dump/1.0"}
PAUSE = 1.5  # seconds between requests; be polite
RETRIES = 4
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _backoff(attempt: int) -> None:
    time.sleep(5 * attempt)


def _pause() -> None:
    time.sleep(PAUSE)


def _open(url: str, method: str = "GET", timeout: int = 120) -> Any:
    request = urllib.request.Request(
        url, method=method, headers=HEADERS, data=b"" if method == "POST" else None
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _retry[T](action: Callable[[], T], description: str) -> T:
    for attempt in range(1, RETRIES + 1):
        try:
            return action()
        except Exception as error:
            if attempt == RETRIES:
                message = f"{description} failed after {RETRIES} tries: {error}"
                raise RuntimeError(message) from error
            logger.warning("%s: %s - retrying (%d/%d)", description, error, attempt, RETRIES)
            _backoff(attempt)
    raise AssertionError("unreachable")


def _get_json(url: str, method: str = "GET") -> dict:
    with _open(url, method) as response:
        return json.load(response)


def list_tables() -> list[str]:
    structure = _retry(lambda: _get_json(f"{BASE}/structure"), "Listing tables")
    names = [table["name"] for table in structure["result"]["tables"]]
    missing = sorted(set(TABLES) - set(names))
    if missing:
        raise RuntimeError(f"TogetherDB structure lacks required tables: {missing}")
    bad = [name for name in names if not _TABLE_NAME.match(name)]
    if bad:
        raise RuntimeError(f"Unexpected table names: {bad}")
    return names


def check_csv(path: Path, table: str) -> None:
    """Reject empty files and files whose first line is not a CSV header."""
    if path.stat().st_size == 0:
        raise ValueError(f"Empty export for table {table}")
    with path.open("rb") as stream:
        first_line = stream.readline(1024 * 1024)
    try:
        text = first_line.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{table}: export is not UTF-8 text") from error
    if "\x00" in text or not text.strip():
        raise ValueError(f"{table}: export does not start with a CSV header")
    headers = next(csv.reader(io.StringIO(text)), [])
    missing = set(TABLES.get(table, ())) - set(headers)
    if missing:
        raise ValueError(f"{table}: export header lacks {sorted(missing)}")


def _download_table(table: str, destination: Path) -> None:
    params = urllib.parse.urlencode({"expand": "false", "filter": "", "separator": ","})
    export_url = f"{BASE}/tables/{urllib.parse.quote(table)}/export?{params}"
    part = destination.with_name(destination.name + ".part")

    def attempt() -> None:
        key = _get_json(export_url, method="POST")["result"]["exportKey"]
        _pause()
        with _open(f"{EXPORTS}/{urllib.parse.quote(key)}", timeout=600) as response, part.open(
            "wb"
        ) as stream:
            shutil.copyfileobj(response, stream, length=1 << 20)
        check_csv(part, table)

    try:
        _retry(attempt, f"Downloading {table}")
        part.replace(destination)
    finally:
        part.unlink(missing_ok=True)


def download(output: Path) -> Path:
    """Download every table into ``output``, which appears only if all tables succeed."""
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    partial = output.with_name(output.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    try:
        tables = list_tables()
        logger.info("%d tables: %s", len(tables), ", ".join(tables))
        for table in tables:
            _pause()
            destination = partial / filename(table)
            _download_table(table, destination)
            logger.info("%s  %.1f MB", destination.name, destination.stat().st_size / 1e6)
        partial.rename(output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return output
