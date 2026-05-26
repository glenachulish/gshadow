# Òrain — Project Notes: Lessons from Ceòl

*Version 4 — last updated 2026-05-22*

## What Òrain is

Òrain is a multi-user app in which each user keeps a personal library of *their own* songs in Gàidhlig and Beurla. It is **not** a communal Gaelic song archive — each library belongs to one curator, and there is no shared pool of canonical content. I run Òrain and hold admin rights; others may hold admin rights too, but admin is about operating the app, not co-owning anyone's library. This distinction matters, because some of Ceòl's conventions (and some of the "do it differently" advice that came out of Ceòl) were framed around either a single-user tune collection or a hypothetical shared archive. Òrain is neither: it's many single-curator libraries under one roof, with songs in two languages and a real wish to share individual songs — lyrics especially — with other people.

## Inherited stack — keep the simplicity

Ceòl is FastAPI + raw `sqlite3` with parameterised queries on the backend, and vanilla JS rendering the DOM directly on the frontend. No SQLAlchemy, no templating engine. That kept Ceòl small and debuggable. Unless Òrain has a concrete reason to diverge, inherit it — the family resemblance is worth more than the marginal convenience of an ORM at this scale.

## Songs and versions — two tables, not one

This is the biggest structural lesson. Ceòl versioned tunes with a self-referencing `parent_id` on a single `tunes` table: a parent row acted as a container, and the real musical data lived on the child rows. The parent often had null `type`/`key`/`abc`. That empty-parent pattern caused a real bug — type filters excluded versioned tunes because the parent had no `type`, and the fix was an awkward `OR EXISTS` subquery.

Don't carry that forward. Òrain should use two tables: a `songs` table for the thing you rate, favourite, and title, and a `song_versions` table for the thing you actually sing. A *song* is the identity; a *version* is a particular setting of it. No empty-container rows, no filter gotchas.

