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
        "category, created_at "
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
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": col,
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
):
    from . import categories as cats_mod
    return templates.TemplateResponse(
        request,
        "new_collection.html",
        {"error": None, "user": user, "categories": cats_mod.CATEGORIES},
    )


@router.post("/collections/new")
async def create_collection(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    transcript: str = Form(""),
    notes: str = Form(""),
    category: str = Form("other"),
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    if not cats_mod.is_valid(category):
        category = "other"

    if not files:
        return templates.TemplateResponse(
            request, "new_collection.html",
            {"error": "Please select at least one audio file.", "user": user,
             "categories": cats_mod.CATEGORIES},
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
                },
                status_code=400,
            )

    slug = _make_slug_unique(db, _slugify(title))

    cur = db.execute(
        "INSERT INTO collections (slug, title, description, transcript, notes, "
        "source_url, category, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            slug,
            title.strip(),
            description.strip(),
            transcript.strip(),
            notes.strip(),
            None,
            category,
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
            {"error": str(e), "user": user},
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
