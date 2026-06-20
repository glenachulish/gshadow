#!/usr/bin/env python3
"""Add loose-clip assignment to collections.py:
  - a helper `_all_collections(db)` for populating pickers
  - a route POST /clips/assign that moves checked loose clips into a target
    collection (existing, by id) and appends position numbers.

Pure UPDATEs of clips.collection_id + clips.position. No files move, audio is
untouched, and it's reversible (assigning to collection_id NULL = back to loose).

Run from ~/gshadow. Reads the live app/collections.py, applies edits in memory,
refuses to write unless each anchor matched exactly once and the result parses.
"""
import ast
import sys

PATH = "app/collections.py"
text = open(PATH).read()

EDITS = [
    # 1. Add _all_collections helper right after _all_series (which the series
    #    recovery added). Anchor on the end of _all_series.
    (
        "Add _all_collections helper after _all_series",
        '''    try:
        return db.execute(
            "SELECT id, slug, title, category FROM series ORDER BY created_at DESC"
        ).fetchall()
    except sqlite3.OperationalError:
        return []''',
        '''    try:
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
    ).fetchall()''',
    ),
    # 2. Add the assignment route. Anchor it just before the split block's
    #    banner comment so it lands among the clip routes, after delete_clip.
    #    delete_clip ends with `return RedirectResponse(url="/", status_code=303)`
    #    immediately followed by the split section comment line.
    (
        "Insert /clips/assign route before the split-on-upload section",
        '''    return RedirectResponse(url="/", status_code=303)
# ===========================================================================
# Split-on-upload — upload one long file, split it in-app, preview, accept.''',
        '''    return RedirectResponse(url="/", status_code=303)


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
# Split-on-upload — upload one long file, split it in-app, preview, accept.''',
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
print(f"OK: wrote {PATH} — added _all_collections + POST /clips/assign")
