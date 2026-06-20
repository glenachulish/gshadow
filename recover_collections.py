#!/usr/bin/env python3
"""Recover collections.py: take the trusted pre-rewrite version (155ad11),
which still contains the split routes, and apply ONLY the series changes onto
it. This restores /split (lost when collections.py was rewritten) while keeping
the series feature.

Run from ~/gshadow. It reads the original from git, applies the edits in
memory, validates each one matched exactly, writes app/collections.py, then
byte-checks the result.

Every edit below corresponds 1:1 to a hunk in the diff between 155ad11 and the
rewritten file, so the output = your original + series additions, nothing else.
"""
import subprocess
import sys

PATH = "app/collections.py"

# Pull the trusted original out of git rather than trusting any on-disk copy.
try:
    original = subprocess.check_output(
        ["git", "show", "155ad11:app/collections.py"], text=True
    )
except subprocess.CalledProcessError:
    sys.exit("ERROR: could not read 155ad11:app/collections.py — are you in ~/gshadow?")

text = original

# Each edit is (description, find, replace). find must appear EXACTLY ONCE.
EDITS = [
    # 1. Add the _all_series + _resolve_series_id helpers. Anchor on the end of
    #    _make_slug_unique (the function just before where they go).
    (
        "Add series helpers after _make_slug_unique",
        '''    while db.execute("SELECT 1 FROM collections WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug''',
        '''    while db.execute("SELECT 1 FROM collections WHERE slug = ?", (slug,)).fetchone():
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
    return row["id"] if row else None''',
    ),
    # 2. view_collection SELECT: add series_id column.
    (
        "Add series_id to view_collection SELECT",
        '        "category, created_at "',
        '        "category, series_id, created_at "',
    ),
    # 3. view_collection: fetch series row + pass into context. Anchor on the
    #    line that builds `cat` then the context dict opening. We insert the
    #    series fetch right before the TemplateResponse, and add the context key.
    #    The original has, after building clips and cat:
    #        return templates.TemplateResponse(
    #            request,
    #            "collection.html",
    #            {
    #                "collection": col,
    #    We add the fetch before `return` and "series": series after "collection".
    (
        "Insert series fetch before view_collection TemplateResponse",
        '''    from . import categories as cats_mod
    cat = cats_mod.get(col["category"])
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "collection": col,''',
        '''    from . import categories as cats_mod
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
            "series": series,''',
    ),
    # 4. new_collection_form: add db dependency + series_list to context.
    (
        "Add db dependency to new_collection_form",
        '''def new_collection_form(
    request: Request,
    user: dict = Depends(require_role("admin", "uploader")),
    _: None = Depends(require_tailnet),
):
    from . import categories as cats_mod
    return templates.TemplateResponse(
        request,
        "new_collection.html",
        {"error": None, "user": user, "categories": cats_mod.CATEGORIES},
    )''',
        '''def new_collection_form(
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
    )''',
    ),
    # 5. create_collection signature: add series_id form field.
    (
        "Add series_id Form field to create_collection",
        '''    category: str = Form("other"),
    files: List[UploadFile] = File(...),''',
        '''    category: str = Form("other"),
    series_id: str = Form(""),
    files: List[UploadFile] = File(...),''',
    ),
    # 6. create_collection body: resolve series id after category validation.
    (
        "Resolve series id in create_collection",
        '''    if not cats_mod.is_valid(category):
        category = "other"

    if not files:''',
        '''    if not cats_mod.is_valid(category):
        category = "other"

    resolved_series_id = _resolve_series_id(db, series_id)

    if not files:''',
    ),
    # 7. "no files" error response: add categories + series_list.
    (
        "Add series_list to the no-files error response",
        '''            {"error": "Please select at least one audio file.", "user": user,
             "categories": cats_mod.CATEGORIES},''',
        '''            {"error": "Please select at least one audio file.", "user": user,
             "categories": cats_mod.CATEGORIES, "series_list": _all_series(db)},''',
    ),
    # 8. unsupported-extension error response: add series_list.
    (
        "Add series_list to the bad-extension error response",
        '''                    "categories": cats_mod.CATEGORIES,
                },''',
        '''                    "categories": cats_mod.CATEGORIES,
                    "series_list": _all_series(db),
                },''',
    ),
    # 9. INSERT statement: add series_id column + a placeholder.
    (
        "Add series_id to the collections INSERT columns",
        '''        "source_url, category, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",''',
        '''        "source_url, category, series_id, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",''',
    ),
    # 10. INSERT values tuple: add resolved_series_id in the right position
    #     (after category, before uploaded_by → user["id"]).
    (
        "Add resolved_series_id to the INSERT values",
        '''            None,
            category,
            user["id"],
            _now(),
        ),
    )
    collection_id = cur.lastrowid''',
        '''            None,
            category,
            resolved_series_id,
            user["id"],
            _now(),
        ),
    )
    collection_id = cur.lastrowid''',
    ),
    # 11. rollback error response in create_collection: add categories+series_list.
    (
        "Add categories + series_list to the size-limit rollback error",
        '''            {"error": str(e), "user": user},
            status_code=400,
        )

    return RedirectResponse(url=f"/c/{slug}", status_code=303)''',
        '''            {"error": str(e), "user": user,
             "categories": cats_mod.CATEGORIES, "series_list": _all_series(db)},
            status_code=400,
        )

    return RedirectResponse(url=f"/c/{slug}", status_code=303)''',
    ),
]

for desc, find, replace in EDITS:
    count = text.count(find)
    if count != 1:
        sys.exit(
            f"ABORT: edit '{desc}' matched {count} times (expected exactly 1). "
            f"No file written. Your collections.py is untouched."
        )
    text = text.replace(find, replace)

# Sanity: the split routes and import must be present in the result.
required = [
    "from . import upload_split",
    'def split_form',
    'def split_upload',
    'def view_split_job',
    'def serve_staged_clip',
    'def rerun_split_job',
    'def accept_split_job',
    'def cancel_split_job',
    # and the series bits we just added
    'def _all_series',
    'def _resolve_series_id',
    'resolved_series_id',
]
missing = [r for r in required if r not in text]
if missing:
    sys.exit(f"ABORT: result is missing expected content: {missing}. No file written.")

with open(PATH, "w") as f:
    f.write(text)

print(f"OK: wrote {PATH}")
print(f"  - restored split routes + 'from . import upload_split'")
print(f"  - applied {len(EDITS)} series edits")
print("Now run: python3 -c \"import ast; ast.parse(open('app/collections.py').read()); print('syntax OK')\"")
