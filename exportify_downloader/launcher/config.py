#!/usr/bin/env python3
"""CLI and configuration helpers for the launcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG_PATH = "./downloader.config.json"
DEFAULT_COOKIES_FILENAME = "music youtube cookies.txt"

DEFAULTS: Dict[str, Any] = {
    "CsvPath": "",
    "CsvFolder": "./exportify.app",
    "DurationTolerance": 10,
    "SearchResults": 6,
    "DownloadEnabled": True,
    "ForceRedownload": False,
    "Limit": 0,
    "SleepRequests": 1.0,
    "LimitRate": "",
    "ThrottledRate": "",
    "SleepInterval": 0.0,
    "MaxSleepInterval": 0.0,
    "IdOrder": "priority",
    "CookiesFromBrowser": "",
    "CookiesFile": "",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run playlist downloads for one CSV or a CSV folder.")
    parser.add_argument("--config-path", "--ConfigPath", default=None, help="Path to config JSON.")
    parser.add_argument("--csv-path", "--CsvPath", default=None, help="Single CSV file to process.")
    parser.add_argument("--csv-folder", "--CsvFolder", default=None, help="Folder containing CSV files.")
    parser.add_argument("--duration-tolerance", "--DurationTolerance", type=int, default=None)
    parser.add_argument("--search-results", "--SearchResults", type=int, default=None)
    parser.add_argument("--download-enabled", "--DownloadEnabled", action="store_true", default=None, dest="download_enabled")
    parser.add_argument("--resolve-only", action="store_false", dest="download_enabled")
    parser.add_argument("--force-redownload", "--ForceRedownload", action="store_true", default=None)
    parser.add_argument("--limit", "--Limit", type=int, default=None)
    parser.add_argument("--sleep-requests", "--SleepRequests", type=float, default=None)
    parser.add_argument("--limit-rate", "--LimitRate", default=None)
    parser.add_argument("--throttled-rate", "--ThrottledRate", default=None)
    parser.add_argument("--sleep-interval", "--SleepInterval", type=float, default=None)
    parser.add_argument("--max-sleep-interval", "--MaxSleepInterval", type=float, default=None)
    parser.add_argument(
        "--id-order",
        "--IdOrder",
        choices=["default", "priority", "ascending", "descending"],
        default=None,
        dest="id_order",
    )
    parser.add_argument("--cookies-from-browser", "--CookiesFromBrowser", default=None)
    parser.add_argument("--cookies-file", "--CookiesFile", default=None)
    return parser


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid config JSON at {config_path}. {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid config JSON at {config_path}. Expected top-level object.")
    return payload


def settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """DEFAULTS overlaid with any known keys from the config file."""
    settings: Dict[str, Any] = dict(DEFAULTS)
    for key in settings:
        if key in config:
            settings[key] = config[key]
    return settings


def apply_default_cookies(settings: Dict[str, Any], script_dir: Path) -> None:
    """Use the repo's cookies file when no cookie source is configured."""
    if str(settings.get("CookiesFromBrowser") or "").strip() or str(settings.get("CookiesFile") or "").strip():
        return
    default_cookies_path = (script_dir / DEFAULT_COOKIES_FILENAME).resolve()
    if default_cookies_path.exists():
        settings["CookiesFile"] = str(default_cookies_path)


def resolve_cookies_file(script_dir: Path, settings: Dict[str, Any]) -> Optional[Path]:
    """Resolved CookiesFile path, or None when unset. Raises RuntimeError if it doesn't exist."""
    value = str(settings.get("CookiesFile") or "").strip()
    if not value:
        return None
    path = resolve_input_path(script_dir, value)
    if not path.exists():
        raise RuntimeError(f"Cookies file not found: {path}")
    return path


def _setting_float(settings: Dict[str, Any], key: str) -> float:
    value = settings.get(key)
    if value is None or str(value).strip() == "":
        return float(DEFAULTS[key])
    return float(value)


def ydl_kwargs_from_settings(script_dir: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Keyword arguments for the yt_dlp_interface helpers. Raises RuntimeError for a missing cookies file."""
    return {
        "cookies_from_browser": str(settings.get("CookiesFromBrowser") or "").strip(),
        "cookies_file": resolve_cookies_file(script_dir, settings),
        "sleep_requests": _setting_float(settings, "SleepRequests"),
        "limit_rate": str(settings.get("LimitRate") or "").strip(),
        "throttled_rate": str(settings.get("ThrottledRate") or "").strip(),
        "sleep_interval": _setting_float(settings, "SleepInterval"),
        "max_sleep_interval": _setting_float(settings, "MaxSleepInterval"),
    }


def load_settings(script_dir: Path, config_path_value: str) -> Dict[str, Any]:
    """Load the config file into settings and apply the default cookies file. Raises RuntimeError."""
    config = load_config(resolve_input_path(script_dir, config_path_value))
    settings = settings_from_config(config)
    apply_default_cookies(settings, script_dir)
    return settings


def merged_settings(args: argparse.Namespace, config: Dict[str, Any]) -> Dict[str, Any]:
    settings = settings_from_config(config)

    arg_map = {
        "CsvPath": args.csv_path,
        "CsvFolder": args.csv_folder,
        "DurationTolerance": args.duration_tolerance,
        "SearchResults": args.search_results,
        "DownloadEnabled": args.download_enabled,
        "ForceRedownload": args.force_redownload,
        "Limit": args.limit,
        "SleepRequests": args.sleep_requests,
        "LimitRate": args.limit_rate,
        "ThrottledRate": args.throttled_rate,
        "SleepInterval": args.sleep_interval,
        "MaxSleepInterval": args.max_sleep_interval,
        "IdOrder": args.id_order,
        "CookiesFromBrowser": args.cookies_from_browser,
        "CookiesFile": args.cookies_file,
    }

    for key, value in arg_map.items():
        if value is not None:
            settings[key] = value

    return settings


def resolve_input_path(script_dir: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = script_dir / candidate
    return candidate.resolve()
