from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from openrussian_mcp.sources.contract import filename

csv.field_size_limit(256 * 1024 * 1024)


class SourceProvider(Protocol):
    def acquire(self) -> Path:
        """Return a local directory of raw TogetherDB CSV exports."""


class DirectorySourceProvider:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()

    def acquire(self) -> Path:
        if not self.directory.is_dir():
            raise FileNotFoundError(self.directory)
        return self.directory


def read_rows(directory: Path, table: str) -> Iterator[dict[str, str]]:
    with (directory / filename(table)).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"{table}: missing CSV header")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{table}: malformed CSV record near line {line}")
            yield row
