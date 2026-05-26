"""URL-import pipeline: download audio, split on silences to match
sentence count, create a collection with one clip per sentence.

Runs as a background task via FastAPI's BackgroundTasks. Concurrency
limited to one job at a time by a process-level lock — the Pi 3B+
doesn't have enough RAM to run two ffmpeg jobs in parallel.
"""
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .adapters import FetchResult, fetch
from .db import _open

# One global lock: only one import can run at a time on this small Pi.
_import_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _http_download(url: str, dest: Path, timeout: int = 60) -> None:
    """Stream a URL to a local file with a browser-like User-Agent."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f, length=64 * 1024)


def _convert_to_wav(src: Path, dest: Path) -> float:
    """Convert any audio format to 44.1k mono WAV. Returns duration in seconds."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(src),
            "-ar", "44100", "-ac", "1",
            str(dest),
        ],
        check=True,
    )
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(probe.stdout.strip())


@dataclass
class _Silence:
    start: float
    end: float

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2

    @property
    def duration(self) -> float:
        return self.end - self.start


def _detect_silences(wav: Path, noise_db: int = -30, min_dur: float = 0.35) -> List[_Silence]:
    """Run ffmpeg's silencedetect filter, return parsed silences."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", str(wav),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    out = proc.stderr  # silencedetect writes to stderr
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start: ([\d.]+)", out)]
    ends_durs = [
        (float(m.group(1)), float(m.group(2)))
        for m in re.finditer(
            r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", out
        )
    ]
    silences = []
    for s, (e, _d) in zip(starts, ends_durs):
        silences.append(_Silence(start=s, end=e))
    return silences


def _detect_silences_with_fallback(wav: Path, mode: str, n_cuts_needed: int) -> List[_Silence]:
    """Try a sequence of (noise_db, min_dur) configs until we get enough
    silences for the requested number of cuts. The configs progress from
    conservative (clean studio audio) toward aggressive (broadcast with
    background music).

    For 'sentences' mode (prose readings), the audio is usually clean
    and a single config works.

    For 'speakers' mode (interviews + news with music beds), we try
    successively shorter and quieter pause definitions, because some
    sources have continuous backing audio that prevents 'true' silence.

    Raises ImportError_ if no config produces enough silences.
    """
    if mode == "speakers":
        # (noise_db, min_dur, label)
        configs = [
            (-30, 0.9, "studio-clean speaker pauses"),
            (-25, 0.6, "moderate-noise speaker pauses"),
            (-20, 0.4, "noisy/music-bed speaker pauses"),
            (-18, 0.3, "very noisy speaker pauses"),
        ]
    else:
        configs = [
            (-30, 0.35, "sentence pauses"),
            (-28, 0.25, "shorter sentence pauses"),
            (-25, 0.2, "very short sentence pauses"),
        ]

    last_count = 0
    for (noise_db, min_dur, _label) in configs:
        silences = _detect_silences(wav, noise_db=noise_db, min_dur=min_dur)
        last_count = len(silences)
        if last_count >= n_cuts_needed:
            return silences

    # All configs failed. Build a helpful message.
    raise ImportError_(
        f"Tried four silence-detection profiles but the best found only "
        f"{last_count} pauses — not enough to make {n_cuts_needed + 1} clips. "
        "This usually means the audio has continuous background sound (e.g. "
        "a music bed under news voiceover) so ffmpeg can't find clear gaps. "
        "Options:\n"
        "  1. Download the audio with the URL on the source page, then split "
        "it on your Mac with mac-splitter.py — you can experiment with "
        "--noise-db and --min-pause values until it cuts cleanly, then "
        "upload via 'New collection'.\n"
        "  2. Skip this episode and try a different one."
    )


def _pick_cut_points(silences: List[_Silence], n_sentences: int) -> List[float]:
    """Pick (n_sentences - 1) cut points from the available silences.

    Strategy: sort silences by duration descending (longer pauses are
    more likely sentence boundaries), take the top (n_sentences - 1),
    then sort those by time and use the silence midpoints as cut points.
    """
    n_cuts = n_sentences - 1
    if n_cuts <= 0:
        return []
    if len(silences) < n_cuts:
        # This shouldn't happen if you came through _detect_silences_with_fallback,
        # but keep the explicit check for safety.
        raise ImportError_(
            f"Only {len(silences)} pauses available, need {n_cuts}."
        )
    by_duration = sorted(silences, key=lambda s: s.duration, reverse=True)
    chosen = by_duration[:n_cuts]
    chosen.sort(key=lambda s: s.start)
    return [s.mid for s in chosen]


class ImportError_(Exception):
    """Raised when an import job fails for a recoverable reason."""


def _split_clips(wav: Path, cut_points: List[float], total_dur: float,
                 out_dir: Path) -> List[Tuple[int, str]]:
    """Split wav at cut points, write MP3 clips. Returns [(position, filename)]."""
    boundaries = [0.0] + cut_points + [total_dur]
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: List[Tuple[int, str]] = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        fname = f"{uuid.uuid4().hex}.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(wav),
                "-ss", f"{start:.3f}",
                "-to", f"{end:.3f}",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(out_dir / fname),
            ],
            check=True,
        )
        clips.append((i + 1, fname))
    return clips


def _make_slug_unique(conn: sqlite3.Connection, base_slug: str) -> str:
    """Ensure the slug isn't already taken; suffix with -2, -3 etc if it is."""
    slug = base_slug
    n = 2
    while conn.execute(
        "SELECT 1 FROM collections WHERE slug = ?", (slug,)
    ).fetchone():
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


