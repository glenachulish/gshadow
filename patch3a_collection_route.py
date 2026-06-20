#!/usr/bin/env python3
"""Collection-page pass: assign an existing collection to a series, and add
existing loose clips to this collection.

This patches app/collections.py:
  - view_collection: also pass `series_list` (all series) and `loose_clips`
    (clips not in any collection) so the template can render the two panels.
  - new route POST /c/{slug}/series: set (or clear) this collection's series_id.

The "add existing clips" panel reuses the already-deployed POST /clips/assign
route (with return_to set to this collection), so no new clip route is needed.

Run from ~/gshadow. Each edit must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/collections.py"
text = open(PATH).read()

EDITS = [
    # 1. Extend view_collection: after building `series`, also fetch series_list
    #    and loose_clips, and add them to the context dict. Anchor on the series
    #    fetch + the start of the TemplateResponse context.
    (
        "Add series_list + loose_clips to view_collection",
        '''    series = None
    if col["series_id"] is not None:
        series = db.execute(
            "SELECT slug, title FROM series WHERE id = ?", (col["series_id"],)
        ).fetchone()
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": col,
            "series": series,''',
        '''    series = None
    if col["series_id"] is not None:
        series = db.execute(
            "SELECT slug, title FROM series WHERE id = ?", (col["series_id"],)
        ).fetchone()
    # All series in THIS collection's category, for the "set series" dropdown.
    series_list = db.execute(
        "SELECT id, slug, title FROM series WHERE category = ? ORDER BY title",
        (col["category"],),
    ).fetchall()
    # Loose clips (not in any collection), for the "add existing clips" panel.
    loose_clips = db.execute(
        "SELECT id, title, filename FROM clips "
        "WHERE collection_id IS NULL ORDER BY uploaded_at DESC"
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": col,
            "series": series,
            "series_list": series_list,
            "loose_clips": loose_clips,''',
    ),
    # 2. Add the series-set route. Anchor it right before the /clips/assign
    #    route we added last pass (its banner comment is unique).
    (
        "Insert /c/{slug}/series route before the assign-clips section",
        '''# ---------------------------------------------------------------------------
# Assign existing loose clips to a collection.''',
        '''# ---------------------------------------------------------------------------
# Set (or clear) an existing collection's series. Lets you group collections
# that already exist — e.g. attach two "Am Misneachadh" collections to one
# series after the fact. Pure UPDATE of collections.series_id.
# ---------------------------------------------------------------------------
@router.post("/c/{slug}/series")
def set_collection_series(
    slug: str,
    request: Request,
    series_id: str = Form(""),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    col = db.execute(
        "SELECT id FROM collections WHERE slug = ?", (slug,)
    ).fetchone()
    if not col:
        raise HTTPException(404, "Collection not found")
    # "" / "0" / "none" clears the series (back to a loose collection).
    resolved = _resolve_series_id(db, series_id)
    db.execute(
        "UPDATE collections SET series_id = ? WHERE id = ?",
        (resolved, col["id"]),
    )
    db.commit()
    return RedirectResponse(url=f"/c/{slug}", status_code=303)


# ---------------------------------------------------------------------------
# Assign existing loose clips to a collection.''',
    ),
]

for desc, find, replace in EDITS:
    n = text.count(find)
    if n != 1:
        sys.exit(f"ABORT: edit '{desc}' matched {n} times (expected 1). No file written.")
    text = text.replace(find, replace)

try:
    ast.parse(text)
except SyntaxError as e:
    sys.exit(f"ABORT: result has a syntax error: {e}. No file written.")

with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — view_collection context extended + POST /c/{{slug}}/series added")
