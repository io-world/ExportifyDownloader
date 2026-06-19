#!/usr/bin/env python3
"""Reconcile downloaded audio files back into the playlist CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..core.csv_work_state import ensure_tracking_columns, playlist_stem, work_csv_path_for, write_csv
from ..core.downloader import STATUS_DOWNLOADED
from ..core.utils import (
    first_artist,
    stable_base_name,
    utc_now,
)

DEFAULT_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav", ".ogg", ".opus"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan an audio folder and update matching CSV rows with output file paths."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        nargs="?",
        help="Path to the playlist CSV to update. If omitted, uses the only CSV found in exportify.app.",
    )
    parser.add_argument(
        "--files-dir",
        type=Path,
        default=None,
        help="Folder containing downloaded audio files. Defaults to <csv folder>/<csv stem>.",
    )
    parser.add_argument(
        "--clear-missing",
        action="store_true",
        help="Clear stale output_file values when a downloaded row no longer has a matching file.",
    )
    return parser.parse_args()


def discover_csv_path() -> Optional[Path]:
    search_roots = [Path.cwd() / "exportify.app", Path.cwd()]
    work_candidates: List[Path] = []
    source_candidates: List[Path] = []
    seen = set()

    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for candidate in sorted(root.glob("*.csv")):
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                if resolved.stem.lower().endswith("_work"):
                    work_candidates.append(resolved)
                else:
                    source_candidates.append(resolved)

    if len(work_candidates) == 1:
        return work_candidates[0]
    if len(source_candidates) == 1:
        return source_candidates[0]
    return None


def resolve_target_csv_path(path: Path) -> Path:
    if path.stem.lower().endswith("_work"):
        return path
    sibling_work = work_csv_path_for(path)
    if sibling_work.exists():
        print(f"Using work CSV: {sibling_work}")
        return sibling_work
    return path


def collect_audio_files(files_dir: Path) -> Dict[str, Path]:
    files_by_stem: Dict[str, Path] = {}
    for path in sorted(files_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in DEFAULT_AUDIO_EXTENSIONS:
            continue
        key = path.stem.casefold()
        current = files_by_stem.get(key)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            files_by_stem[key] = path.resolve()
    return files_by_stem


def candidate_stems(row: Dict[str, str]) -> List[str]:
    candidates: List[str] = []

    output_file = (row.get("output_file") or "").strip()
    if output_file:
        candidates.append(Path(output_file).stem)

    artist = first_artist((row.get("Artist Name(s)") or "").strip())
    track = (row.get("Track Name") or "").strip()
    if artist and track:
        candidates.append(stable_base_name(artist, track))

    deduped: List[str] = []
    seen = set()
    for item in candidates:
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def main() -> int:
    args = parse_args()

    csv_path = args.csv_path.resolve() if args.csv_path is not None else discover_csv_path()
    if csv_path is None:
        print(
            "Could not determine CSV automatically. Pass csv_path explicitly, for example: "
            r"reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv",
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
        fieldnames = ensure_tracking_columns(list(reader.fieldnames))
        rows = [dict(row) for row in reader]

    files_by_stem = collect_audio_files(files_dir)
    matched = 0
    updated = 0
    cleared = 0

    for row in rows:
        match: Optional[Path] = None
        for stem in candidate_stems(row):
            match = files_by_stem.get(stem.casefold())
            if match is not None:
                break

        current_output = (row.get("output_file") or "").strip()
        current_status = (row.get("download_status") or "").strip().lower()

        if match is not None:
            matched += 1
            resolved_match = str(match)
            if current_output != resolved_match or current_status != STATUS_DOWNLOADED:
                row["download_status"] = STATUS_DOWNLOADED
                row["output_file"] = resolved_match
                row["attempted_at"] = utc_now()
                row["error_message"] = ""
                updated += 1
            continue

        if args.clear_missing and current_status == STATUS_DOWNLOADED and current_output:
            row["output_file"] = ""
            row["attempted_at"] = utc_now()
            row["error_message"] = "File not found during reconcile"
            cleared += 1

    write_csv(csv_path, fieldnames, rows)
    print(
        f"scanned_files={len(files_by_stem)} matched_rows={matched} "
        f"updated_rows={updated} cleared_rows={cleared}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())