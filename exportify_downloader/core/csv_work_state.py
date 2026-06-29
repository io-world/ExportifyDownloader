#!/usr/bin/env python3
"""CSV source/work file state helpers."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

from .utils import extract_spotify_track_id, normalize_text

ID_COLUMN = "id"
ROW_KEY_COLUMN = "row_key"
TRACKING_COLUMNS = [
    "download_status",
    "artwork_status",
    "youtube_url",
    "selected_title",
    "selected_duration_s",
    "duration_delta_s",
    "output_file",
    "attempted_at",
    "error_message",
]


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise RuntimeError(f"CSV appears empty or invalid: {path}")
        fieldnames = list(reader.fieldnames)
        rows = [dict(r) for r in reader]
    return fieldnames, rows


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def row_key_base(row: Dict[str, str]) -> str:
    spotify_id = extract_spotify_track_id(row.get("Track URI", ""))
    if spotify_id:
        return f"sp:{spotify_id}"

    parts = [
        normalize_text(row.get("Track Name", "")),
        normalize_text(row.get("Artist Name(s)", "")),
        normalize_text(row.get("Album Name", "")),
        normalize_text(row.get("Track Duration (ms)", "")),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"fp:{digest}"


def derive_row_keys(rows: List[Dict[str, str]]) -> None:
    seen: Dict[str, int] = {}
    for row in rows:
        base = row_key_base(row)
        seen[base] = seen.get(base, 0) + 1
        row[ROW_KEY_COLUMN] = base if seen[base] == 1 else f"{base}#{seen[base]}"


def ensure_row_keys(rows: List[Dict[str, str]]) -> None:
    seen: Dict[str, int] = {}
    for row in rows:
        key = (row.get(ROW_KEY_COLUMN) or "").strip()
        if key:
            continue
        base = row_key_base(row)
        seen[base] = seen.get(base, 0) + 1
        row[ROW_KEY_COLUMN] = base if seen[base] == 1 else f"{base}#{seen[base]}"


def ensure_row_ids(rows: List[Dict[str, str]]) -> None:
    next_id = 1
    for row in rows:
        raw_value = (row.get(ID_COLUMN) or "").strip()
        if raw_value.isdigit() and int(raw_value) > 0:
            next_id = max(next_id, int(raw_value) + 1)

    for row in rows:
        raw_value = (row.get(ID_COLUMN) or "").strip()
        if raw_value.isdigit() and int(raw_value) > 0:
            row[ID_COLUMN] = str(int(raw_value))
            continue
        row[ID_COLUMN] = str(next_id)
        next_id += 1


def ensure_all_columns(rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    for row in rows:
        for col in fieldnames:
            row.setdefault(col, "")


def ordered_work_fieldnames(fieldnames: List[str]) -> List[str]:
    ordered = [col for col in fieldnames if col != ID_COLUMN]
    return [ID_COLUMN, *ordered]


def ensure_tracking_columns(fieldnames: List[str]) -> List[str]:
    updated = list(fieldnames)
    if ID_COLUMN not in updated:
        updated.append(ID_COLUMN)
    if ROW_KEY_COLUMN not in updated:
        updated.append(ROW_KEY_COLUMN)
    for col in TRACKING_COLUMNS:
        if col not in updated:
            updated.append(col)
    return ordered_work_fieldnames(updated)


def work_csv_path_for(source_csv_path: Path) -> Path:
    return source_csv_path.with_name(f"{source_csv_path.stem}_work{source_csv_path.suffix}")


def playlist_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    if stem.lower().endswith("_work"):
        return stem[:-5]
    return stem


def prepare_work_csv(source_csv_path: Path) -> Path:
    work_csv_path = work_csv_path_for(source_csv_path)

    source_fieldnames, source_rows = read_csv(source_csv_path)
    derive_row_keys(source_rows)

    source_keyed: Dict[str, Dict[str, str]] = {}
    for row in source_rows:
        source_keyed[row[ROW_KEY_COLUMN]] = row

    if not work_csv_path.exists():
        fieldnames = list(source_fieldnames)
        if ID_COLUMN not in fieldnames:
            fieldnames.append(ID_COLUMN)
        if ROW_KEY_COLUMN not in fieldnames:
            fieldnames.append(ROW_KEY_COLUMN)
        for col in TRACKING_COLUMNS:
            if col not in fieldnames:
                fieldnames.append(col)
        fieldnames = ordered_work_fieldnames(fieldnames)

        rows_to_write: List[Dict[str, str]] = []
        for source_row in source_rows:
            new_row = {col: source_row.get(col, "") for col in source_fieldnames}
            new_row[ROW_KEY_COLUMN] = source_row[ROW_KEY_COLUMN]
            for col in TRACKING_COLUMNS:
                new_row[col] = ""
            rows_to_write.append(new_row)

        ensure_row_ids(rows_to_write)
        ensure_all_columns(rows_to_write, fieldnames)
        write_csv(work_csv_path, fieldnames, rows_to_write)
        print(f"Created work CSV: {work_csv_path.name}")
        return work_csv_path

    work_fieldnames, work_rows = read_csv(work_csv_path)

    if ID_COLUMN not in work_fieldnames:
        work_fieldnames.append(ID_COLUMN)
    if ROW_KEY_COLUMN not in work_fieldnames:
        work_fieldnames.append(ROW_KEY_COLUMN)
    for col in TRACKING_COLUMNS:
        if col not in work_fieldnames:
            work_fieldnames.append(col)
    for col in source_fieldnames:
        if col not in work_fieldnames:
            work_fieldnames.append(col)
    work_fieldnames = ordered_work_fieldnames(work_fieldnames)

    for row in work_rows:
        row.setdefault(ID_COLUMN, "")
        row.setdefault(ROW_KEY_COLUMN, "")

    missing_key_rows = [row for row in work_rows if not row.get(ROW_KEY_COLUMN, "").strip()]
    if missing_key_rows:
        derive_row_keys(work_rows)

    ensure_row_ids(work_rows)

    work_by_key: Dict[str, Dict[str, str]] = {}
    for row in work_rows:
        key = (row.get(ROW_KEY_COLUMN) or "").strip()
        if key:
            work_by_key[key] = row

    added = 0
    for key, source_row in source_keyed.items():
        if key in work_by_key:
            existing = work_by_key[key]
            for col in source_fieldnames:
                existing[col] = source_row.get(col, "")
            continue

        new_row = {col: "" for col in work_fieldnames}
        for col in source_fieldnames:
            new_row[col] = source_row.get(col, "")
        new_row[ROW_KEY_COLUMN] = key
        work_rows.append(new_row)
        added += 1

    ensure_row_ids(work_rows)
    ensure_all_columns(work_rows, work_fieldnames)
    write_csv(work_csv_path, work_fieldnames, work_rows)

    if added:
        print(f"Synced work CSV: {work_csv_path.name} (+{added} new rows)")
    else:
        print(f"Synced work CSV: {work_csv_path.name} (no new rows)")

    return work_csv_path
