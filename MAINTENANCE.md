# Maintenance Guide

Operational commands and recovery steps for this downloader project.

Playlist CSV files are expected to be exported from https://exportify.app/ and placed in the local `exportify.app` folder.

## 0) Config Defaults

Use `downloader.config.json` for default values (tolerance, search results, sleep delay, cookies, etc.).

- CLI arguments override config values.
- Use `--config-path` to load a different config file.
- `Limit` controls how many rows are processed in one run. `0` means all rows.
- Current default values are `Limit: 60` and `SleepRequests: 1.1`.

Example:

```bash
python main.py --config-path ./downloader.config.json
```

## 1) Normal Run

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv
```

Live console feedback now shows each row as it moves through `checking`, `downloading`, `downloaded`, `skip`, `unresolved`, or `error`.

## 2) Retry Problem Rows

Retry unresolved and error rows with cookies:

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --cookies-from-browser edge
```

Force retry of all downloaded rows:

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --force-redownload
```

## 3) Full Retag-Only Pass

If audio files exist and you only want metadata updates:

```powershell
$code = @'
import csv
from pathlib import Path
from spotify_csv_yt_dlp import build_audio_metadata, embed_audio_metadata, STATUS_DOWNLOADED

csv_path = Path(r".\exportify.app\3_dnb_dance_floor_work.csv")
rows = list(csv.DictReader(csv_path.open("r", newline="", encoding="utf-8-sig")))

updated = 0
for idx, row in enumerate(rows, start=1):
    if (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
        continue
    p = Path((row.get("output_file") or "").strip())
    if not p.exists():
        continue
    row_id = row.get("id") or str(idx)
    embed_audio_metadata(p, build_audio_metadata(row, int(row_id)))
    updated += 1

print(f"retagged={updated}")
'@
$code | .\.venv\Scripts\python.exe -
```

## 4) Reconcile Downloaded Rows With Empty output_file

If a row is `downloaded` but `output_file` is empty, rebuild path references by matching file stems, then retag.

Note: with the source/work CSV model, reconcile updates the `_work.csv`. If you pass a source CSV and a sibling `_work.csv` exists, the script automatically switches to `_work.csv`.

Run the reconcile utility directly:

```powershell
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor_work.csv
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv --files-dir .\exportify.app\3_dnb_dance_floor
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv --clear-missing
```

If there is only one CSV in `exportify.app`, the script can also be run without arguments:

```powershell
.\.venv\Scripts\python.exe .\reconcile_csv_files.py
```

Practical rule:

- Use exact stem matching, not glob wildcards, for names containing square brackets (`[` and `]`).

## 5) Health Checks

Python syntax check:

```powershell
.\.venv\Scripts\python.exe -m py_compile .\spotify_csv_yt_dlp.py .\reconcile_csv_files.py
```

Inspect tag values:

```powershell
ffprobe -v error -show_entries format_tags=title,artist,album,track,row_id,spotify_track_id,comment -of default=noprint_wrappers=1:nokey=0 ".\exportify.app\3_dnb_dance_floor\<file>.m4a"
```

## 6) Common Issues

- HTTP 403 on YouTube: pass `--cookies-from-browser`.
- Repeated `This content isn't available, try again later` errors: stop the run and retry later or increase `--sleep-requests`.
- Blank title in Windows: ensure file was retagged and refresh Explorer cache.
- Missing output file path in CSV: reconcile output path and rerun retag.
