# Implementation Guide

This document is for another engineer taking over or extending this project.
It focuses on how the downloader actually works, where state lives, what can be changed safely, and what operational behaviors matter in practice.

## Project Goal

The project downloads audio tracks for Spotify playlist exports created from Exportify CSV files.

Those CSV files are expected to come from https://exportify.app/.

The main design choice is:

- the Exportify CSV is source input, and a sibling `_work.csv` is the persistent state store

That means the downloader does not keep a separate database or cache. Each row in the work CSV is enriched with tracking columns that describe what happened for that track.

## Main Files

- `main.py`: thin root wrapper that calls the packaged launcher
- `tools/reconcile_csv_files.py`: wrapper for the packaged reconcile utility
- `tools/reconcile_metadata.py`: wrapper for metadata-only reconcile
- `exportify_downloader/launcher/main.py`: packaged launcher that loads config, resolves cookies, and runs one or more CSV files
- `exportify_downloader/core/downloader.py`: packaged core downloader, matcher coordinator, metadata writer, and CSV state updater
- `exportify_downloader/scripts/reconcile.py`: packaged repair utility that scans audio files already on disk and writes matching `output_file` values back into the CSV
- `exportify_downloader/scripts/reconcile_metadata.py`: packaged metadata-only maintenance utility for existing local files
- `tools/`: one-off and maintenance utility scripts (`check_tags.py`, `embed_artwork.py`, `reconcile_csv_files.py`, `reconcile_metadata.py`)
- `downloader.config.json`: default settings for the Python launcher
- `README.md`: user-facing overview and basic usage
- `docs/MAINTENANCE.md`: operational recipes and recovery steps
- `docs/METADATA_TAGGING.md`: metadata-writing behavior and troubleshooting

## Execution Model

There are two layers:

1. `main.py` is the entrypoint for normal use.
2. `exportify_downloader/core/downloader.py` performs the actual work.

### Launcher Responsibilities

The launcher exists to keep orchestration separate from core download/matching logic.

It is responsible for:

- loading defaults from `downloader.config.json`
- allowing CLI arguments to override config values
- resolving relative paths for config and cookie files
- automatically using `music youtube cookies.txt` when present and no explicit cookie option is passed
- creating/syncing `<playlist>_work.csv` from source CSV inputs
- running one CSV or all CSV files in `CsvFolder`
- printing batch-level progress such as `[1/3] Starting: playlist.csv`
- forcing unbuffered Python output with `python -u` so row-by-row logs appear live

The launcher should stay thin. Business logic belongs in Python, not the orchestration layer.

### Python Downloader Responsibilities

`exportify_downloader/core/downloader.py` is the actual application.

It is responsible for:

- validating required CSV columns
- appending tracking columns if missing
- deciding whether a row should be skipped
- searching YouTube through the `yt_dlp` Python API
- persisting chosen YouTube matches into the work CSV before download
- scoring candidate matches using project heuristics
- optionally downloading audio with the `yt_dlp` Python API when downloads are enabled
- locating the final saved file on disk
- writing metadata to the downloaded file via `ffmpeg`
- writing status and result fields back to the CSV after each row
- printing row-by-row live logs

## State Model

State is stored directly in the CSV through these columns:

- `id`
- `row_key`
- `download_status`
- `artwork_status`
- `youtube_url`
- `selected_title`
- `selected_duration_s`
- `duration_delta_s`
- `output_file`
- `attempted_at`
- `error_message`

`download_status` values used by the Python script:

- `resolved`
- `downloaded`
- `unresolved`
- `error`
- `skipped` is mainly a runtime outcome rather than a persisted path in the current flow

`artwork_status` values:

- `embedded`: a sidecar image file was found and successfully embedded as the APIC cover art tag
- *(empty)*: no matching sidecar image was found, or artwork has not yet been processed for this row

Important behavior:

- rows are updated in place in the `_work.csv` after each attempt
- by default, rows with tracking data are skipped unless `--force-redownload` is used
- rows already marked `resolved` can continue directly into download when `DownloadEnabled` is true

Identity behavior:

