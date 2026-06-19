#!/usr/bin/env python3
"""CLI and configuration helpers for the launcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "CsvPath": "",
    "CsvFolder": "./exportify.app",
    "DurationTolerance": 10,
    "SearchResults": 6,
    "ForceRedownload": False,
    "Limit": 0,
    "SleepRequests": 1.0,
    "LimitRate": "",
    "ThrottledRate": "",
    "SleepInterval": 0.0,
    "MaxSleepInterval": 0.0,
    "IdOrder": "default",
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
        choices=["default", "ascending", "descending"],
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


def merged_settings(args: argparse.Namespace, config: Dict[str, Any]) -> Dict[str, Any]:
    settings: Dict[str, Any] = dict(DEFAULTS)

    arg_map = {
        "CsvPath": args.csv_path,
        "CsvFolder": args.csv_folder,
        "DurationTolerance": args.duration_tolerance,
        "SearchResults": args.search_results,
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

    for key in settings:
        if key in config:
            settings[key] = config[key]

    for key, value in arg_map.items():
        if value is not None:
            settings[key] = value

    return settings


def resolve_input_path(script_dir: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = script_dir / candidate
    return candidate.resolve()
