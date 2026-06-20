"""Shared audio pause-splitting logic.

This is the single source of truth for threshold-driven ("--mode pauses")
splitting. Both mac-splitter.py (CLI, on the Mac) and the in-app upload
splitter (app/upload_split.py, on the Pi) import from here so the cut
logic can never drift between them.

Pure functions only — no DB, no web, no argparse. ffmpeg/ffprobe are the
only external dependency.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List


# Default knobs for pause mode. Kept here so the CLI and the app agree.
DEFAULT_NOISE_DB = -30.0
DEFAULT_MIN_PAUSE = 0.6
DEFAULT_MIN_CLIP_LEN = 3.5
DEFAULT_MAX_CLIP_LEN = 18.0

# Sensitivity presets offered by the in-app "re-run" step. Each is a
# (noise_db, min_pause) pair, from gentlest (fewer, longer clips) to most
# aggressive (more, shorter clips).
SENSITIVITY_PRESETS: Dict[str, Dict[str, float]] = {
    "gentle":   {"noise_db": -33.0, "min_pause": 0.9},
    "normal":   {"noise_db": -30.0, "min_pause": 0.6},
    "fine":     {"noise_db": -27.0, "min_pause": 0.4},
    "finest":   {"noise_db": -24.0, "min_pause": 0.3},
}


def convert_to_wav(src: Path, dest: Path) -> float:
    """Decode any ffmpeg-readable input to mono 44.1k WAV. Returns duration (s)."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(src),
            "-ar", "44100", "-ac", "1",
            str(dest),
        ],
        check=True,
    )
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(dest),
        ],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def detect_silences(wav: Path, noise_db: float, min_pause: float) -> List[dict]:
    """Run ffmpeg silencedetect and parse start/end/duration/mid for each gap."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(wav),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_pause}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    out = proc.stderr
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start: ([\d.]+)", out)]
    ends = [
        (float(m.group(1)), float(m.group(2)))
        for m in re.finditer(
            r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", out
        )
    ]
    silences = []
    for s, (e, d) in zip(starts, ends):
        silences.append({"start": s, "end": e, "duration": d, "mid": (s + e) / 2})
    return silences


def pick_pause_cuts(silences, total_dur, min_pause, min_clip_len, max_clip_len):
    """Threshold-driven cut selection.

    Keeps EVERY pause at or above min_pause as a cut, then tidies up:
      - clips shorter than min_clip_len are merged into a neighbour, by
        dropping the weaker (shorter) of the two pauses bounding them;
      - clips longer than max_clip_len are force-split, at the longest
        pause found inside them, or by time if there is no pause at all.

    Returns a sorted list of cut times (seconds). This is a verbatim port
    of the logic that was in mac-splitter.py.
    """
    def clips_for(times):
        bounds = [0.0] + list(times) + [total_dur]
        return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    cut_objs = sorted(
        (
            {"t": s["mid"], "dur": s["duration"]}
            for s in silences
            if s["duration"] >= min_pause
        ),
        key=lambda c: c["t"],
    )

    # --- merge clips that are too short ---
    for _ in range(100000):
        times = [c["t"] for c in cut_objs]
        clips = clips_for(times)
        idx = min(range(len(clips)), key=lambda i: clips[i][1] - clips[i][0])
        s, e = clips[idx]
        if (e - s) >= min_clip_len or not cut_objs:
            break
        left = cut_objs[idx - 1] if idx - 1 >= 0 else None
        right = cut_objs[idx] if idx < len(cut_objs) else None
        if left is None:
            cut_objs.pop(idx)
        elif right is None:
            cut_objs.pop(idx - 1)
        elif left["dur"] <= right["dur"]:
            cut_objs.pop(idx - 1)
        else:
            cut_objs.pop(idx)

    # --- force-split clips that are too long ---
    cuts = sorted(c["t"] for c in cut_objs)
    all_pauses = sorted((s["mid"], s["duration"]) for s in silences)
    for _ in range(100000):
        clips = clips_for(cuts)
        idx = max(range(len(clips)), key=lambda i: clips[i][1] - clips[i][0])
        s, e = clips[idx]
        if (e - s) <= max_clip_len:
            break
        inside = [(t, d) for (t, d) in all_pauses if s < t < e]
        if inside:
            new_cut = max(inside, key=lambda x: x[1])[0]
        else:
            new_cut = (s + e) / 2
        cuts = sorted(cuts + [new_cut])

    return cuts


def split_to_files(wav: Path, cuts, total_dur: float, out_dir: Path,
                   name_fn) -> List[dict]:
    """Cut `wav` at `cuts` into MP3s in `out_dir`.

    `name_fn(i)` returns the filename (no directory) for clip i (1-based).
    Returns a list of {position, filename, start, end, duration} dicts.
    """
    boundaries = [0.0] + list(cuts) + [total_dur]
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: List[dict] = []
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        fname = name_fn(i + 1)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(wav),
                "-ss", f"{s:.3f}",
                "-to", f"{e:.3f}",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(out_dir / fname),
            ],
            check=True,
        )
        clips.append({
            "position": i + 1,
            "filename": fname,
            "start": round(s, 2),
            "end": round(e, 2),
            "duration": round(e - s, 2),
        })
    return clips
