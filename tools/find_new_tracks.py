#!/usr/bin/env python3
"""Report audio files in a new folder that have no close match in the original folder."""

from __future__ import annotations

import argparse
import csv
import difflib
import sys
from datetime import datetime
from pathlib import Path
from typing import List, NamedTuple, Optional

from exportify_downloader.core.utils import normalize_text

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav", ".ogg", ".opus"}

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_LOGS_DIR = REPO_ROOT / "run_logs"

DEFAULT_ORIGINAL_DIR = Path(r"C:\Users\me\OneDrive\Desktop\DJ Music\Randy DJ Music\3. DnB Dance Floor")
DEFAULT_NEW_DIR = Path(r"C:\Users\me\OneDrive\Desktop\DJ Music\Downloader\exportify.app\3_dnb_dance_floor")
DEFAULT_THRESHOLD = 0.85


class Track(NamedTuple):
    path: Path
    normalized: str
    normalized_title: str


def split_title(stem: str) -> str:
    """Return the part after the first ' - ' (artist prefix), or the whole stem if there's none."""
    artist, sep, rest = stem.partition(" - ")
    return rest if sep else stem


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find audio files in a new folder with no close-name match in the original folder."
    )
    parser.add_argument(
        "original_dir", type=Path, nargs="?", default=DEFAULT_ORIGINAL_DIR, help="Folder with the existing library."
    )
    parser.add_argument(
        "new_dir", type=Path, nargs="?", default=DEFAULT_NEW_DIR, help="Folder with the newly downloaded files."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Similarity ratio (0-1) above which a file counts as already present (default: {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Path to write the missing-files report as CSV (default: run_logs/find_new_tracks_<timestamp>.csv).",
    )
    return parser.parse_args()


def collect_tracks(folder: Path) -> List[Track]:
    tracks = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            tracks.append(
                Track(
                    path=path,
                    normalized=normalize_text(path.stem),
                    normalized_title=normalize_text(split_title(path.stem)),
                )
            )
    return tracks


def similarity(track: Track, candidate: Track) -> float:
    full_ratio = difflib.SequenceMatcher(None, track.normalized, candidate.normalized).ratio()
    title_ratio = difflib.SequenceMatcher(None, track.normalized_title, candidate.normalized_title).ratio()
    return max(full_ratio, title_ratio)


def best_match(track: Track, candidates: List[Track]) -> Optional[tuple[float, Track]]:
    best: Optional[tuple[float, Track]] = None
    for candidate in candidates:
        score = similarity(track, candidate)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best


def main() -> int:
    args = parse_args()

    if not args.original_dir.is_dir():
        print(f"Original folder not found: {args.original_dir}", file=sys.stderr)
        return 1
    if not args.new_dir.is_dir():
        print(f"New folder not found: {args.new_dir}", file=sys.stderr)
        return 1

    original_tracks = collect_tracks(args.original_dir)
    new_tracks = collect_tracks(args.new_dir)

    missing_rows = []
    matched = 0
    for track in new_tracks:
        result = best_match(track, original_tracks)
        if result is not None and result[0] >= args.threshold:
            matched += 1
            continue
        score, closest = (result[0], result[1].path.name) if result is not None else (0.0, "")
        missing_rows.append((track.path.name, f"{score:.2f}", closest))

    for name, score, closest in missing_rows:
        print(f"MISSING  {name}  (closest: {score} -> {closest!r})")

    print(f"scanned_new={len(new_tracks)} matched={matched} missing={len(missing_rows)}")

    if args.csv_out is not None:
        csv_out = args.csv_out
    else:
        RUN_LOGS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_out = RUN_LOGS_DIR / f"find_new_tracks_{timestamp}.csv"

    with csv_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["new_file", "closest_match_score", "closest_match_file"])
        writer.writerows(missing_rows)
    print(f"wrote {csv_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
