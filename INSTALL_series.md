# Series grouping — install guide (read me first)

Good morning. This is the collection-grouping feature ("series" / "book")
built to the design we agreed. It is staged for you to install; I could not
deploy or verify it myself (no access to your Mac or Pi), so this guide makes
the install as low-risk and recoverable as possible.

**The headline caution first**, because it matters:

> The repo connected to my Claude project is an OLDER copy — it predates your
> 2026-06-20 work. The `collection.html` in what I can see does NOT contain the
> resume-position `localStorage` code or the per-clip Delete buttons you shipped
> yesterday. So I deliberately did **NOT** give you a new `collection.html` —
> replacing yours would wipe out resume + per-clip delete. Instead there is a
> tiny by-hand edit to YOUR current `collection.html` (step 3 below).
>
> For the same reason, before you copy any file below, sanity-check it against
> your real `~/gshadow` copy. I'm confident about the files I rewrote (they don't
> overlap with yesterday's changes), but you know what's current and I'm working
> from a stale mirror.

---

## What's in this drop

**New files** (copy straight in):
- `app/series.py` — all series routes (create, view, delete).
- `app/templates/series.html` — the series page.
- `app/templates/new_series.html` — the create-series form.
- `deploy-series.sh` — deploy script with a service-health check baked in.

**Replace these** (I rewrote them from your committed versions + the new
feature; they don't touch yesterday's work):
- `app/db.py` — adds the `series` table + `series_id` column (idempotent).
- `app/collections.py` — series dropdown handling + series breadcrumb data.
- `app/main.py` — registers the series router; category page now shows series.
- `app/templates/category.html` — two bands: series, then loose collections.
- `app/templates/new_collection.html` — adds the optional "Series" dropdown.

**Edit by hand** (do NOT replace — see caution above):
- `app/templates/collection.html` — one breadcrumb change, step 3.

---

## Step 1 — Place the files

Copy the new and replaced files into `~/gshadow`, preserving paths. The
`app/templates/collection.html` in this drop is intentionally absent.

## Step 2 — Sanity-check before committing

```
cd ~/gshadow
git status
git diff --stat
```

Confirm the changed files are the ones listed above and nothing about
`.env`, `data/`, or `audio/` is staged. (`.gitignore` should already cover
them — confirm with `git status` rather than trusting it.)

## Step 3 — The one by-hand edit to collection.html

Open your CURRENT `app/templates/collection.html`. Near the top is the
breadcrumb block. It currently looks like this:

```
  <nav class="breadcrumb">
    <a href="/">Home</a>
    <span class="sep">›</span>
    <a href="/category/{{ category.slug }}">{{ category.title }}</a>
    <span class="sep">›</span>
    <span>{{ collection.title }}</span>
  </nav>
```

Insert ONE conditional block so a series level appears only when the
collection is in a series. The result should read:

```
  <nav class="breadcrumb">
    <a href="/">Home</a>
    <span class="sep">›</span>
    <a href="/category/{{ category.slug }}">{{ category.title }}</a>
    <span class="sep">›</span>
    {% if series %}
      <a href="/series/{{ series.slug }}">{{ series.title }}</a>
      <span class="sep">›</span>
    {% endif %}
    <span>{{ collection.title }}</span>
  </nav>
```

That's the only change to this file. The `series` variable is now passed to
the template by the rewritten `view_collection` route (it's `None` for
collections that aren't in a series, so the block simply doesn't render).

## Step 4 — Commit, then deploy

```
cd ~/gshadow
git add -A
git status
git commit -m "Add series grouping for collections (book/chapter)"
git push
chmod +x deploy-series.sh
./deploy-series.sh
```

`deploy-series.sh` rsyncs, restarts, then checks the service is
`active (running)`. **If the app fails to start, the script automatically
prints the last 50 journalctl lines** so you get the real traceback instead
of guessing — and prints the rollback line.

## Step 5 — Verify in real use (then, and only then, tick it off)

The migration runs on startup (idempotent — restart IS the upgrade). Once
the service is green:

1. Go to the **Other Audio** category page. As admin/uploader you'll see a
   **+ New series (book)** link. Create one (e.g. "Am Misneachadh").
2. Go to **New collection**. Confirm the new **Series** dropdown lists it.
   Create a collection assigned to that series.
3. Confirm that collection now appears **under the series card** on the
   category page, NOT in the loose list, and isn't shown twice.
4. Open that collection. Breadcrumb should read
   `Home › Other Audio › Am Misneachadh › <title>`.
5. Open a collection that is NOT in a series. Confirm its page, its
   breadcrumb (three levels, unchanged), the resume feature, and per-clip
   delete ALL still work exactly as before. This is the regression check
   that matters most.

## If something's wrong

- App won't start: the script already showed the traceback. Most likely
  cause if anything, given it compiled cleanly here, is a stale-file
  mismatch on the Mac. Read the traceback.
- Roll back entirely: `git revert HEAD` then `./deploy-series.sh` again.
- The migration is additive only (new table, new nullable column). It does
  not alter or drop anything, so a rollback of the code leaves the DB happy
  — the extra column/table just sit unused.

---

## Design notes carried into the build

- A series belongs to a category (its `category` column). It shows on that
  category's page, not the home page. The three-card home page is untouched.
- One series per collection (`collections.series_id`, nullable).
- Deleting a series orphans its chapters back to loose collections (their
  audio is kept) — both via `ON DELETE SET NULL` and an explicit UPDATE.
- Chapter order on the series page is by `created_at` (v1). If you ever add
  chapters out of order and care about sequence, that's the `series_position`
  follow-up we flagged — not built yet.
- Empty series are shown (with "0 chapters"), so you can create one then fill
  it.

When verified, update STATUS.md: mark the book-grouping item done, and note
the deferred `series_position` ordering question.
