#!/usr/bin/env python3
"""
BPM Analysis Pipeline
======================
Reads a folder of mp3 files, runs three independent BPM detectors
(librosa, essentia, libraz/bpm-detector), gets an independent BPM estimate
from Claude via live web search, and writes a combined CSV with all
readings, per-tool confidence, and the average BPM.

SETUP
-----
pip install librosa essentia mutagen requests --break-system-packages
# essentia install can be finicky on some platforms; see note below.
pip install bpm-detector  # https://github.com/libraz/bpm-detector

export ANTHROPIC_API_KEY=your_key_here

INPUT CSV FORMAT
----------------
A folder containing mp3 files, scanned recursively.

USAGE
-----
python bpm_analysis.py input_mp3s output_results.csv
"""

import csv
import json
import os
import sys
import subprocess
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

INPUT_FOLDER = Path(r"C:\Users\me\OneDrive\Desktop\DJ Music\Randy DJ Music\2. House Garage UK")
RUN_LOGS_DIR = Path("run_logs")
OUTPUT_CSV_PATH = RUN_LOGS_DIR / "bpm_analysis_results.csv"

# ---- Optional heavy imports, loaded lazily with clear errors ----
def _try_import(name):
    try:
        return __import__(name)
    except ImportError:
        return None


def get_song_metadata(mp3_path: str):
    """Pull artist/title from ID3 tags, fall back to filename."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3
        tags = EasyID3(mp3_path)
        artist = tags.get("artist", [None])[0]
        title = tags.get("title", [None])[0]
        if artist and title:
            return artist, title
    except Exception:
        pass
    # fallback: filename without extension, best-effort split on " - "
    stem = Path(mp3_path).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return None, stem


def analyze_librosa(mp3_path: str):
    librosa = _try_import("librosa")
    if librosa is None:
        return None, "librosa not installed"
    try:
        y, sr = librosa.load(mp3_path, sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        # librosa doesn't give a native confidence score; we proxy with
        # onset strength consistency as a rough stand-in
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        confidence = float(min(1.0, onset_env.std() / (onset_env.mean() + 1e-6) / 2))
        return round(bpm, 2), round(confidence, 2)
    except Exception as e:
        return None, f"error: {e}"


def analyze_essentia(mp3_path: str):
    es = _try_import("essentia.standard")
    if es is None:
        return None, "essentia not installed"
    try:
        loader = es.MonoLoader(filename=mp3_path)
        audio = loader()
        rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
        bpm, beats, beats_confidence, _, _ = rhythm_extractor(audio)
        # essentia's beats_confidence is roughly 0-5.32, normalize to 0-1
        norm_conf = round(min(1.0, beats_confidence / 5.32), 2)
        return round(float(bpm), 2), norm_conf
    except Exception as e:
        return None, f"error: {e}"


def analyze_bpm_detector(mp3_path: str):
    """Uses libraz/bpm-detector's CLI since its Python API expects wav."""
    try:
        result = subprocess.run(
            ["bpm-detector", "--rhythm", mp3_path],
            capture_output=True, text=True, timeout=120
        )
        out = result.stdout
        bpm = None
        for line in out.splitlines():
            if "BPM" in line.upper():
                digits = "".join(c for c in line if c.isdigit() or c == ".")
                if digits:
                    bpm = float(digits)
                    break
        if bpm is None:
            return None, "could not parse output"
        return round(bpm, 2), None  # tool doesn't expose a confidence score
    except FileNotFoundError:
        return None, "bpm-detector not installed"
    except Exception as e:
        return None, f"error: {e}"


def analyze_llm_web_research(artist, title):
    """Independent BPM estimate via Claude with live web search."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"
    if not artist or not title:
        query_desc = title or "unknown track"
    else:
        query_desc = f"{artist} - {title}"

    prompt = (
        f'Search the web to find the BPM (tempo) of the song "{query_desc}". '
        f"Check sites like Tunebat, SongBPM, or similar BPM databases. "
        f"Respond ONLY with a JSON object, no other text: "
        f'{{"bpm": <number or null>, "confidence": <0.0-1.0>, "source": "<short source name>"}}'
    )

    try:
        payload = json.dumps(
            {
                "model": "claude-sonnet-4-6",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        full_text = "\n".join(text_blocks).strip()
        # strip code fences if present
        full_text = full_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(full_text)
        bpm = parsed.get("bpm")
        confidence = parsed.get("confidence")
        return (round(float(bpm), 2) if bpm else None), confidence
    except urlerror.HTTPError as e:
        return None, f"error: HTTP {e.code}"
    except urlerror.URLError as e:
        return None, f"error: {e.reason}"
    except Exception as e:
        return None, f"error: {e}"


def main():
    input_folder = Path(sys.argv[1]) if len(sys.argv) >= 2 else INPUT_FOLDER
    output_csv = Path(sys.argv[2]) if len(sys.argv) >= 3 else OUTPUT_CSV_PATH

    RUN_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) > 3:
        print("Usage: python bpm_analysis.py [input_mp3s] [output_results.csv]")
        sys.exit(1)

    if not input_folder.exists() or not input_folder.is_dir():
        print(f"[error] input folder not found: {input_folder}")
        sys.exit(1)

    paths = sorted(
        str(path)
        for path in input_folder.rglob("*.mp3")
        if path.is_file()
    )

    if not paths:
        print(f"[error] no mp3 files found in: {input_folder}")
        sys.exit(1)

    rows = []
    for path in paths:
        if not os.path.exists(path):
            print(f"[skip] file not found: {path}")
            continue

        print(f"Analyzing: {path}")
        artist, title = get_song_metadata(path)
        song_name = f"{artist} - {title}" if artist else title

        librosa_bpm, librosa_conf = analyze_librosa(path)
        essentia_bpm, essentia_conf = analyze_essentia(path)
        detector_bpm, detector_conf = analyze_bpm_detector(path)
        llm_bpm, llm_conf = analyze_llm_web_research(artist, title)

        bpm_values = [b for b in [librosa_bpm, essentia_bpm, detector_bpm, llm_bpm] if b is not None]
        average_bpm = round(sum(bpm_values) / len(bpm_values), 2) if bpm_values else None

        rows.append({
            "song_name": song_name,
            "librosa_bpm": librosa_bpm, "librosa_confidence": librosa_conf,
            "essentia_bpm": essentia_bpm, "essentia_confidence": essentia_conf,
            "bpm_detector_bpm": detector_bpm, "bpm_detector_confidence": detector_conf,
            "llm_research_bpm": llm_bpm, "llm_research_confidence": llm_conf,
            "average_bpm": average_bpm,
        })

    fieldnames = [
        "song_name",
        "librosa_bpm", "librosa_confidence",
        "essentia_bpm", "essentia_confidence",
        "bpm_detector_bpm", "bpm_detector_confidence",
        "llm_research_bpm", "llm_research_confidence",
        "average_bpm",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Wrote {len(rows)} rows to {output_csv}")


if __name__ == "__main__":
    main()