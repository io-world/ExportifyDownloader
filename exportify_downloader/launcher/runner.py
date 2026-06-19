#!/usr/bin/env python3
"""Downloader process invocation helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from .config import resolve_input_path


def invoke_csv_download(script_dir: Path, target_csv_path: Path, settings: Dict[str, Any], current: int, total: int) -> int:
    arguments: List[str] = [
        "-m",
        "exportify_downloader.core.downloader",
        str(target_csv_path),
        "--duration-tolerance",
        str(settings["DurationTolerance"]),
        "--search-results",
        str(settings["SearchResults"]),
        "--limit",
        str(settings["Limit"]),
        "--sleep-requests",
        str(settings["SleepRequests"]),
        "--sleep-interval",
        str(settings["SleepInterval"]),
        "--max-sleep-interval",
        str(settings["MaxSleepInterval"]),
        "--id-order",
        str(settings["IdOrder"]),
    ]

    if not settings["DownloadEnabled"]:
        arguments.append("--resolve-only")

    if settings["LimitRate"]:
        arguments.extend(["--limit-rate", str(settings["LimitRate"])])

    if settings["ThrottledRate"]:
        arguments.extend(["--throttled-rate", str(settings["ThrottledRate"])])

    if settings["ForceRedownload"]:
        arguments.append("--force-redownload")

    if settings["CookiesFromBrowser"]:
        arguments.extend(["--cookies-from-browser", str(settings["CookiesFromBrowser"])])

    cookies_file_value = str(settings["CookiesFile"]).strip() if settings["CookiesFile"] else ""
    if cookies_file_value:
        cookies_file_path = resolve_input_path(script_dir, cookies_file_value)
        if not cookies_file_path.exists():
            raise RuntimeError(f"Cookies file not found: {cookies_file_path}")
        arguments.extend(["--cookies-file", str(cookies_file_path)])

    csv_name = target_csv_path.name
    print("")
    if total > 0 and current > 0:
        print(f"[{current}/{total}] Starting: {csv_name}")
    else:
        print(f"Starting: {csv_name}")

    print(f"  CSV path: {target_csv_path}")
    print(
        "  Settings: "
        f"tolerance={settings['DurationTolerance']} "
        f"searchResults={settings['SearchResults']} "
        f"downloadEnabled={settings['DownloadEnabled']} "
        f"limit={settings['Limit']} "
        f"sleepRequests={settings['SleepRequests']} "
        f"sleepInterval={settings['SleepInterval']} "
        f"maxSleepInterval={settings['MaxSleepInterval']} "
        f"limitRate={settings['LimitRate']} "
        f"throttledRate={settings['ThrottledRate']} "
        f"idOrder={settings['IdOrder']} "
        f"forceRedownload={settings['ForceRedownload']}"
    )

    proc = subprocess.run([sys.executable, "-u", *arguments], check=False, cwd=script_dir)
    if proc.returncode == 0:
        print(f"Completed: {csv_name}")
        return 0

    print(f"Failed: {csv_name} (exit code {proc.returncode})")
    return int(proc.returncode)
