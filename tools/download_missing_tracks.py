#!/usr/bin/env python3
"""Root entrypoint wrapper for downloading tracks from a report CSV."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from exportify_downloader.scripts.download_missing_tracks import main

# Set this to a report CSV path to use it by default, or leave None to use the
# most recently generated report in run_logs. A command-line path takes priority.
REPORT_CSV_PATH: Path | None = None


if __name__ == "__main__":
    raise SystemExit(main(REPORT_CSV_PATH))
