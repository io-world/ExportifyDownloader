# Maintenance Guide

Operational commands and recovery steps for this downloader project.

Playlist CSV files are expected to be exported from https://exportify.app/ and placed in the local `exportify.app` folder.

## 0) Config Defaults

Use `downloader.config.json` for default values (tolerance, search results, sleep delay, cookies, etc.).

- CLI arguments override config values.
- Use `-ConfigPath` to load a different config file.
- `Limit` controls how many rows are processed in one run. `0` means all rows.
- Current default values are `Limit: 10` and `SleepRequests: 0`.

Example:

```powershell
.\run_playlist_downloader.ps1 -ConfigPath .\downloader.config.json
```

## 1) Normal Run

```powershell
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv
```

Live console feedback now shows each row as it moves through `checking`, `downloading`, `downloaded`, `skip`, `unresolved`, or `error`.

## 2) Retry Problem Rows

Retry unresolved and error rows with cookies:

```powershell
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv -CookiesFromBrowser edge
```

Force retry of all downloaded rows:

```powershell
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv -ForceRedownload
```

## 3) Full Retag-Only Pass

If audio files exist and you only want metadata updates:

```powershell
$code = @'
import csv
from pathlib import Path
from spotify_csv_yt_dlp import build_audio_metadata, embed_audio_metadata, STATUS_DOWNLOADED

csv_path = Path(r".\exportify.app\3_dnb_dance_floor.csv")
rows = list(csv.DictReader(csv_path.open("r", newline="", encoding="utf-8-sig")))

updated = 0
for idx, row in enumerate(rows, start=1):
    if (row.get("download_status") or "").strip().lower() != STATUS_DOWNLOADED:
        continue
    p = Path((row.get("output_file") or "").strip())
    if not p.exists():
        continue
    embed_audio_metadata(p, build_audio_metadata(row, idx))
    updated += 1

print(f"retagged={updated}")
'@
$code | .\.venv\Scripts\python.exe -
```

## 4) Reconcile Downloaded Rows With Empty output_file

If a row is `downloaded` but `output_file` is empty, rebuild path references by matching file stems, then retag.

Run the reconcile utility directly:

```powershell
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv
.\.venv\Scripts\python.exe .\reconcile_csv_files.py .\exportify.app\3_dnb_dance_floor.csv --files-dir .\3_dnb_dance_floor
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

- HTTP 403 on YouTube: pass `-CookiesFromBrowser`.
- Repeated `This content isn't available, try again later` errors: stop the run and retry later or increase `-SleepRequests`.
- Blank title in Windows: ensure file was retagged and refresh Explorer cache.
- Missing output file path in CSV: reconcile output path and rerun retag.
