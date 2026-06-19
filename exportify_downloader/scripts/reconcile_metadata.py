#!/usr/bin/env python3
"""Reconcile local audio files and refresh metadata without downloading."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional

from ..core.csv_work_state import write_csv
from ..core.downloader import STATUS_DOWNLOADED
from ..core.metadata import build_audio_metadata, embed_audio_metadata
from ..core.utils import utc_now
from .reconcile import (
    candidate_stems,
    collect_audio_files,
    discover_csv_path,
    resolve_target_csv_path,
    playlist_stem,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan local audio files, match them to the work CSV, and refresh metadata tags without downloading."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        nargs="?",
        help="Path to the playlist CSV to use. If omitted, uses the only CSV found in exportify.app.",
    )
    parser.add_argument(
        "--files-dir",
        type=Path,
        default=None,
        help="Folder containing downloaded audio files. Defaults to <csv folder>/<csv stem>.",
    )
    parser.add_argument(
        "--downloaded-only",
        action="store_true",
        help="Only retag rows already marked downloaded in the CSV.",
    )
    return parser.parse_args()


def metadata_row_id(row: dict[str, str], row_index: int) -> int:
    raw_value = (row.get("id") or "").strip()
    if raw_value.isdigit() and int(raw_value) > 0:
        return int(raw_value)
    return row_index


def main() -> int:
    args = parse_args()

    csv_path = args.csv_path.resolve() if args.csv_path is not None else discover_csv_path()
    if csv_path is None:
        print(
            "Could not determine CSV automatically. Pass csv_path explicitly, for example: "
            r"reconcile_metadata.py .\exportify.app\3_dnb_dance_floor.csv",
            file=sys.stderr,
        )
        return 2

    csv_path = resolve_target_csv_path(csv_path)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    files_dir = (
        args.files_dir.resolve()
        if args.files_dir is not None
        else (csv_path.parent / playlist_stem(csv_path)).resolve()
    )
    if not files_dir.exists() or not files_dir.is_dir():
        print(f"Files folder not found: {files_dir}", file=sys.stderr)
        return 1

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            print("CSV appears empty or invalid.", file=sys.stderr)
            return 1
        fieldnames = list(reader.fieldnames)
        rows = [dict(row) for row in reader]

    files_by_stem = collect_audio_files(files_dir)
    matched = 0
    retagged = 0
    updated_rows = 0
    errors = 0

    for idx, row in enumerate(rows, start=1):
        if args.downloaded_only and (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
            continue

        match: Optional[Path] = None
        for stem in candidate_stems(row):
            match = files_by_stem.get(stem.casefold())
            if match is not None:
                break

        if match is None:
            continue

        matched += 1
        try:
            embed_audio_metadata(match, build_audio_metadata(row, metadata_row_id(row, idx)))
            retagged += 1

            resolved_match = str(match)
            if (row.get("output_file") or "").strip() != resolved_match:
                row["output_file"] = resolved_match
                updated_rows += 1
            if (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
                row["download_status"] = STATUS_DOWNLOADED
                updated_rows += 1
            row["attempted_at"] = utc_now()
            row["error_message"] = ""
        except Exception as exc:  # noqa: BLE001
            row["attempted_at"] = utc_now()
            row["error_message"] = f"Metadata write failed: {str(exc).strip()[:350]}"
            errors += 1

    write_csv(csv_path, fieldnames, rows)
    print(
        f"scanned_files={len(files_by_stem)} matched_rows={matched} "
        f"retagged_rows={retagged} updated_rows={updated_rows} errors={errors}"
    )
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
