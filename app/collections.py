"""Routes for collections, bulk upload, and URL imports."""
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .auth import current_user, require_role, require_tailnet
from .db import get_db
from .importer import run_import_job, is_import_running
from .adapters import is_supported as adapter_is_supported
from . import upload_split

router = APIRouter()

# Templates are wired up by main.py and injected here.
templates: Optional[Jinja2Templates] = None
audio_dir: Optional[Path] = None
allowed_exts: set = {".mp3", ".m4a", ".ogg", ".wav", ".opus", ".flac", ".aac"}
max_upload_bytes: int = 25 * 1024 * 1024


def configure(t: Jinja2Templates, a: Path, exts: set, max_bytes: int) -> None:
    """Called once by main.py at startup."""
    global templates, audio_dir, allowed_exts, max_upload_bytes
    templates, audio_dir = t, a
    allowed_exts = exts
    max_upload_bytes = max_bytes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(text: str) -> str:
    """Conservative slug: lowercase, hyphens, ASCII letters/digits only."""
    text = text.lower()
    # Replace accented Gaelic chars with their unaccented equivalents.
    for src, dst in (
        ("àáâãä", "a"), ("èéêë", "e"), ("ìíîï", "i"),
        ("òóôõö", "o"), ("ùúûü", "u"), ("ñ", "n"),
    ):
        for c in src:
            text = text.replace(c, dst)
    text = re.sub(r"\s+", "-", text.strip())
    text = _SLUG_RE.sub("", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "collection"


def _make_slug_unique(db: sqlite3.Connection, base: str) -> str:
    slug = base
    n = 2
    while db.execute("SELECT 1 FROM collections WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _all_series(db: sqlite3.Connection) -> list:
    """All series, newest first — used to populate the New Collection
    'Series' dropdown. Returns [] if the table is somehow absent."""
    try:
        return db.execute(
            "SELECT id, slug, title, category FROM series ORDER BY created_at DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def _all_collections(db: sqlite3.Connection) -> list:
    """All collections (id, slug, title, category), title order — for the
    'add existing clips to…' and 'assign loose clip to…' pickers."""
    return db.execute(
        "SELECT id, slug, title, category FROM collections ORDER BY title"
    ).fetchall()


def _resolve_series_id(db: sqlite3.Connection, raw: str) -> Optional[int]:
    """Turn a posted series_id form value into a valid series id or None.
    Empty string / 'none' / a non-existent id all resolve to None (ungrouped)."""
    if not raw or raw.strip().lower() in ("", "none"):
        return None
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return None
    row = db.execute("SELECT id FROM series WHERE id = ?", (sid,)).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Public: list and view collections
# ---------------------------------------------------------------------------
@router.get("/c/{slug}", response_class=HTMLResponse)
def view_collection(
    slug: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    col = db.execute(
        "SELECT id, slug, title, description, transcript, notes, source_url, "
        "category, series_id, created_at "
        "FROM collections WHERE slug = ?", (slug,)
    ).fetchone()
    if not col:
        raise HTTPException(404, "Collection not found")
    clips = db.execute(
        "SELECT id, title, description, advice, filename, position "
        "FROM clips WHERE collection_id = ? ORDER BY position",
        (col["id"],),
    ).fetchall()
    from . import categories as cats_mod
    cat = cats_mod.get(col["category"])
    # If this collection belongs to a series, fetch its slug + title so the
    # template can render the extra breadcrumb level. None otherwise.
    series = None
    if col["series_id"] is not None:
        series = db.execute(
            "SELECT slug, title FROM series WHERE id = ?", (col["series_id"],)
        ).fetchone()
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": col,
            "series": series,
            "clips": clips,
            "category": cat,
            "user": current_user(request),
        },
    )


# ---------------------------------------------------------------------------
# Bulk file upload — new collection from multiple files
# ---------------------------------------------------------------------------
@router.get("/collections/new", response_class=HTMLResponse)
def new_collection_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    return templates.TemplateResponse(
        request,
        "new_collection.html",
        {"error": None, "user": user, "categories": cats_mod.CATEGORIES,
         "series_list": _all_series(db)},
    )


@router.post("/collections/new")
async def create_collection(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    transcript: str = Form(""),
    notes: str = Form(""),
    category: str = Form("other"),
    series_id: str = Form(""),
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    if not cats_mod.is_valid(category):
        category = "other"

    resolved_series_id = _resolve_series_id(db, series_id)

    if not files:
        return templates.TemplateResponse(
            request, "new_collection.html",
            {"error": "Please select at least one audio file.", "user": user,
             "categories": cats_mod.CATEGORIES, "series_list": _all_series(db)},
            status_code=400,
        )

    # Sort by original filename so 01.mp3 ... 28.mp3 land in order.
    files_sorted = sorted(files, key=lambda f: (f.filename or "").lower())

    # Validate all extensions before writing anything.
    for f in files_sorted:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in allowed_exts:
            return templates.TemplateResponse(
                request, "new_collection.html",
                {
                    "error": f"Unsupported file type '{ext}' in '{f.filename}'. "
                             f"Allowed: {', '.join(sorted(allowed_exts))}",
                    "user": user,
                    "categories": cats_mod.CATEGORIES,
                    "series_list": _all_series(db),
                },
                status_code=400,
            )

    slug = _make_slug_unique(db, _slugify(title))

    cur = db.execute(
        "INSERT INTO collections (slug, title, description, transcript, notes, "
        "source_url, category, series_id, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            slug,
            title.strip(),
            description.strip(),
            transcript.strip(),
            notes.strip(),
            None,
            category,
            resolved_series_id,
            user["id"],
            _now(),
        ),
    )
    collection_id = cur.lastrowid

    saved: List[Path] = []
    try:
        for pos, f in enumerate(files_sorted, start=1):
            ext = Path(f.filename or "").suffix.lower()
            safe_name = f"{uuid.uuid4().hex}{ext}"
            dest = audio_dir / safe_name
            total = 0
            with dest.open("wb") as out:
                while True:
                    chunk = await f.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_upload_bytes:
                        raise ValueError(
                            f"'{f.filename}' exceeds the size limit"
                        )
                    out.write(chunk)
            saved.append(dest)
            db.execute(
                "INSERT INTO clips (title, description, advice, filename, "
                "uploaded_by, uploaded_at, collection_id, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    Path(f.filename or "").stem,
                    "",
                    None,
                    safe_name,
                    user["id"],
                    _now(),
                    collection_id,
                    pos,
                ),
            )
        db.commit()
    except ValueError as e:
        # Roll back partially-uploaded files + DB rows.
        for p in saved:
            p.unlink(missing_ok=True)
        db.execute("DELETE FROM clips WHERE collection_id = ?", (collection_id,))
        db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        db.commit()
        return templates.TemplateResponse(
            request, "new_collection.html",
            {"error": str(e), "user": user,
             "categories": cats_mod.CATEGORIES, "series_list": _all_series(db)},
            status_code=400,
        )

    return RedirectResponse(url=f"/c/{slug}", status_code=303)


# ---------------------------------------------------------------------------
# URL import — paste a URL, background-process into a new collection
# ---------------------------------------------------------------------------
@router.get("/import", response_class=HTMLResponse)
def import_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    return templates.TemplateResponse(
        request,
        "import.html",
        {"error": None, "user": user},
    )


@router.post("/import")
def import_url(
    request: Request,
    background: BackgroundTasks,
    url: str = Form(...),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    url = url.strip()
    if not adapter_is_supported(url):
        return templates.TemplateResponse(
            request, "import.html",
            {
                "error": (
                    "No adapter for that URL. Currently supported: "
                    "learngaelic.scot Litir Bheag and Litir pages. For other "
                    "audio, use the Mac splitter script."
                ),
                "user": user,
            },
            status_code=400,
        )
    if is_import_running():
        return templates.TemplateResponse(
            request, "import.html",
            {
                "error": "Another import is already running. Wait a minute and try again.",
                "user": user,
            },
            status_code=409,
        )

    cur = db.execute(
        "INSERT INTO import_jobs (url, status, message, created_at, updated_at) "
        "VALUES (?, 'queued', 'Job queued', ?, ?)",
        (url, _now(), _now()),
    )
    job_id = cur.lastrowid
    db.commit()

    # Kick off the worker in a background thread. We don't use FastAPI's
    # BackgroundTasks because they only run after the response is sent on
    # success — we want it to start immediately and survive across the
    # request lifecycle.
    threading.Thread(
        target=run_import_job,
        args=(job_id, url, audio_dir, user["id"]),
        daemon=True,
    ).start()

    return RedirectResponse(url=f"/import/jobs/{job_id}", status_code=303)


@router.get("/import/jobs/{job_id}", response_class=HTMLResponse)
def view_import_job(
    job_id: int,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    job = db.execute(
        "SELECT id, url, status, message, collection_id, created_at, updated_at "
        "FROM import_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    collection_slug = None
    if job["collection_id"]:
        row = db.execute(
            "SELECT slug FROM collections WHERE id = ?", (job["collection_id"],)
        ).fetchone()
        if row:
            collection_slug = row["slug"]
    return templates.TemplateResponse(
        request,
        "import_job.html",
        {
            "job": job,
            "collection_slug": collection_slug,
            "user": user,
        },
    )


# ---------------------------------------------------------------------------
# Delete routes — admin/uploader only, tailnet-only.
# Both POST-only (no GET), so a stray link can't trigger them.
# ---------------------------------------------------------------------------
@router.post("/c/{slug}/delete")
def delete_collection(
    slug: str,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    """Delete a collection AND all of its clips AND the underlying audio files.
    Irreversible.
    """
    row = db.execute(
        "SELECT id FROM collections WHERE slug = ?", (slug,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Collection not found")
    collection_id = row["id"]

    # Gather audio filenames first so we can unlink them after the DB delete.
    filenames = [
        r["filename"]
        for r in db.execute(
            "SELECT filename FROM clips WHERE collection_id = ?",
            (collection_id,),
        )
    ]
    db.execute("DELETE FROM clips WHERE collection_id = ?", (collection_id,))
    db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    db.commit()

    # Best-effort file cleanup. Missing files don't error.
    if audio_dir is not None:
        for fname in filenames:
            try:
                (audio_dir / fname).unlink(missing_ok=True)
            except OSError:
                pass

    return RedirectResponse(url="/", status_code=303)


@router.post("/clips/{clip_id}/delete")
def delete_clip(
    clip_id: int,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    """Delete a single standalone clip and its audio file."""
    row = db.execute(
        "SELECT filename, collection_id FROM clips WHERE id = ?",
        (clip_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Clip not found")
    db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    db.commit()
    if audio_dir is not None and row["filename"]:
        try:
            (audio_dir / row["filename"]).unlink(missing_ok=True)
        except OSError:
            pass
    # Redirect back to wherever made sense: home if standalone, the
    # collection page otherwise (though "otherwise" shouldn't happen
    # from the UI since collection pages don't expose per-clip delete).
    if row["collection_id"]:
        col = db.execute(
            "SELECT slug FROM collections WHERE id = ?",
            (row["collection_id"],),
        ).fetchone()
        if col:
            return RedirectResponse(url=f"/c/{col['slug']}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Assign existing loose clips to a collection.
# Moves checked clips into the target collection, appending position numbers
# after the collection's current maximum. Pure DB updates — audio untouched.
# Reversible: assigning to an empty/zero target id detaches back to loose.
# ---------------------------------------------------------------------------
@router.post("/clips/assign")
def assign_clips(
    request: Request,
    target_collection_id: str = Form(...),
    clip_ids: List[int] = Form(default=[]),
    return_to: str = Form("/"),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    if not clip_ids:
        return RedirectResponse(url=return_to or "/", status_code=303)

    # Resolve the target. "0" / "" / "loose" means detach to loose clips.
    detach = target_collection_id.strip().lower() in ("", "0", "loose", "none")
    target_id = None
    if not detach:
        try:
            tid = int(target_collection_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "Bad target collection")
        row = db.execute(
            "SELECT id FROM collections WHERE id = ?", (tid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Target collection not found")
        target_id = row["id"]

    if detach:
        # Send the selected clips back to the loose pool.
        for cid in clip_ids:
            db.execute(
                "UPDATE clips SET collection_id = NULL, position = NULL WHERE id = ?",
                (cid,),
            )
        db.commit()
        return RedirectResponse(url=return_to or "/", status_code=303)

    # Find the current max position in the target so we append rather than clash.
    row = db.execute(
        "SELECT COALESCE(MAX(position), 0) AS maxpos FROM clips WHERE collection_id = ?",
        (target_id,),
    ).fetchone()
    next_pos = (row["maxpos"] or 0) + 1

    # Only move clips that are currently loose (collection_id IS NULL), to avoid
    # silently yanking a clip out of another collection by guessed id.
    moved = 0
    for cid in clip_ids:
        existing = db.execute(
            "SELECT collection_id FROM clips WHERE id = ?", (cid,)
        ).fetchone()
        if existing is None:
            continue
        if existing["collection_id"] is not None:
            # Already in a collection — skip (use the collection page to move it).
            continue
        db.execute(
            "UPDATE clips SET collection_id = ?, position = ? WHERE id = ?",
            (target_id, next_pos, cid),
        )
        next_pos += 1
        moved += 1
    db.commit()

    # Redirect to the target collection so the user sees the result.
    slug_row = db.execute(
        "SELECT slug FROM collections WHERE id = ?", (target_id,)
    ).fetchone()
    if slug_row:
        return RedirectResponse(url=f"/c/{slug_row['slug']}", status_code=303)
    return RedirectResponse(url=return_to or "/", status_code=303)


# ===========================================================================
# Split-on-upload — upload one long file, split it in-app, preview, accept.
# Added 2026-06-19. Routes live here; the worker + accept/cancel logic is in
# app/upload_split.py; the cut logic is in app/splitter.py.
# (Add `from . import upload_split` to the imports at the TOP of this file.)
# ===========================================================================


@router.get("/split", response_class=HTMLResponse)
def split_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    from . import categories as cats_mod
    return templates.TemplateResponse(
        request, "split.html",
        {"error": None, "user": user, "categories": cats_mod.CATEGORIES},
    )


@router.post("/split")
async def split_upload(
    request: Request,
    title: str = Form(...),
    category: str = Form("other"),
    sensitivity: str = Form("normal"),
    file: UploadFile = File(...),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    if not cats_mod.is_valid(category):
        category = "other"

    def _form_error(msg: str, code: int = 400):
        return templates.TemplateResponse(
            request, "split.html",
            {"error": msg, "user": user, "categories": cats_mod.CATEGORIES},
            status_code=code,
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_exts:
        return _form_error(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed_exts))}"
        )
    if upload_split.is_busy():
        return _form_error(
            "The Pi is busy with another split or import. Wait a minute and try again.",
            code=409,
        )

    # Create the job row first so we have an id for the staging dir.
    cur = db.execute(
        "INSERT INTO split_jobs (title, category, status, message, created_at, updated_at) "
        "VALUES (?, ?, 'queued', 'Uploading…', ?, ?)",
        (title.strip(), category, _now(), _now()),
    )
    job_id = cur.lastrowid
    db.commit()

    # Stream the upload into the job's staging dir, enforcing the size cap.
    job_dir = upload_split._job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    source_path = job_dir / f"source{ext}"
    total = 0
    try:
        with source_path.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_upload_bytes:
                    raise ValueError("exceeds the size limit")
                out.write(chunk)
    except ValueError:
        upload_split.cleanup_staging(job_id)
        db.execute("DELETE FROM split_jobs WHERE id = ?", (job_id,))
        db.commit()
        return _form_error(
            f"'{file.filename}' is over the upload size limit. Split the book "
            "into smaller chapters and upload one at a time."
        )

    upload_split._write_meta(job_id, {"title": title.strip(), "category": category})

    preset = upload_split.splitter.SENSITIVITY_PRESETS.get(sensitivity, None)
    if preset is None:
        sensitivity = "normal"

    threading.Thread(
        target=upload_split.run_split_job,
        args=(job_id, source_path, sensitivity,
              upload_split.splitter.DEFAULT_MIN_CLIP_LEN,
              upload_split.splitter.DEFAULT_MAX_CLIP_LEN),
        daemon=True,
    ).start()

    return RedirectResponse(url=f"/split/jobs/{job_id}", status_code=303)


@router.get("/split/jobs/{job_id}", response_class=HTMLResponse)
def view_split_job(
    job_id: int,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    job = db.execute(
        "SELECT id, title, category, status, message, n_clips, collection_id "
        "FROM split_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    meta = upload_split.read_meta(job_id) or {}
    clips = meta.get("clips", [])
    collection_slug = None
    if job["collection_id"]:
        row = db.execute(
            "SELECT slug FROM collections WHERE id = ?", (job["collection_id"],)
        ).fetchone()
        if row:
            collection_slug = row["slug"]
    return templates.TemplateResponse(
        request, "split_job.html",
        {"job": job, "meta": meta, "clips": clips,
         "collection_slug": collection_slug, "user": user},
    )


@router.get("/split/{job_id}/clip/{filename}")
def serve_staged_clip(
    job_id: int,
    filename: str,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    from fastapi.responses import FileResponse
    # Guard against path traversal: only allow NN.mp3 from this job's clips dir.
    if "/" in filename or "\\" in filename or not filename.endswith(".mp3"):
        raise HTTPException(400, "Bad filename")
    path = upload_split._job_dir(job_id) / "clips" / filename
    if not path.exists():
        raise HTTPException(404, "Clip not found")
    return FileResponse(str(path), media_type="audio/mpeg")


@router.post("/split/{job_id}/rerun")
def rerun_split_job(
    job_id: int,
    sensitivity: str = Form("normal"),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    job = db.execute(
        "SELECT id, status FROM split_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    if upload_split.is_busy():
        # Don't start a second job; just bounce back to the preview.
        return RedirectResponse(url=f"/split/jobs/{job_id}", status_code=303)

    source_candidates = list(upload_split._job_dir(job_id).glob("source.*"))
    if not source_candidates:
        raise HTTPException(409, "The uploaded file is no longer staged; re-upload.")

    db.execute(
        "UPDATE split_jobs SET status = 'queued', message = 'Re-running…', "
        "updated_at = ? WHERE id = ?", (_now(), job_id),
    )
    db.commit()
    threading.Thread(
        target=upload_split.run_split_job,
        args=(job_id, source_candidates[0], sensitivity,
              upload_split.splitter.DEFAULT_MIN_CLIP_LEN,
              upload_split.splitter.DEFAULT_MAX_CLIP_LEN),
        daemon=True,
    ).start()
    return RedirectResponse(url=f"/split/jobs/{job_id}", status_code=303)


@router.post("/split/{job_id}/accept")
def accept_split_job(
    job_id: int,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        slug = upload_split.accept_job(db, job_id, user["id"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    return RedirectResponse(url=f"/c/{slug}", status_code=303)


@router.post("/split/{job_id}/cancel")
def cancel_split_job(
    job_id: int,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    job = db.execute("SELECT id FROM split_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    upload_split.cancel_job(db, job_id)
    return RedirectResponse(url=f"/split/jobs/{job_id}", status_code=303)
