#!/usr/bin/env python3
"""Make the home page able to render the 'assign loose clips to a collection'
picker by passing a `collections` list (id, title) into index.html.

Run from ~/gshadow. Validates the single anchor matched once and the result
parses before writing.
"""
import ast
import sys

PATH = "app/main.py"
text = open(PATH).read()

OLD = '''    from .categories import CATEGORIES
    cats = [
        {
            "slug": c.slug,
            "title": c.title,
            "description": c.description,
            "count": counts.get(c.slug, 0),
        }
        for c in CATEGORIES
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "clips": standalone,
            "categories": cats,
            "user": current_user(request),
        },
    )'''

NEW = '''    from .categories import CATEGORIES
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
    )'''

n = text.count(OLD)
if n != 1:
    sys.exit(f"ABORT: anchor matched {n} times (expected 1). No file written.")
text = text.replace(OLD, NEW)
try:
    ast.parse(text)
except SyntaxError as e:
    sys.exit(f"ABORT: result has a syntax error: {e}. No file written.")
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — index route now passes `collections` to the template")
