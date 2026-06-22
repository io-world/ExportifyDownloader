#!/usr/bin/env python3
"""Utility helpers for the downloader."""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from yt_dlp.utils import parse_bytes


def log(message: str) -> None:
    print(message, flush=True)


def shorten_error_message(value: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    return compact if len(compact) <= limit else compact[: limit - 3].rstrip() + "..."


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


def parse_rate_limit(value: str, option_name: str) -> Optional[int]:
    if not value:
        return None
    parsed = parse_bytes(value)
    if parsed is None or parsed <= 0:
        raise ValueError(f"Invalid {option_name} value: {value}")
    return int(parsed)


def classify_download_error(message: str) -> str:
    lowered = message.lower()
    patterns = (
        "rate-limited by youtube",
        "the current session has been rate-limited",
        "try again later",
        "too many requests",
        "http error 429",
        "status code 429",
        "retry after",
    )
    return "rate_limit" if any(pattern in lowered for pattern in patterns) else ""


def clean_meta_value(value: str) -> str:
    return value.replace("\x00", "").strip()


def extract_spotify_track_id(track_uri: str) -> str:
    value = clean_meta_value(track_uri)
    if not value:
        return ""
    match = re.search(r"track[:/](?P<id>[A-Za-z0-9]+)", value)
    return match.group("id") if match else ""
