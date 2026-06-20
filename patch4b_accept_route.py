#!/usr/bin/env python3
"""Thread the target-collection choice through the split-accept route, and give
the preview page the list of collections to choose from.

Modifies app/collections.py:
  - view_split_job: pass `all_collections` (id, title) to split_job.html.
  - accept_split_job: read optional target_collection_id form field and pass it
    to upload_split.accept_job.

Run from ~/gshadow. Anchors must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/collections.py"
text = open(PATH).read()

EDITS = [
    # 1. view_split_job: add all_collections to context. Anchor on its
    #    TemplateResponse context dict (unique to split_job.html).
    (
        "Pass all_collections to split_job.html",
        '''    return templates.TemplateResponse(
        request, "split_job.html",
        {"job": job, "meta": meta, "clips": clips,
         "collection_slug": collection_slug, "user": user},
    )''',
        '''    all_collections = db.execute(
        "SELECT id, title FROM collections ORDER BY title"
    ).fetchall()
    return templates.TemplateResponse(
        request, "split_job.html",
        {"job": job, "meta": meta, "clips": clips,
         "collection_slug": collection_slug, "all_collections": all_collections,
         "user": user},
    )''',
    ),
    # 2. accept_split_job: add the target_collection_id form param + pass it on.
    (
        "Thread target_collection_id through accept_split_job",
        '''@router.post("/split/{job_id}/accept")
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
    return RedirectResponse(url=f"/c/{slug}", status_code=303)''',
        '''@router.post("/split/{job_id}/accept")
def accept_split_job(
    job_id: int,
    target_collection_id: str = Form(""),
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
    db: sqlite3.Connection = Depends(get_db),
):
    # Empty / "new" => create a new collection (original behaviour).
    target = None
    raw = (target_collection_id or "").strip().lower()
    if raw not in ("", "new", "0", "none"):
        try:
            target = int(target_collection_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "Bad target collection")
    try:
        slug = upload_split.accept_job(db, job_id, user["id"],
                                       target_collection_id=target)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return RedirectResponse(url=f"/c/{slug}", status_code=303)''',
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
print(f"OK: wrote {PATH} — split accept route now forwards target_collection_id")
