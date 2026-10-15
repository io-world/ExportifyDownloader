#!/usr/bin/env python3
"""Download tracks from a missing-tracks report CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict

from ..core.downloader import REQUIRED_COLUMNS
from ..launcher.config import DEFAULTS, load_config, resolve_input_path
from ..launcher.runner import invoke_csv_download

OUTPUT_FOLDER_COLUMN = "output_folder"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download tracks from a missing-tracks report CSV."
    )
    parser.add_argument(
        "report_csv",
        type=Path,
        nargs="?",
        default=None,
        help="Playlist download report CSV created by tools/playlist_download_report.py.",
    )
    parser.add_argument(
        "--config-path",
        default="./downloader.config.json",
        help="Path to downloader JSON config (default: ./downloader.config.json).",
    )
    return parser.parse_args()


def validate_report(report_path: Path) -> int:
    try:
        with report_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise RuntimeError(f"CSV appears empty or invalid: {report_path}")

            missing_columns = [
                column
                for column in [*REQUIRED_COLUMNS, OUTPUT_FOLDER_COLUMN]
                if column not in reader.fieldnames
            ]
            if missing_columns:
                raise RuntimeError(
                    "Missing required report CSV columns: " + ", ".join(missing_columns)
                )
            return sum(1 for _ in reader)
    except (OSError, csv.Error) as exc:
        raise RuntimeError(f"Could not read report CSV {report_path}: {exc}") from exc


def main(default_report_csv: Path | None = None) -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parents[2]
    if args.report_csv is not None:
        report_path = resolve_input_path(script_dir, str(args.report_csv))
    elif default_report_csv is not None:
        report_path = resolve_input_path(script_dir, str(default_report_csv))
    else:
        report_directory = script_dir / "run_logs"
        reports = sorted(
            report_directory.glob("playlist_download_report_*.csv"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not reports:
            print(
                "No report CSV specified and no playlist_download_report_*.csv files found in "
                f"{report_directory}",
                file=sys.stderr,
            )
            return 1
        report_path = reports[0].resolve()

    if not report_path.is_file():
        print(f"Report CSV not found: {report_path}", file=sys.stderr)
        return 1

    try:
        row_count = validate_report(report_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if row_count == 0:
        print(f"No tracks to download in report: {report_path}")
        return 0

    config_path = resolve_input_path(script_dir, args.config_path)
    try:
        config = load_config(config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    settings: Dict[str, Any] = dict(DEFAULTS)
    for key in settings:
        if key in config:
            settings[key] = config[key]

    default_cookies_path = (script_dir / "music youtube cookies.txt").resolve()
    if not str(settings.get("CookiesFromBrowser", "")).strip() and not str(
        settings.get("CookiesFile", "")
    ).strip():
        if default_cookies_path.exists():
            settings["CookiesFile"] = str(default_cookies_path)

    try:
        return invoke_csv_download(script_dir, report_path, settings, 1, 1)
    except (OSError, RuntimeError) as exc:
        print(f"Could not start missing-track downloads: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
