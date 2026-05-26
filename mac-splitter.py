#!/usr/bin/env python3
"""mac-splitter.py — split an audio file into numbered sentence clips.

Run this on your Mac (or anywhere with Python 3 + ffmpeg installed).

Usage:
    python3 mac-splitter.py audio.mp3 --sentences 28
    python3 mac-splitter.py audio.mp3 --transcript transcript.txt
    python3 mac-splitter.py audio.mp3 --sentences 28 --outdir my-clips
    python3 mac-splitter.py audio.mp3 --sentences 28 --noise-db -25 --min-pause 0.5

It uses ffmpeg's silence detection to find natural sentence breaks. If
you give it `--transcript`, it counts sentences in the transcript and
uses that count. If you give it `--sentences N`, it splits into N clips.

The output is `outdir/01.mp3, 02.mp3, …` — ready to drag into the
website's "New collection" upload form.

If a particular file splits badly, try a different `--noise-db` (less
negative = more aggressive silence detection) or `--min-pause` (smaller
= more cut candidates).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def check_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if subprocess.run(
            ["which", tool], capture_output=True, text=True
        ).returncode != 0:
            sys.exit(
                f"ERROR: {tool} not found. Install with `brew install ffmpeg` on "
                "macOS or `sudo apt install ffmpeg` on Linux."
            )


def count_sentences(transcript_path: Path) -> int:
    text = transcript_path.read_text(encoding="utf-8")
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.?!])\s+(?=[A-Z\u00C0-\u017F])", text)
    return len([p for p in parts if p.strip()])


def convert_to_wav(src: Path, dest: Path) -> float:
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


def detect_silences(wav: Path, noise_db: float, min_pause: float):
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


def pick_cuts(silences, n_sentences):
    n_cuts = n_sentences - 1
    if n_cuts <= 0:
        return []
    if len(silences) < n_cuts:
        sys.exit(
            f"ERROR: only {len(silences)} pauses detected but need {n_cuts} cuts "
            f"for {n_sentences} sentences. Try --noise-db -25 (more aggressive "
            "silence detection) or --min-pause 0.25 (smaller minimum pause)."
        )
    by_dur = sorted(silences, key=lambda s: s["duration"], reverse=True)
    chosen = by_dur[:n_cuts]
    chosen.sort(key=lambda s: s["start"])
    return [s["mid"] for s in chosen]


def split(wav: Path, cuts, total_dur, out_dir: Path):
    boundaries = [0.0] + cuts + [total_dur]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{'#':>3}  {'start':>7}  {'end':>7}  {'dur':>6}")
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        out = out_dir / f"{i + 1:02d}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(wav),
                "-ss", f"{s:.3f}",
                "-to", f"{e:.3f}",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(out),
            ],
            check=True,
        )
        print(f"{i + 1:>3}  {s:7.2f}  {e:7.2f}  {e - s:6.2f}")
    print(f"\nWrote {len(boundaries) - 1} clips to {out_dir}/")


def main() -> int:
    check_tools()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio", type=Path, help="Input audio file (any ffmpeg-readable format)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sentences", type=int, help="Number of clips to produce")
    g.add_argument("--transcript", type=Path, help="Transcript file (sentences will be counted)")
    p.add_argument("--outdir", type=Path, default=None,
                   help="Output directory (default: <audio name>-clips/ next to the input)")
    p.add_argument("--noise-db", type=float, default=-30,
                   help="Silence threshold in dB (default: -30; less negative = more aggressive)")
    p.add_argument("--min-pause", type=float, default=None,
                   help="Minimum silence duration to count (seconds). "
                        "Default: 0.35 for sentence mode, 0.9 for speaker mode.")
    p.add_argument("--mode", choices=["sentences", "speakers"], default="sentences",
                   help="'sentences' splits at short pauses (~0.35s) — for read prose "
                        "like Litir Bheag. 'speakers' splits at longer pauses (~0.9s) — "
                        "for interview-style content where you want one clip per "
                        "speaker turn rather than one per sentence.")
    args = p.parse_args()

    if not args.audio.exists():
        sys.exit(f"ERROR: {args.audio} not found.")

    # If --min-pause wasn't explicitly set, choose default by mode.
    if args.min_pause is None:
        args.min_pause = 0.9 if args.mode == "speakers" else 0.35

    if args.transcript:
        if not args.transcript.exists():
            sys.exit(f"ERROR: {args.transcript} not found.")
        n_sent = count_sentences(args.transcript)
        print(f"Counted {n_sent} sentences in transcript.")
    else:
        n_sent = args.sentences

    out_dir = args.outdir or args.audio.with_suffix("").parent / f"{args.audio.stem}-clips"

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "tmp.wav"
        print(f"Converting {args.audio} to wav…")
        total = convert_to_wav(args.audio, wav)
        print(f"Duration: {total:.2f}s")
        print(f"Detecting silences (threshold {args.noise_db}dB, min duration {args.min_pause}s)…")
        silences = detect_silences(wav, args.noise_db, args.min_pause)
        print(f"Found {len(silences)} silences.")
        cuts = pick_cuts(silences, n_sent)
        print(f"Picking {len(cuts)} cut points for {n_sent} clips.\n")
        split(wav, cuts, total, out_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
