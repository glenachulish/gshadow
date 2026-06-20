"""Routes for series — an overarching grouping above collections.

A "series" (think: a book or podcast season) groups several collections
that belong together — e.g. each chapter of an audiobook is its own
collection, and they sit under one series. A collection's membership is
the nullable `collections.series_id` column; a series is otherwise just
metadata (slug, title, description, category).

This module mirrors the conventions in collections.py: it shares the
Jinja2 templates injected at startup, slugifies titles the same way, and
gates authoring routes on admin/uploader + tailnet.
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .auth import current_user, require_role, require_tailnet
from .db import get_db
from .collections import _slugify  # reuse the exact same slug rules

router = APIRouter()

# Injected by main.py at startup (same pattern as collections.configure).
templates: Optional[Jinja2Templates] = None


def configure(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_series_slug_unique(db: sqlite3.Connection, base: str) -> str:
    """Like collections._make_slug_unique, but checks the series table."""
    slug = base
    n = 2
    while db.execute("SELECT 1 FROM series WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ---------------------------------------------------------------------------
# Create a series (admin/uploader, tailnet-only)
# ---------------------------------------------------------------------------
@router.get("/series/new", response_class=HTMLResponse)
def new_series_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    from . import categories as cats_mod
    return templates.TemplateResponse(
        request,
        "new_series.html",
        {"error": None, "user": user, "categories": cats_mod.CATEGORIES},
    )


@router.post("/series/new")
def create_series(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form("other"),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    from . import categories as cats_mod
    if not cats_mod.is_valid(category):
        category = "other"

    if not title.strip():
        return templates.TemplateResponse(
            request, "new_series.html",
            {"error": "Please give the series a title.", "user": user,
             "categories": cats_mod.CATEGORIES},
            status_code=400,
        )

    slug = _make_series_slug_unique(db, _slugify(title))
    db.execute(
        "INSERT INTO series (slug, title, description, category, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (slug, title.strip(), description.strip(), category, _now()),
    )
    db.commit()
    return RedirectResponse(url=f"/series/{slug}", status_code=303)


# ---------------------------------------------------------------------------
# View a series and its member collections (public)
# ---------------------------------------------------------------------------
@router.get("/series/{slug}", response_class=HTMLResponse)
def view_series(
    slug: str,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    series = db.execute(
        "SELECT id, slug, title, description, category, created_at "
        "FROM series WHERE slug = ?", (slug,)
    ).fetchone()
    if not series:
        raise HTTPException(404, "Series not found")

    # Member collections, in chapter order. v1 orders by created_at
    # (chapters are normally created in order). Clip counts via LEFT JOIN
    # so an empty collection still shows.
    collections = db.execute(
        "SELECT c.id, c.slug, c.title, c.description, c.created_at, "
        "       c.series_position, COUNT(cl.id) AS clip_count "
        "FROM collections c "
        "LEFT JOIN clips cl ON cl.collection_id = c.id "
        "WHERE c.series_id = ? "
        "GROUP BY c.id "
        "ORDER BY c.series_position IS NULL, c.series_position, c.created_at ASC",
        (series["id"],),
    ).fetchall()

    from . import categories as cats_mod
    cat = cats_mod.get(series["category"])
    return templates.TemplateResponse(
        request,
        "series.html",
        {
            "series": series,
            "category": cat,
            "collections": collections,
            "user": current_user(request),
        },
    )


# ---------------------------------------------------------------------------
# Save chapter order within a series (admin/uploader, tailnet-only).
# Reads a typed number per chapter, sorts by it, and writes back a clean 1..N
# sequence — so the numbers express RELATIVE order; you needn't keep them
# contiguous. Chapters with no number sort after numbered ones, by created_at.
# ---------------------------------------------------------------------------
@router.post("/series/{slug}/order")
async def reorder_series(
    slug: str,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    series = db.execute(
        "SELECT id FROM series WHERE slug = ?", (slug,)
    ).fetchone()
    if not series:
        raise HTTPException(404, "Series not found")

    # Form posts pos_<collection_id> = <typed number> for each chapter.
    form = await request.form()
    members = db.execute(
        "SELECT id, created_at FROM collections WHERE series_id = ?",
        (series["id"],),
    ).fetchall()

    # Build (sort_key, collection_id). Typed numbers sort first (ascending);
    # blanks/garbage sort last, ordered by created_at among themselves.
    ranked = []
    for i, m in enumerate(members):
        raw = (form.get(f"pos_{m['id']}") or "").strip()
        try:
            num = float(raw)
            key = (0, num, i)  # numbered: group 0, by number, stable by row
        except (TypeError, ValueError):
            key = (1, m["created_at"], i)  # unnumbered: group 1, by created_at
        ranked.append((key, m["id"]))

    ranked.sort(key=lambda t: t[0])

    # Write back a normalised 1..N.
    for new_pos, (_key, cid) in enumerate(ranked, start=1):
        db.execute(
            "UPDATE collections SET series_position = ? WHERE id = ?",
            (new_pos, cid),
        )
    db.commit()
    return RedirectResponse(url=f"/series/{slug}", status_code=303)


# ---------------------------------------------------------------------------
# Delete a series (admin/uploader, tailnet-only).
# ON DELETE SET NULL means member collections are orphaned back to loose
# collections — their audio is untouched. POST-only so a stray link can't
# trigger it.
# ---------------------------------------------------------------------------
@router.post("/series/{slug}/delete")
def delete_series(
    slug: str,
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT id, category FROM series WHERE slug = ?", (slug,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Series not found")
    category = row["category"] or "other"
    # Explicitly null out members too (don't rely solely on the FK action,
    # since PRAGMA foreign_keys must be ON for it to fire — it is, per
    # _open(), but being explicit is safer and self-documenting).
    db.execute("UPDATE collections SET series_id = NULL WHERE series_id = ?", (row["id"],))
    db.execute("DELETE FROM series WHERE id = ?", (row["id"],))
    db.commit()
    # Members are now loose collections; send the operator back to the
    # category page where they'll reappear in the loose list.
    return RedirectResponse(url=f"/category/{category}", status_code=303)