- `id` is a persistent numeric work-row identifier and is written as the first CSV column.
- `row_key` is generated explicitly for each row.
- Preferred base key is Spotify track identity from `Track URI`: `sp:<id>`.
- Fallback base key is a fingerprint hash from normalized track metadata: `fp:<hash>`.
- Duplicate base keys in the same file get suffixed (`#2`, `#3`, ...).

## Row Processing Flow

For each CSV row, the downloader roughly does this:

1. Check whether the row should be skipped.
2. Validate that track, primary artist, and duration are present.
3. Reuse a saved resolution when the row is already `resolved`.
4. Otherwise, build a YouTube Music search URL: `https://music.youtube.com/search?q=<artist+track>`.
5. Use `yt_dlp` to extract candidates from YouTube Music search results.
6. Score candidates using weighted overlap: duration penalty + title/artist token overlap + version/noise keyword penalties.
7. Select the lowest-scored candidate (best match).
8. Persist the chosen candidate into the work CSV and mark the row `resolved`.
9. If downloads are enabled, download the chosen candidate as audio with yt-dlp rate limiting applied.
10. Resolve the actual saved output file from the target folder.
11. Write metadata tags with `ffmpeg`.
12. Look for a sidecar image file (`.jpg`, `.png`, `.webp`) alongside the audio file and embed it as APIC cover art. If no sidecar exists, attempt to download the thumbnail from YouTube as a fallback.
13. Set `artwork_status = embedded` in the row when artwork is successfully applied.
14. Write the final `downloaded` result back into the CSV.

For already-downloaded (skipped) rows, the same artwork lookup and embed step runs on every subsequent pass, using only local sidecar files (no YouTube request). `artwork_status` is written and the CSV is saved immediately after a successful embed.

If any step fails, the row is marked `error` with a shortened `error_message`.

## Matching Heuristics

The matcher balances **weighted overlap** over hard rejects, inspired by spotDL.

It factors in:

- expected duration in seconds (duration mismatch penalty: 35x weight)
- a configurable duration tolerance
- normalized token overlap between track title and candidate title (title weight: 280x)
- normalized token overlap between artist name and candidate title/uploader (artist weight: 180x)
- soft penalties for noisy keywords such as `lyrics`, `nightcore`, `bass boosted`, `sped up` (penalty: 90 per keyword)
- soft penalties for version mismatches (penalty: 45 per mismatch)
- minimum thresholds to prevent absurd matches (title overlap >= 30%, artist overlap >= 20%)

The current direction is: use weighted scoring to reduce false positives while still resolving more tracks than a purely strict approach.

If you change scoring, preserve that bias unless the project goal changes.

## Download Output Model

Each CSV downloads into a sibling folder named after the CSV stem.

Example:

