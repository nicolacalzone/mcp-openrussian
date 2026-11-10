"""Fetch the latest monthly CSV release from GitHub and turn it into the active database."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from openrussian_mcp.pipeline.build import build_database
from openrussian_mcp.pipeline.publish import activate, prune
from openrussian_mcp.sources.contract import TABLES, filename
from openrussian_mcp.sources.manifest import create_snapshot, file_sha256, verify_snapshot

logger = logging.getLogger(__name__)

API = "https://api.github.com"
ASSET_NAME = "openrussian-csv.zip"
HASH_NAME = ASSET_NAME + ".sha256"
ACQUISITION_METHOD = "togetherdb_export_github_release"
STALE_DAYS = 40  # GitHub disables scheduled workflows after 60 days without repo activity
MAX_UNPACKED_BYTES = 4 * 1024**3
_TAG = re.compile(r"^dump-(\d{4}-\d{2}-\d{2})$")
_EXTRA_CSV = re.compile(r"^openrussian_public - [A-Za-z0-9_]+\.csv$")


def _headers(accept: str) -> dict[str, str]:
    headers = {"User-Agent": "openrussian-mcp-pull/1.0", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers("application/vnd.github+json"))
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=_headers("application/octet-stream"))
    with urllib.request.urlopen(request, timeout=600) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out, length=1 << 20)


def release_date(tag: str) -> str:
    match = _TAG.match(tag)
    if not match:
        raise ValueError(f"Unexpected release tag {tag!r}; expected dump-YYYY-MM-DD")
    date.fromisoformat(match.group(1))
    return match.group(1)


def verify_hash(archive: Path, hash_file: Path) -> None:
    words = hash_file.read_text(encoding="utf-8").split()
    if not words:
        raise ValueError(f"Empty hash file: {hash_file.name}")
    expected = words[0].lower()
    actual = file_sha256(archive)
    if actual != expected:
        raise ValueError(f"{archive.name}: SHA-256 mismatch (expected {expected}, got {actual})")


def extract_csvs(archive: Path, destination: Path) -> None:
    """Extract the expected CSV tables only; any unexpected archive entry is an error."""
    wanted = {filename(table) for table in TABLES}
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        for info in infos:
            name = info.filename
            allowed = name == "NOTICE" or _EXTRA_CSV.match(name)
            if info.is_dir() or not allowed:
                raise ValueError(f"Unexpected entry in {archive.name}: {name!r}")
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise ValueError(f"{archive.name}: unpacked size is implausibly large")
        names = {info.filename for info in infos}
        missing = sorted(wanted - names)
        if missing:
            raise ValueError(f"{archive.name} lacks tables: {missing}")
        for name in sorted(wanted):
            with bundle.open(name) as source, (destination / name).open("wb") as target:
                shutil.copyfileobj(source, target, length=1 << 20)


def _asset_url(release: dict[str, Any], name: str) -> str:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return str(asset["url"])
    raise ValueError(f"Release {release.get('tag_name')} has no asset {name}")


def _active_snapshot_date(root: Path) -> str | None:
    manifest = root / "active" / "manifest.json"
    if not manifest.is_file():
        return None
    return json.loads(manifest.read_text(encoding="utf-8")).get("snapshot_date")


def _free_build_id(builds: Path, snapshot_date: str) -> str:
    candidate, number = snapshot_date, 1
    while (builds / candidate).exists():
        number += 1
        candidate = f"{snapshot_date}-v{number}"
    return candidate


def pull(root: Path, repo: str, keep: int = 2, force: bool = False) -> dict[str, Any]:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError(f"Invalid repository {repo!r}; expected OWNER/NAME")
    release = fetch_json(f"{API}/repos/{repo}/releases/latest")
    snapshot_date = release_date(release["tag_name"])
    age = (date.today() - date.fromisoformat(snapshot_date)).days
    if age > STALE_DAYS:
        logger.warning(
            "Latest release is %d days old. Scheduled GitHub workflows stop after 60 days "
            "without repository activity; check the Actions tab.",
            age,
        )
    active_date = _active_snapshot_date(root)
    if active_date is not None and active_date >= snapshot_date and not force:
        return {"status": "up to date", "snapshot_date": active_date}

    snapshots = root / "snapshots"
    snapshot_dir = snapshots / snapshot_date
    if snapshot_dir.exists():
        # An earlier pull stopped after the snapshot step, or --force: reuse the stored copy.
        verify_snapshot(snapshot_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="openrussian-pull-") as scratch:
            work = Path(scratch)
            archive, hash_file = work / ASSET_NAME, work / HASH_NAME
            fetch_file(_asset_url(release, ASSET_NAME), archive)
            fetch_file(_asset_url(release, HASH_NAME), hash_file)
            verify_hash(archive, hash_file)
            extract_csvs(archive, work / "csv")
            snapshot_dir = create_snapshot(
                work / "csv", snapshots, snapshot_date, ACQUISITION_METHOD
            )
    builds = root / "builds"
    build_dir = build_database(snapshot_dir, builds, _free_build_id(builds, snapshot_date))
    database = activate(build_dir, root / "active")
    pruned = prune(root, keep)
    return {
        "status": "updated",
        "snapshot_date": snapshot_date,
        "build_id": build_dir.name,
        "database": str(database),
        "pruned": pruned,
        "note": "Restart the MCP client so the server opens the new database.",
    }
