#!/usr/bin/env python3
"""Candidate matching and scoring logic."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from downloader_utils import normalize_text

VERSION_KEYWORDS = {
    "remix",
    "vip",
    "live",
    "acoustic",
    "instrumental",
    "edit",
    "radio",
    "extended",
    "bootleg",
    "cover",
    "rework",
    "flip",
    "mashup",
}

NOISY_KEYWORDS = {
    "nightcore",
    "sped up",
    "slowed",
    "reverb",
    "bass boosted",
    "8d",
    "hour",
    "lyrics",
    "lyric",
    "karaoke",
    "compilation",
}


def has_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return phrase in text


def track_version_keywords(track: str) -> List[str]:
    norm = normalize_text(track)
    present: List[str] = []
    for key in VERSION_KEYWORDS:
        if has_phrase(norm, key):
            present.append(key)
    return present


def count_token_hits(tokens: List[str], *fields: str) -> int:
    if not tokens:
        return 0
    merged = " ".join(fields)
    return sum(1 for token in tokens if token and token in merged)


def token_overlap_ratio(tokens: List[str], *fields: str) -> float:
    if not tokens:
        return 0.0
    hits = count_token_hits(tokens, *fields)
    return hits / max(1, len(tokens))


def score_candidate(
    candidate: Dict[str, object],
    expected_duration_s: int,
    artist_tokens: List[str],
    track_tokens: List[str],
    required_versions: List[str],
    tolerance: int,
) -> Optional[Tuple[int, int]]:
    duration = candidate.get("duration")
    if not isinstance(duration, int):
        return None

    delta = abs(duration - expected_duration_s)
    # SpotDL-style behavior: prefer best weighted result, but reject extreme duration misses.
    if delta > max(tolerance * 2, 20):
        return None

    title = normalize_text(str(candidate.get("title", "")))
    uploader = normalize_text(str(candidate.get("uploader", "")))
    combined = f"{title} {uploader}".strip()

    track_hits = count_token_hits(track_tokens, title)
    artist_hits = count_token_hits(artist_tokens, title, uploader)
    track_overlap = token_overlap_ratio(track_tokens, title)
    artist_overlap = token_overlap_ratio(artist_tokens, title, uploader)

    # Guard against obviously unrelated results while still allowing weighted ranking.
    if track_overlap < 0.30:
        return None
    if artist_tokens and artist_overlap < 0.20:
        return None

    penalty = 0
    for noisy in NOISY_KEYWORDS:
        if has_phrase(combined, noisy):
            penalty += 90

    # Version markers are preferred, not absolute hard-fails.
    for version in required_versions:
        if version not in combined:
            penalty += 120

    # Penalize version mismatch when candidate has extra version words not present in track metadata.
    candidate_versions = [v for v in VERSION_KEYWORDS if has_phrase(combined, v)]
    for version in candidate_versions:
        if version not in required_versions:
            penalty += 45

    if has_phrase(combined, "official audio"):
        penalty -= 30
    if has_phrase(uploader, "topic"):
        penalty -= 25

    # Lower score is better.
    # Weighting favors title/artist overlap heavily, then duration proximity.
    score = (
        delta * 35
        - int(track_overlap * 280)
        - int(artist_overlap * 180)
        - (track_hits * 18 + artist_hits * 12)
        + penalty
    )
    return score, delta


def choose_candidate(
    candidates: List[Dict[str, object]],
    expected_duration_s: int,
    artist: str,
    track: str,
    tolerance: int,
) -> Optional[Tuple[Dict[str, object], int]]:
    artist_tokens = [t for t in normalize_text(artist).split(" ") if len(t) >= 3]
    track_tokens = [t for t in normalize_text(track).split(" ") if len(t) >= 3]
    required_versions = track_version_keywords(track)

    best: Optional[Tuple[Dict[str, object], int, int]] = None
    for cand in candidates:
        scored = score_candidate(
            cand,
            expected_duration_s,
            artist_tokens,
            track_tokens,
            required_versions,
            tolerance,
        )
        if scored is None:
            continue
        score, delta = scored
        if best is None or score < best[2]:
            best = (cand, delta, score)

    if best is None:
        return None
    return best[0], best[1]
