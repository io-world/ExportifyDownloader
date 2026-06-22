#!/usr/bin/env python3
"""Download tracks from an Exportify CSV using yt-dlp and track progress in-place.

This script uses work CSV as both input and state store.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .matcher import choose_candidate
from .csv_work_state import (
    ID_COLUMN,
    TRACKING_COLUMNS,
    ensure_row_ids,
    ensure_row_keys,
    ensure_tracking_columns,
    playlist_stem,
    write_csv,
)
from .utils import (
    first_artist,
    log,
    shorten_error_message,
    stable_base_name,
    utc_now,
)
from .metadata import build_audio_metadata, embed_audio_metadata, embed_cover_art
from .yt_dlp_interface import (
    download_audio,
    download_thumbnail,
    resolve_downloaded_file,
    resolve_thumbnail_file,
    run_yt_dlp_json,
)

REQUIRED_COLUMNS = ["Track Name", "Artist Name(s)", "Track Duration (ms)"]

STATUS_RESOLVED = "resolved"
STATUS_DOWNLOADED = "downloaded"
STATUS_UNRESOLVED = "unresolved"
STATUS_ERROR = "error"

SKIP_TRACKING_COLUMNS = [col for col in TRACKING_COLUMNS if col != "attempted_at"]





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download tracks from Exportify CSV and update the same CSV with progress."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to Exportify CSV file.",
    )
    parser.add_argument(
        "--duration-tolerance",
        type=int,
        default=10,
        help="Maximum allowed duration difference in seconds for a match (default: 10).",
    )
    parser.add_argument(
        "--search-results",
        type=int,
        default=6,
        help="Number of YouTube candidates to inspect for each track (default: 6).",
    )
    parser.add_argument(
        "--download-enabled",
        action="store_true",
        default=True,
        dest="download_enabled",
        help="Download audio after resolving a YouTube Music candidate (default: enabled).",
    )
    parser.add_argument(
        "--resolve-only",
        action="store_false",
        dest="download_enabled",
        help="Resolve YouTube Music candidates into the work CSV without downloading audio.",
    )
    parser.add_argument(
        "--force-redownload",
        action="store_true",
        help="Retry rows already marked downloaded.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default="",
        help=(
            "Optional browser name for yt-dlp cookies (for example: chrome, edge, firefox). "
            "Useful when YouTube returns HTTP 403 without cookies."
        ),
    )
    parser.add_argument(
        "--cookies-file",
        type=Path,
        default=None,
        help="Optional path to a Netscape cookies.txt file for yt-dlp.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N rows that need work (0 means all).",
    )
    parser.add_argument(
        "--sleep-requests",
        type=float,
        default=1.0,
        help="Delay in seconds between yt-dlp requests to reduce rate-limit issues (default: 1.0).",
    )
    parser.add_argument(
        "--limit-rate",
        default="",
        help="yt-dlp download limit rate (for example: 4M).",
    )
    parser.add_argument(
        "--throttled-rate",
        default="",
        help="yt-dlp throttled rate fallback (for example: 50K).",
    )
    parser.add_argument(
        "--sleep-interval",
        type=float,
        default=0.0,
        help="yt-dlp minimum random sleep interval between requests in seconds.",
    )
    parser.add_argument(
        "--max-sleep-interval",
        type=float,
        default=0.0,
        help="yt-dlp maximum random sleep interval between requests in seconds.",
    )
    parser.add_argument(
        "--id-order",
        choices=["default", "ascending", "descending"],
        default="default",
        help="Process rows by persistent work CSV id order.",
        dest="id_order",
    )
    return parser.parse_args()


def metadata_row_id(row: Dict[str, str], row_index: int) -> int:
    raw_value = (row.get(ID_COLUMN) or "").strip()
    if raw_value.isdigit() and int(raw_value) > 0:
        return int(raw_value)
    return row_index


def should_skip_row(row: Dict[str, str], force_redownload: bool) -> bool:
    if force_redownload:
        return False

    status = (row.get("download_status") or "").strip().lower()
    output_file = (row.get("output_file") or "").strip()

    if status == STATUS_DOWNLOADED and output_file:
        file_path = Path(output_file)
        if file_path.exists():
            return True
    return False


def has_saved_resolution(row: Dict[str, str]) -> bool:
    return bool((row.get("youtube_url") or "").strip())


def has_tracking_data(row: Dict[str, str]) -> bool:
    for col in SKIP_TRACKING_COLUMNS:
        if (row.get(col) or "").strip():
            return True
    return False


def tracking_data_details(row: Dict[str, str]) -> List[str]:
    details: List[str] = []
    for col in SKIP_TRACKING_COLUMNS:
        value = (row.get(col) or "").strip()
        if value:
            details.append(f"{col}={value}")
    return details


def reset_result_columns(row: Dict[str, str]) -> None:
    for col in TRACKING_COLUMNS:
        if col not in row:
            row[col] = ""


def row_id_value(row: Dict[str, str]) -> Optional[int]:
    value = (row.get(ID_COLUMN) or "").strip()
    if value.isdigit():
        return int(value)
    return None


def get_row_processing_order(rows: List[Dict[str, str]], id_order: str) -> List[int]:
    order = list(range(len(rows)))
    if id_order == "default":
        return order

    if id_order == "ascending":
        return sorted(
            order,
            key=lambda i: (
                row_id_value(rows[i]) is None,
                row_id_value(rows[i]) if row_id_value(rows[i]) is not None else 0,
                i,
            ),
        )

    return sorted(
        order,
        key=lambda i: (
            row_id_value(rows[i]) is None,
            -(row_id_value(rows[i]) if row_id_value(rows[i]) is not None else 0),
            i,
        ),
    )


def main() -> int:
    args = parse_args()

    csv_path = args.csv_path.resolve()
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    cookies_file: Optional[Path] = None
    if args.cookies_file is not None:
        cookies_file = args.cookies_file.resolve()
        if not cookies_file.exists():
            print(f"Cookies file not found: {cookies_file}", file=sys.stderr)
            return 1

    output_dir = csv_path.parent / playlist_stem(csv_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("CSV appears empty or invalid.", file=sys.stderr)
            return 1
        fieldnames = list(reader.fieldnames)
        rows = [dict(r) for r in reader]

    missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        print("Missing required CSV columns: " + ", ".join(missing), file=sys.stderr)
        return 1

    fieldnames = ensure_tracking_columns(fieldnames)
    for row in rows:
        reset_result_columns(row)
    ensure_row_ids(rows)
    ensure_row_keys(rows)

    # Persist added columns immediately so CSV becomes the source of state.
    write_csv(csv_path, fieldnames, rows)

    processed = 0
    downloaded = 0
    resolved = 0
    skipped = 0
    unresolved = 0
    failed = 0
    row_order = get_row_processing_order(rows, args.id_order)
    log(f"Processing order: id {args.id_order}")
    log(f"Download enabled: {args.download_enabled}")

    for row_index in row_order:
        idx = row_index + 1
        row = rows[row_index]
        if args.limit and processed >= args.limit:
            break

        status = (row.get("download_status") or "").strip().lower()
        saved_resolution = has_saved_resolution(row)
        tracking_details = tracking_data_details(row)

        if not args.force_redownload and status == STATUS_RESOLVED and saved_resolution and args.download_enabled:
            pass
        elif not args.force_redownload and tracking_details:
            skipped += 1
            log(f"[{idx}] skip: tracking columns already populated ({'; '.join(tracking_details)})")
            continue

        if should_skip_row(row, args.force_redownload):
            output_file = (row.get("output_file") or "").strip()
            if output_file:
                try:
                    embed_audio_metadata(Path(output_file), build_audio_metadata(row, metadata_row_id(row, idx)))
                except Exception as exc:  # noqa: BLE001
                    row["download_status"] = STATUS_ERROR
                    row["attempted_at"] = utc_now()
                    row["error_message"] = f"Metadata write failed: {str(exc).strip()[:350]}"
                    write_csv(csv_path, fieldnames, rows)
                    failed += 1
                    processed += 1
                    log(f"[{idx}] error: metadata update failed :: {shorten_error_message(str(exc))}")
                    continue
            skipped += 1
            log(f"[{idx}] skip: already downloaded")
            continue

        track = (row.get("Track Name") or "").strip()
        artists = (row.get("Artist Name(s)") or "").strip()
        artist = first_artist(artists)
        duration_ms_raw = (row.get("Track Duration (ms)") or "").strip()

        if not track or not artist or not duration_ms_raw.isdigit():
            row["download_status"] = STATUS_ERROR
            row["attempted_at"] = utc_now()
            row["error_message"] = "Missing track, artist, or valid duration"
            write_csv(csv_path, fieldnames, rows)
            failed += 1
            processed += 1
            log(f"[{idx}] error: invalid row metadata")
            continue

        expected_duration_s = round(int(duration_ms_raw) / 1000)
        query = f"{artist} {track}"

        try:
            if saved_resolution and status == STATUS_RESOLVED and not args.force_redownload:
                url = str(row.get("youtube_url") or "").strip()
                title = str(row.get("selected_title") or "").strip()
                selected_duration_raw = (row.get("selected_duration_s") or "").strip()
                candidate_duration = int(selected_duration_raw) if selected_duration_raw.isdigit() else None
                delta_raw = (row.get("duration_delta_s") or "").strip()
                delta = int(delta_raw) if delta_raw.isdigit() else 0
                log(f"[{idx}] using saved resolution: {artist} - {track} <- {title or url}")
            else:
                log(f"[{idx}] checking: {artist} - {track}")
                candidates = run_yt_dlp_json(
                    query,
                    args.search_results,
                    args.cookies_from_browser.strip(),
                    cookies_file,
                    args.sleep_requests,
                    args.limit_rate.strip(),
                    args.throttled_rate.strip(),
                    args.sleep_interval,
                    args.max_sleep_interval,
                )
                picked = choose_candidate(
                    candidates,
                    expected_duration_s,
                    artist,
                    track,
                    args.duration_tolerance,
                )
                if picked is None:
                    row["download_status"] = STATUS_UNRESOLVED
                    row["attempted_at"] = utc_now()
                    row["error_message"] = f"No match within {args.duration_tolerance}s"
                    row["youtube_url"] = ""
                    row["selected_title"] = ""
                    row["selected_duration_s"] = ""
                    row["duration_delta_s"] = ""
                    write_csv(csv_path, fieldnames, rows)
                    unresolved += 1
                    processed += 1
                    log(f"[{idx}] unresolved: {artist} - {track}")
                    continue

                candidate, delta = picked
                url = str(candidate.get("webpage_url") or "").strip()
                title = str(candidate.get("title") or "").strip()
                candidate_duration = candidate.get("duration")

                if not url:
                    row["download_status"] = STATUS_ERROR
                    row["attempted_at"] = utc_now()
                    row["error_message"] = "Matched candidate missing URL"
                    write_csv(csv_path, fieldnames, rows)
                    failed += 1
                    processed += 1
                    log(f"[{idx}] error: match missing URL")
                    continue

                row["download_status"] = STATUS_RESOLVED
                row["youtube_url"] = url
                row["selected_title"] = title
                row["selected_duration_s"] = str(candidate_duration if isinstance(candidate_duration, int) else "")
                row["duration_delta_s"] = str(delta)
                row["attempted_at"] = utc_now()
                row["error_message"] = ""
                write_csv(csv_path, fieldnames, rows)
                resolved += 1

                if not args.download_enabled:
                    processed += 1
                    log(f"[{idx}] resolved: {artist} - {track} <- {title}")
                    continue

            base_name = stable_base_name(artist, track)
            output_template = str(output_dir / f"{base_name}.%(ext)s")
            log(f"[{idx}] downloading: {artist} - {track} <- {title}")

            saved_file = download_audio(
                url,
                output_template,
                args.cookies_from_browser.strip(),
                cookies_file,
                args.sleep_requests,
                args.limit_rate.strip(),
                args.throttled_rate.strip(),
                args.sleep_interval,
                args.max_sleep_interval,
            )
            if saved_file is None:
                saved_file = resolve_downloaded_file(output_dir, base_name)
            if saved_file is not None:
                embed_audio_metadata(saved_file, build_audio_metadata(row, metadata_row_id(row, idx)))
                cover_image = resolve_thumbnail_file(saved_file.parent, saved_file.stem)
                if cover_image is None:
                    try:
                        cover_image = download_thumbnail(
                            url,
                            str(saved_file.with_suffix(".%(ext)s")),
                            args.cookies_from_browser.strip(),
                            cookies_file,
                            args.sleep_requests,
                            args.limit_rate.strip(),
                            args.throttled_rate.strip(),
                            args.sleep_interval,
                            args.max_sleep_interval,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log(f"[{idx}] warning: artwork download failed :: {shorten_error_message(str(exc))}")
                if cover_image is not None:
                    try:
                        embed_cover_art(saved_file, cover_image)
                    except Exception as exc:  # noqa: BLE001
                        log(f"[{idx}] warning: artwork embed failed :: {shorten_error_message(str(exc))}")

            row["download_status"] = STATUS_DOWNLOADED
            row["output_file"] = str(saved_file.resolve()) if saved_file else ""
            row["attempted_at"] = utc_now()
            row["error_message"] = ""

            write_csv(csv_path, fieldnames, rows)
            downloaded += 1
            processed += 1
            log(f"[{idx}] downloaded: {artist} - {track}")

        except Exception as exc:  # noqa: BLE001
            row["download_status"] = STATUS_ERROR
            row["attempted_at"] = utc_now()
            row["error_message"] = str(exc).strip()[:400]
            write_csv(csv_path, fieldnames, rows)
            failed += 1
            processed += 1
            log(f"[{idx}] error: {artist} - {track} :: {shorten_error_message(str(exc))}")

    log("\nRun complete")
    log(f"  resolved:   {resolved}")
    log(f"  downloaded: {downloaded}")
    log(f"  skipped:    {skipped}")
    log(f"  unresolved: {unresolved}")
    log(f"  errors:     {failed}")
    log(f"  csv:        {csv_path}")
    log(f"  out dir:    {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
