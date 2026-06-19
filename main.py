#!/usr/bin/env python3
"""Root entrypoint wrapper for the packaged launcher."""

from __future__ import annotations

from exportify_downloader.launcher.main import main


if __name__ == "__main__":
    raise SystemExit(main())
