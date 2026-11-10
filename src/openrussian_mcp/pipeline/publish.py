from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from openrussian_mcp.sources.manifest import file_sha256, write_json
from openrussian_mcp.storage.schema import SCHEMA_VERSION


def validate_build(build_dir: Path) -> dict:
    report_path = build_dir / "report.json"
    manifest_path = build_dir / "manifest.json"
    db_path = build_dir / "openrussian.db"
    if not all(path.is_file() for path in (report_path, manifest_path, db_path)):
        raise ValueError("Incomplete database build")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if report["status"] != "validated":
        raise ValueError("Build is not validated")
    if manifest["snapshot_date"] != report["snapshot_date"]:
        raise ValueError("Build manifest and report disagree on snapshot date")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unexpected build schema version")
    if db_path.stat().st_size != manifest["database_bytes"]:
        raise ValueError("Database size differs from build manifest")
    with closing(
        sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    ) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("Unexpected database schema version")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Database quick_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database has foreign key violations")
    return manifest


def activate(build_dir: Path, active_dir: Path) -> Path:
    manifest = validate_build(build_dir)
    active_dir.mkdir(parents=True, exist_ok=True)
    db_path = (build_dir / manifest["database_file"]).resolve()
    # Store the path relative to the data root so the data directory can be moved or
    # shared between Windows and WSL. A pointer update leaves the previous database untouched.
    try:
        stored_path = db_path.relative_to(active_dir.resolve().parent).as_posix()
    except ValueError:
        stored_path = str(db_path)
    write_json(
        active_dir / "manifest.json",
        {
            "build_id": manifest.get("build_id", manifest["snapshot_date"]),
            "snapshot_date": manifest["snapshot_date"],
            "schema_version": manifest["schema_version"],
            "database_path": stored_path,
            "database_sha256": file_sha256(db_path),
        },
    )
    return db_path


def active_database(active_dir: Path, *, verify_hash: bool = True) -> Path:
    manifest_path = active_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"No active database: {manifest_path} is missing. Run `openrussian-data activate`."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    path = Path(manifest["database_path"])
    if not path.is_absolute():
        path = active_dir.resolve().parent / path
    if not path.is_file():
        raise FileNotFoundError(
            f"Active database not found: {path}. Re-run `openrussian-data activate --build ID`."
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Active database uses schema {manifest.get('schema_version')}, this server needs "
            f"{SCHEMA_VERSION}. Rebuild with `openrussian-data build` and activate it."
        )
    if verify_hash and file_sha256(path) != manifest["database_sha256"]:
        raise ValueError("Active database SHA-256 mismatch")
    return path


def _build_time(build_dir: Path) -> str:
    report = json.loads((build_dir / "report.json").read_text(encoding="utf-8"))
    return str(report.get("completed_at") or report.get("started_at") or "")


def prune(data_root: Path, keep: int = 2, dry_run: bool = False) -> dict:
    """Delete old builds and unreferenced snapshots.

    Keeps the active build plus the newest ``keep - 1`` other builds that pass
    ``validate_build``. Never deletes the active build or ``verified_builds``.
    """
    if keep < 1:
        raise ValueError("--keep must be at least 1")
    builds_dir = data_root / "builds"
    snapshots_dir = data_root / "snapshots"
    active_dir = data_root / "active"
    active_build = active_database(active_dir, verify_hash=False).resolve().parent
    candidates: list[tuple[str, Path]] = []
    for build in sorted(builds_dir.iterdir()) if builds_dir.is_dir() else []:
        if not build.is_dir() or build.resolve() == active_build:
            continue
        try:
            validate_build(build)
            candidates.append((_build_time(build), build))
        except (ValueError, OSError, KeyError):
            continue  # failed or incomplete builds are deleted below
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    kept = {active_build} | {build.resolve() for _, build in candidates[: keep - 1]}
    kept_snapshots: set[str] = set()
    for build in kept:
        manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
        kept_snapshots.add(manifest["snapshot_date"])
    deleted_builds = [
        build
        for build in sorted(builds_dir.iterdir() if builds_dir.is_dir() else [])
        if build.is_dir() and build.resolve() not in kept
    ]
    deleted_snapshots = [
        snapshot
        for snapshot in sorted(snapshots_dir.iterdir() if snapshots_dir.is_dir() else [])
        if snapshot.is_dir() and snapshot.name not in kept_snapshots
    ]
    if not dry_run:
        for path in (*deleted_builds, *deleted_snapshots):
            shutil.rmtree(path)
    return {
        "dry_run": dry_run,
        "active": active_build.name,
        "kept_builds": sorted(build.name for build in kept),
        "deleted_builds": [path.name for path in deleted_builds],
        "deleted_snapshots": [path.name for path in deleted_snapshots],
    }
