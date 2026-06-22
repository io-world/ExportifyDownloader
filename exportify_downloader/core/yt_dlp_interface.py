#!/usr/bin/env python3
"""yt-dlp interface for searching and downloading."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .utils import parse_rate_limit

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".aac", ".flac", ".wav", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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
    options.update(
        {
            "playlistend": limit,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
    )

    try:
        with YoutubeDL(options) as ydl:
            payload = ydl.extract_info(search_url, download=False)
    except DownloadError as exc:
        raise RuntimeError(str(exc).strip() or "yt-dlp search failed") from exc

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
) -> Optional[Path]:
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
            "writethumbnail": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "paths": {"home": str(output_path.parent)},
            "outtmpl": {"default": output_path.name},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                },
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": "jpg",
                },
            ],
        }
    )

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            final_path = Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise RuntimeError(str(exc).strip() or "yt-dlp download failed") from exc

    if final_path.suffix.lower() != ".mp3":
        mp3_path = final_path.with_suffix(".mp3")
        if mp3_path.exists():
            return mp3_path
    if final_path.exists():
        return final_path
    return None


def download_thumbnail(
    url: str,
    output_template: str,
    cookies_from_browser: str = "",
    cookies_file: Optional[Path] = None,
    sleep_requests: float = 0.0,
    limit_rate: str = "",
    throttled_rate: str = "",
    sleep_interval: float = 0.0,
    max_sleep_interval: float = 0.0,
) -> Optional[Path]:
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
            "noplaylist": True,
            "skip_download": True,
            "writethumbnail": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "paths": {"home": str(output_path.parent)},
            "outtmpl": {"default": output_path.name},
            "postprocessors": [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": "jpg",
                }
            ],
        }
    )

    try:
        with YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise RuntimeError(str(exc).strip() or "yt-dlp thumbnail download failed") from exc

    return resolve_thumbnail_file(output_path.parent, output_path.stem)


def resolve_downloaded_file(output_dir: Path, base_name: str) -> Optional[Path]:
    files = sorted(
        [
            path
            for path in output_dir.glob(f"{base_name}.*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def resolve_thumbnail_file(output_dir: Path, base_name: str) -> Optional[Path]:
    files = sorted(
        [
            path
            for path in output_dir.glob(f"{base_name}.*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None
