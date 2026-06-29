from pathlib import Path
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from mutagen.mp3 import MP3

FOLDER = Path(r"C:\Users\me\OneDrive\Desktop\DJ Music\Downloader\exportify.app\2_house_uk_garage")

MIME = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
}

# Prefer jpg > png > webp when multiple images exist for one track
IMAGE_PRIORITY = [".jpg", ".jpeg", ".png", ".webp"]


def find_image(mp3_path: Path) -> Path | None:
    for ext in IMAGE_PRIORITY:
        candidate = mp3_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def embed(mp3_path: Path, img_path: Path) -> None:
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    mime = MIME[img_path.suffix.lower()]
    tags["APIC"] = APIC(
        encoding=3,
        mime=mime,
        type=3,       # 3 = Cover (front)
        desc="",
        data=img_path.read_bytes(),
    )
    tags.save(mp3_path)


matched, skipped, missing = [], [], []

for mp3 in sorted(FOLDER.glob("*.mp3")):
    img = find_image(mp3)
    if img is None:
        missing.append(mp3.name)
        continue

    # Skip if APIC already present
    try:
        existing = ID3(mp3)
        if "APIC:" in existing or any(k.startswith("APIC") for k in existing.keys()):
            skipped.append(f"{mp3.name}  (already has art)")
            continue
    except ID3NoHeaderError:
        pass

    embed(mp3, img)
    matched.append(f"{mp3.name}  <--  {img.name}")

print(f"\n=== Embedded artwork ({len(matched)}) ===")
for line in matched:
    print(" ", line)

print(f"\n=== Skipped — art already present ({len(skipped)}) ===")
for line in skipped:
    print(" ", line)

print(f"\n=== No image found ({len(missing)}) ===")
for line in missing:
    print(" ", line)
