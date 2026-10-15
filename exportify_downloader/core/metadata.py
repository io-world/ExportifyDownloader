#!/usr/bin/env python3
"""Metadata extraction and writing helpers."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .csv_work_state import ID_COLUMN, ROW_KEY_COLUMN
from .utils import clean_meta_value, extract_spotify_track_id, first_artist

# 100-ns intervals between Windows epoch (1601-01-01) and Unix epoch (1970-01-01)
_EPOCH_AS_FILETIME = 116_444_736_000_000_000

_kernel32 = None


def _get_kernel32():
    """kernel32 with explicit signatures so 64-bit HANDLEs are not truncated to int."""
    global _kernel32
    if _kernel32 is None:
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        k32.SetFileTime.restype = wintypes.BOOL
        k32.SetFileTime.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32 = k32
    return _kernel32


def _restore_timestamps(path: Path, original_stat: os.stat_result) -> None:
    os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
    if sys.platform == "win32":
        _restore_windows_creation_time(path, original_stat.st_ctime)


def _restore_windows_creation_time(path: Path, ctime: float) -> None:
    k32 = _get_kernel32()
    # FILETIME is two little-endian DWORDs, which is the same layout as one ULONGLONG.
    ft = ctypes.c_ulonglong(int(ctime * 10_000_000) + _EPOCH_AS_FILETIME)
    handle = k32.CreateFileW(
        str(path),
        0x0100,  # FILE_WRITE_ATTRIBUTES
        0,
        None,
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
        return
    try:
        k32.SetFileTime(handle, ctypes.byref(ft), None, None)
    finally:
        k32.CloseHandle(handle)


def _container_args(file_path: Path) -> List[str]:
    suffix = file_path.suffix.lower()
    if suffix == ".mp3":
        return ["-id3v2_version", "3", "-write_id3v1", "1"]
    if suffix in {".m4a", ".mp4"}:
        return ["-movflags", "+use_metadata_tags"]
    return []


def _run_ffmpeg_rewrite(file_path: Path, args: List[str], temp_tag: str, failure_message: str) -> None:
    """Run ffmpeg into a temp file next to file_path, then swap it in, keeping original timestamps."""
    tagged_file = file_path.with_name(f"{file_path.stem}.{temp_tag}{file_path.suffix}")
    cmd = ["ffmpeg", "-y", "-i", str(file_path), *args, *_container_args(file_path), str(tagged_file)]

    original_stat = file_path.stat()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise RuntimeError(stderr or failure_message)
        tagged_file.replace(file_path)
    finally:
        tagged_file.unlink(missing_ok=True)
    _restore_timestamps(file_path, original_stat)


def metadata_row_id(row: Dict[str, str], fallback: int) -> int:
    """The work CSV's persistent id, or the fallback (usually the 1-based row number)."""
    raw_value = (row.get(ID_COLUMN) or "").strip()
    if raw_value.isdigit() and int(raw_value) > 0:
        return int(raw_value)
    return fallback


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


def has_embedded_art(file_path: Path) -> bool:
    """True if ffprobe sees a video (cover art) stream in the file."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def embed_audio_metadata(file_path: Path, metadata: Dict[str, str]) -> None:
    if not metadata:
        return

    # "0:v?" carries over existing cover art (if any) so retagging never strips it.
    args = ["-map", "0:a:0", "-map", "0:v?", "-c", "copy"]
    for key, value in metadata.items():
        if value:
            args.extend(["-metadata", f"{key}={value}"])

    # Some Windows property readers are more reliable with stream-level fields present.
    for key in ("title", "artist", "album", "track"):
        value = metadata.get(key)
        if value:
            args.extend(["-metadata:s:a:0", f"{key}={value}"])

    _run_ffmpeg_rewrite(file_path, args, "tagtmp", "ffmpeg metadata embedding failed")


def _embed_cover(file_path: Path, cover_source: str, failure_message: str) -> None:
    args = [
        "-i",
        cover_source,
        "-map_metadata",
        "0",
        "-map",
        "0:a:0",
        "-map",
        "1:v:0",
        "-c:a",
        "copy",
        "-c:v",
        "mjpeg",
        "-metadata:s:v:0",
        "title=Cover",
        "-metadata:s:v:0",
        "comment=Cover (front)",
        "-disposition:v:0",
        "attached_pic",
    ]
    _run_ffmpeg_rewrite(file_path, args, "covertmp", failure_message)


def embed_cover_art(file_path: Path, cover_image_path: Path) -> None:
    if not cover_image_path.exists():
        raise RuntimeError(f"Cover image not found: {cover_image_path}")
    _embed_cover(file_path, str(cover_image_path), "ffmpeg cover art embedding failed")


def embed_cover_art_from_url(file_path: Path, cover_image_url: str) -> None:
    url = cover_image_url.strip()
    if not url:
        raise RuntimeError("Cover image URL is empty")
    _embed_cover(file_path, url, "ffmpeg cover art embedding from URL failed")
