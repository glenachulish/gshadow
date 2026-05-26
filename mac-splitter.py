#!/usr/bin/env python3
"""mac-splitter.py — split an audio file into numbered clips.

Run this on your Mac (or anywhere with Python 3 + ffmpeg installed).

Three modes:

  --mode sentences   Split read prose into one clip per sentence.
                     Needs --sentences N or --transcript FILE.
                       python3 mac-splitter.py letter.mp3 --sentences 28
                       python3 mac-splitter.py letter.mp3 --transcript t.txt

  --mode speakers    Split interview-style audio at longer pauses, one
                     clip per speaker turn. Needs --sentences N or
                     --transcript FILE for the count.

  --mode pauses      Split at every natural pause — NO target count.
                     For audiobooks and other long recordings where you
                     don't know the clip count in advance.
                       python3 mac-splitter.py chapter1.mp3 --mode pauses

It uses ffmpeg's silence detection to find natural breaks.

The output is `outdir/01.mp3, 02.mp3, …` — ready to drag into the
website's "New collection" upload form.

AUDIOBOOKS: split the book into chapters first (most audiobook files
carry chapter markers), then run this once per chapter so each chapter
becomes its own collection. A whole book as a single collection would
be thousands of clips on one page.

If a file splits badly, try a different --noise-db (less negative =
more aggressive silence detection). In --mode pauses you can also tune
--min-pause, --min-clip-len and --max-clip-len.
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
    """Count-driven cut selection: pick the (n-1) longest pauses.

    Used by --mode sentences and --mode speakers.
    """
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


def pick_pause_cuts(silences, total_dur, min_pause, min_clip_len, max_clip_len):
    """Threshold-driven cut selection for --mode pauses.

    Unlike pick_cuts (which picks a fixed number of the longest pauses),
    this keeps EVERY pause at or above min_pause as a cut, then tidies up:

      - clips shorter than min_clip_len are merged into a neighbour, by
        dropping the weaker (shorter) of the two pauses bounding them;
      - clips longer than max_clip_len are force-split, at the longest
        pause found inside them, or by time if there is no pause at all.

    Returns a sorted list of cut times (seconds).
    """
    def clips_for(times):
        bounds = [0.0] + list(times) + [total_dur]
        return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    # Start with every pause at or above the breath-group threshold.
    cut_objs = sorted(
        (
            {"t": s["mid"], "dur": s["duration"]}
            for s in silences
            if s["duration"] >= min_pause
        ),
        key=lambda c: c["t"],
    )

    # --- merge clips that are too short ---
    # Each iteration removes one cut, so this is guaranteed to terminate;
    # the range() is just a hard safety stop.
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
            cut_objs.pop(idx)            # first clip: drop its end cut
        elif right is None:
            cut_objs.pop(idx - 1)        # last clip: drop its start cut
        elif left["dur"] <= right["dur"]:
            cut_objs.pop(idx - 1)        # merge across the weaker pause
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
            new_cut = (s + e) / 2        # no pause at all: cut by time
        cuts = sorted(cuts + [new_cut])

    return cuts


def split(wav: Path, cuts, total_dur, out_dir: Path):
    boundaries = [0.0] + list(cuts) + [total_dur]
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
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("audio", type=Path, help="Input audio file (any ffmpeg-readable format)")
    # Not required: --mode pauses needs neither of these. The count-driven
    # modes are validated by hand further down.
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--sentences", type=int, help="Number of clips to produce")
    g.add_argument("--transcript", type=Path, help="Transcript file (sentences will be counted)")
    p.add_argument("--outdir", type=Path, default=None,
                   help="Output directory (default: <audio name>-clips/ next to the input)")
    p.add_argument("--noise-db", type=float, default=-30,
                   help="Silence threshold in dB (default: -30; less negative = more aggressive)")
    p.add_argument("--min-pause", type=float, default=None,
                   help="Minimum silence duration to count as a break (seconds). "
                        "Default: 0.35 (sentences), 0.9 (speakers), 0.6 (pauses).")
    p.add_argument("--mode", choices=["sentences", "speakers", "pauses"], default="sentences",
                   help="'sentences' splits at short pauses (~0.35s) — for read prose "
                        "like Litir Bheag. 'speakers' splits at longer pauses (~0.9s) — "
                        "for interview-style content, one clip per speaker turn. "
                        "'pauses' splits at EVERY natural pause with no target count — "
                        "for audiobooks and other long recordings.")
    p.add_argument("--min-clip-len", type=float, default=None,
                   help="(--mode pauses only) Merge clips shorter than this many "
                        "seconds into a neighbour. Default: 3.5")
    p.add_argument("--max-clip-len", type=float, default=None,
                   help="(--mode pauses only) Force-split clips longer than this "
                        "many seconds. Default: 18")
    args = p.parse_args()

    if not args.audio.exists():
        sys.exit(f"ERROR: {args.audio} not found.")

    # Mode-dependent default for --min-pause.
    if args.min_pause is None:
        args.min_pause = {"sentences": 0.35, "speakers": 0.9, "pauses": 0.6}[args.mode]

    out_dir = args.outdir or args.audio.with_suffix("").parent / f"{args.audio.stem}-clips"

    # ------------------------------------------------------------------
    # --mode pauses : threshold-driven, no count needed (audiobooks)
    # ------------------------------------------------------------------
    if args.mode == "pauses":
        if args.sentences or args.transcript:
            print("Note: --sentences / --transcript are ignored in --mode pauses.\n")
        if args.min_clip_len is None:
            args.min_clip_len = 3.5
        if args.max_clip_len is None:
            args.max_clip_len = 18.0
        if args.min_clip_len >= args.max_clip_len:
            sys.exit("ERROR: --min-clip-len must be less than --max-clip-len.")

        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "tmp.wav"
            print(f"Converting {args.audio} to wav…")
            total = convert_to_wav(args.audio, wav)
            print(f"Duration: {total:.2f}s ({total / 60:.1f} min)")
            print(f"Detecting pauses (threshold {args.noise_db}dB)…")
            silences = detect_silences(wav, args.noise_db, 0.20)
            print(f"Found {len(silences)} candidate pauses.")
            cuts = pick_pause_cuts(
                silences, total, args.min_pause,
                args.min_clip_len, args.max_clip_len,
            )
            print(
                f"Producing {len(cuts) + 1} clips "
                f"(pause \u2265 {args.min_pause}s, "
                f"clip length {args.min_clip_len}\u2013{args.max_clip_len}s).\n"
            )
            split(wav, cuts, total, out_dir)
        return 0

    # ------------------------------------------------------------------
    # --mode sentences / speakers : count-driven (unchanged behaviour)
    # ------------------------------------------------------------------
    if not args.sentences and not args.transcript:
        sys.exit(
            f"ERROR: --mode {args.mode} needs either --sentences N or "
            "--transcript FILE so it knows how many clips to produce. "
            "(For audiobooks with no known count, use --mode pauses.)"
        )

    if args.transcript:
        if not args.transcript.exists():
            sys.exit(f"ERROR: {args.transcript} not found.")
        n_sent = count_sentences(args.transcript)
        print(f"Counted {n_sent} sentences in transcript.")
    else:
        n_sent = args.sentences

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
