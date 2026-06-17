# CSV Playlist Downloader (yt-dlp)

Download a Spotify Exportify CSV playlist with yt-dlp while using the same CSV as a persistent state file.

Get the playlist CSV from https://exportify.app/ and place the exported file in `exportify.app` inside this project.

## Current Features

- Uses one CSV as both input and progress tracker.
- Uses stricter SpotDL-style match logic (duration + artist/title token overlap + version checks).
- Extracts audio and requests MP3 at 320 kbps during download.
- Embeds metadata into output files from CSV fields (title, artist, album, date, ISRC, row ID, Spotify track ID).
- Re-runs skip files that already exist and can retag existing downloaded files.
- Streams live row-by-row console logs so you can see what track is being checked, downloaded, skipped, or failing.
- Includes a reconcile utility to scan existing audio files and write matching paths back into the CSV.

## CSV Tracking Columns

On first run, these columns are appended to the CSV if missing:

- download_status
- youtube_url
- selected_title
- selected_duration_s
- duration_delta_s
- output_file
- attempted_at
- error_message

Status values:

- downloaded: File exists and row is complete.
- unresolved: No safe candidate match found within tolerance.
- error: Search, download, or metadata write failed.
- skipped: Runtime-only counter for already-complete rows.

## Run

Export your playlist CSV from https://exportify.app/, place it in `exportify.app`, and run from PowerShell in this project folder:

```powershell
.\run_playlist_downloader.ps1
```

## Config File

Defaults are now loaded from `downloader.config.json`.

- Edit `downloader.config.json` to keep your preferred settings in one place.
- CLI flags always override config values.
- You can point to another config with `-ConfigPath`.
- `Limit` is the maximum number of rows to process in one run. `0` means no limit.
- `SleepRequests` is the yt-dlp delay between requests. The current default is `0`.

Example:

```powershell
.\run_playlist_downloader.ps1 -ConfigPath .\downloader.config.json
```

Common options:

```powershell
.\run_playlist_downloader.ps1 -CsvFolder .\exportify.app -DurationTolerance 12 -SearchResults 8
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv -Limit 5
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv -SleepRequests 2.0
.\run_playlist_downloader.ps1 -CsvFolder .\exportify.app -ForceRedownload
.\run_playlist_downloader.ps1 -CsvFolder .\exportify.app -CookiesFromBrowser edge
.\run_playlist_downloader.ps1 -CsvFolder .\exportify.app -CookiesFile ".\music youtube cookies.txt"
.\run_playlist_downloader.ps1 -CsvPath .\exportify.app\3_dnb_dance_floor.csv
```

Default config currently ships with:

- `Limit: 10`
- `SleepRequests: 0`

## Metadata Behavior

- Title, artist, album, track, and other tags are written back to audio files using ffmpeg.
- Metadata `track` is set to the CSV row number (row-aware tagging).
- Additional tags include `row_id`, `spotify_track_id`, and combined `comment`.
- For Windows compatibility, tags are written at both container and stream metadata levels.

## Project Files

- `spotify_csv_yt_dlp.py`: Main downloader + matcher + metadata logic.
- `run_playlist_downloader.ps1`: Batch wrapper for folder/CSV runs.
- `reconcile_csv_files.py`: Scans an audio folder and updates CSV `output_file` / `download_status` fields from files already on disk.
- `downloader.config.json`: Default tuning values used by the PowerShell wrapper.
- `music youtube cookies.txt`: Optional cookies file used automatically when present.

## Troubleshooting Notes

- If YouTube returns HTTP 403, run with `-CookiesFromBrowser edge` (or your browser).
- If you see rate-limit behavior, increase `-SleepRequests` (for example 1.5 to 3.0).
- If you see repeated `try again later` or rate-limit errors across several rows, stop the run and retry later or with a higher sleep delay.
- If some titles appear blank in Windows Explorer, retag files and refresh Explorer metadata cache.
- If a row is `downloaded` but `output_file` is blank, reconcile the path then retag.

See also:

- `METADATA_TAGGING.md`
- `MAINTENANCE.md`
