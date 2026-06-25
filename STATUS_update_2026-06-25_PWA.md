# STATUS update — 2026-06-25 (PWA)

*Standalone session block. The PWA session entry and follow-ups were already
folded into `STATUS.md` directly this session (via `pwa_tidy_and_status.py`)
and committed/pushed — so this file is a self-contained record of the session
rather than something to paste in. Keep it alongside the other
`STATUS_update_*` files, or delete once you've confirmed `STATUS.md` reads
correctly.*

---

## Session history — 2026-06-25: installable PWA (app shell)

Made the site an installable Progressive Web App. App-shell only — audio is
deliberately NOT cached for offline (see decision). Verified installed to the
iOS home screen with a custom icon. Committed and pushed
(`6d91369..5296897`); Mac, Pi, and GitHub are consistent.

### Shipped and verified

- **Installable PWA.** Site can be added to the iOS home screen and launches
  standalone with a green waveform icon. The app shell loads from a
  service-worker cache; page navigations are network-first so logged-in /
  admin / fresh content always win when online, falling back to the cached
  shell offline.
- **New assets, all under `audio/_pwa/`** (the only writable path besides
  `data/` under systemd `ProtectSystem=strict`):
  - `manifest.json` — name, short_name, theme colour `#2d5a3d`, `standalone`
    display, icon set (192/512 + maskable variants).
  - `sw.js` — service worker. Network-first for navigations; cache-first for
    the small shell asset list. **Explicitly bypasses** `/audio/*`, `/login`,
    `/logout`, `/upload`, `/admin`, `/import`, `/split` — no audio bytes and
    no auth-state pages are ever cached.
  - Icons: `icon-192`, `icon-512`, `icon-192-maskable`, `icon-512-maskable`,
    `apple-touch-icon.png` (green waveform motif on accent green).
- **`app/main.py`** — three new routes, inserted before `/healthz`:
  `GET /manifest.json`, `GET /sw.js`, and a name-allowlisted
  `GET /{icon}.png`. All read from `audio/_pwa/` via `FileResponse`. `/sw.js`
  sends `Service-Worker-Allowed: /` and `Cache-Control: no-cache`.
- **`app/templates/base.html`** — manifest link, `theme-color`, iOS
  web-app meta tags, `apple-touch-icon` link, and the service-worker
  registration script before `</body>`.

### Key decisions

- **Served from site root, not `/audio/`.** A service worker can only control
  URLs at or below its own path, so `/sw.js` must sit at root for its scope to
  cover the whole app. Hence dedicated routes rather than the existing
  `/audio` static mount.
- **Tracked in git despite `audio/*` being gitignored.** Added a
  `!audio/_pwa/` + `!audio/_pwa/*` exception. These are app *source* (they
  define the installable app), not runtime data like uploaded clips — without
  versioning them, a fresh Pi rebuild would silently ship a broken PWA with no
  error.
- **Audio NOT cached offline (v1).** Caching clips for true offline shadowing
  is a separate, larger job (storage caps, cache invalidation on clip
  delete/replace). v1 is an installable, fast app shell only. Offline-audio is
  a possible future item, not committed to.

### Deploy gotcha learned

The rsync deploy excludes `audio/`, so the `_pwa/` files do **not** travel via
the normal deploy. This session they reached the Pi by direct scp:

    scp -r audio/_pwa pi@ceol-pi.local:/home/pi/gshadow/audio/

After any future change to PWA assets: scp them across (or temporarily drop
the `audio` rsync exclude for that deploy), then restart the `gshadow`
service. A route-not-found symptom (404 on `/manifest.json`) means the Pi has
the asset files but not the patched `main.py`, or the service wasn't
restarted — that exact sequence bit us this session and was fixed by
rsyncing `app/` and restarting.

### iOS icon caching note

The home-screen icon comes from `apple-touch-icon`, **not** the manifest
icons, and Safari caches it hard. An early install attempt (made while the
routes were still 404) cached the icon's absence; the fix was
Settings → Apps → Safari → Clear History and Website Data, then reload the
site and Add to Home Screen. Confirmed working afterwards.

### Housekeeping done this session

- Deleted the one-shot patch scripts (`patch_base_html.py`,
  `patch_main_py.py`) and the tidy script (`pwa_tidy_and_status.py`) after
  use.
- Committed the long-standing `deploy-series.sh` mode change
  (`100644 => 100755`) to settle the persistent `M` in `git status`.

---

## To-do list — ticks from this session

- [x] **Installable PWA (app shell).** DONE & verified 2026-06-25. Manifest,
      service worker, icons under `audio/_pwa/`; root-scoped routes in
      `main.py`; meta + SW registration in `base.html`; `audio/_pwa/`
      git-tracked via gitignore exception. Installed to iOS home screen.

### New follow-ups logged (not scheduled)

- [ ] (Optional) Cache audio for true offline practice. Bigger job: storage
      caps, cache invalidation when clips are deleted/replaced. Not committed
      to.
- [ ] (Housekeeping) Add `.DS_Store` to the rsync `--exclude` list in
      `deploy-series.sh` so Mac cruft stops reaching the Pi (one
      `app/.DS_Store` already synced once; harmless, untracked). `.DS_Store`
      is already in `.gitignore`.

### Still open (carried over, unchanged)

- [ ] **Audit `main.py` against `155ad11`** (from 2026-06-20 session 2 — still
      outstanding). Until done, treat `main.py` as "working but unaudited".
      Note: today's PWA routes are an *expected* addition on top of whatever
      that audit establishes as the clean baseline.
- [ ] Three transcript blocks on collections (`language_notes` column, etc.)
- [ ] Whisper / ÈIST Gaelic transcription — decide whether to pursue
- [ ] "Currently working on" filter on collections
- [ ] Tune splitter defaults; update `USER_GUIDE.md` with `--mode pauses`
- [ ] Reordering of clips *within* a collection
- [ ] Refile `~/Desktop/misfiled-from-gshadow/`; decide on
      `~/dot-git-OLD-home-repo`

---

## Quick reference — routes added this session

- `GET /manifest.json` — serves `audio/_pwa/manifest.json`
  (`application/manifest+json`).
- `GET /sw.js` — serves `audio/_pwa/sw.js` with `Service-Worker-Allowed: /`
  and `Cache-Control: no-cache`.
- `GET /{icon}.png` — name-allowlisted icon route (icon-192, icon-512,
  the two maskable variants, apple-touch-icon), serving from `audio/_pwa/`.

## Files changed this session

- New: `audio/_pwa/{manifest.json, sw.js, icon-192.png, icon-512.png,
  icon-192-maskable.png, icon-512-maskable.png, apple-touch-icon.png}`
- Modified: `app/main.py`, `app/templates/base.html`, `.gitignore`,
  `STATUS.md`, `deploy-series.sh` (mode only).
- No schema changes. No new Python dependencies.
