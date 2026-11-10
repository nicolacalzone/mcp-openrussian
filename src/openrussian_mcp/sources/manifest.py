from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from openrussian_mcp.sources.contract import (
    SCHEMA_VERSION,
    SOURCE_LICENSE,
    SOURCE_URL,
    TABLES,
    filename,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


DEFAULT_ACQUISITION_METHOD = "manual_togetherdb_export"


def inspect_directory(
    directory: Path, snapshot_date: str, acquisition_method: str = DEFAULT_ACQUISITION_METHOD
) -> dict:
    date.fromisoformat(snapshot_date)
    files = {}
    for table, required in TABLES.items():
        path = directory / filename(table)
        if not path.is_file():
            raise ValueError(f"Missing source table: {path.name}")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            try:
                headers = next(reader)
            except StopIteration as error:
                raise ValueError(f"Empty source table: {path.name}") from error
            missing = set(required) - set(headers)
            if missing or len(set(headers)) != len(headers):
                raise ValueError(f"{path.name}: missing {sorted(missing)} or duplicate headers")
            count = sum(1 for _ in reader)
        files[table] = {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
            "rows": count,
            "headers": headers,
        }
    return {
        "format_version": 1,
        "source_schema_version": SCHEMA_VERSION,
        "snapshot_date": snapshot_date,
        "created_at": datetime.now(UTC).isoformat(),
        "acquisition_method": acquisition_method,
        "source_url": SOURCE_URL,
        "source_license": SOURCE_LICENSE,
        "files": files,
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_snapshot(
    incoming: Path,
    snapshots: Path,
    snapshot_date: str,
    acquisition_method: str = DEFAULT_ACQUISITION_METHOD,
) -> Path:
    manifest = inspect_directory(incoming, snapshot_date, acquisition_method)
    target = snapshots / snapshot_date
    if target.exists():
        raise FileExistsError(f"Snapshot already exists: {target}")
    target.mkdir(parents=True)
    # A failed copy is left visible for inspection; it cannot be built without a manifest.
    for item in manifest["files"].values():
        shutil.copy2(incoming / item["filename"], target / item["filename"])
    write_json(target / "manifest.json", manifest)
    verify_snapshot(target)
    return target


def verify_snapshot(directory: Path) -> dict:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing snapshot manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for table, item in manifest["files"].items():
        path = directory / item["filename"]
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise ValueError(f"{table}: missing or changed source file")
        if file_sha256(path) != item["sha256"]:
            raise ValueError(f"{table}: SHA-256 mismatch")
    return manifest