- CSV: `exportify.app\3_dnb_dance_floor.csv`
- output dir: `exportify.app\3_dnb_dance_floor\`

If the active CSV is `exportify.app\3_dnb_dance_floor_work.csv`, the output dir is still `exportify.app\3_dnb_dance_floor\`.

The downloader builds a stable base name from:

- first artist
- track name

Characters invalid for Windows filenames are normalized.

`resolve_downloaded_file()` then searches for `base_name.*` and picks the newest match.

## Metadata Model

After download, metadata is written with `ffmpeg`.

Notable tag behavior:

- `title`, `artist`, `album`, `album_artist`, `date`, `disc`, `isrc` come from CSV columns when present
- `track` is intentionally set to the persistent work CSV `id` when available
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

`reconcile_metadata.py` exists for the related case where the local audio file is already on disk and you want to refresh metadata from the CSV without downloading. It reuses the same file-matching approach as reconcile, then writes metadata tags to the matched files.

## Configuration Model

The config file currently includes:

- `CsvPath`
- `CsvFolder`
- `DurationTolerance`
- `SearchResults`
- `DownloadEnabled`
- `ForceRedownload`
- `Limit`
- `SleepRequests`
- `IdOrder`
- `CookiesFromBrowser`
- `CookiesFile`

Current meaning of the most important runtime settings:

- `Limit`: maximum number of rows to process in one run; `0` means no limit
- `SleepRequests`: delay between yt-dlp requests; current config default is `1.1`
- `SearchResults`: how many YouTube candidates are inspected for matching
- `DownloadEnabled`: whether the run stops after resolution or continues into download
- `DurationTolerance`: maximum allowed duration mismatch in seconds
- `IdOrder`: row processing order by persistent work CSV `id`

CLI arguments override config values.

`DownloadEnabled` is the main workflow switch:

- `true`: resolve candidates and continue into download
- `false`: resolve candidates into the work CSV and stop before download

## Logging Model

There are two levels of logs.

### Launcher-Level Logs

The launcher prints:

- which CSV started
- which CSV path is being used
- active settings for the run
- whether the CSV completed or failed at process level
- batch summary counts when scanning a folder

### Row-Level Logs

The Python script prints live logs such as:

- `[12] checking: Artist - Track`
- `[12] resolved: Artist - Track <- Candidate Title`
- `[12] using saved resolution: Artist - Track <- Candidate Title`
- `[12] downloading: Artist - Track <- Candidate Title`
- `[12] downloaded: Artist - Track`
- `[12] skip: already downloaded`
- `[12] unresolved: Artist - Track`
- `[12] error: Artist - Track :: shortened message`

This live feedback is important operationally. If you refactor logging, keep it immediate and readable.

## Known Operational Realities

These are not theoretical edge cases. They happen in normal use.

- YouTube rate limiting is common; the config includes a tuned throttling profile (`--limit-rate 4M --throttled-rate 50K --sleep-interval 10 --max-sleep-interval 35`) designed for YouTube Music compliance.
- `This content isn't available, try again later` can repeat across many rows during a bad session.
- cookies materially improve success rates for age-restricted or protected videos.
- metadata may appear missing in Windows Explorer until tags are rewritten and the cache refreshes.
- path mismatches can happen between similar output folders and are recoverable with `reconcile_csv_files.py`.
- id ordering can help you process rows in playlist order (via `--id-order ascending/descending`) for better manual monitoring and checkpoint context.

Practical operator rules:

- if repeated rate-limit errors appear across multiple rows, stop the run and retry later or use `--id-order ascending` to resume where you left off.
- the YouTube Music-only search strategy means your candidate pool is narrower but higher quality than generic YouTube.

## Safe Change Areas

These are usually safe to change with low arc (tuning profile, track order, limits)
- launcher log formatting in `exportify_downloader/launcher/main.py`
- Python log wording in `exportify_downloader/core/downloader.py`
- scoring weights and token overlap thresholds in the matcher
- reconcile filename matching rules in `exportify_downloader/scripts/reconcile.py`
- yt-dlp command flags and rate-limit tuning parameters
- scoring weights and keyword lists in the matcher
- reconcile filename matching rules in `exportify_downloader/scripts/reconcile.py`
- documentation files

## Risky Change Areas

These need more care because they affect persistence or operational correctness:

- changing tracking column names
- changing skip logic for `download_status=downloaded`
- changing filename normalization in `stable_base_name()`
- changing how `output_file` is resolved and persisted
- changing metadata-writing semantics, especially `track`, `row_id`, and `spotify_track_id`
- moving business rules from `exportify_downloader/core/downloader.py` into `exportify_downloader/launcher/main.py`

If you touch any of those, validate against a real CSV, not just syntax checks.

## Recommended Workflow For Another Engineer

When implementing new behavior, use this order:

1. update Python logic first
2. keep `main.py` as a thin launcher wrapper
3. run a one-row test with `--limit 1`
4. inspect the CSV row that changed
5. inspect the saved audio file if the change affects download or tags
6. only then try a broader batch run

Good validation commands:

```bash
python -m py_compile main.py reconcile_csv_files.py exportify_downloader/launcher/main.py exportify_downloader/core/downloader.py exportify_downloader/scripts/reconcile.py
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --limit 1
python tools/reconcile_csv_files.py
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
2. `main.py` is the wrapper entrypoint, `exportify_downloader/launcher/main.py` is orchestration, and `exportify_downloader/core/downloader.py` is business logic
3. reruns depend on `download_status` plus a real `output_file`
4. YouTube rate limiting is the main operational constraint
5. `reconcile_csv_files.py` is the wrapper entrypoint and `exportify_downloader/scripts/reconcile.py` is the repair tool when CSV state and disk state drift apart