```sql
CREATE TABLE songs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  slug         TEXT UNIQUE NOT NULL,        -- for /songs/{slug}
  title        TEXT NOT NULL,
  composer     TEXT,
  rating       INTEGER,
  is_favourite INTEGER DEFAULT 0,
  on_hitlist   INTEGER DEFAULT 0,
  notes        TEXT,
  created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE song_versions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id       INTEGER NOT NULL REFERENCES songs(id),
  version_label TEXT,
  language      TEXT NOT NULL,              -- 'gd' | 'en' (Gàidhlig / Beurla)
  lyrics        TEXT,
  melody        TEXT,                       -- ABC or other notation
  source        TEXT,
  contributor   TEXT,
  transpose     INTEGER DEFAULT 0,
  is_canonical  INTEGER NOT NULL DEFAULT 0,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Personal metadata (rating, favourite, hitlist, notes, composer) lives on `songs` — a song is the thing you rate. Per-rendition data (lyrics, melody, source, contributor, transpose) lives on `song_versions`.

## Language is first-class

Òrain is bilingual, and the model for this is now **decided: language lives on `song_versions`, and a Beurla translation is a version of the song — not a separate, cross-referenced song.** A Gàidhlig song with a Beurla singing-translation is one song with two versions in different languages, distinguished by the `language` column on each version row.

This keeps "this is the same song" as the organising idea, which is how I think about them anyway. It also means the canonical-version machinery, the version panel, and share-by-URL all work for translations for free — no parallel cross-reference table, no second code path.

One wrinkle to settle when the version schema is finalised: a song's `title` lives on `songs`, but the Gàidhlig and Beurla renditions may be sung under genuinely different titles. Either the `version_label` carries the alternate title, or `song_versions` gets an optional `version_title` column. Flagged in the to-do list as an open decision.

## Versioning lifecycle

Keep Ceòl's explicit choice between editing in place and creating a new version. Plain edits (title, composer, notes, rating, favourite) PATCH the existing row in place. "Save as new version" creates a new `song_versions` row and prompts for a `version_label` — "Diggers version", "Up a 4th", "English singing translation".

Trap worth restating loudly: **every field that should differ between versions must be in the `VersionCreate` Pydantic model.** Ceòl lost five patches discovering that `transpose` wasn't in `TuneCreate` — FastAPI silently dropped it, and every child came out identical to its parent. Audit the create model against the versioned columns before trusting it.

## First-class canonical version

Ceòl had an `is_default` flag but barely used it — the parent row was the de facto default. Òrain should make this real: an `is_canonical` flag on `song_versions`, enforced as exactly-one-per-song at the application layer. When you add a version, you explicitly choose whether it *replaces* the canonical one or *supplements* it. The canonical version is what auto-loads when you open a song.

## Real URLs for songs

Ceòl is a single-page app served at `/mobile`; tunes have no shareable URL. For Òrain this is worth fixing, because you send people lyrics. Give songs real URLs — `/songs/{slug}` for a song, `/songs/{slug}/v/{version_id}` for a specific version. A slug derived from the title is far friendlier than an opaque id when the URL ends up in a text message.

## Sharing — reframed for a personal library

The original Ceòl notes suggested a "public catalogue + personal annotations layered on top" model, on the assumption Òrain was a shared archive. It isn't — it's my library, so the communal-archive design doesn't apply. But the underlying observation still holds: songs want to be shareable in a way tunes don't.

The right shape for Òrain is **one-directional, read-only sharing**: a song (or a specific version) can be made viewable at its URL so I can send lyrics to someone, without giving them an account or any edit rights. No public catalogue, no contributor model — just a per-song "shareable" flag plus the clean URLs above.

## User / admin model

Òrain is multi-user, and the model is now **decided: per-user SQLite databases**, following Ceòl. Each user gets their own library file — `data/users/{user_id}/orain.db` — plus a shared `data/users.db` for auth (users, sessions, invites, password resets). There is no `user_id` column on `songs` or `song_versions`; isolation is by file, not by `WHERE` clause.

Why inherit this: the library schema needs zero multi-user changes, and a buggy "return all rows" query cannot leak across users by construction — there is nothing to leak into, because each connection only ever opens one user's file. The cost is that genuine cross-user features (read-only song sharing) need an explicit, deliberate cross-database read — which is fine, because that is exactly the one place where crossing the boundary should be a conscious act.

Admin is a simple `is_admin` integer flag on the `users` row in `users.db`. I am the first admin; others can be granted admin too. Admin governs *operating* the app — issuing invites, disabling accounts, bootstrap — not co-ownership of anyone's library. There is no "editor"/"viewer" middle tier: you're admin or you're not, which is right for this scale.

Auth lessons from Ceòl to carry forward verbatim:

- Use bcrypt directly, not passlib. Passlib 1.7.4 breaks against bcrypt 5.x on Python 3.13 — it reads `_bcrypt.__about__.__version__`, which no longer exists. Work factor 12. Pin `bcrypt>=4.0.0`.
- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure`, 90-day `Max-Age`. Survives PWA close/reopen on iOS.
- The auth DB context manager does **not** auto-commit. Session INSERTs need an explicit `conn.commit()` or they roll back silently when the connection closes. (Lost an evening to this in Ceòl.)
- Resolve the session user once in HTTP middleware into a `contextvars` variable, and let the `_db()` connection factory read it to pick the right database file. No endpoint signature should ever mention `user_id`.
- For initial admin bootstrap, use the pattern Ceòl intended but never shipped: an `ORAIN_INITIAL_ADMIN` env var checked at startup, prompting for a password on first boot if no admin exists. Cleaner than the manual SQL route.

## Seed content and migrating my existing songs

New accounts start with an empty library — the right default, since each user's songs are their own. If a starter corpus of well-known songs is ever wanted for new singers, the clean pattern is to ship a `data/seed/orain.db` and `cp` it into `data/users/{new_id}/orain.db` during the invite-accept flow, rather than inventing a live "starter pack" mechanism.

For my own library, "seeding" is a one-off import of my existing songs, run after my account is bootstrapped.

