#!/usr/bin/env python3
"""Metadata extraction and writing helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .utils import clean_meta_value, extract_spotify_track_id, first_artist

ROW_KEY_COLUMN = "row_key"


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
    row_key = clean_meta_value(row.get(ROW_KEY_COLUMN, ""))

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
    if row_key:
        metadata["row_key"] = row_key
    if row_id is not None and row_id > 0:
        metadata["row_id"] = str(row_id)
    if spotify_track_id or row_id is not None or row_key:
        parts: List[str] = []
        if row_id is not None and row_id > 0:
            parts.append(f"row_id={row_id}")
        if row_key:
            parts.append(f"row_key={row_key}")
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
