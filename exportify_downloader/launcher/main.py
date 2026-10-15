#!/usr/bin/env python3
"""Packaged launcher for playlist CSV downloads."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

from ..core.csv_work_state import prepare_work_csv
from ..core.downloader import EXIT_STOPPED_EARLY
from .config import (
    DEFAULT_CONFIG_PATH,
    apply_default_cookies,
    build_parser,
    load_config,
    merged_settings,
    resolve_cookies_file,
    resolve_input_path,
)
from .runner import invoke_csv_download


def is_work_csv(path: Path) -> bool:
    return path.stem.lower().endswith("_work")


def run_csv(script_dir: Path, csv_path: Path, settings: Dict[str, Any], current: int, total: int) -> int:
    target_csv = csv_path.resolve()
    if not is_work_csv(target_csv):
        target_csv = prepare_work_csv(target_csv)
    return int(invoke_csv_download(script_dir, target_csv, settings, current, total))


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parents[2]
    config_path = resolve_input_path(script_dir, args.config_path or DEFAULT_CONFIG_PATH)

    try:
        config = load_config(config_path)
        settings = merged_settings(args, config)
        apply_default_cookies(settings, script_dir)
        resolve_cookies_file(script_dir, settings)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    csv_path_value = str(settings.get("CsvPath", "")).strip()
    if csv_path_value:
        resolved_csv_path = resolve_input_path(script_dir, csv_path_value)
        if not resolved_csv_path.exists():
            print(f"CSV not found: {resolved_csv_path}", file=sys.stderr)
            return 1
        return run_csv(script_dir, resolved_csv_path, settings, 1, 1)

    csv_folder_raw = str(settings.get("CsvFolder", "")).strip() or "./exportify.app"
    resolved_folder = resolve_input_path(script_dir, csv_folder_raw)
    if resolved_folder.is_file():
        if resolved_folder.suffix.lower() != ".csv":
            print(f"CSV file not found: {resolved_folder}", file=sys.stderr)
            return 1
        return run_csv(script_dir, resolved_folder, settings, 1, 1)

    if not resolved_folder.is_dir():
        print(f"CSV folder not found: {resolved_folder}", file=sys.stderr)
        return 1

    all_csvs = sorted((p for p in resolved_folder.glob("*.csv") if p.is_file()), key=lambda p: p.name.lower())
    # Prefer source CSVs (each gets its _work.csv synced); fall back to bare work CSVs.
    csv_files = [p for p in all_csvs if not is_work_csv(p)] or [p for p in all_csvs if is_work_csv(p)]
    if not csv_files:
        print(f"No CSV files found in folder: {resolved_folder}")
        return 0

    succeeded = 0
    failed = 0
    stopped_early = False
    for index, csv_file in enumerate(csv_files, start=1):
        code = run_csv(script_dir, csv_file, settings, index, len(csv_files))
        if code == 0:
            succeeded += 1
        elif code == EXIT_STOPPED_EARLY:
            stopped_early = True
            print("Stopping batch: YouTube rate limit or network failure. Rerun later to continue.")
            break
        else:
            failed += 1

    print("")
    print("Batch scan complete")
    print(f"  CSV processed: {succeeded + failed + (1 if stopped_early else 0)}/{len(csv_files)}")
    print(f"  succeeded:     {succeeded}")
    print(f"  failed:        {failed}")
    if stopped_early:
        print("  stopped:       early (rate limit / network)")
        return EXIT_STOPPED_EARLY

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