def _update_job(conn: sqlite3.Connection, job_id: int, status: str,
                message: Optional[str] = None, collection_id: Optional[int] = None) -> None:
    fields = ["status = ?", "updated_at = ?"]
    params: list = [status, _now()]
    if message is not None:
        fields.append("message = ?")
        params.append(message)
    if collection_id is not None:
        fields.append("collection_id = ?")
        params.append(collection_id)
    params.append(job_id)
    conn.execute(
        f"UPDATE import_jobs SET {', '.join(fields)} WHERE id = ?", params
    )
    conn.commit()


def run_import_job(job_id: int, url: str, audio_dir: Path,
                   uploaded_by: Optional[int] = None) -> None:
    """Execute one import job. Designed to be called in a background thread.

    Updates the import_jobs row with progress and the final state.
    """
    # Serialise imports — Pi RAM is tight.
    acquired = _import_lock.acquire(blocking=False)
    if not acquired:
        conn = _open()
        try:
            _update_job(
                conn, job_id, "failed",
                message="Another import is already running. Try again in a minute.",
            )
        finally:
            conn.close()
        return

    conn = _open()
    try:
        _update_job(conn, job_id, "running", message="Fetching page…")

        # 1. Adapter: scrape the page for audio URL + transcript.
        try:
            result: FetchResult = fetch(url)
        except Exception as e:
            _update_job(conn, job_id, "failed", message=f"Could not parse page: {e}")
            return

        # Determine split mode: sentences or speaker turns.
        mode = result.split_mode or "sentences"
        if mode == "speakers":
            n_clips = len(result.turns_gd)
            unit = "speaker turn"
        else:
            n_clips = len(result.sentences_gd)
            unit = "sentence"
        if n_clips < 2:
            _update_job(
                conn, job_id, "failed",
                message=f"Found only {n_clips} {unit}(s) in the transcript. "
                        "Cannot split into clips.",
            )
            return

        kind = "video" if result.is_video else "audio"
        _update_job(conn, job_id, "running",
                    message=f"Downloading {kind} ({n_clips} {unit}s expected)…")

        # 2. Download the source (audio or video) + convert to WAV.
        # ffmpeg picks the audio track automatically from video inputs.
        with tempfile.TemporaryDirectory(prefix="gshadow-import-") as tmpdir:
            tmp = Path(tmpdir)
            # Pick a sensible suffix for the temp source file.
            url_path = result.audio_url.split("?", 1)[0].lower()
            if url_path.endswith(".mp4"):
                src_suffix = ".mp4"
            elif url_path.endswith(".m4a"):
                src_suffix = ".m4a"
            elif url_path.endswith(".mp3"):
                src_suffix = ".mp3"
            else:
                src_suffix = ".caf"
            src = tmp / f"src{src_suffix}"
            wav = tmp / "src.wav"
            try:
                _http_download(result.audio_url, src)
            except Exception as e:
                _update_job(conn, job_id, "failed",
                            message=f"Failed to download {kind}: {e}")
                return

            _update_job(conn, job_id, "running",
                        message=f"Decoding {kind}…")
            try:
                total_dur = _convert_to_wav(src, wav)
            except subprocess.CalledProcessError as e:
                _update_job(conn, job_id, "failed",
                            message=f"ffmpeg conversion failed: {e}")
                return

            if mode == "speakers":
                detect_msg = "Detecting speaker-turn boundaries"
            else:
                detect_msg = "Detecting sentence boundaries"
            _update_job(conn, job_id, "running",
                        message=f"{detect_msg} in {total_dur:.0f}s of {kind}…")

            # 3. Find boundary silences. Escalates through profiles if the
            #    first one doesn't find enough pauses (handles noisy
            #    sources like news clips with a music bed).
            try:
                silences = _detect_silences_with_fallback(
                    wav, mode=mode, n_cuts_needed=n_clips - 1
                )
                cuts = _pick_cut_points(silences, n_clips)
            except ImportError_ as e:
                _update_job(conn, job_id, "failed", message=str(e))
                return

            _update_job(conn, job_id, "running",
                        message=f"Splitting into {n_clips} clips…")

            # 4. Cut clips, write to the audio directory.
            try:
                clips = _split_clips(wav, cuts, total_dur, audio_dir)
            except subprocess.CalledProcessError as e:
                _update_job(conn, job_id, "failed",
                            message=f"ffmpeg split failed: {e}")
                return

        # 5. Insert collection + clip rows.
        slug = _make_slug_unique(conn, result.suggested_slug or f"import-{job_id}")
        title = result.title_en or result.title_gd or slug
        if result.title_gd and result.title_gd != result.title_en:
            title = f"{result.title_en} / {result.title_gd}"
        # Category preference: adapter's explicit hint > slug prefix > 'other'.
        category = result.suggested_category or "other"
        if category == "other":
            if result.suggested_slug.startswith("litir-bheag"):
                category = "litir-bheag"
            elif result.suggested_slug.startswith("litir"):
                category = "litir"
        cur = conn.execute(
            "INSERT INTO collections "
            "(slug, title, description, transcript, notes, source_url, "
            "category, uploaded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                slug,
                title,
                None,
                result.transcript_gd,
                result.transcript_en,
                result.source_url,
                category,
                uploaded_by,
                _now(),
            ),
        )
        collection_id = cur.lastrowid

        # Per-clip text comes from either turns_gd or sentences_gd
        # depending on the mode.
        units = result.turns_gd if mode == "speakers" else result.sentences_gd
        unit_label = "Turn" if mode == "speakers" else "Sentence"
        for (pos, fname) in clips:
            unit_text = units[pos - 1] if pos - 1 < len(units) else ""
            clip_title = f"{unit_label} {pos}"
            conn.execute(
                "INSERT INTO clips "
                "(title, description, advice, filename, uploaded_by, "
                "uploaded_at, collection_id, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clip_title,
                    unit_text,
                    None,
                    fname,
                    uploaded_by,
                    _now(),
                    collection_id,
                    pos,
                ),
            )
        conn.commit()
        _update_job(conn, job_id, "done",
                    message=f"Imported {len(clips)} clips into '{title}'.",
                    collection_id=collection_id)
    except Exception as e:  # noqa: BLE001 — last-ditch catch
        try:
            _update_job(conn, job_id, "failed", message=f"Unexpected error: {e}")
        except Exception:
            pass
        raise
    finally:
        conn.close()
        _import_lock.release()


def is_import_running() -> bool:
    """Cheap, non-blocking check for whether any import is in progress."""
    if _import_lock.acquire(blocking=False):
        _import_lock.release()
        return False
    return True
