from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3

path = r"C:\Users\me\OneDrive\Desktop\DJ Music\Downloader\exportify.app\3_dnb_dance_floor\[IVY] - Flow.mp3"

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
