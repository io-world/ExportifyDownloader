# Implementation Guide

This document is for another engineer taking over or extending this project.
It focuses on how the downloader actually works, where state lives, what can be changed safely, and what operational behaviors matter in practice.

## Project Goal

The project downloads audio tracks for Spotify playlist exports created from Exportify CSV files.

Those CSV files are expected to come from https://exportify.app/.

The main design choice is:

- the CSV is both the input and the persistent state store

That means the downloader does not keep a separate database or cache. Each row in the CSV is enriched with tracking columns that describe what happened for that track.

## Main Files

- `spotify_csv_yt_dlp.py`: core downloader, matcher, metadata writer, and CSV state updater
- `run_playlist_downloader.ps1`: Windows-friendly wrapper that loads config, resolves cookies, and runs one or more CSV files
- `reconcile_csv_files.py`: repair utility that scans audio files already on disk and writes matching `output_file` values back into the CSV
- `downloader.config.json`: default settings for the PowerShell wrapper
- `README.md`: user-facing overview and basic usage
- `MAINTENANCE.md`: operational recipes and recovery steps
- `METADATA_TAGGING.md`: metadata-writing behavior and troubleshooting

## Execution Model

There are two layers:

1. `run_playlist_downloader.ps1` is the entrypoint for normal use.
2. `spotify_csv_yt_dlp.py` performs the actual work.

### PowerShell Wrapper Responsibilities

The wrapper exists mostly to make the Python script easier to run in this Windows setup.

It is responsible for:

- loading defaults from `downloader.config.json`
- allowing CLI arguments to override config values
- resolving relative paths for config and cookie files
- automatically using `music youtube cookies.txt` when present and no explicit cookie option is passed
- running one CSV or all CSV files in `CsvFolder`
- printing batch-level progress such as `[1/3] Starting: playlist.csv`
- forcing unbuffered Python output with `python -u` so row-by-row logs appear live

The wrapper should stay thin. Business logic belongs in Python, not PowerShell.

### Python Downloader Responsibilities

`spotify_csv_yt_dlp.py` is the actual application.

It is responsible for:

- validating required CSV columns
- appending tracking columns if missing
- deciding whether a row should be skipped
- searching YouTube through `yt-dlp`
- scoring candidate matches using project heuristics
- downloading audio with `yt-dlp`
- locating the final saved file on disk
- writing metadata to the downloaded file via `ffmpeg`
- writing status and result fields back to the CSV after each row
- printing row-by-row live logs

## State Model

State is stored directly in the CSV through these columns:

- `download_status`
- `youtube_url`
- `selected_title`
- `selected_duration_s`
- `duration_delta_s`
- `output_file`
- `attempted_at`
- `error_message`

Current status values used by the Python script:

- `downloaded`
- `unresolved`
- `error`
- `skipped` exists as a constant/documented concept but is mainly a runtime outcome rather than a persisted path in the current flow

Important behavior:

- rows are updated in place after each attempt
- reruns use the CSV state to avoid repeating already-complete work
- a row is skipped when `download_status=downloaded` and `output_file` exists on disk, unless `--force-redownload` is used

## Row Processing Flow

For each CSV row, the downloader roughly does this:

1. Check whether the row should be skipped.
2. Validate that track, primary artist, and duration are present.
3. Build a YouTube search query from first artist + track name.
4. Call `yt-dlp --dump-single-json ytsearchN:...` to get candidates.
5. Score candidates using duration tolerance and token overlap rules.
6. Reject candidates that fail version-keyword expectations.
7. Download the chosen candidate as audio.
8. Resolve the actual saved output file from the target folder.
9. Write metadata tags with `ffmpeg`.
10. Write the result back into the CSV.

If any step fails, the row is marked `error` with a shortened `error_message`.

## Matching Heuristics

The matcher is intentionally stricter than a plain YouTube search.

It uses:

- expected duration in seconds
- a configurable duration tolerance
- normalized token overlap between track title and candidate title
- normalized token overlap between artist name and candidate title/uploader
- required version keywords from the Spotify title, such as `remix`, `vip`, `live`, `edit`
- penalties for noisy keywords such as `lyrics`, `nightcore`, `bass boosted`, `sped up`

The current direction is: avoid false positives even if that means some rows become `unresolved`.

If you change scoring, preserve that bias unless the project goal changes.

## Download Output Model

Each CSV downloads into a sibling folder named after the CSV stem.

Example:

