#!/usr/bin/env python3
"""yt-dlp interface for searching and downloading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, NoReturn, Optional, Tuple
from urllib.parse import quote_plus

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .utils import classify_download_error, parse_rate_limit

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

EXTRACTOR_ARGS = {"youtube": {"player_client": ["android", "web"]}}


class RateLimitError(RuntimeError):
    pass


class TransientError(RuntimeError):
    """Network or server failure unrelated to the track; safe to retry later."""


def raise_download_error(exc: DownloadError, fallback_message: str) -> NoReturn:
    message = str(exc).strip() or fallback_message
    kind = classify_download_error(message)
    if kind == "rate_limit":
        raise RateLimitError(message) from exc
    if kind == "transient":
        raise TransientError(message) from exc
    raise RuntimeError(message) from exc


def build_ydl_options(
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> Dict[str, object]:
    options: Dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": EXTRACTOR_ARGS,
    }

    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser, None, None, None)
    if cookies_file is not None:
        options["cookiefile"] = str(cookies_file)

    if sleep_requests > 0:
        options["sleep_requests"] = sleep_requests
    if sleep_interval > 0:
        options["sleep_interval"] = sleep_interval
    if max_sleep_interval > 0:
        options["max_sleep_interval"] = max_sleep_interval

    limit_rate_bps = parse_rate_limit(limit_rate, "--limit-rate")
    if limit_rate_bps is not None:
        options["ratelimit"] = limit_rate_bps

    throttled_rate_bps = parse_rate_limit(throttled_rate, "--throttled-rate")
    if throttled_rate_bps is not None:
        options["throttledratelimit"] = throttled_rate_bps

    return options


def run_yt_dlp_json(
    query: str,
    limit: int,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> List[Dict[str, object]]:
    search_url = f"https://music.youtube.com/search?q={quote_plus(query)}"
    options = build_ydl_options(
        cookies_from_browser,
        cookies_file,
        sleep_requests,
        limit_rate,
        throttled_rate,
        sleep_interval,
        max_sleep_interval,
    )
    options["playlistend"] = limit

    try:
        with YoutubeDL(options) as ydl:
            payload = ydl.extract_info(search_url, download=False)
    except DownloadError as exc:
        raise_download_error(exc, "yt-dlp search failed")

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


def download_audio(
    url: str,
    output_template: str,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Download and convert to mp3. Returns (saved file or None, yt-dlp info dict)."""
    output_path = Path(output_template)
    options = build_ydl_options(
        cookies_from_browser,
        cookies_file,
        sleep_requests,
        limit_rate,
        throttled_rate,
        sleep_interval,
        max_sleep_interval,
    )
    options.update(
        {
            "format": "bestaudio/best",
            "noplaylist": True,
            "paths": {"home": str(output_path.parent)},
            "outtmpl": {"default": output_path.name},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                },
            ],
        }
    )

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            final_path = Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise_download_error(exc, "yt-dlp download failed")

    info = info if isinstance(info, dict) else {}
    if final_path.suffix.lower() != ".mp3":
        mp3_path = final_path.with_suffix(".mp3")
        if mp3_path.exists():
            return mp3_path, info
    if final_path.exists():
        return final_path, info
    return None, info


def fetch_info(
    url: str,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> Dict[str, Any]:
    options = build_ydl_options(
        cookies_from_browser,
        cookies_file,
        sleep_requests,
        limit_rate,
        throttled_rate,
        sleep_interval,
        max_sleep_interval,
    )
    options["noplaylist"] = True

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise_download_error(exc, "yt-dlp metadata lookup failed")

    if not isinstance(info, dict):
        raise RuntimeError("Could not read metadata for URL")
    return info


def find_file_by_stem(output_dir: Path, base_name: str, extensions: Iterable[str]) -> Optional[Path]:
    """Newest file named exactly <base_name><ext>. Avoids glob so names with [ ] match literally."""
    wanted = base_name.casefold()
    allowed = set(extensions)
    if not output_dir.is_dir():
        return None
    files = [
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.lower() in allowed and path.stem.casefold() == wanted
    ]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def resolve_downloaded_file(output_dir: Path, base_name: str) -> Optional[Path]:
    return find_file_by_stem(output_dir, base_name, AUDIO_EXTENSIONS)


def resolve_thumbnail_file(output_dir: Path, base_name: str) -> Optional[Path]:
    return find_file_by_stem(output_dir, base_name, IMAGE_EXTENSIONS)


def best_thumbnail_url(info: Dict[str, Any]) -> str:
    thumbnail = info.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.strip():
        return thumbnail.strip()

    thumbnails = info.get("thumbnails")
    if not isinstance(thumbnails, list):
        return ""

    best_url = ""
    best_size = -1
    for item in thumbnails:
        if not isinstance(item, dict):
            continue
        candidate_url = item.get("url")
        if not isinstance(candidate_url, str) or not candidate_url.strip():
            continue
        width = item.get("width")
        height = item.get("height")
        score = (width if isinstance(width, int) else 0) + (height if isinstance(height, int) else 0)
        if score >= best_size:
            best_size = score
            best_url = candidate_url.strip()
    return best_url


def get_thumbnail_url(
    url: str,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> Optional[str]:
    info = fetch_info(
        url,
        cookies_from_browser,
        cookies_file,
        sleep_requests,
        limit_rate,
        throttled_rate,
        sleep_interval,
        max_sleep_interval,
    )
    return best_thumbnail_url(info) or None
