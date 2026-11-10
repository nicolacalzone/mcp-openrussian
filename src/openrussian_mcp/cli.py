from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from openrussian_mcp.config import data_root
from openrussian_mcp.pipeline.build import build_database
from openrussian_mcp.pipeline.publish import activate, active_database, prune, validate_build
from openrussian_mcp.service.dictionary import DictionaryService
from openrussian_mcp.sources.manifest import create_snapshot, inspect_directory


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="openrussian-data")
    result.add_argument("--data-dir", type=Path, default=None)
    commands = result.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect headers, row counts and hashes")
    inspect.add_argument("--input", type=Path, required=True)
    inspect.add_argument("--date", required=True)
    snapshot = commands.add_parser(
        "snapshot", help="Copy manual exports into an immutable snapshot"
    )
    snapshot.add_argument("--input", type=Path, required=True)
    snapshot.add_argument("--date", required=True)
    build = commands.add_parser("build", help="Build SQLite from a snapshot")
    build.add_argument("--snapshot", required=True)
    build.add_argument(
        "--build-id", default=None, help="Build directory name (default: the snapshot date)"
    )
    validate = commands.add_parser("validate", help="Validate a completed build")
    validate.add_argument("--build", required=True)
    publish = commands.add_parser("activate", help="Select a validated build")
    publish.add_argument("--build", required=True)
    refresh = commands.add_parser("refresh", help="Snapshot, build and activate manual exports")
    refresh.add_argument("--input", type=Path, required=True)
    refresh.add_argument("--date", required=True)
    download = commands.add_parser(
        "download", help="Download all tables from TogetherDB into a new directory"
    )
    download.add_argument("--output", type=Path, required=True)
    pull = commands.add_parser(
        "pull", help="Fetch the latest GitHub release, then snapshot, build and activate it"
    )
    pull.add_argument(
        "--repo",
        default=os.environ.get("OPENRUSSIAN_RELEASE_REPO"),
        help="OWNER/NAME (default: $OPENRUSSIAN_RELEASE_REPO)",
    )
    pull.add_argument("--keep", type=int, default=2)
    pull.add_argument("--force", action="store_true", help="Rebuild even if already up to date")
    pruning = commands.add_parser("prune", help="Delete old builds and unreferenced snapshots")
    pruning.add_argument("--keep", type=int, default=2)
    pruning.add_argument("--dry-run", action="store_true")
    commands.add_parser("info", help="Show active dataset metadata")
    lookup = commands.add_parser("lookup", help="Query a headword locally")
    lookup.add_argument("lemma")
    search = commands.add_parser("search", help="Search the active dictionary")
    search.add_argument("query")
    search.add_argument("--language", choices=["en", "de"], default=None)
    analyze = commands.add_parser("analyze", help="Check every Russian word in a text")
    analyze.add_argument("text")
    browse = commands.add_parser("browse", help="List words by frequency")
    browse.add_argument("--level", default=None)
    browse.add_argument("--pos", default=None)
    browse.add_argument("--max-rank", type=int, default=None)
    browse.add_argument("--limit", type=int, default=20)
    examples = commands.add_parser("examples", help="Example sentences for a word")
    examples.add_argument("word")
    examples.add_argument("--max-level", default=None)
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parser().parse_args()
    root = args.data_dir.resolve() if args.data_dir else data_root()
    if args.command == "inspect":
        output = inspect_directory(args.input.resolve(), args.date)
    elif args.command == "snapshot":
        output = {
            "snapshot": str(create_snapshot(args.input.resolve(), root / "snapshots", args.date))
        }
    elif args.command == "build":
        snapshot_dir = root / "snapshots" / args.snapshot
        build_dir = build_database(snapshot_dir, root / "builds", args.build_id)
        output = {"build": str(build_dir)}
    elif args.command == "validate":
        output = validate_build(root / "builds" / args.build)
    elif args.command == "activate":
        output = {"database": str(activate(root / "builds" / args.build, root / "active"))}
    elif args.command == "refresh":
        snapshot_dir = create_snapshot(args.input.resolve(), root / "snapshots", args.date)
        build_dir = build_database(snapshot_dir, root / "builds")
        output = {"database": str(activate(build_dir, root / "active"))}
    elif args.command == "download":
        from openrussian_mcp.sources.togetherdb import download

        output = {"output": str(download(args.output))}
    elif args.command == "pull":
        from openrussian_mcp.sources.release import pull as pull_release

        if not args.repo:
            sys.exit("pull needs --repo OWNER/NAME or OPENRUSSIAN_RELEASE_REPO")
        output = pull_release(root, args.repo, args.keep, args.force)
    elif args.command == "prune":
        output = prune(root, args.keep, args.dry_run)
    else:
        service = DictionaryService(active_database(root / "active"))
        if args.command == "info":
            output = service.info()
        elif args.command == "lookup":
            output = service.lookup_entries(args.lemma)
        elif args.command == "search":
            output = service.search_entries(args.query, args.language)
        elif args.command == "analyze":
            output = service.analyze_text(args.text)
        elif args.command == "browse":
            output = service.browse_entries(
                args.level, args.pos, None, args.max_rank, "en", args.limit
            )
        else:
            output = service.find_examples(args.word, args.max_level)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
