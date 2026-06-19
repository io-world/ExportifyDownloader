#!/usr/bin/env python3
"""Root entrypoint wrapper for the packaged reconcile utility."""

from __future__ import annotations

from exportify_downloader.scripts.reconcile import main


if __name__ == "__main__":
    raise SystemExit(main())
