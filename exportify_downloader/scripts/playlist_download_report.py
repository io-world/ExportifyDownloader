#!/usr/bin/env python3
"""Report playlist download state and export rows whose audio is missing."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Counter as CounterType, Dict, Iterable, List, Tuple

from ..core.csv_work_state import (
    OUTPUT_FOLDER_COLUMN,
    STATUS_DOWNLOADED,
    STATUS_ERROR,
    STATUS_RESOLVED,
    STATUS_RETRY,
    STATUS_UNRESOLVED,
    playlist_stem,
    read_csv,
    work_csv_path_for,
    write_csv,
)

DOWNLOAD_STATUS_COLUMN = "download_status"
OUTPUT_FILE_COLUMN = "output_file"
BLANK_STATUS = "blank"
KNOWN_STATUS_ORDER = [
    BLANK_STATUS,
    STATUS_RESOLVED,
    STATUS_DOWNLOADED,
    STATUS_UNRESOLVED,
    STATUS_ERROR,
    STATUS_RETRY,
]


@dataclass
class CsvCompletionReport:
    csv_path: Path
    total_rows: int
    completed_rows: int
    downloaded_rows: int
    missing_file_rows: int
    status_counts: CounterType[str]

    @property
    def pending_rows(self) -> int:
        return self.total_rows - self.completed_rows

    @property
    def is_complete(self) -> bool:
        return self.total_rows > 0 and self.completed_rows == self.total_rows

    @property
    def completion_percent(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return (self.completed_rows / self.total_rows) * 100.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize download status across playlist CSVs and export tracks "
            "whose audio file is missing."
        )
    )
    parser.add_argument(
        "folder_path",
        type=Path,
        nargs="?",
        default=Path("./exportify.app"),
        help="Folder containing playlist CSV files (default: ./exportify.app).",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Output CSV path (default: run_logs/playlist_download_report_<timestamp>.csv).",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Include CSV files that contain zero data rows in the summary.",
    )
    return parser.parse_args()


def row_has_downloaded_file(row: Dict[str, str]) -> bool:
    status = (row.get(DOWNLOAD_STATUS_COLUMN) or "").strip().lower()
    output_file = (row.get(OUTPUT_FILE_COLUMN) or "").strip()
    return status == STATUS_DOWNLOADED and bool(output_file) and Path(output_file).exists()


def discover_csv_paths(folder_path: Path) -> List[Path]:
    source_candidates = sorted(
        [
            path.resolve()
            for path in folder_path.glob("*.csv")
            if path.is_file() and not path.stem.lower().endswith("_work")
        ],
        key=lambda path: path.name.lower(),
    )
    work_candidates = sorted(
        [
            path.resolve()
            for path in folder_path.glob("*.csv")
            if path.is_file() and path.stem.lower().endswith("_work")
        ],
        key=lambda path: path.name.lower(),
    )

    if source_candidates:
        return [
            work_csv_path_for(source_path).resolve()
            if work_csv_path_for(source_path).exists()
            else source_path
            for source_path in source_candidates
        ]
    return work_candidates


def count_completed_rows(csv_path: Path) -> CsvCompletionReport:
    fieldnames, rows = read_csv(csv_path)
    if not fieldnames:
        raise RuntimeError(f"CSV appears empty or invalid: {csv_path}")

    completed_rows = 0
    downloaded_rows = 0
    missing_file_rows = 0
    status_counts: CounterType[str] = Counter()
    for row in rows:
        status = (row.get(DOWNLOAD_STATUS_COLUMN) or "").strip().lower()
        status_counts[status or BLANK_STATUS] += 1
        if status != STATUS_DOWNLOADED:
            continue

        downloaded_rows += 1
        output_file = (row.get(OUTPUT_FILE_COLUMN) or "").strip()
        if output_file and Path(output_file).exists():
            completed_rows += 1
        else:
            missing_file_rows += 1

    return CsvCompletionReport(
        csv_path=csv_path,
        total_rows=len(rows),
        completed_rows=completed_rows,
        downloaded_rows=downloaded_rows,
        missing_file_rows=missing_file_rows,
        status_counts=status_counts,
    )


def format_status_counts(status_counts: CounterType[str]) -> str:
    ordered_parts = [
        f"{status_name}={status_counts.get(status_name, 0)}"
        for status_name in KNOWN_STATUS_ORDER
    ]
    extra_statuses = sorted(name for name in status_counts if name not in KNOWN_STATUS_ORDER)
    ordered_parts.extend(f"{status_name}={status_counts[status_name]}" for status_name in extra_statuses)
    return " ".join(ordered_parts)


def collect_missing_rows(csv_paths: List[Path]) -> Tuple[List[str], List[Dict[str, str]]]:
    fieldnames: List[str] = []
    missing_rows: List[Dict[str, str]] = []

    for csv_path in csv_paths:
        csv_fieldnames, rows = read_csv(csv_path)
        for name in csv_fieldnames:
            if name not in fieldnames:
                fieldnames.append(name)

        target_folder = str((csv_path.parent / playlist_stem(csv_path)).resolve())
        for row in rows:
            normalized_row = {key: value or "" for key, value in row.items()}
            if row_has_downloaded_file(normalized_row):
                continue

            normalized_row[OUTPUT_FOLDER_COLUMN] = target_folder
            if (normalized_row.get(DOWNLOAD_STATUS_COLUMN) or "").strip().lower() == STATUS_ERROR:
                normalized_row[DOWNLOAD_STATUS_COLUMN] = ""
                if "error_message" in normalized_row:
                    normalized_row["error_message"] = ""
            missing_rows.append(normalized_row)

    if OUTPUT_FOLDER_COLUMN not in fieldnames:
        fieldnames.append(OUTPUT_FOLDER_COLUMN)
    return fieldnames, missing_rows


def render_summary(csv_paths: List[Path], csv_out: Path, include_empty: bool) -> int:
    reports = []
    for csv_path in csv_paths:
        try:
            report = count_completed_rows(csv_path)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if report.total_rows == 0 and not include_empty:
            continue
        reports.append(report)

    if not reports:
        print("No CSV files found." if not csv_paths else "No non-empty CSV files found.")
        return 0

    total_rows = sum(report.total_rows for report in reports)
    completed_rows = sum(report.completed_rows for report in reports)
    downloaded_rows = sum(report.downloaded_rows for report in reports)
    missing_file_rows = sum(report.missing_file_rows for report in reports)
    fully_complete_csvs = sum(1 for report in reports if report.is_complete)

    combined_status_counts: Counter[str] = Counter()
    for report in reports:
        combined_status_counts.update(report.status_counts)

    print(f"Folder download report: {reports[0].csv_path.parent}")
    print(
        "Summary: "
        f"csv_files={len(reports)} "
        f"fully_complete_csvs={fully_complete_csvs} "
        f"completed_rows={completed_rows}/{total_rows} "
        f"downloaded_status_rows={downloaded_rows} "
        f"missing_files={missing_file_rows}"
    )
    print(f"Statuses: {format_status_counts(combined_status_counts)}")
    print("")

    for report in reports:
        print(
            f"{playlist_stem(report.csv_path)}: "
            f"completed={report.completed_rows}/{report.total_rows} "
            f"pending={report.pending_rows} "
            f"downloaded_status={report.downloaded_rows} "
            f"missing_files={report.missing_file_rows} "
            f"percent={report.completion_percent:.1f}%"
        )
        print(f"  statuses: {format_status_counts(report.status_counts)}")

    try:
        fieldnames, missing_rows = collect_missing_rows([report.csv_path for report in reports])
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(csv_out, fieldnames, missing_rows)
    print("")
    print(f"Tracks needing download: {len(missing_rows)}")
    print(f"Playlist download report CSV: {csv_out.resolve()}")
    return 0


def main() -> int:
    args = parse_args()
    folder_path = args.folder_path.resolve()
    if not folder_path.exists() or not folder_path.is_dir():
        print(f"CSV folder not found: {folder_path}", file=sys.stderr)
        return 1

    csv_paths = discover_csv_paths(folder_path)
    if not csv_paths:
        print(f"No CSV files found in folder: {folder_path}")
        return 0

    if args.csv_out is None:
        repo_root = Path(__file__).resolve().parents[2]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_out = repo_root / "run_logs" / f"playlist_download_report_{timestamp}.csv"
    else:
        csv_out = args.csv_out.resolve()

    try:
        return render_summary(csv_paths, csv_out, args.include_empty)
    except OSError as exc:
        print(f"Could not write playlist download report CSV: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