- CSV: `exportify.app\3_dnb_dance_floor.csv`
- output dir: `exportify.app\3_dnb_dance_floor\`

The downloader builds a stable base name from:

- first artist
- track name

Characters invalid for Windows filenames are normalized.

`resolve_downloaded_file()` then searches for `base_name.*` and picks the newest match.

## Metadata Model

After download, metadata is written with `ffmpeg`.

Notable tag behavior:

- `title`, `artist`, `album`, `album_artist`, `date`, `disc`, `isrc` come from CSV columns when present
- `track` is intentionally set to the CSV row number when available
- `spotify_track_id` is extracted from `Track URI`
- `row_id` is also written
- `comment` combines row and Spotify IDs

For Windows compatibility, metadata is written both:

- at container level
- at audio stream level for selected keys

## Reconcile Utility

`reconcile_csv_files.py` exists because file paths in the CSV can become stale or blank even when the audio file is already on disk.

It works by:

- loading the CSV
- scanning the target audio directory for supported audio extensions
- generating candidate stems for each row from existing `output_file` and normalized artist/title naming
- updating `output_file` and `download_status` when a match is found

Use it when:

- rows are `downloaded` but `output_file` is wrong or empty
- files were moved between equivalent download folders
- you want to restore retagging ability without redownloading

It can auto-discover the CSV if there is exactly one `.csv` in `exportify.app`.

## Configuration Model

The config file currently includes:

- `CsvPath`
- `CsvFolder`
- `DurationTolerance`
- `SearchResults`
- `ForceRedownload`
- `Limit`
- `SleepRequests`
- `CookiesFromBrowser`
- `CookiesFile`

Current meaning of the most important runtime settings:

- `Limit`: maximum number of rows to process in one run; `0` means no limit
- `SleepRequests`: delay between yt-dlp requests; current default is `0`
- `SearchResults`: how many YouTube candidates are inspected for matching
- `DurationTolerance`: maximum allowed duration mismatch in seconds

CLI arguments override config values.

## Logging Model

There are two levels of logs.

### Wrapper-Level Logs

The PowerShell wrapper prints:

- which CSV started
- which CSV path is being used
- active settings for the run
- whether the CSV completed or failed at process level
- batch summary counts when scanning a folder

### Row-Level Logs

The Python script prints live logs such as:

- `[12] checking: Artist - Track`
- `[12] downloading: Artist - Track <- Candidate Title`
- `[12] downloaded: Artist - Track`
- `[12] skip: already downloaded`
- `[12] unresolved: Artist - Track`
- `[12] error: Artist - Track :: shortened message`

This live feedback is important operationally. If you refactor logging, keep it immediate and readable.

## Known Operational Realities

These are not theoretical edge cases. They happen in normal use.

- YouTube rate limiting is common.
- `This content isn't available, try again later` can repeat across many rows during a bad session.
- cookies materially improve success rates for age-restricted or protected videos.
- metadata may appear missing in Windows Explorer until tags are rewritten and the cache refreshes.
- path mismatches can happen between similar output folders and are recoverable with `reconcile_csv_files.py`.

Practical operator rule:

- if repeated rate-limit errors appear across multiple rows, stop the run and retry later or increase `SleepRequests`

## Safe Change Areas

These are usually safe to change with low architectural risk:

- config defaults in `downloader.config.json`
- PowerShell log formatting in `run_playlist_downloader.ps1`
- Python log wording in `spotify_csv_yt_dlp.py`
- scoring weights and keyword lists in the matcher
- reconcile filename matching rules in `reconcile_csv_files.py`
- documentation files

## Risky Change Areas

These need more care because they affect persistence or operational correctness:

- changing tracking column names
- changing skip logic for `download_status=downloaded`
- changing filename normalization in `stable_base_name()`
- changing how `output_file` is resolved and persisted
- changing metadata-writing semantics, especially `track`, `row_id`, and `spotify_track_id`
- moving business rules from Python into PowerShell

If you touch any of those, validate against a real CSV, not just syntax checks.

## Recommended Workflow For Another Engineer

When implementing new behavior, use this order:

1. update Python logic first
2. keep PowerShell as a thin wrapper
3. run a one-row test with `-Limit 1`
4. inspect the CSV row that changed
5. inspect the saved audio file if the change affects download or tags
6. only then try a broader batch run

Good validation commands:

```powershell
.\.venv\Scripts\python.exe -m py_compile .\spotify_csv_yt_dlp.py .\reconcile_csv_files.py
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv -Limit 1
.\.venv\Scripts\python.exe .\reconcile_csv_files.py
```

## Extension Ideas

Reasonable future improvements:

- better structured error classification instead of plain strings
- a retry mode that only reruns `error` and `unresolved` rows
- a dry-run mode that shows candidate choices without downloading
- optional CSV backup creation before row mutations
- a second matching fallback strategy for unresolved rows
- more precise process exit codes when rows fail but the script completes

## Handoff Summary

If you only remember five things about this codebase, remember these:

1. the CSV is the source of truth for state
2. PowerShell is orchestration, Python is business logic
3. reruns depend on `download_status` plus a real `output_file`
4. YouTube rate limiting is the main operational constraint
5. `reconcile_csv_files.py` is the repair tool when CSV state and disk state drift apart