# Maintenance Guide

Operational commands and recovery steps for this downloader project.

Playlist CSV files are expected to be exported from https://exportify.app/ and placed in the local `exportify.app` folder.

## 0) Config Defaults

Use `downloader.config.json` for default values (tolerance, search results, sleep delay, cookies, etc.).

- CLI arguments override config values.
- Use `--config-path` to load a different config file.
- `Limit` controls how many rows are processed in one run. `0` means all rows.
- `DownloadEnabled` controls whether a run resolves only or resolves and downloads.
- Current default values are `Limit: 60` and `SleepRequests: 1.1`.

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
python reconcile_metadata.py ./exportify.app/3_dnb_dance_floor.csv
```

Only retag rows already marked downloaded:

```bash
python reconcile_metadata.py ./exportify.app/3_dnb_dance_floor.csv --downloaded-only
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
.\.venv\Scripts\python.exe -m py_compile .\main.py .\reconcile_csv_files.py .\reconcile_metadata.py .\exportify_downloader\launcher\main.py .\exportify_downloader\core\downloader.py .\exportify_downloader\scripts\reconcile.py .\exportify_downloader\scripts\reconcile_metadata.py
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
