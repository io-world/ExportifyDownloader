# Exportify Downloader

Project documentation now lives in `docs/`.

Start here:
- `docs/README.md`: user-facing overview and usage
- `docs/IMPLEMENTATION.md`: engineering and architecture notes
- `docs/MAINTENANCE.md`: operational commands and recovery steps
- `docs/METADATA_TAGGING.md`: metadata behavior and validation

Current workflow highlights:
- `DownloadEnabled` in `downloader.config.json` controls whether runs stop after candidate resolution or continue into download.
- `reconcile_metadata.py` refreshes metadata from the CSV for existing local files without downloading anything.
