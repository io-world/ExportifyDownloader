#!/usr/bin/env python3
"""Print duration, bitrate, and every ID3 frame of an MP3 file."""

import sys

from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/check_tags.py <file.mp3>")
        return 1
    path = sys.argv[1]

    try:
        audio = MP3(path)
        print(f"Duration : {audio.info.length:.1f}s")
        print(f"Bitrate  : {audio.info.bitrate // 1000} kbps")
        print()

        tags = ID3(path)
        for key, value in sorted(tags.items()):
            print(f"{key:30s} {value}")
    except ID3NoHeaderError:
        print("No ID3 tags found on this file.")
    except FileNotFoundError:
        print("File not found.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
