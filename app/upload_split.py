"""In-app audio splitting for uploaded files (the "preview" flow).

Mirrors importer.py's machinery (a global lock, a jobs table, a threaded
worker, status polling) but instead of scraping a URL it splits a file
the user has already uploaded, into a STAGING area. The user then previews
the proposed clips and either accepts them (promote to a real collection),
re-runs at a different sensitivity, or cancels (discard staging).

It deliberately reuses importer's lock so an upload-split and a URL import
can never run at the same time — the Pi can't afford two ffmpeg jobs.

Staging layout, per job:
    <staging_root>/<job_id>/source.<ext>   the uploaded original
    <staging_root>/<job_id>/clips/NN.mp3   proposed clips (regenerated each run)
    <staging_root>/<job_id>/meta.json      title/category/sensitivity + clip list
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import splitter
from .importer import _import_lock  # reuse the single import lock


# Wired up by main.py at startup (same pattern as collections.configure).
_db_path: Optional[Path] = None
_staging_root: Optional[Path] = None
_audio_dir: Optional[Path] = None


def configure(db_path: Path, staging_root: Path, audio_dir: Path) -> None:
    global _db_path, _staging_root, _audio_dir
    _db_path = db_path
    _staging_root = staging_root
    _audio_dir = audio_dir
    _staging_root.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _job_dir(job_id: int) -> Path:
    return _staging_root / str(job_id)


def _update_job(conn, job_id, status=None, message=None, n_clips=None,
                collection_id=None) -> None:
    fields, params = ["updated_at = ?"], [_now()]
    if status is not None:
        fields.append("status = ?"); params.append(status)
    if message is not None:
        fields.append("message = ?"); params.append(message)
    if n_clips is not None:
        fields.append("n_clips = ?"); params.append(n_clips)
    if collection_id is not None:
        fields.append("collection_id = ?"); params.append(collection_id)
    params.append(job_id)
    conn.execute(f"UPDATE split_jobs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def _write_meta(job_id: int, meta: dict) -> None:
    (_job_dir(job_id) / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def read_meta(job_id: int) -> Optional[dict]:
    p = _job_dir(job_id) / "meta.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_busy() -> bool:
    """Whether any import OR split is currently running (shared lock)."""
    if _import_lock.acquire(blocking=False):
        _import_lock.release()
        return False
    return True


def run_split_job(job_id: int, source_path: Path, sensitivity: str,
                  min_clip_len: float, max_clip_len: float) -> None:
    """Decode + split the staged source into proposed clips. Threaded worker."""
    acquired = _import_lock.acquire(blocking=False)
    if not acquired:
        conn = _open()
        try:
            _update_job(conn, job_id, status="failed",
                        message="The Pi is busy with another job. Try again in a minute.")
        finally:
            conn.close()
        return

    conn = _open()
    try:
        _update_job(conn, job_id, status="running", message="Decoding audio…")
        preset = splitter.SENSITIVITY_PRESETS.get(
            sensitivity, splitter.SENSITIVITY_PRESETS["normal"]
        )
        clips_dir = _job_dir(job_id) / "clips"
        # Wipe any clips from a previous run (re-run case).
        if clips_dir.exists():
            for old in clips_dir.glob("*.mp3"):
                old.unlink(missing_ok=True)

        with tempfile.TemporaryDirectory(prefix="gshadow-split-") as td:
            wav = Path(td) / "tmp.wav"
            total = splitter.convert_to_wav(source_path, wav)
            _update_job(conn, job_id, message="Detecting pauses…")
            silences = splitter.detect_silences(
                wav, preset["noise_db"], min_pause=0.20
            )
            cuts = splitter.pick_pause_cuts(
                silences, total, preset["min_pause"],
                min_clip_len, max_clip_len,
            )
            _update_job(conn, job_id, message=f"Writing {len(cuts) + 1} clips…")
            clip_info = splitter.split_to_files(
                wav, cuts, total, clips_dir,
                name_fn=lambda i: f"{i:02d}.mp3",
            )

        meta = read_meta(job_id) or {}
        meta.update({
            "sensitivity": sensitivity,
            "min_clip_len": min_clip_len,
            "max_clip_len": max_clip_len,
            "total_duration": round(total, 2),
            "clips": clip_info,
        })
        _write_meta(job_id, meta)
        _update_job(conn, job_id, status="ready", n_clips=len(clip_info),
                    message=f"{len(clip_info)} clips proposed. Preview and accept, "
                            "or re-run at a different sensitivity.")
    except Exception as e:  # noqa: BLE001
        try:
            _update_job(conn, job_id, status="failed", message=f"Split failed: {e}")
        except Exception:
            pass
    finally:
        conn.close()
        _import_lock.release()


def accept_job(conn: sqlite3.Connection, job_id: int, uploaded_by: int):
    """Promote staged clips into a real collection. Returns the new slug.

    Raises ValueError if the job isn't in a ready state or staging is gone.
    """
    job = conn.execute(
        "SELECT id, title, category, status FROM split_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not job:
        raise ValueError("Job not found.")
    if job["status"] != "ready":
        raise ValueError("This split isn't ready to accept.")
    meta = read_meta(job_id)
    if not meta or not meta.get("clips"):
        raise ValueError("No proposed clips found to accept.")

    clips_dir = _job_dir(job_id) / "clips"

    # Slug uniqueness (same approach as collections._make_slug_unique).
    from . import collections as cols
    slug = cols._make_slug_unique(conn, cols._slugify(job["title"]))

    cur = conn.execute(
        "INSERT INTO collections (slug, title, description, transcript, notes, "
        "source_url, category, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, job["title"], "", "", "", None, job["category"],
         uploaded_by, _now()),
    )
    collection_id = cur.lastrowid

    moved: List[Path] = []
    try:
        for clip in meta["clips"]:
            src = clips_dir / clip["filename"]
            dest_name = f"{uuid.uuid4().hex}.mp3"
            dest = _audio_dir / dest_name
            dest.write_bytes(src.read_bytes())
            moved.append(dest)
            conn.execute(
                "INSERT INTO clips (title, description, advice, filename, "
                "uploaded_by, uploaded_at, collection_id, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"Clip {clip['position']:02d}", "", None, dest_name,
                 uploaded_by, _now(), collection_id, clip["position"]),
            )
        conn.commit()
    except Exception:
        for p in moved:
            p.unlink(missing_ok=True)
        conn.execute("DELETE FROM clips WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
        raise

    _update_job(conn, job_id, status="accepted", collection_id=collection_id,
                message=f"Accepted into collection '{job['title']}'.")
    cleanup_staging(job_id)
    return slug


def cleanup_staging(job_id: int) -> None:
    """Best-effort removal of a job's staging directory."""
    import shutil
    d = _job_dir(job_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def cancel_job(conn: sqlite3.Connection, job_id: int) -> None:
    _update_job(conn, job_id, status="cancelled", message="Cancelled by user.")
    cleanup_staging(job_id)
