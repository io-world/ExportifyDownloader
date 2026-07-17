#!/usr/bin/env python3
"""Download one YouTube Music track URL using launcher config defaults."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from exportify_downloader.core.metadata import embed_audio_metadata, embed_cover_art_from_url
from exportify_downloader.core.utils import stable_base_name
from exportify_downloader.core.yt_dlp_interface import (
    build_ydl_options,
    download_audio,
    resolve_downloaded_file,
)
from exportify_downloader.launcher.config import DEFAULTS, load_config, resolve_input_path


# Set this to a YouTube Music URL if you prefer running the script without passing a URL arg.
DEFAULT_URL = "https://music.youtube.com/watch?v=hcGO5p4gQ-k"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download one YouTube Music URL using downloader.config.json defaults."
    )
    parser.add_argument("url", nargs="?", default="", help="YouTube or YouTube Music track URL.")
    parser.add_argument(
        "--config-path",
        default="./downloader.config.json",
        help="Path to JSON config file (default: ./downloader.config.json).",
    )
    parser.add_argument(
        "--output-folder",
        default="./tools/url_downloads",
        help="Output folder for downloaded songs (default: ./tools/url_downloads).",
    )
    parser.add_argument(
        "--filename",
        default="",
        help="Optional custom filename stem (without extension).",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="Override config CookiesFromBrowser value.",
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="Override config CookiesFile value.",
    )
    return parser.parse_args()


def choose_thumbnail_url(info: Dict[str, Any]) -> str:
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
        score = 0
        if isinstance(width, int):
            score += width
        if isinstance(height, int):
            score += height

        if score >= best_size:
            best_size = score
            best_url = candidate_url.strip()

    return best_url


def clean_date(raw_date: str) -> str:
    if not raw_date:
        return ""
    if re.fullmatch(r"\d{8}", raw_date):
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return raw_date


def build_metadata(info: Dict[str, Any]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}

    title = str(info.get("track") or info.get("title") or "").strip()
    artist = str(info.get("artist") or info.get("uploader") or info.get("channel") or "").strip()
    album = str(info.get("album") or "").strip()
    release_date = clean_date(str(info.get("release_date") or info.get("upload_date") or "").strip())

    if title:
        metadata["title"] = title
    if artist:
        metadata["artist"] = artist
    if album:
        metadata["album"] = album
    if release_date:
        metadata["date"] = release_date

    return metadata


def fetch_info(
    url: str,
    cookies_from_browser: str,
    cookies_file: Optional[Path],
    sleep_requests: float,
    limit_rate: str,
    throttled_rate: str,
    sleep_interval: float,
    max_sleep_interval: float,
) -> Dict[str, Any]:
    options = build_ydl_options(
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        sleep_requests=sleep_requests,
        limit_rate=limit_rate,
        throttled_rate=throttled_rate,
        sleep_interval=sleep_interval,
        max_sleep_interval=max_sleep_interval,
    )
    options.update(
        {
            "noplaylist": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
    )

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        message = str(exc).strip() or "yt-dlp metadata lookup failed"
        raise RuntimeError(message) from exc

    if not isinstance(info, dict):
        raise RuntimeError("Could not read metadata for URL")

    return info


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parents[1]
    config_path = resolve_input_path(script_dir, args.config_path)

    try:
        config = load_config(config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    settings = dict(DEFAULTS)
    for key in settings:
        if key in config:
            settings[key] = config[key]

    if args.cookies_from_browser is not None:
        settings["CookiesFromBrowser"] = args.cookies_from_browser
    if args.cookies_file is not None:
        settings["CookiesFile"] = args.cookies_file

    cookies_from_browser = str(settings.get("CookiesFromBrowser", "") or "").strip()
    cookies_file_value = str(settings.get("CookiesFile", "") or "").strip()
    cookies_file: Optional[Path] = None
    if cookies_file_value:
        cookies_file = resolve_input_path(script_dir, cookies_file_value)
        if not cookies_file.exists():
            print(f"Cookies file not found: {cookies_file}", file=sys.stderr)
            return 1

    if not cookies_from_browser and cookies_file is None:
        default_cookies_file = (script_dir / "music youtube cookies.txt").resolve()
        if default_cookies_file.exists():
            cookies_file = default_cookies_file

    output_dir = resolve_input_path(script_dir, args.output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = args.url.strip() or DEFAULT_URL.strip()
    if not url:
        print("URL is required. Pass it as an argument or set DEFAULT_URL in this script.", file=sys.stderr)
        return 1

    sleep_requests = float(settings.get("SleepRequests", 1.0) or 1.0)
    limit_rate = str(settings.get("LimitRate", "") or "").strip()
    throttled_rate = str(settings.get("ThrottledRate", "") or "").strip()
    sleep_interval = float(settings.get("SleepInterval", 0.0) or 0.0)
    max_sleep_interval = float(settings.get("MaxSleepInterval", 0.0) or 0.0)

    try:
        info = fetch_info(
            url=url,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            sleep_requests=sleep_requests,
            limit_rate=limit_rate,
            throttled_rate=throttled_rate,
            sleep_interval=sleep_interval,
            max_sleep_interval=max_sleep_interval,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Metadata lookup failed: {exc}", file=sys.stderr)
        return 1

    title = str(info.get("track") or info.get("title") or "Track").strip() or "Track"
    artist = str(info.get("artist") or info.get("uploader") or "Unknown Artist").strip() or "Unknown Artist"

    if args.filename.strip():
        base_name = args.filename.strip()
    else:
        base_name = stable_base_name(artist, title)

    output_template = str(output_dir / f"{base_name}.%(ext)s")

    print("Downloading...")
    print(f"  URL: {url}")
    print(f"  Output folder: {output_dir}")

    try:
        saved_file = download_audio(
            url=url,
            output_template=output_template,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            sleep_requests=sleep_requests,
            limit_rate=limit_rate,
            throttled_rate=throttled_rate,
            sleep_interval=sleep_interval,
            max_sleep_interval=max_sleep_interval,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    if saved_file is None:
        saved_file = resolve_downloaded_file(output_dir, base_name)
    if saved_file is None:
        print("Download finished but output file was not found.", file=sys.stderr)
        return 1

    try:
        metadata = build_metadata(info)
        if metadata:
            embed_audio_metadata(saved_file, metadata)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: metadata embed failed: {exc}", file=sys.stderr)

    thumbnail_url = choose_thumbnail_url(info)
    if thumbnail_url:
        try:
            embed_cover_art_from_url(saved_file, thumbnail_url)
            print("Artwork embedded.")
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: artwork embed failed: {exc}", file=sys.stderr)
    else:
        print("Warning: no thumbnail URL found for artwork embedding.", file=sys.stderr)

    print(f"Saved: {saved_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
