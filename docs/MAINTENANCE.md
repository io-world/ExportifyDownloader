# Maintenance Guide

Operational commands and recovery steps for this downloader project.

Playlist CSV files are expected to be exported from https://exportify.app/ and placed in the local `exportify.app` folder.

## 0) Config Defaults

Use `downloader.config.json` for default values (tolerance, search results, sleep delay, cookies, etc.).

- CLI arguments override config values.
- Use `--config-path` to load a different config file.
- `Limit` controls how many rows are processed in one run. `0` means all rows.
- `DownloadEnabled` controls whether a run resolves only or resolves and downloads.
- Current shipped defaults include `Limit: 0`, `DownloadEnabled: true`, `SleepRequests: 1.1`, and `IdOrder: priority`.

Example:

```bash
python main.py --config-path ./downloader.config.json
```

## 1) Normal Run

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv
```

Live console feedback now shows each row as it moves through `checking`, `resolved`, `using saved resolution`, `downloading`, `downloaded`, `skip`, `unresolved`, or `error`.

Resolve-only pass without downloading audio:

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --resolve-only
```

Equivalent config-driven flow:

```json
"DownloadEnabled": false
```

## 2) Retry Problem Rows

Retry unresolved and error rows with cookies:

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --cookies-from-browser edge
```

Rows marked with `download_status=retry` do not need manual CSV cleanup. Rerun later and the downloader will automatically attempt those rows again.

Force retry of all downloaded rows:

```bash
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --force-redownload
```

## 3) Full Retag-Only Pass

If audio files exist and you only want metadata updates:

```bash
python -m exportify_downloader.scripts.reconcile_metadata ./exportify.app/3_dnb_dance_floor.csv
```

Only retag rows already marked downloaded:

```bash
python -m exportify_downloader.scripts.reconcile_metadata ./exportify.app/3_dnb_dance_floor.csv --downloaded-only
```

## 4) Reconcile Downloaded Rows With Empty output_file

If a row is `downloaded` but `output_file` is empty, rebuild path references by matching file stems, then retag.

Note: with the source/work CSV model, reconcile updates the `_work.csv`. If you pass a source CSV and a sibling `_work.csv` exists, the script automatically switches to `_work.csv`.

Run the reconcile utility directly:

```powershell
.\.venv\Scripts\python.exe -m exportify_downloader.scripts.reconcile .\exportify.app\3_dnb_dance_floor.csv
.\.venv\Scripts\python.exe -m exportify_downloader.scripts.reconcile .\exportify.app\3_dnb_dance_floor_work.csv
.\.venv\Scripts\python.exe -m exportify_downloader.scripts.reconcile .\exportify.app\3_dnb_dance_floor.csv --files-dir .\exportify.app\3_dnb_dance_floor
.\.venv\Scripts\python.exe -m exportify_downloader.scripts.reconcile .\exportify.app\3_dnb_dance_floor.csv --clear-missing
```

If there is only one CSV in `exportify.app`, the script can also be run without arguments:

```powershell
.\.venv\Scripts\python.exe -m exportify_downloader.scripts.reconcile
```

Create a combined download-status summary and CSV of tracks that still need downloading:

```powershell
.\.venv\Scripts\python.exe .\tools\playlist_download_report.py .\exportify.app
```

The report writes to `run_logs/playlist_download_report_<timestamp>.csv` by default. It includes per-playlist and folder-wide completion counts. Each missing track row includes `output_folder`, the playlist's normal download folder. To download the report, pass the exact path printed by the report:

```powershell
.\.venv\Scripts\python.exe .\tools\download_missing_tracks.py .\run_logs\playlist_download_report_20261014_120000.csv
```

The command uses `downloader.config.json` for download settings and updates the report CSV as it processes rows. Pass `--config-path <path>` to use another config.
You can set `REPORT_CSV_PATH` near the top of `tools/download_missing_tracks.py` to select a default report CSV. If left as `None`, the tool automatically uses the newest matching report in `run_logs`. A CSV path passed as an argument overrides the variable.

Use `--csv-out <path>` with the report command to choose the report CSV path.

## 5) Health Checks

Python syntax check:

```powershell
.\.venv\Scripts\python.exe -m py_compile .\main.py .\exportify_downloader\launcher\main.py .\exportify_downloader\core\downloader.py .\exportify_downloader\scripts\reconcile.py .\exportify_downloader\scripts\reconcile_metadata.py
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