**Where those songs are.** There is an earlier, separate app — also called Òrain — already deployed on the Pi at `https://ceol-pi.tail01672f.ts.net`. I built it with DeepSeek; it describes itself as a "Gaelic song archive". It is *not* this project and shares no code with it: it predates the rethink in these notes (single shared archive, no per-user libraries, no `songs`/`song_versions` split, monolingual framing). I have no attachment to that app itself — the only thing worth keeping from it is the songs. It is the **migration source**, nothing more.

**Migration plan.** Once my account exists (end of Phase 2), do a one-off extraction from the old app and load it into my new per-user `orain.db`. The clean route, in order of preference:

1. If the old app exposes a JSON API or its raw SQLite file can be copied off the Pi, read songs directly from that — most reliable.
2. Otherwise, scrape the live song list and per-song pages via the browser tools (Chrome MCP), which can reach the Pi URL directly.

Either way the extracted data must be mapped onto the new schema: each old song becomes a `songs` row, its lyrics/melody become a `song_versions` row with `is_canonical = 1` and an explicit `language`. The old app's flat model will not carry version or language structure, so every imported song starts as a single canonical version, to be enriched later. This is a throwaway script, not a permanent feature — it belongs in a one-off `scripts/` file, not the app.

Until the import is done and verified, the old Pi app is the source of truth for those songs and must not be disturbed or deleted.

## Traps to carry forward — quick checklist

