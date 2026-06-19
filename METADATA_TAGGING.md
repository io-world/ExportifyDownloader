# Metadata Tagging Guide

This project writes metadata from CSV rows into downloaded audio files using ffmpeg.

## Source Fields

Metadata is derived from these CSV columns:

- Track Name
- Artist Name(s)
- Album Name
- Album Artist Name(s)
- Album Release Date
- Track Number
- Disc Number
- ISRC
- Track URI

## Written Tags

The script writes the following tag keys when values exist:

- title
- artist
- album
- album_artist
- date
- track
- disc
- isrc
- spotify_track_id
- row_key
- row_id
- comment

Notes:

- `track` is row-aware and mirrors the persistent work CSV `id` when available.
- `spotify_track_id` is parsed from `Track URI`.
- `row_key` is the explicit per-row identity key used by the work CSV.
- `row_id` also stores the persistent work CSV `id`.
- `comment` stores both row and Spotify IDs.

## Windows Compatibility

Windows sometimes reads metadata inconsistently when only container-level tags exist.
To improve compatibility, the script writes both:

- container tags (`-metadata key=value`)
- stream tags for audio stream 0 (`-metadata:s:a:0 key=value`)

## Why Some Titles Can Appear Blank

Common reasons:

- File was never retagged because `output_file` was empty for that row.
- File name contains special characters and lookup logic misses it.
- Explorer metadata cache has stale values.

If `output_file` is blank but the audio file already exists on disk, first run `reconcile_csv_files.py` to restore the CSV path reference, then run the retag flow.

## Validation Command

Use ffprobe to confirm written tags:

```powershell
ffprobe -v error -show_entries format_tags=title,artist,album,track,row_id,row_key,spotify_track_id,comment -of default=noprint_wrappers=1:nokey=0 ".\exportify.app\3_dnb_dance_floor\<file>.m4a"
```
