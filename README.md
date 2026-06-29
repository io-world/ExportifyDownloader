# CSV Playlist Downloader (yt-dlp)

Download a Spotify Exportify CSV playlist with yt-dlp using a generated work CSV as the persistent state file.

Get the playlist CSV from https://exportify.app/ and place the exported file in `exportify.app` inside this project.

## Current Features

- Uses a two-file workflow: source CSV from Exportify plus a sibling `_work.csv` state file.
- Searches **YouTube Music only** using yt-dlp for better relevance.
- Can run in resolve-only mode, saving YouTube Music matches into the work CSV without downloading audio.
- Uses SpotDL-style weighted matching (duration proximity + title/artist overlap scoring instead of hard rejects).
- Extracts audio and requests MP3 at 320 kbps during download.
- Embeds metadata into output files from CSV fields (title, artist, album, date, ISRC, row ID, row key, Spotify track ID).
- Automatically embeds cover artwork from sidecar image files (`.jpg`, `.png`, `.webp`) whenever a matching image exists alongside the audio file — both on first download and on subsequent reruns of already-downloaded tracks.
- Records `artwork_status = embedded` in the work CSV when artwork is successfully embedded.
- Can reuse saved `resolved` rows and download them later without repeating YouTube Music search.
- By default, rows with tracking data are skipped unless a mode explicitly continues from `resolved` or force-redownload is used.
- Streams live row-by-row console logs so you can see what track is being checked, downloaded, skipped, or failing.
- Includes reconcile utilities to scan existing audio files, restore CSV paths, and refresh metadata without downloading.
- Supports processing order by persistent work CSV `id` using `--id-order` (ascending, descending, or default CSV order).
- Configurable yt-dlp throttling profile (rate limiting, sleep intervals) tuned by default for YouTube Music compliance.

## Source And Work CSV

- Put your raw Exportify CSV in `exportify.app` and treat it as source data.
- On first run, `main.py` creates `<playlist>_work.csv` and sends that file to the downloader.
- On later runs, source fields are synced into `<playlist>_work.csv` and new rows are appended.
- Each `_work.csv` row gets a persistent `id` column as the first column; new rows are assigned the next available numeric ID.
- Downloads go into `<playlist>/`, not `<playlist>_work/`, even when the downloader is running from `<playlist>_work.csv`.
- Folder runs skip `_work.csv` files when source CSVs exist to avoid double-processing.
- If a folder only contains `_work.csv` files, those are processed directly.

## CSV Tracking Columns

On first run, these columns are appended to the work CSV if missing:

- id
- row_key
- download_status
- artwork_status
- youtube_url
- selected_title
- selected_duration_s
- duration_delta_s
- output_file
- attempted_at
- error_message

`download_status` values:

- **resolved**: A YouTube Music match was chosen and saved in the work CSV, but download is disabled or not yet run.
- **downloaded**: File successfully downloaded and exists on disk. Row is complete. Skipped on subsequent runs (unless `--force-redownload` is used).
- **unresolved**: No safe candidate match found within duration tolerance. Row is skipped and not retried unless explicitly re-running.
- **error**: Search, download, or metadata write failed. Row is skipped and marked for potential manual review.
- **retry**: The row hit a transient YouTube rate limit (e.g., HTTP 429). Should be retried on a later rerun to allow the rate limit to clear.
- **skipped**: Runtime-only counter for rows already marked as downloaded or complete (not stored in CSV).

`artwork_status` values:

- **embedded**: A sidecar image file was found alongside the audio file and successfully embedded as the APIC cover art tag.
- *(empty)*: No matching image file was found, or artwork embedding has not yet been attempted for this row.

`row_key` is an explicit identity key per row:

- `sp:<spotify_track_id>` when Track URI includes a Spotify track ID.
- `fp:<hash>` fallback when Track URI is missing.
- `#2`, `#3`, and so on for duplicate rows with the same base identity.