- Every per-version field must be in the `VersionCreate` Pydantic model, or FastAPI drops it.
- No empty-container rows — the `songs`/`song_versions` split avoids the type-filter bug class entirely.
- Auth DB context manager: commit explicitly.
- bcrypt direct, not passlib; pin `bcrypt>=4.0.0`.
- Enforce exactly-one canonical version per song in application code, not just at the schema level.
- Language lives on `song_versions`; a Beurla translation is a version of the song, not a cross-referenced second song.
- Isolation is per-file — there is no `user_id` column. Cross-user reads (shared songs) are the one deliberate boundary crossing.
- Test-only dependencies (e.g. `httpx`, which FastAPI's `TestClient` needs) belong in a separate dev-requirements file — never in `requirements.txt`. Keep the runtime dependency list as lean as the Ceòl stack intended.

---

# Build to-do list

How to use this: this list lives at the bottom of the project notes. At the end of each working session, tick off what's done, add anything new that surfaced, and add a one-line entry to the session log below. Items are ordered roughly by dependency — schema before endpoints, endpoints before UI — so working top-down should mostly avoid blocking yourself.

File-handling convention: the canonical `orain-project-notes.md` replaces the project copy each session, so there is only ever one notes file in the project. A timestamped twin (e.g. `orain-project-notes_2026-05-22_1730.md`) is kept as a personal archive *outside* the Claude project. Bump the `Version` line at the top of this document each session.

## Phase 1 — Foundations

- [x] Scaffold the FastAPI app and project layout (`backend/`, `data/`, `static/`)
- [x] Pin dependencies (`fastapi`, `uvicorn`, `bcrypt>=4.0.0`) — no passlib, no SQLAlchemy
- [x] Define the `users.db` schema: `users`, `sessions`, `invites`, `password_resets`
- [x] Define the per-user `orain.db` schema: `songs`, `song_versions`
- [x] Write an incremental `_migrate()` for future schema changes
- [x] Build the `_db()` connection factory that opens the right user's file from a contextvar

## Phase 2 — Auth and multi-user

Split into two halves on purpose: build and test 2a before starting 2b, so
that "can I log in on the Mac?" is verified before the invite/admin work
piles more on top. A login bug found at the end of 2a is cheap; the same bug
found after 2b is buried under five other moving parts.

### Phase 2a — Core auth (login must work end-to-end before 2b)

- [ ] Password hashing with bcrypt directly, work factor 12
- [ ] Session middleware: resolve the session token into a `current_user_id` contextvar
- [ ] Login / logout endpoints; set the session cookie (`HttpOnly`, `SameSite=Lax`, `Secure`, 90-day)
- [ ] Remember the explicit `conn.commit()` on every auth-DB write
- [ ] `ORAIN_INITIAL_ADMIN` bootstrap — prompt for a password on first boot if no admin exists
- [ ] **Checkpoint:** boot on the Mac, log in as the bootstrapped admin, confirm the session cookie survives a browser restart

### Phase 2b — Invites and admin

- [ ] Invite flow: create an invite, accept an invite, provision the new per-user `orain.db`
- [ ] `is_admin` checks on admin-only endpoints

## Phase 3 — Songs and versions

- [ ] Song CRUD endpoints (list, get, create, patch, delete)
- [ ] Version endpoints — audit `VersionCreate` against **every** per-version column before trusting it
- [ ] `is_canonical`: enforce exactly-one-per-song in application code
- [ ] "Save as new version" vs "edit in place" lifecycle
- [ ] Slug generation from title; `/songs/{slug}` and `/songs/{slug}/v/{version_id}` routes
- [ ] **Decision:** how to handle differently-titled translations — `version_label` vs a `version_title` column

## Phase 3.5 — Import existing songs

Runs once the song schema and endpoints exist (needs Phase 3) and my admin
account exists (needs Phase 2a). A throwaway one-off script in `scripts/`,
not an app feature. See "Seed content and migrating my existing songs" above.

- [ ] Inspect the old DeepSeek-built Òrain on the Pi — does it expose a JSON API, or can its SQLite file be copied off?
- [ ] Write a one-off extraction: API/DB file if available, otherwise scrape the live pages via Chrome MCP
- [ ] Map each old song to one `songs` row + one canonical `song_versions` row with an explicit `language`
- [ ] Run the import into my `orain.db`; spot-check song count and a few sets of lyrics against the old app
- [ ] Only after the import is verified: the old Pi app is no longer the source of truth and may be retired

## Phase 4 — Frontend

- [ ] Library list view (vanilla JS, direct DOM rendering)
- [ ] Song view with a version panel and back-to-versions navigation
- [ ] Language display / toggle for `gd` vs `en` versions
- [ ] Create and edit forms for songs and versions
- [ ] Lyric diff between versions (more valuable for lyrics than it ever was for ABC)

## Phase 5 — Sharing

- [ ] Per-song `shareable` flag
- [ ] Read-only public song view at `/songs/{slug}`
- [ ] Cross-database read to serve a shared song — the one deliberate boundary crossing

---

# Session log

One or two lines per session: date, what got done, what's next.

- **2026-05-22** — Project notes drafted from the Ceòl lessons. Locked in: multi-user with per-user databases, language as a property of `song_versions` (translation = version), build to-do list created. Next: start Phase 1, scaffold the app.
- **2026-05-22** — Phase 1 complete. Built the app scaffold, pinned dependencies, the `users.db` and `orain.db` schemas, an incremental `PRAGMA user_version` `_migrate()`, and the `_db()` / `auth_db()` connection factories. Smoke-tested in development and confirmed running on the Mac (`/health` returns 200 OK). Decisions recorded: (1) deliberate commit asymmetry — `_db()` auto-commits on clean exit, `auth_db()` does not; revisit if consistency is preferred. (2) The project ships with a `setup_orain.sh` builder script rather than loose files, so the layout is reproducible. Next: Phase 2 — auth and session middleware.
- **2026-05-22** — Housekeeping session. Ticked off all of Phase 1. Identified the app at `https://ceol-pi.tail01672f.ts.net` (titled "Òrain — Gaelic Song Archive") as the *earlier* DeepSeek-built Òrain — a separate app, not this codebase, kept only as the source of existing songs. Restructured the to-do list: Phase 2 split into 2a (core auth, with a login checkpoint on the Mac) and 2b (invites + admin); new Phase 3.5 added for the one-off song import from the old Pi app. Notes section "Seed content" rewritten as "Seed content and migrating my existing songs" with the migration plan. Next session: Phase 2a.
