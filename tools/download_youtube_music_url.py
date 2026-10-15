#!/usr/bin/env python3
"""Download one YouTube Music track URL using launcher config defaults."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exportify_downloader.core.metadata import embed_audio_metadata, embed_cover_art_from_url
from exportify_downloader.core.utils import stable_base_name
from exportify_downloader.core.yt_dlp_interface import (
    best_thumbnail_url,
    download_audio,
    resolve_downloaded_file,
)
from exportify_downloader.launcher.config import (
    DEFAULT_CONFIG_PATH,
    load_settings,
    resolve_input_path,
    ydl_kwargs_from_settings,
)


# Set this to a YouTube Music URL if you prefer running the script without passing a URL arg.
DEFAULT_URL = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download one YouTube Music URL using downloader.config.json defaults."
    )
    parser.add_argument("url", nargs="?", default="", help="YouTube or YouTube Music track URL.")
    parser.add_argument(
        "--config-path",
        default=DEFAULT_CONFIG_PATH,
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


def main() -> int:
    args = parse_args()

    url = args.url.strip() or DEFAULT_URL.strip()
    if not url:
        print("URL is required. Pass it as an argument or set DEFAULT_URL in this script.", file=sys.stderr)
        return 1

    try:
        settings = load_settings(REPO_ROOT, args.config_path)
        if args.cookies_from_browser is not None:
            settings["CookiesFromBrowser"] = args.cookies_from_browser
        if args.cookies_file is not None:
            settings["CookiesFile"] = args.cookies_file
        ydl_kwargs = ydl_kwargs_from_settings(REPO_ROOT, settings)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = resolve_input_path(REPO_ROOT, args.output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download under a temporary id-based name, then rename from the same request's metadata,
    # so the track is only fetched from YouTube once.
    temp_stem = "_url_download_%(id)s"
    output_template = str(output_dir / f"{temp_stem}.%(ext)s")

    print("Downloading...")
    print(f"  URL: {url}")
    print(f"  Output folder: {output_dir}")

    try:
        saved_file, info = download_audio(url=url, output_template=output_template, **ydl_kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    if saved_file is None and info.get("id"):
        saved_file = resolve_downloaded_file(output_dir, f"_url_download_{info['id']}")
    if saved_file is None:
        print("Download finished but output file was not found.", file=sys.stderr)
        return 1

    if args.filename.strip():
        base_name = args.filename.strip()
    else:
        title = str(info.get("track") or info.get("title") or "Track").strip() or "Track"
        artist = str(info.get("artist") or info.get("uploader") or "Unknown Artist").strip() or "Unknown Artist"
        base_name = stable_base_name(artist, title)
    final_file = saved_file.with_name(f"{base_name}{saved_file.suffix}")
    saved_file = saved_file.replace(final_file)

    try:
        metadata = build_metadata(info)
        if metadata:
            embed_audio_metadata(saved_file, metadata)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: metadata embed failed: {exc}", file=sys.stderr)

    thumbnail_url = best_thumbnail_url(info)
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
