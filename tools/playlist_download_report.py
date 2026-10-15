#!/usr/bin/env python3
"""Root entrypoint wrapper for the playlist download report utility."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exportify_downloader.scripts.playlist_download_report import main


if __name__ == "__main__":
    raise SystemExit(main())
