#!/usr/bin/env python3
"""Report download completion across playlist CSV files in a folder."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Counter as CounterType, Iterable, List

from ..core.csv_work_state import playlist_stem, work_csv_path_for
from ..core.downloader import (
    STATUS_DOWNLOADED,
    STATUS_ERROR,
    STATUS_RESOLVED,
    STATUS_RETRY,
    STATUS_UNRESOLVED,
)

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
            "Report how many rows are fully downloaded across all playlist CSV files in a folder."
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
        "--include-empty",
        action="store_true",
        help="Include CSV files that contain zero data rows in the per-file report.",
    )
    return parser.parse_args()


def discover_csv_paths(folder_path: Path) -> List[Path]:
    source_candidates = sorted(
        [path.resolve() for path in folder_path.glob("*.csv") if path.is_file() and not path.stem.lower().endswith("_work")],
        key=lambda path: path.name.lower(),
    )
    work_candidates = sorted(
        [path.resolve() for path in folder_path.glob("*.csv") if path.is_file() and path.stem.lower().endswith("_work")],
        key=lambda path: path.name.lower(),
    )

    if source_candidates:
        preferred: List[Path] = []
        for source_path in source_candidates:
            work_path = work_csv_path_for(source_path)
            preferred.append(work_path.resolve() if work_path.exists() else source_path)
        return preferred

    return work_candidates


def count_completed_rows(csv_path: Path) -> CsvCompletionReport:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError(f"CSV appears empty or invalid: {csv_path}")

        total_rows = 0
        completed_rows = 0
        downloaded_rows = 0
        missing_file_rows = 0
        status_counts: CounterType[str] = Counter()

        for row in reader:
            total_rows += 1
            status = (row.get("download_status") or "").strip().lower()
            status_key = status or BLANK_STATUS
            status_counts[status_key] += 1
            if status != STATUS_DOWNLOADED:
                continue

            downloaded_rows += 1
            output_file = (row.get("output_file") or "").strip()
            if output_file and Path(output_file).exists():
                completed_rows += 1
                continue

            missing_file_rows += 1

    return CsvCompletionReport(
        csv_path=csv_path,
        total_rows=total_rows,
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


def render_report(reports: Iterable[CsvCompletionReport]) -> None:
    report_list = list(reports)
    if not report_list:
        print("No CSV files found.")
        return

    complete_csvs = sum(1 for report in report_list if report.is_complete)
    total_rows = sum(report.total_rows for report in report_list)
    completed_rows = sum(report.completed_rows for report in report_list)
    downloaded_rows = sum(report.downloaded_rows for report in report_list)
    missing_file_rows = sum(report.missing_file_rows for report in report_list)
    folder_status_counts: CounterType[str] = Counter()
    for report in report_list:
        folder_status_counts.update(report.status_counts)

    print(f"Folder completion report: {report_list[0].csv_path.parent}")
    print(
        "Summary: "
        f"csv_files={len(report_list)} "
        f"fully_complete_csvs={complete_csvs} "
        f"completed_rows={completed_rows}/{total_rows} "
        f"downloaded_status_rows={downloaded_rows} "
        f"missing_files={missing_file_rows}"
    )
    print(f"Statuses: {format_status_counts(folder_status_counts)}")
    print("")

    for report in report_list:
        print(
            f"{playlist_stem(report.csv_path)}: "
            f"completed={report.completed_rows}/{report.total_rows} "
            f"pending={report.pending_rows} "
            f"downloaded_status={report.downloaded_rows} "
            f"missing_files={report.missing_file_rows} "
            f"percent={report.completion_percent:.1f}%"
        )
        print(f"  statuses: {format_status_counts(report.status_counts)}")


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

    reports: List[CsvCompletionReport] = []
    for csv_path in csv_paths:
        try:
            report = count_completed_rows(csv_path)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if report.total_rows == 0 and not args.include_empty:
            continue
        reports.append(report)

    render_report(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())