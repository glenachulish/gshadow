"""Gaelic Shadowing Practice — FastAPI application."""
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import (
    current_user,
    hash_password,
    require_role,
    require_tailnet,
    verify_password,
)
from .db import get_db, init_db
from . import collections as collections_module
from . import series as series_module
from . import upload_split

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).parent.parent
AUDIO_DIR = ROOT / "audio"
TEMPLATES_DIR = Path(__file__).parent / "templates"
AUDIO_DIR.mkdir(exist_ok=True)

# --- Config (from environment) ---------------------------------------------
SESSION_SECRET = os.environ.get("GSHADOW_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    print(
        "WARNING: GSHADOW_SECRET is not set. A random secret has been generated, "
        "but sessions will NOT survive a process restart. Set GSHADOW_SECRET in "
        "your .env / systemd EnvironmentFile for production."
    )

MAX_UPLOAD_MB = int(os.environ.get("GSHADOW_MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTS = {".mp3", ".m4a", ".ogg", ".wav", ".opus", ".flac", ".aac"}

# --- App -------------------------------------------------------------------
app = FastAPI(title="Gaelic Shadowing Practice")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 24 * 14,  # 14 days
    same_site="lax",
    https_only=False,  # Tailscale terminates TLS for us
)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Wire the collections + imports module to share templates and config.
collections_module.configure(
    templates, AUDIO_DIR, ALLOWED_EXTS, MAX_UPLOAD_BYTES
)
app.include_router(collections_module.router)

# Wire the series module (must be configured AFTER collections, since
# series.py imports a helper from collections.py at module load).
series_module.configure(templates)
app.include_router(series_module.router)

# Wire the in-app split feature. Staging MUST live under data/ — the systemd
# service runs with ProtectSystem=strict and can only write to data/ and audio/.
from .db import DB_PATH
STAGING_DIR = ROOT / "data" / "staging"
upload_split.configure(DB_PATH, STAGING_DIR, AUDIO_DIR)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# --- Public pages ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: sqlite3.Connection = Depends(get_db)):
    # Standalone clips: those NOT in any collection. Newest first.
    standalone = db.execute(
        "SELECT id, title, description, advice, filename, uploaded_at "
        "FROM clips WHERE collection_id IS NULL ORDER BY uploaded_at DESC"
    ).fetchall()
    # Count collections per category for the three top-level cards.
    counts = {row["category"]: row["n"] for row in db.execute(
        "SELECT category, COUNT(*) AS n FROM collections GROUP BY category"
    )}
    from .categories import CATEGORIES
    cats = [
        {
            "slug": c.slug,
            "title": c.title,
            "description": c.description,
            "count": counts.get(c.slug, 0),
        }
        for c in CATEGORIES
    ]
    # All collections (id, title), title order — populates the "add loose
    # clips to a collection" picker shown to admin/uploader on the home page.
    all_collections = db.execute(
        "SELECT id, title FROM collections ORDER BY title"
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "clips": standalone,
            "categories": cats,
            "collections": all_collections,
            "user": current_user(request),
        },
    )


@app.get("/category/{cat_slug}", response_class=HTMLResponse)
def category_page(
    cat_slug: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    if not cats_mod.is_valid(cat_slug):
        raise HTTPException(404, "Category not found")
    cat = cats_mod.get(cat_slug)

    # Band 1: series in this category, with a chapter (member-collection)
    # count. A series is shown even with zero chapters (the creator just
    # made it and will add to it).
    series = db.execute(
        "SELECT s.id, s.slug, s.title, s.description, "
        "       COUNT(c.id) AS chapter_count "
        "FROM series s "
        "LEFT JOIN collections c ON c.series_id = s.id "
        "WHERE s.category = ? "
        "GROUP BY s.id "
        "ORDER BY s.created_at DESC",
        (cat_slug,),
    ).fetchall()

    # Band 2: loose collections in this category — those NOT in any series.
    # A collection that belongs to a series appears under its series card
    # instead, so it is excluded here to avoid showing it twice.
    collections = db.execute(
        "SELECT c.id, c.slug, c.title, c.description, c.created_at, "
        "       COUNT(cl.id) AS clip_count "
        "FROM collections c "
        "LEFT JOIN clips cl ON cl.collection_id = c.id "
        "WHERE c.category = ? AND c.series_id IS NULL "
        "GROUP BY c.id "
        "ORDER BY c.created_at DESC",
        (cat_slug,),
    ).fetchall()

    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": cat,
            "series": series,
            "collections": collections,
            "user": current_user(request),
        },
    )


# --- User guide (served from the markdown file at request time) ------------
_GUIDE_HTML_CACHE: dict = {"html": None, "mtime": 0.0}


