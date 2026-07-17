# Tools Folder Reference

This file explains what each script in this folder does.

## bpm_analysis.py
- Runs BPM analysis on MP3 files in a folder.
- Uses multiple sources for tempo estimation:
  - librosa
  - essentia
  - bpm-detector CLI
  - Anthropic web-search estimate (if `ANTHROPIC_API_KEY` is set)
- Writes combined results to CSV (default under `run_logs/bpm_analysis_results.csv`).
- Good for comparing BPM estimates and averaging across methods.

## check_tags.py
- Quick one-off tag inspection script for a single MP3 path.
- Prints duration, bitrate, and all ID3 frames.
- Useful for debugging metadata on a specific file.
- Note: path is currently hardcoded in the script.

## download_youtube_music_url.py
- Downloads one YouTube/YouTube Music track URL.
- Uses project config defaults from `downloader.config.json`.
- Supports cookie auth (`CookiesFromBrowser` or `CookiesFile`) and output folder overrides.
- After download, embeds:
  - core audio metadata (title/artist/album/date)
  - artwork from the best thumbnail URL
- Default output folder is `tools/url_downloads`.

## embed_artwork.py
- Finds matching image files next to MP3s and embeds them as front cover art (ID3 APIC).
- Image preference order: `.jpg`/`.jpeg`, then `.png`, then `.webp`.
- Skips tracks that already have artwork.
- Prints embedded/skipped/missing summary.
- Note: target folder is currently hardcoded in the script.

## find_new_tracks.py
- Compares audio files in a "new" folder against an "original" folder.
- Uses fuzzy filename matching (full name and title-only variants) to detect near-duplicates.
- Reports files in the new folder that do not have a close match above threshold.
- Prints missing files and writes a CSV report to `run_logs/find_new_tracks_<timestamp>.csv` by default.

## reconcile_csv_files.py
- Thin wrapper that launches the packaged reconcile command.
- Delegates execution to `exportify_downloader.scripts.reconcile.main()`.
- Use this instead of importing the package manually when you want a script entrypoint.

## url_downloads/
- Output folder used by `download_youtube_music_url.py` for downloaded tracks.
- Created/populated as needed.