## Run

Export your playlist CSV from https://exportify.app/, place it in `exportify.app`, and run from this project folder:

```bash
python main.py
```

## Config File

Defaults are loaded from `downloader.config.json`.

- Edit `downloader.config.json` to keep your preferred settings in one place.
- CLI flags always override config values.
- You can point to another config with `--config-path`.
- `Limit` is the maximum number of rows to process in one run. `0` means no limit.
- `DownloadEnabled` controls whether rows stop after resolution or continue into audio download.
- `SleepRequests` is the yt-dlp delay between requests. The current config default is `1.1`.

Example:

```bash
python main.py --config-path ./downloader.config.json
```

Common options:

```bash
python main.py --csv-folder ./exportify.app --duration-tolerance 12 --search-results 8
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --resolve-only
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --limit 5
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv --sleep-requests 2.0
python main.py --csv-folder ./exportify.app --force-redownload
python main.py --csv-folder ./exportify.app --cookies-from-browser edge
python main.py --csv-folder ./exportify.app --cookies-file "./music youtube cookies.txt"
python main.py --csv-path ./exportify.app/3_dnb_dance_floor.csv
```

Default config currently ships with:

- `Limit: 0`
- `DownloadEnabled: false`
- `SleepRequests: 1.1`
- `LimitRate: 4M`
- `ThrottledRate: 50K`
- `SleepInterval: 10`
- `MaxSleepInterval: 35`
- `IdOrder: descending` (by work CSV `id`)

## Metadata Behavior

- Title, artist, album, track, and other tags are written back to audio files using ffmpeg.
- Cover artwork is embedded from sidecar image files (`.jpg`, `.png`, `.webp`) that sit alongside the audio file. During a fresh download yt-dlp writes and converts the YouTube thumbnail automatically; on reruns of already-downloaded tracks the downloader checks for an existing sidecar and embeds it without hitting YouTube again. Embedding is best-effort and non-blocking.
- `artwork_status` in the work CSV is set to `embedded` when artwork is successfully applied.
- Metadata `track` is set to the persistent work CSV `id` when available.
- Additional tags include `row_id`, `row_key`, `spotify_track_id`, and combined `comment`.
- For Windows compatibility, tags are written at both container and stream metadata levels.
- `reconcile_metadata.py` can backfill artwork for existing files using local sidecar thumbnails or by refetching from each row's `youtube_url`.

## Project Files

- `main.py`: Root launcher wrapper for normal folder/CSV runs.
- `reconcile_csv_files.py`: Root wrapper for the reconcile utility.
- `reconcile_metadata.py`: Root wrapper for metadata-only reconcile.
- `exportify_downloader/launcher/`: Packaged launcher config, runner, and main orchestration.
- `exportify_downloader/core/`: Packaged downloader, matcher, CSV state, metadata, yt-dlp, and utility logic.
- `exportify_downloader/scripts/`: Packaged maintenance script implementations.
- `downloader.config.json`: Default tuning values used by the Python launcher.
- `music youtube cookies.txt`: Optional cookies file used automatically when present.

## Troubleshooting Notes

- If YouTube returns HTTP 403, run with `--cookies-from-browser edge` (or your browser).
- If you see rate-limit behavior, increase `--sleep-requests` (for example 1.5 to 3.0).
- If you see repeated `try again later` or session rate-limit errors, the downloader now marks the row with `download_status=retry`, then stops early so the rest of the run is not flooded with the same transient error.
- Rerun later and those `retry` rows will be attempted again automatically without clearing CSV fields.
- If some titles appear blank in Windows Explorer, retag files and refresh Explorer metadata cache.
- If a row is `downloaded` but `output_file` is blank, reconcile the path then retag.

See also:

- `docs/METADATA_TAGGING.md`
- `docs/MAINTENANCE.md`

Additional engineering notes live in `docs/IMPLEMENTATION.md`.