def _render_guide() -> str:
    """Render the bundled USER_GUIDE.md to HTML. Cached, re-renders if the
    file changes on disk."""
    guide_path = ROOT / "USER_GUIDE.md"
    if not guide_path.exists():
        return "<p>User guide not found on the server.</p>"
    try:
        mtime = guide_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _GUIDE_HTML_CACHE["html"] is not None and _GUIDE_HTML_CACHE["mtime"] == mtime:
        return _GUIDE_HTML_CACHE["html"]
    text = guide_path.read_text(encoding="utf-8")
    try:
        import markdown  # type: ignore
        html = markdown.markdown(text, extensions=["fenced_code", "tables"])
    except Exception:
        # Fall back: wrap as preformatted text. Still readable.
        from html import escape as h
        html = f"<pre style='white-space: pre-wrap;'>{h(text)}</pre>"
    _GUIDE_HTML_CACHE["html"] = html
    _GUIDE_HTML_CACHE["mtime"] = mtime
    return html


@app.get("/guide", response_class=HTMLResponse)
def guide(request: Request):
    return templates.TemplateResponse(
        request,
        "guide.html",
        {"guide_html": _render_guide(), "user": current_user(request)},
    )


# --- Login (tailnet only) --------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, _: None = Depends(require_tailnet)):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "user": current_user(request)},
    )


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT id, email, password_hash, role FROM users "
        "WHERE email = ? AND is_active = 1",
        (email.strip().lower(),),
    ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password", "user": None},
            status_code=401,
        )
    request.session["user_id"] = row["id"]
    request.session["email"] = row["email"]
    request.session["role"] = row["role"]
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# --- Upload (uploader+ only; also tailnet-only for now) --------------------
@app.get("/upload", response_class=HTMLResponse)
def upload_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"error": None, "user": user},
    )


@app.post("/upload")
async def upload(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    advice: str = Form(""),
    audio: UploadFile = File(...),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    ext = Path(audio.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "error": f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTS))}",
                "user": user,
            },
            status_code=400,
        )

    # Stream to disk with a hard size cap. Random filename to avoid
    # collisions and to keep user-supplied names off the filesystem.
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = AUDIO_DIR / safe_name
    total = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await audio.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError(f"File exceeds {MAX_UPLOAD_MB} MB limit")
                f.write(chunk)
    except ValueError as e:
        dest.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"error": str(e), "user": user},
            status_code=400,
        )

    db.execute(
        "INSERT INTO clips (title, description, advice, filename, uploaded_by, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            title.strip(),
            description.strip(),
            advice.strip(),
            safe_name,
            user["id"],
            _now(),
        ),
    )
    db.commit()
    return RedirectResponse(url="/", status_code=303)


# --- Admin user management (admin only; tailnet-only) ----------------------
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(
    request: Request,
    user: dict = Depends(require_role("admin")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    users = db.execute(
        "SELECT id, email, role, is_active, created_at FROM users ORDER BY created_at"
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"users": users, "user": user, "error": None},
    )


@app.post("/admin/users")
def admin_create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    user: dict = Depends(require_role("admin")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    if role not in {"admin", "uploader", "viewer"}:
        raise HTTPException(400, "Invalid role")
    if len(password) < 8:
        users = db.execute(
            "SELECT id, email, role, is_active, created_at FROM users ORDER BY created_at"
        ).fetchall()
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "users": users,
                "user": user,
                "error": "Password must be at least 8 characters",
            },
            status_code=400,
        )
    try:
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (email.strip().lower(), hash_password(password), role, _now()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        users = db.execute(
            "SELECT id, email, role, is_active, created_at FROM users ORDER BY created_at"
        ).fetchall()
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "users": users,
                "user": user,
                "error": f"A user with email '{email}' already exists",
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{uid}/toggle")
def admin_toggle_user(
    request: Request,
    uid: int,
    user: dict = Depends(require_role("admin")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    if uid == user["id"]:
        raise HTTPException(400, "You cannot deactivate yourself")
    db.execute("UPDATE users SET is_active = 1 - is_active WHERE id = ?", (uid,))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


# --- PWA (manifest, service worker, icons) ---------------------------------
# Files live under audio/_pwa/ so they sit on a ProtectSystem=strict-writable
# path. The service worker is served from the site root (/sw.js) so its scope
# covers the whole app, not just /audio.
from fastapi.responses import FileResponse, Response as _Response

_PWA_DIR = AUDIO_DIR / "_pwa"


@app.get("/manifest.json")
def pwa_manifest():
    f = _PWA_DIR / "manifest.json"
    if not f.exists():
        raise HTTPException(404, "manifest not found")
    return FileResponse(str(f), media_type="application/manifest+json")


@app.get("/sw.js")
def pwa_service_worker():
    f = _PWA_DIR / "sw.js"
    if not f.exists():
        raise HTTPException(404, "service worker not found")
    # Service-Worker-Allowed lets the SW claim root scope; no-cache so updates
    # to sw.js are picked up promptly by the browser.
    return FileResponse(
        str(f),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/{icon_name:path}.png")
def pwa_icon(icon_name: str):
    allowed = {
        "icon-192", "icon-512", "icon-192-maskable",
        "icon-512-maskable", "apple-touch-icon",
    }
    if icon_name not in allowed:
        raise HTTPException(404, "not found")
    f = _PWA_DIR / f"{icon_name}.png"
    if not f.exists():
        raise HTTPException(404, "icon not found")
    return FileResponse(str(f), media_type="image/png")


# --- Health check ----------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}
