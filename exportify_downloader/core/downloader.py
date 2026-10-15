#!/usr/bin/env python3
"""Download tracks from an Exportify CSV using yt-dlp and track progress in-place.

This script uses work CSV as both input and state store.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .matcher import choose_candidate
from .csv_work_state import (
    ID_COLUMN,
    OUTPUT_FOLDER_COLUMN,
    STATUS_DOWNLOADED,
    STATUS_ERROR,
    STATUS_RESOLVED,
    STATUS_RETRY,
    STATUS_UNRESOLVED,
    TRACKING_COLUMNS,
    ensure_row_ids,
    ensure_row_keys,
    ensure_tracking_columns,
    playlist_stem,
    read_csv,
    write_csv,
)
from .utils import (
    classify_download_error,
    first_artist,
    log,
    parse_rate_limit,
    shorten_error_message,
    stable_base_name,
    utc_now,
)
from .metadata import (
    build_audio_metadata,
    embed_audio_metadata,
    embed_cover_art,
    embed_cover_art_from_url,
    metadata_row_id,
)
from .yt_dlp_interface import (
    RateLimitError,
    TransientError,
    best_thumbnail_url,
    download_audio,
    resolve_downloaded_file,
    resolve_thumbnail_file,
    run_yt_dlp_json,
)

REQUIRED_COLUMNS = ["Track Name", "Artist Name(s)", "Track Duration (ms)"]

# Exit code when the run stopped early because YouTube (or the network) is unavailable.
# The launcher uses it to stop a batch instead of hammering the next playlist. (BSD EX_TEMPFAIL)
EXIT_STOPPED_EARLY = 75

# Stop after this many back-to-back network failures; the connection is probably down.
MAX_CONSECUTIVE_TRANSIENT_ERRORS = 3


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
        choices=["default", "priority", "ascending", "descending"],
        default="default",
        help="Process rows by persistent work CSV id order.",
        dest="id_order",
    )
    return parser.parse_args()


def should_skip_row(row: Dict[str, str], force_redownload: bool) -> bool:
    if force_redownload:
        return False

    status = (row.get("download_status") or "").strip().lower()
    output_file = (row.get("output_file") or "").strip()
    return status == STATUS_DOWNLOADED and bool(output_file) and Path(output_file).exists()


def has_saved_resolution(row: Dict[str, str]) -> bool:
    return bool((row.get("youtube_url") or "").strip())


def add_missing_tracking_values(row: Dict[str, str]) -> None:
    for col in TRACKING_COLUMNS:
        row.setdefault(col, "")


def row_id_value(row: Dict[str, str]) -> Optional[int]:
    value = (row.get(ID_COLUMN) or "").strip()
    if value.isdigit():
        return int(value)
    return None


def row_priority_bucket(row: Dict[str, str]) -> int:
    status = (row.get("download_status") or "").strip().lower()
    if not status:
        return 0
    if status == STATUS_RETRY:
        return 2
    return 1


def get_row_processing_order(rows: List[Dict[str, str]], id_order: str) -> List[int]:
    order = list(range(len(rows)))
    if id_order == "default":
        return order

    sign = -1 if id_order == "descending" else 1

    def id_key(i: int) -> Tuple[bool, int, int]:
        # Rows without an id always sort last, in file order.
        row_id = row_id_value(rows[i])
        return (row_id is None, sign * (row_id or 0), i)

    if id_order == "priority":
        return sorted(order, key=lambda i: (row_priority_bucket(rows[i]), *id_key(i)))
    return sorted(order, key=id_key)


def resolve_row_output_dir(row: Dict[str, str], csv_path: Path, default_dir: Path) -> Path:
    value = (row.get(OUTPUT_FOLDER_COLUMN) or "").strip()
    if not value:
        return default_dir
    row_dir = Path(value)
    if not row_dir.is_absolute():
        row_dir = csv_path.parent / row_dir
    return row_dir.resolve()


def tag_downloaded_file(
    idx: int,
    row: Dict[str, str],
    saved_file: Path,
    info: Dict[str, Any],
) -> None:
    """Write CSV metadata and cover art. Failures are warnings; the audio is already saved."""
    try:
        embed_audio_metadata(saved_file, build_audio_metadata(row, metadata_row_id(row, idx)))
    except Exception as exc:  # noqa: BLE001
        log(f"[{idx}] warning: metadata embed failed :: {shorten_error_message(str(exc))}")

    cover_image = resolve_thumbnail_file(saved_file.parent, saved_file.stem)
    thumbnail_url = "" if cover_image is not None else best_thumbnail_url(info)
    if cover_image is None and not thumbnail_url:
        return
    try:
        if cover_image is not None:
            embed_cover_art(saved_file, cover_image)
        else:
            embed_cover_art_from_url(saved_file, thumbnail_url)
        row["artwork_status"] = "embedded"
    except Exception as exc:  # noqa: BLE001
        row["artwork_status"] = "failed"
        log(f"[{idx}] warning: artwork embed failed :: {shorten_error_message(str(exc))}")


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

    # Validate once up front; otherwise a typo would fail (and mark) every row.
    try:
        parse_rate_limit(args.limit_rate.strip(), "--limit-rate")
        parse_rate_limit(args.throttled_rate.strip(), "--throttled-rate")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    ydl_settings: Dict[str, Any] = {
        "cookies_from_browser": args.cookies_from_browser.strip(),
        "cookies_file": cookies_file,
        "sleep_requests": args.sleep_requests,
        "limit_rate": args.limit_rate.strip(),
        "throttled_rate": args.throttled_rate.strip(),
        "sleep_interval": args.sleep_interval,
        "max_sleep_interval": args.max_sleep_interval,
    }

    try:
        fieldnames, rows = read_csv(csv_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        print("Missing required CSV columns: " + ", ".join(missing), file=sys.stderr)
        return 1

    output_dir = csv_path.parent / playlist_stem(csv_path)
    if any(not (row.get(OUTPUT_FOLDER_COLUMN) or "").strip() for row in rows):
        output_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = ensure_tracking_columns(fieldnames)
    for row in rows:
        add_missing_tracking_values(row)
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
    rate_limited = 0
    retry_later = 0
    consecutive_transient = 0
    stop_reason = ""
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
        error_message = (row.get("error_message") or "").strip()

        # Older runs marked rate-limit/network failures as permanent errors; give them another go.
        if status == STATUS_ERROR and error_message and classify_download_error(error_message):
            row["download_status"] = STATUS_RETRY
            status = STATUS_RETRY
            write_csv(csv_path, fieldnames, rows)

        if status == STATUS_RETRY and not error_message:
            row["download_status"] = ""
            status = ""
            write_csv(csv_path, fieldnames, rows)

        if status == STATUS_ERROR and not args.force_redownload:
            skipped += 1
            log(f"[{idx}] skip: previous permanent error ({shorten_error_message(error_message)})")
            continue

        if should_skip_row(row, args.force_redownload):
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
            if saved_resolution and status in {STATUS_RESOLVED, STATUS_RETRY} and not args.force_redownload:
                url = str(row.get("youtube_url") or "").strip()
                title = str(row.get("selected_title") or "").strip()
                if status == STATUS_RETRY:
                    log(f"[{idx}] retrying saved resolution: {artist} - {track} <- {title or url}")
                else:
                    log(f"[{idx}] using saved resolution: {artist} - {track} <- {title or url}")
            else:
                log(f"[{idx}] checking: {artist} - {track}")
                candidates = run_yt_dlp_json(query, args.search_results, **ydl_settings)
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
                    consecutive_transient = 0
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
                consecutive_transient = 0

                if not args.download_enabled:
                    processed += 1
                    log(f"[{idx}] resolved: {artist} - {track} <- {title}")
                    continue

            base_name = stable_base_name(artist, track)
            row_output_dir = resolve_row_output_dir(row, csv_path, output_dir)
            row_output_dir.mkdir(parents=True, exist_ok=True)
            output_template = str(row_output_dir / f"{base_name}.%(ext)s")
            log(f"[{idx}] downloading: {artist} - {track} <- {title}")

            saved_file, info = download_audio(url, output_template, **ydl_settings)
            if saved_file is None:
                saved_file = resolve_downloaded_file(row_output_dir, base_name)
            if saved_file is None:
                raise RuntimeError(f"Download finished but no audio file was found in {row_output_dir}")

            # Record the download before tagging so a tagging failure can't orphan the file.
            row["download_status"] = STATUS_DOWNLOADED
            row["output_file"] = str(saved_file.resolve())
            row["attempted_at"] = utc_now()
            row["error_message"] = ""
            write_csv(csv_path, fieldnames, rows)

            tag_downloaded_file(idx, row, saved_file, info)
            write_csv(csv_path, fieldnames, rows)
            downloaded += 1
            processed += 1
            consecutive_transient = 0
            log(f"[{idx}] downloaded: {artist} - {track}")

        except RateLimitError as exc:
            row["download_status"] = STATUS_RETRY
            row["attempted_at"] = utc_now()
            row["error_message"] = str(exc).strip()[:400]
            write_csv(csv_path, fieldnames, rows)
            rate_limited += 1
            processed += 1
            stop_reason = "session rate-limited; rerun later to retry"
            log(f"[{idx}] rate-limited: marked for retry :: {shorten_error_message(str(exc))}")
            log("Stopping run early because the current YouTube session is rate-limited.")
            break
        except TransientError as exc:
            row["download_status"] = STATUS_RETRY
            row["attempted_at"] = utc_now()
            row["error_message"] = str(exc).strip()[:400]
            write_csv(csv_path, fieldnames, rows)
            retry_later += 1
            processed += 1
            consecutive_transient += 1
            log(f"[{idx}] network error: marked for retry :: {shorten_error_message(str(exc))}")
            if consecutive_transient >= MAX_CONSECUTIVE_TRANSIENT_ERRORS:
                stop_reason = "repeated network errors; check the connection and rerun"
                log(f"Stopping run early after {consecutive_transient} network errors in a row.")
                break
        except Exception as exc:  # noqa: BLE001
            row["download_status"] = STATUS_ERROR
            row["attempted_at"] = utc_now()
            row["error_message"] = str(exc).strip()[:400]
            write_csv(csv_path, fieldnames, rows)
            failed += 1
            processed += 1
            consecutive_transient = 0
            log(f"[{idx}] error: {artist} - {track} :: {shorten_error_message(str(exc))}")

    log("\nRun complete")
    log(f"  resolved:   {resolved}")
    log(f"  downloaded: {downloaded}")
    log(f"  skipped:    {skipped}")
    log(f"  unresolved: {unresolved}")
    log(f"  errors:     {failed}")
    log(f"  rate-limit: {rate_limited}")
    log(f"  retry:      {retry_later}")
    if stop_reason:
        log(f"  stopped:    {stop_reason}")
    log(f"  csv:        {csv_path}")
    log(f"  out dir:    {output_dir}")
    return EXIT_STOPPED_EARLY if stop_reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
