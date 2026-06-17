#!/usr/bin/env python3
"""Download tracks from an Exportify CSV using yt-dlp and track progress in-place.

This script uses the same CSV file as both input and state store.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REQUIRED_COLUMNS = ["Track Name", "Artist Name(s)", "Track Duration (ms)"]
TRACKING_COLUMNS = [
    "download_status",
    "youtube_url",
    "selected_title",
    "selected_duration_s",
    "duration_delta_s",
    "output_file",
    "attempted_at",
    "error_message",
]

STATUS_DOWNLOADED = "downloaded"
STATUS_SKIPPED = "skipped"
STATUS_UNRESOLVED = "unresolved"
STATUS_ERROR = "error"


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
    return parser.parse_args()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def first_artist(artists: str) -> str:
    if not artists:
        return ""
    return artists.split(",", 1)[0].strip()


def stable_base_name(artist: str, track: str) -> str:
    merged = f"{artist} - {track}".strip(" -")
    merged = re.sub(r"[\\/:*?\"<>|]", "_", merged)
    merged = re.sub(r"\s+", " ", merged).strip()
    return merged[:160] if merged else "track"


def build_cookie_args(cookies_from_browser: str = "", cookies_file: Optional[Path] = None) -> List[str]:
    args: List[str] = []
    if cookies_from_browser:
        args.extend(["--cookies-from-browser", cookies_from_browser])
    if cookies_file is not None:
        args.extend(["--cookies", str(cookies_file)])
    return args


def run_yt_dlp_json(
    query: str,
    limit: int,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
) -> List[Dict[str, object]]:
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--no-warnings",
        f"ytsearch{limit}:{query}",
    ]
    if sleep_requests > 0:
        cmd.extend(["--sleep-requests", str(sleep_requests)])
    cmd.extend(build_cookie_args(cookies_from_browser, cookies_file))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(stderr or "yt-dlp search failed")

    payload = json.loads(proc.stdout)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []

    out: List[Dict[str, object]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        duration = item.get("duration")
        title = item.get("title")
        webpage_url = item.get("webpage_url") or item.get("url")
        uploader = item.get("uploader")
        out.append(
            {
                "duration": int(duration) if isinstance(duration, (int, float)) else None,
                "title": str(title) if title is not None else "",
                "webpage_url": str(webpage_url) if webpage_url is not None else "",
                "uploader": str(uploader) if uploader is not None else "",
            }
        )
    return out


VERSION_KEYWORDS = {
    "remix",
    "vip",
    "live",
    "acoustic",
    "instrumental",
    "edit",
    "radio",
    "extended",
    "bootleg",
    "cover",
    "rework",
    "flip",
    "mashup",
}

NOISY_KEYWORDS = {
    "nightcore",
    "sped up",
    "slowed",
    "reverb",
    "bass boosted",
    "8d",
    "hour",
    "lyrics",
    "lyric",
    "karaoke",
    "compilation",
}


def has_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return phrase in text


def track_version_keywords(track: str) -> List[str]:
    norm = normalize_text(track)
    present: List[str] = []
    for key in VERSION_KEYWORDS:
        if has_phrase(norm, key):
            present.append(key)
    return present


def count_token_hits(tokens: List[str], *fields: str) -> int:
    if not tokens:
        return 0
    merged = " ".join(fields)
    return sum(1 for token in tokens if token and token in merged)


def score_candidate(
    candidate: Dict[str, object],
    expected_duration_s: int,
    artist_tokens: List[str],
    track_tokens: List[str],
    required_versions: List[str],
    tolerance: int,
) -> Optional[Tuple[int, int]]:
    duration = candidate.get("duration")
    if not isinstance(duration, int):
        return None

    delta = abs(duration - expected_duration_s)
    if delta > tolerance:
        return None

    title = normalize_text(str(candidate.get("title", "")))
    uploader = normalize_text(str(candidate.get("uploader", "")))
    combined = f"{title} {uploader}".strip()

    track_hits = count_token_hits(track_tokens, title)
    artist_hits = count_token_hits(artist_tokens, title, uploader)

    # Require meaningful overlap to reduce false positives.
    min_track_hits = max(1, len(track_tokens) // 2)
    if track_hits < min_track_hits:
        return None
    if artist_tokens and artist_hits < 1:
        return None

    # If the Spotify track includes a version marker (VIP, remix, etc.), keep only that version.
    for version in required_versions:
        if version not in combined:
            return None

    penalty = 0
    for noisy in NOISY_KEYWORDS:
        if has_phrase(combined, noisy):
            penalty += 120

    # Penalize version mismatch when candidate has extra version words not present in track metadata.
    candidate_versions = [v for v in VERSION_KEYWORDS if has_phrase(combined, v)]
    for version in candidate_versions:
        if version not in required_versions:
            penalty += 70

    if has_phrase(combined, "official audio"):
        penalty -= 30
    if has_phrase(uploader, "topic"):
        penalty -= 25

    # Lower score is better: duration delta first, then prefer more token hits.
    score = delta * 100 - (track_hits * 30 + artist_hits * 20) + penalty
    return score, delta


def choose_candidate(
    candidates: List[Dict[str, object]],
    expected_duration_s: int,
    artist: str,
    track: str,
    tolerance: int,
) -> Optional[Tuple[Dict[str, object], int]]:
    artist_tokens = [t for t in normalize_text(artist).split(" ") if len(t) >= 3]
    track_tokens = [t for t in normalize_text(track).split(" ") if len(t) >= 3]
    required_versions = track_version_keywords(track)

    best: Optional[Tuple[Dict[str, object], int, int]] = None
    for cand in candidates:
        scored = score_candidate(
            cand,
            expected_duration_s,
            artist_tokens,
            track_tokens,
            required_versions,
            tolerance,
        )
        if scored is None:
            continue
        score, delta = scored
        if best is None or score < best[2]:
            best = (cand, delta, score)

    if best is None:
        return None
    return best[0], best[1]


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def ensure_tracking_columns(fieldnames: List[str]) -> List[str]:
    updated = list(fieldnames)
    for col in TRACKING_COLUMNS:
        if col not in updated:
            updated.append(col)
    return updated


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


def reset_result_columns(row: Dict[str, str]) -> None:
    for col in TRACKING_COLUMNS:
        if col not in row:
            row[col] = ""


def download_audio(
    url: str,
    output_template: str,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
) -> None:
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "320K",
        "-f",
        "bestaudio/best",
        "--no-playlist",
        "--no-warnings",
        "--extractor-args",
        "youtube:player_client=android,web",
        "--paths",
        str(Path(output_template).parent),
        "-o",
        Path(output_template).name,
        url,
    ]
    if sleep_requests > 0:
        cmd.extend(["--sleep-requests", str(sleep_requests)])
    cmd.extend(build_cookie_args(cookies_from_browser, cookies_file))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(stderr or "yt-dlp download failed")


def resolve_downloaded_file(output_dir: Path, base_name: str) -> Optional[Path]:
    files = sorted(output_dir.glob(f"{base_name}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def clean_meta_value(value: str) -> str:
    return value.replace("\x00", "").strip()


def extract_spotify_track_id(track_uri: str) -> str:
    value = clean_meta_value(track_uri)
    if not value:
        return ""
    # Supports spotify:track:<id> and https://open.spotify.com/track/<id>
    match = re.search(r"track[:/](?P<id>[A-Za-z0-9]+)", value)
    return match.group("id") if match else ""


def build_audio_metadata(row: Dict[str, str], row_id: Optional[int] = None) -> Dict[str, str]:
    metadata: Dict[str, str] = {}

    title = clean_meta_value(row.get("Track Name", ""))
    artist = clean_meta_value(first_artist(row.get("Artist Name(s)", "")))
    album = clean_meta_value(row.get("Album Name", ""))
    album_artist = clean_meta_value(first_artist(row.get("Album Artist Name(s)", "")))
    release_date = clean_meta_value(row.get("Album Release Date", ""))
    track_number = clean_meta_value(row.get("Track Number", ""))
    disc_number = clean_meta_value(row.get("Disc Number", ""))
    isrc = clean_meta_value(row.get("ISRC", ""))
    spotify_track_id = extract_spotify_track_id(row.get("Track URI", ""))

    if title:
        metadata["title"] = title
    if artist:
        metadata["artist"] = artist
    if album:
        metadata["album"] = album
    if album_artist:
        metadata["album_artist"] = album_artist
    if release_date:
        metadata["date"] = release_date
    # User-requested behavior: metadata track ID should mirror the CSV row number.
    if row_id is not None and row_id > 0:
        metadata["track"] = str(row_id)
    elif track_number and disc_number:
        metadata["track"] = f"{track_number}/{disc_number}"
    elif track_number:
        metadata["track"] = track_number
    if disc_number:
        metadata["disc"] = disc_number
    if isrc:
        metadata["isrc"] = isrc
    if spotify_track_id:
        metadata["spotify_track_id"] = spotify_track_id
    if row_id is not None and row_id > 0:
        metadata["row_id"] = str(row_id)
    if spotify_track_id or row_id is not None:
        parts: List[str] = []
        if row_id is not None and row_id > 0:
            parts.append(f"row_id={row_id}")
        if spotify_track_id:
            parts.append(f"spotify_track_id={spotify_track_id}")
        metadata["comment"] = "; ".join(parts)

    return metadata


def embed_audio_metadata(file_path: Path, metadata: Dict[str, str]) -> None:
    if not metadata:
        return

    tagged_file = file_path.with_name(f"{file_path.stem}.tagtmp{file_path.suffix}")
    suffix = file_path.suffix.lower()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(file_path),
        "-map",
        "0:a:0",
        "-c",
        "copy",
    ]

    if suffix == ".mp3":
        cmd.extend(["-id3v2_version", "3", "-write_id3v1", "1"])
    elif suffix in {".m4a", ".mp4"}:
        cmd.extend(["-movflags", "+use_metadata_tags"])

    for key, value in metadata.items():
        if value:
            cmd.extend(["-metadata", f"{key}={value}"])

    # Some Windows property readers are more reliable with stream-level fields present.
    for key in ("title", "artist", "album", "track"):
        value = metadata.get(key)
        if value:
            cmd.extend(["-metadata:s:a:0", f"{key}={value}"])

    cmd.append(str(tagged_file))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(stderr or "ffmpeg metadata embedding failed")

    tagged_file.replace(file_path)


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

    output_dir = csv_path.parent / csv_path.stem
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

    # Persist added columns immediately so CSV becomes the source of state.
    write_csv(csv_path, rows, fieldnames)

    processed = 0
    downloaded = 0
    skipped = 0
    unresolved = 0
    failed = 0

    for idx, row in enumerate(rows, start=1):
        if args.limit and processed >= args.limit:
            break

        if should_skip_row(row, args.force_redownload):
            output_file = (row.get("output_file") or "").strip()
            if output_file:
                try:
                    embed_audio_metadata(Path(output_file), build_audio_metadata(row, idx))
                except Exception as exc:  # noqa: BLE001
                    row["download_status"] = STATUS_ERROR
                    row["attempted_at"] = utc_now()
                    row["error_message"] = f"Metadata write failed: {str(exc).strip()[:350]}"
                    write_csv(csv_path, rows, fieldnames)
                    failed += 1
                    processed += 1
                    print(f"[{idx}] error: metadata update failed :: {exc}")
                    continue
            skipped += 1
            continue

        track = (row.get("Track Name") or "").strip()
        artists = (row.get("Artist Name(s)") or "").strip()
        artist = first_artist(artists)
        duration_ms_raw = (row.get("Track Duration (ms)") or "").strip()

        if not track or not artist or not duration_ms_raw.isdigit():
            row["download_status"] = STATUS_ERROR
            row["attempted_at"] = utc_now()
            row["error_message"] = "Missing track, artist, or valid duration"
            write_csv(csv_path, rows, fieldnames)
            failed += 1
            processed += 1
            print(f"[{idx}] error: invalid row metadata")
            continue

        expected_duration_s = round(int(duration_ms_raw) / 1000)
        query = f"{artist} {track}"

        try:
            candidates = run_yt_dlp_json(
                query,
                args.search_results,
                args.cookies_from_browser.strip(),
                cookies_file,
                args.sleep_requests,
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
                write_csv(csv_path, rows, fieldnames)
                unresolved += 1
                processed += 1
                print(f"[{idx}] unresolved: {artist} - {track}")
                continue

            candidate, delta = picked
            url = str(candidate.get("webpage_url") or "").strip()
            title = str(candidate.get("title") or "").strip()
            candidate_duration = candidate.get("duration")

            if not url:
                row["download_status"] = STATUS_ERROR
                row["attempted_at"] = utc_now()
                row["error_message"] = "Matched candidate missing URL"
                write_csv(csv_path, rows, fieldnames)
                failed += 1
                processed += 1
                print(f"[{idx}] error: match missing URL")
                continue

            base_name = stable_base_name(artist, track)
            output_template = str(output_dir / f"{base_name}.%(ext)s")

            download_audio(
                url,
                output_template,
                args.cookies_from_browser.strip(),
                cookies_file,
                args.sleep_requests,
            )
            saved_file = resolve_downloaded_file(output_dir, base_name)
            if saved_file is not None:
                embed_audio_metadata(saved_file, build_audio_metadata(row, idx))

            row["download_status"] = STATUS_DOWNLOADED
            row["youtube_url"] = url
            row["selected_title"] = title
            row["selected_duration_s"] = str(candidate_duration if isinstance(candidate_duration, int) else "")
            row["duration_delta_s"] = str(delta)
            row["output_file"] = str(saved_file.resolve()) if saved_file else ""
            row["attempted_at"] = utc_now()
            row["error_message"] = ""

            write_csv(csv_path, rows, fieldnames)
            downloaded += 1
            processed += 1
            print(f"[{idx}] downloaded: {artist} - {track}")

        except Exception as exc:  # noqa: BLE001
            row["download_status"] = STATUS_ERROR
            row["attempted_at"] = utc_now()
            row["error_message"] = str(exc).strip()[:400]
            write_csv(csv_path, rows, fieldnames)
            failed += 1
            processed += 1
            print(f"[{idx}] error: {artist} - {track} :: {exc}")

    print("\nRun complete")
    print(f"  downloaded: {downloaded}")
    print(f"  skipped:    {skipped}")
    print(f"  unresolved: {unresolved}")
    print(f"  errors:     {failed}")
    print(f"  csv:        {csv_path}")
    print(f"  out dir:    {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
