#!/usr/bin/env python3
"""
BPM Analysis Pipeline
======================
Reads a folder of mp3 files (recursively), runs three independent BPM detectors
(librosa, essentia, libraz/bpm-detector), gets an independent BPM estimate
from Claude via live web search, and writes a combined CSV with all readings,
per-tool confidence, and a consensus BPM.

Detectors often report half or double the real tempo (87 vs 174 for DnB), so each
reading is folded into one octave, [--min-bpm, 2 * --min-bpm], before taking the
median. The default range of 88-176 suits house, garage, breaks and DnB.

Rows are written as each file finishes. Rerunning with the same output CSV skips
files that are already in it, so an interrupted run can be resumed.

SETUP
-----
pip install librosa essentia mutagen anthropic
# essentia install can be finicky on some platforms.
pip install bpm-detector  # https://github.com/libraz/bpm-detector

set ANTHROPIC_API_KEY=your_key_here   (optional; skips the web-research column if unset)

USAGE
-----
python tools/bpm_analysis.py [input_folder] [output_results.csv] [--min-bpm 88] [--fresh]
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_FOLDER = Path(r"C:\Users\me\OneDrive\Desktop\DJ Music\Randy DJ Music\2. House Garage UK")
RUN_LOGS_DIR = REPO_ROOT / "run_logs"
OUTPUT_CSV_PATH = RUN_LOGS_DIR / "bpm_analysis_results.csv"

LLM_MODEL = "claude-sonnet-5-5"
DEFAULT_MIN_BPM = 88.0

FIELDNAMES = [
    "file_path",
    "song_name",
    "librosa_bpm", "librosa_confidence",
    "essentia_bpm", "essentia_confidence",
    "bpm_detector_bpm",
    "llm_research_bpm", "llm_research_confidence", "llm_research_source",
    "consensus_bpm",
    "bpm_spread",
    "notes",
]

# A reading is (bpm or None, confidence or None, note). The note explains a missing value.
Reading = Tuple[Optional[float], Optional[float], str]


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def get_song_metadata(mp3_path: str) -> Tuple[Optional[str], str]:
    """Pull artist/title from ID3 tags, fall back to filename."""
    try:
        from mutagen.easyid3 import EasyID3

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


def analyze_librosa(mp3_path: str) -> Reading:
    librosa = _try_import("librosa")
    if librosa is None:
        return None, None, "librosa not installed"
    try:
        y, sr = librosa.load(mp3_path, sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        # librosa has no native tempo confidence; onset-strength variability is a rough
        # stand-in for "how pronounced the beat is", not a probability the BPM is right.
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        confidence = float(min(1.0, onset_env.std() / (onset_env.mean() + 1e-6) / 2))
        return round(bpm, 2), round(confidence, 2), ""
    except Exception as e:
        return None, None, f"librosa error: {e}"


def analyze_essentia(mp3_path: str) -> Reading:
    es = _try_import("essentia.standard")
    if es is None:
        return None, None, "essentia not installed"
    try:
        audio = es.MonoLoader(filename=mp3_path)()
        bpm, _, beats_confidence, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
        # essentia's beats_confidence is roughly 0-5.32, normalize to 0-1
        norm_conf = round(min(1.0, beats_confidence / 5.32), 2)
        return round(float(bpm), 2), norm_conf, ""
    except Exception as e:
        return None, None, f"essentia error: {e}"


_BPM_AFTER = re.compile(r"bpm\D{0,12}?(\d{2,3}(?:\.\d+)?)", re.IGNORECASE)
_BPM_BEFORE = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*bpm", re.IGNORECASE)


def parse_bpm_detector_output(text: str) -> Optional[float]:
    for line in text.splitlines():
        match = _BPM_BEFORE.search(line) or _BPM_AFTER.search(line)
        if match:
            return float(match.group(1))
    return None


def analyze_bpm_detector(mp3_path: str) -> Reading:
    """Uses libraz/bpm-detector's CLI since its Python API expects wav. It reports no confidence."""
    try:
        result = subprocess.run(
            ["bpm-detector", "--rhythm", mp3_path],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return None, None, "bpm-detector not installed"
    except Exception as e:
        return None, None, f"bpm-detector error: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return None, None, f"bpm-detector exit {result.returncode}: {detail[-1] if detail else ''}"
    bpm = parse_bpm_detector_output(result.stdout)
    if bpm is None:
        return None, None, "bpm-detector: could not parse output"
    return round(bpm, 2), None, ""


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Last {...} object in the text that parses as JSON (the model may add prose or citations)."""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text))):
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


_llm_client = None


def analyze_llm_web_research(artist: Optional[str], title: str) -> Tuple[Optional[float], Optional[float], str, str]:
    """Independent BPM estimate via Claude with live web search. Returns (bpm, confidence, source, note)."""
    global _llm_client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, None, "", "ANTHROPIC_API_KEY not set"
    anthropic = _try_import("anthropic")
    if anthropic is None:
        return None, None, "", "anthropic not installed"
    if _llm_client is None:
        _llm_client = anthropic.Anthropic()

    query_desc = f"{artist} - {title}" if artist and title else (title or "unknown track")
    prompt = (
        f'Search the web to find the BPM (tempo) of the song "{query_desc}". '
        "Check sites like Tunebat, SongBPM, Beatport, or similar BPM databases. "
        "End your reply with a single JSON object on its own line: "
        '{"bpm": <number or null>, "confidence": <0.0-1.0>, "source": "<short source name>"}'
    )
    messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

    try:
        response = None
        for _ in range(3):  # web search can pause a long server-side turn; resume it
            response = _llm_client.beta.messages.create(
                model=LLM_MODEL,
                max_tokens=4000,
                output_config={"effort": "low"},
                # Re-run on Anthropic's recommended fallback model if this one declines.
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
                messages=messages,
            )
            if response.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
    except anthropic.RateLimitError:
        return None, None, "", "llm error: rate limited"
    except anthropic.APIStatusError as e:
        return None, None, "", f"llm error: HTTP {e.status_code}"
    except anthropic.APIConnectionError as e:
        return None, None, "", f"llm error: connection failed ({e})"
    except Exception as e:  # noqa: BLE001 - one bad lookup shouldn't stop the whole run
        return None, None, "", f"llm error: {e}"

    if response is None or response.stop_reason == "refusal":
        return None, None, "", "llm: request declined"

    text = "\n".join(block.text for block in response.content if block.type == "text")
    parsed = _extract_json_object(text)
    if parsed is None:
        return None, None, "", "llm: no JSON in reply"

    try:
        bpm = float(parsed["bpm"]) if parsed.get("bpm") else None
        confidence = float(parsed["confidence"]) if parsed.get("confidence") is not None else None
    except (TypeError, ValueError):
        return None, None, "", f"llm: unparseable values {parsed}"
    source = str(parsed.get("source") or "")
    return (round(bpm, 2) if bpm else None), confidence, source, ("" if bpm else "llm: BPM not found")


def fold_bpm(bpm: float, min_bpm: float) -> float:
    """Halve or double until the BPM lands in [min_bpm, 2 * min_bpm]."""
    while bpm < min_bpm:
        bpm *= 2
    while bpm > 2 * min_bpm:
        bpm /= 2
    return bpm


def consensus(values: List[float], min_bpm: float) -> Tuple[Optional[float], Optional[float]]:
    """Median of octave-folded readings, plus the spread (max - min) as a disagreement signal."""
    if not values:
        return None, None
    folded = [fold_bpm(v, min_bpm) for v in values]
    return round(statistics.median(folded), 2), round(max(folded) - min(folded), 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate BPM for every mp3 in a folder.")
    parser.add_argument("input_folder", type=Path, nargs="?", default=INPUT_FOLDER)
    parser.add_argument("output_csv", type=Path, nargs="?", default=OUTPUT_CSV_PATH)
    parser.add_argument(
        "--min-bpm",
        type=float,
        default=DEFAULT_MIN_BPM,
        help=f"Lower bound of the one-octave range readings are folded into (default: {DEFAULT_MIN_BPM:g}).",
    )
    parser.add_argument("--fresh", action="store_true", help="Overwrite the output CSV instead of resuming it.")
    return parser.parse_args()


def load_done_paths(output_csv: Path) -> Optional[set]:
    """File paths already in the output CSV, or None if it has a different column layout."""
    with output_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDNAMES:
            return None
        return {row["file_path"] for row in reader if row.get("file_path")}


def main() -> int:
    args = parse_args()
    input_folder: Path = args.input_folder
    output_csv: Path = args.output_csv

    if not input_folder.is_dir():
        print(f"[error] input folder not found: {input_folder}")
        return 1

    paths = sorted(str(path) for path in input_folder.rglob("*.mp3") if path.is_file())
    if not paths:
        print(f"[error] no mp3 files found in: {input_folder}")
        return 1

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    done: set = set()
    if output_csv.exists() and not args.fresh:
        existing = load_done_paths(output_csv)
        if existing is None:
            print(f"[error] {output_csv} has a different column layout; pass --fresh to overwrite it.")
            return 1
        done = existing

    todo = [p for p in paths if p not in done]
    if done:
        print(f"Resuming: {len(paths) - len(todo)} already analyzed, {len(todo)} to go.")

    write_header = args.fresh or not output_csv.exists()
    with output_csv.open("w" if write_header else "a", newline="", encoding="utf-8-sig" if write_header else "utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for count, path in enumerate(todo, start=1):
            print(f"[{count}/{len(todo)}] Analyzing: {path}")
            artist, title = get_song_metadata(path)

            librosa_bpm, librosa_conf, librosa_note = analyze_librosa(path)
            essentia_bpm, essentia_conf, essentia_note = analyze_essentia(path)
            detector_bpm, _, detector_note = analyze_bpm_detector(path)
            llm_bpm, llm_conf, llm_source, llm_note = analyze_llm_web_research(artist, title)

            bpm_values = [b for b in (librosa_bpm, essentia_bpm, detector_bpm, llm_bpm) if b is not None]
            consensus_bpm, spread = consensus(bpm_values, args.min_bpm)

            writer.writerow({
                "file_path": path,
                "song_name": f"{artist} - {title}" if artist else title,
                "librosa_bpm": librosa_bpm, "librosa_confidence": librosa_conf,
                "essentia_bpm": essentia_bpm, "essentia_confidence": essentia_conf,
                "bpm_detector_bpm": detector_bpm,
                "llm_research_bpm": llm_bpm, "llm_research_confidence": llm_conf,
                "llm_research_source": llm_source,
                "consensus_bpm": consensus_bpm,
                "bpm_spread": spread,
                "notes": "; ".join(n for n in (librosa_note, essentia_note, detector_note, llm_note) if n),
            })
            f.flush()

    print(f"\nDone. Analyzed {len(todo)} files; results in {output_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
