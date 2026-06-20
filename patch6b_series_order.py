#!/usr/bin/env python3
"""Order chapters within a series by a manual position (falling back to
created_at where unset), expose the current positions to the template, and add
a route to save a new order.

Modifies app/series.py:
  - view_series: SELECT series_position; ORDER BY series_position IS NULL,
    series_position, created_at  (nulls last, then position, then creation).
  - new route POST /series/{slug}/order: read typed numbers, sort chapters by
    them, write back a normalised 1..N sequence.

Run from ~/gshadow. Each anchor must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/series.py"
text = open(PATH).read()

EDITS = [
    # 1. view_series query: add series_position to SELECT and change ORDER BY.
    (
        "Order view_series chapters by position then created_at",
        '''    collections = db.execute(
        "SELECT c.id, c.slug, c.title, c.description, c.created_at, "
        "       COUNT(cl.id) AS clip_count "
        "FROM collections c "
        "LEFT JOIN clips cl ON cl.collection_id = c.id "
        "WHERE c.series_id = ? "
        "GROUP BY c.id "
        "ORDER BY c.created_at ASC",
        (series["id"],),
    ).fetchall()''',
        '''    collections = db.execute(
        "SELECT c.id, c.slug, c.title, c.description, c.created_at, "
        "       c.series_position, COUNT(cl.id) AS clip_count "
        "FROM collections c "
        "LEFT JOIN clips cl ON cl.collection_id = c.id "
        "WHERE c.series_id = ? "
        "GROUP BY c.id "
        "ORDER BY c.series_position IS NULL, c.series_position, c.created_at ASC",
        (series["id"],),
    ).fetchall()''',
    ),
    # 2. Add the order route. Anchor it just before the delete-series section
    #    comment (unique).
    (
        "Insert /series/{slug}/order route before the delete-series section",
        '''# ---------------------------------------------------------------------------
# Delete a series (admin/uploader, tailnet-only).''',
        '''# ---------------------------------------------------------------------------
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
# Delete a series (admin/uploader, tailnet-only).''',
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
print(f"OK: wrote {PATH} — view_series orders by position; POST /series/{{slug}}/order added")
