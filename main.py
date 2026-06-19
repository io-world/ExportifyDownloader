#!/usr/bin/env python3
"""Cross-platform launcher for playlist CSV downloads."""

from __future__ import annotations

import sys
from pathlib import Path
from csv_work_state import prepare_work_csv
from download_runner import invoke_csv_download
from launcher_config import build_parser, load_config, merged_settings, resolve_input_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    config_path_raw = args.config_path if args.config_path is not None else "./downloader.config.json"
    config_path = resolve_input_path(script_dir, config_path_raw)

    try:
        config = load_config(config_path)
        settings = merged_settings(args, config)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    default_cookies_path = (script_dir / "music youtube cookies.txt").resolve()
    if not str(settings.get("CookiesFromBrowser", "")).strip() and not str(settings.get("CookiesFile", "")).strip():
        if default_cookies_path.exists():
            settings["CookiesFile"] = str(default_cookies_path)

    csv_path_value = str(settings.get("CsvPath", "")).strip()
    if csv_path_value:
        resolved_csv_path = resolve_input_path(script_dir, csv_path_value)
        if not resolved_csv_path.exists():
            print(f"CSV not found: {resolved_csv_path}", file=sys.stderr)
            return 1
        target_csv = resolved_csv_path
        if not resolved_csv_path.stem.lower().endswith("_work"):
            target_csv = prepare_work_csv(resolved_csv_path)
        code = invoke_csv_download(script_dir, target_csv, settings, 1, 1)
        return int(code)

    csv_folder_raw = str(settings.get("CsvFolder", "")).strip() or "./exportify.app"
    resolved_folder = resolve_input_path(script_dir, csv_folder_raw)
    if not resolved_folder.exists() or not resolved_folder.is_dir():
        print(f"CSV folder not found: {resolved_folder}", file=sys.stderr)
        return 1

    csv_files = sorted(
        [p for p in resolved_folder.glob("*.csv") if p.is_file() and not p.stem.lower().endswith("_work")],
        key=lambda p: p.name.lower(),
    )
    if not csv_files:
        csv_files = sorted(
            [p for p in resolved_folder.glob("*.csv") if p.is_file() and p.stem.lower().endswith("_work")],
            key=lambda p: p.name.lower(),
        )
    if not csv_files:
        print(f"No CSV files found in folder: {resolved_folder}")
        return 0

    succeeded = 0
    failed = 0
    for index, csv_file in enumerate(csv_files, start=1):
        target_csv = csv_file.resolve()
        if not target_csv.stem.lower().endswith("_work"):
            target_csv = prepare_work_csv(target_csv)
        code = invoke_csv_download(script_dir, target_csv, settings, index, len(csv_files))
        if code == 0:
            succeeded += 1
        else:
            failed += 1

    print("")
    print("Batch scan complete")
    print(f"  CSV processed: {len(csv_files)}")
    print(f"  succeeded:     {succeeded}")
    print(f"  failed:        {failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
