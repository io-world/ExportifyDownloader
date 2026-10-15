#!/usr/bin/env python3
"""Reconcile local audio files and refresh metadata without downloading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

from ..core.csv_work_state import (
    STATUS_DOWNLOADED,
    ensure_tracking_columns,
    playlist_stem,
    read_csv,
    write_csv,
)
from ..core.metadata import (
    build_audio_metadata,
    embed_audio_metadata,
    embed_cover_art,
    embed_cover_art_from_url,
    has_embedded_art,
    metadata_row_id,
)
from ..core.utils import shorten_error_message, utc_now
from ..core.yt_dlp_interface import RateLimitError, get_thumbnail_url, resolve_thumbnail_file
from ..launcher.config import DEFAULT_CONFIG_PATH, load_settings, ydl_kwargs_from_settings
from .reconcile import (
    collect_audio_files,
    discover_csv_path,
    find_matching_file,
    resolve_target_csv_path,
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
    parser.add_argument(
        "--refresh-art",
        action="store_true",
        help="Re-embed artwork even for files that already have it (default: only fill in missing art).",
    )
    parser.add_argument(
        "--config-path",
        default=DEFAULT_CONFIG_PATH,
        help="Downloader JSON config used for cookies and request pacing (default: ./downloader.config.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parents[2]

    try:
        ydl_kwargs: Dict[str, Any] = ydl_kwargs_from_settings(
            script_dir, load_settings(script_dir, args.config_path)
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    csv_path = args.csv_path.resolve() if args.csv_path is not None else discover_csv_path()
    if csv_path is None:
        print(
            "Could not determine CSV automatically. Pass csv_path explicitly, for example: "
            r"python -m exportify_downloader.scripts.reconcile_metadata .\exportify.app\3_dnb_dance_floor.csv",
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

    try:
        fieldnames, rows = read_csv(csv_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    fieldnames = ensure_tracking_columns(fieldnames)

    files_by_stem = collect_audio_files(files_dir)
    matched = 0
    retagged = 0
    updated_rows = 0
    errors = 0
    artwork_embedded = 0
    artwork_kept = 0
    artwork_missing_source = 0
    artwork_warnings = 0
    art_fetch_disabled = False

    for idx, row in enumerate(rows, start=1):
        if args.downloaded_only and (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
            continue

        match = find_matching_file(row, files_by_stem)
        if match is None:
            continue

        matched += 1
        try:
            embed_audio_metadata(match, build_audio_metadata(row, metadata_row_id(row, idx)))
        except Exception as exc:  # noqa: BLE001
            row["attempted_at"] = utc_now()
            row["error_message"] = f"Metadata write failed: {str(exc).strip()[:350]}"
            errors += 1
            continue
        retagged += 1

        try:
            cover_image = resolve_thumbnail_file(match.parent, match.stem)
            youtube_url = (row.get("youtube_url") or "").strip()
            if cover_image is not None:
                embed_cover_art(match, cover_image)
                artwork_embedded += 1
            elif not args.refresh_art and has_embedded_art(match):
                artwork_kept += 1
            elif youtube_url and not art_fetch_disabled:
                thumbnail_url = get_thumbnail_url(youtube_url, **ydl_kwargs)
                if thumbnail_url:
                    embed_cover_art_from_url(match, thumbnail_url)
                    artwork_embedded += 1
                else:
                    artwork_missing_source += 1
            else:
                artwork_missing_source += 1
        except RateLimitError as exc:
            artwork_warnings += 1
            art_fetch_disabled = True
            print(
                f"[{idx}] rate-limited fetching artwork; skipping YouTube art for the rest of this run :: "
                f"{shorten_error_message(str(exc))}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            artwork_warnings += 1
            print(
                f"[{idx}] warning: artwork fetch/embed failed :: {shorten_error_message(str(exc))}",
                flush=True,
            )

        resolved_match = str(match)
        if (row.get("output_file") or "").strip() != resolved_match:
            row["output_file"] = resolved_match
            updated_rows += 1
        if (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
            row["download_status"] = STATUS_DOWNLOADED
            updated_rows += 1
        row["attempted_at"] = utc_now()
        row["error_message"] = ""

    write_csv(csv_path, fieldnames, rows)
    print(
        f"scanned_files={len(files_by_stem)} matched_rows={matched} "
        f"retagged_rows={retagged} updated_rows={updated_rows} "
        f"artwork_embedded={artwork_embedded} "
        f"artwork_kept={artwork_kept} "
        f"artwork_missing_source={artwork_missing_source} "
        f"artwork_warnings={artwork_warnings} errors={errors}"
    )
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
