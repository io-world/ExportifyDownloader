# Tools Folder Reference

This file explains what each script in this folder does.

## bpm_analysis.py
- Runs BPM analysis on MP3 files in a folder.
- Uses multiple sources for tempo estimation:
  - librosa
  - essentia
  - bpm-detector CLI
  - Anthropic web-search estimate (if `ANTHROPIC_API_KEY` is set)
- Writes combined results to CSV (default under `run_logs/bpm_analysis_results.csv`), one row per file as it finishes.
- Rerunning with the same output CSV skips files already analyzed; pass `--fresh` to start over.
- `consensus_bpm` is the median of all readings after folding each into one octave (`--min-bpm`, default 88, gives 88-176), so half/double-time readings don't skew it. `bpm_spread` shows how much the folded readings disagree.
- Missing tools and errors are listed in the `notes` column.
- The web-search estimate uses the `anthropic` SDK with `claude-sonnet-5-5`.

## check_tags.py
- Quick tag inspection for a single MP3: `python tools/check_tags.py <file.mp3>`.
- Prints duration, bitrate, and all ID3 frames.
- Useful for debugging metadata on a specific file.

## download_youtube_music_url.py
- Downloads one YouTube/YouTube Music track URL: `python tools/download_youtube_music_url.py <url>` (a URL is required unless `DEFAULT_URL` is set in the script).
- Uses project config defaults from `downloader.config.json`.
- Supports cookie auth (`CookiesFromBrowser` or `CookiesFile`) and output folder overrides.
- After download, embeds:
  - core audio metadata (title/artist/album/date)
  - artwork from the best thumbnail URL
- Default output folder is `tools/url_downloads`.

## find_new_tracks.py
- Compares audio files in a "new" folder against an "original" folder.
- Uses fuzzy filename matching (full name and title-only variants) to detect near-duplicates.
- Reports files in the new folder that do not have a close match above threshold.
- Prints missing files and writes a CSV report to `run_logs/find_new_tracks_<timestamp>.csv` by default.

## playlist_download_report.py
- Summarizes row statuses and completion counts across playlist CSVs.
- Writes one CSV containing each track whose recorded audio file is missing, with an `output_folder` column for its original playlist destination.
- The downloader honors `output_folder`, so the exported rows can be processed together without moving tracks into one shared playlist folder.
- Errors are cleared in the exported rows so those tracks are eligible for another attempt; source/work CSVs are not modified.
- Prefers sibling `_work.csv` files when both source and work CSVs are present.
- Defaults to writing `run_logs/playlist_download_report_<timestamp>.csv`; use `--csv-out` to choose another path.

## download_missing_tracks.py
- Downloads tracks from a playlist download report CSV created by `playlist_download_report.py`.
- Uses the normal downloader settings from `downloader.config.json` and downloads each row into its `output_folder`.
- Updates download status in the report CSV as tracks are processed.
- Set `REPORT_CSV_PATH` near the top of the script to choose a default CSV; when left as `None`, the newest `run_logs/playlist_download_report_*.csv` is used.
- A CSV path passed on the command line takes priority over `REPORT_CSV_PATH`.
- Example: `python tools/download_missing_tracks.py run_logs/playlist_download_report_YYYYMMDD_HHMMSS.csv`.

## CSV reconciliation
- Reconciles audio files on disk with matching playlist CSV rows and restores output paths without downloading.
- Run with `python -m exportify_downloader.scripts.reconcile <csv-path>`.
- Use `python -m exportify_downloader.scripts.reconcile_metadata <csv-path>` to refresh tags and artwork for existing files. Existing embedded art is kept unless `--refresh-art` is passed.

## url_downloads/
- Output folder used by `download_youtube_music_url.py` for downloaded tracks.
- Created/populated as needed. Downloaded files here are git-ignored.
