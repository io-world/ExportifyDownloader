#!/usr/bin/env python3
"""Root entrypoint wrapper for the CSV completion report utility."""

from __future__ import annotations

from exportify_downloader.scripts.check_csv_download_completion import main


if __name__ == "__main__":
    raise SystemExit(main())