# Gaelic Shadowing Practice

A small self-hosted site for Scottish Gaelic shadowing practice: browse and
listen to short audio clips with descriptions and learner advice. Designed
to run on `ceol-pi` alongside the existing `ceol` service.

## Architecture in one paragraph

FastAPI + SQLite + Jinja2, listening on `0.0.0.0:8003`. Public access via
**Tailscale Funnel on port 10000** (since 443 and 8443 are taken). All
browse / listen routes are public. Login, upload, and admin routes are
gated by a **Tailscale-network source IP check** — Funnel proxies arrive
from `127.0.0.1` and are blocked, direct tailnet traffic arrives from
`100.64.0.0/10` and is allowed. On top of that, a normal email/password
session (bcrypt + signed cookie) with three roles: `admin`, `uploader`,
`viewer`.

## Project layout

```
gshadow/
├── app/
│   ├── main.py             # FastAPI app and routes
│   ├── auth.py             # password hashing, session, tailnet gate
│   ├── db.py               # SQLite connection + schema + migrations
│   ├── users.py            # CLI for user management
│   ├── collections.py      # routes for collections + bulk upload + URL import
│   ├── importer.py         # background URL-import pipeline
│   ├── adapters.py         # site-specific scrapers (learngaelic.scot)
│   ├── migrations/
│   │   └── bundle_litir947.py  # one-off: bundle the original 28 clips
│   └── templates/          # Jinja2 HTML
├── seed/
│   ├── seed.py             # idempotent seeder from manifest.yaml
│   └── manifest.yaml       # list of pre-populated clips
├── audio/               # audio files (mounted at /audio)
├── data/                # SQLite database lives here
├── requirements.txt
├── gshadow.service      # systemd unit
├── mac-splitter.py      # local audio-splitting CLI for your Mac
└── .env.example
```

## One-time deployment on ceol-pi

```bash
# 1. Copy the project across (rsync, scp, or git clone)
rsync -av --exclude .venv --exclude data/gshadow.db --exclude audio \
    ./gshadow/ pi@ceol-pi.local:/home/pi/gshadow/

ssh pi@ceol-pi.local
cd ~/gshadow

# 2. Python environment
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3. Environment file (stable session secret!)
cp .env.example .env
sed -i "s/replace-me-with-a-long-random-hex-string/$(python3 -c 'import secrets; print(secrets.token_hex(32))')/" .env
chmod 600 .env

# 4. Create your admin user (prompts for password)
.venv/bin/python -m app.users create --email you@example.com --role admin

# 5. Drop pre-populated audio files into audio/, edit seed/manifest.yaml
#    to match, then seed:
.venv/bin/python -m seed.seed

# 6. Install and start the systemd service
sudo cp gshadow.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gshadow
systemctl status gshadow --no-pager

# 7. Expose via Tailscale Funnel on port 10000
sudo tailscale funnel --bg --https=10000 http://localhost:8003
sudo tailscale funnel status
```

Public URL: `https://ceol-pi.tail01672f.ts.net:10000/`

## How the access split works

| Route                  | Public via Funnel | Tailnet direct |
|------------------------|-------------------|----------------|
| `/`, `/audio/*`        | ✓                 | ✓              |
| `/login`               | ✗ (403)           | ✓              |
| `/upload`              | ✗ (403)           | ✓ + role       |
| `/admin/*`             | ✗ (403)           | ✓ + admin      |

- Funnel proxies HTTPS public traffic from port 10000 to `127.0.0.1:8003`
  on the Pi. The app sees source IP `127.0.0.1` and rejects login/upload/admin.
- A device on the tailnet hitting `http://ceol-pi:8003` directly arrives
  with a `100.x.x.x` source IP and passes the gate.
- Even after logging in, the `require_tailnet` dependency is re-checked
  on every protected request, so a stolen session cookie can't be used
  from outside the tailnet.

If you later want to invite an external user with upload rights (no
Tailscale install on their device), remove the `_: None = Depends(require_tailnet)`
line from the `/upload` routes in `app/main.py`. Their `role='uploader'`
+ password will be the gate.

## User management

```bash
# Create users (admin, uploader, or viewer)
.venv/bin/python -m app.users create --email alice@x.com --role uploader

# List
.venv/bin/python -m app.users list

# Reset password
.venv/bin/python -m app.users passwd --email alice@x.com

# Deactivate / reactivate
.venv/bin/python -m app.users deactivate --email alice@x.com
.venv/bin/python -m app.users activate   --email alice@x.com
```

Admins can also do all of this through the web UI at `/admin`.

## Useful one-liners

```bash
# Tail logs
ssh pi@ceol-pi.local 'sudo journalctl -u gshadow -n 50 --no-pager'
ssh pi@ceol-pi.local 'sudo journalctl -u gshadow -f'        # follow

# Restart the service
ssh pi@ceol-pi.local 'sudo systemctl restart gshadow'

# Kill a stuck port
ssh pi@ceol-pi.local 'sudo lsof -ti :8003 | xargs -r sudo kill -9'

# Service status
ssh pi@ceol-pi.local 'systemctl status gshadow --no-pager'

# Funnel status / disable
ssh pi@ceol-pi.local 'sudo tailscale funnel status'
ssh pi@ceol-pi.local 'sudo tailscale funnel --https=10000 off'

# Push code changes
rsync -av --exclude .venv --exclude data --exclude audio \
    ./ pi@ceol-pi.local:/home/pi/gshadow/ \
  && ssh pi@ceol-pi.local 'sudo systemctl restart gshadow'

# Backup database + audio
ssh pi@ceol-pi.local 'tar czf - -C /home/pi/gshadow data audio' \
  > gshadow-backup-$(date +%F).tar.gz
```

## What's been verified

The scaffold was smoke-tested end-to-end:

| What                                            | Result |
|-------------------------------------------------|--------|
| `GET /` lists clips publicly                    | 200    |
| `GET /healthz`                                  | 200    |
| `GET /login` from non-tailnet IP                | 403    |
| `GET /login` from loopback (dev override on)    | 200    |
| `POST /login` with wrong password               | 401    |
| `POST /login` with right password               | 303 + session cookie |
| `GET /upload` without session                   | 401    |
| `GET /upload` with admin session                | 200    |
| `POST /upload` with `.mp3`                      | 303, file persisted, listed on home page |
| `POST /upload` with `.txt`                      | 400 (extension rejected) |
| `POST /upload` with 30MB file                   | 400 (size limit), partial file cleaned up |
| `GET /audio/<filename>`                         | 200    |
| `POST /admin/users` creating an uploader        | 303, user appears in CLI listing |
| `POST /logout` + retry `/admin`                 | 401    |

Two bugs were caught and fixed during testing, both worth knowing about
if you ever need to debug:

1. **Starlette 1.0** changed `TemplateResponse`'s signature — `request`
   is now the first positional arg, not a key inside the context dict.
   Old form (`TemplateResponse("x.html", {"request": request, ...})`)
   raises `TypeError: unhashable type: 'dict'` at template lookup time.
2. **SQLite + async routes**: FastAPI runs sync dependencies on a
   threadpool and `async def` routes on the event loop. A connection
   created in one thread and used in another trips
   `sqlite3.ProgrammingError`. Fix is `check_same_thread=False` on
   `sqlite3.connect()` — safe here because each request gets a fresh
   connection via the `get_db` dependency.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Allow loopback through the admin gate for local testing.
# DO NOT set this on the Pi.
export GSHADOW_ALLOW_LOOPBACK_ADMIN=1
export GSHADOW_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

.venv/bin/python -m app.users create --email dev@local --role admin
.venv/bin/uvicorn app.main:app --reload --port 8003
```

Open <http://localhost:8003>.

## Things that are deliberately out of scope (for now)

- No per-clip edit/delete. Add a `DELETE /clips/{id}` route gated by
  `require_role("admin")` when you want it.
- No audio transcoding or duration extraction. If you want `duration_s`
  shown, add `ffprobe` shelling out in the upload handler.
- No self-signup. Add a `/signup` route creating `role='viewer'` rows when
  you're ready to open that up.
- No CSRF tokens. Session cookies are `SameSite=lax` which covers most
  cases for a small site, but add `itsdangerous`-backed CSRF if you start
  embedding the upload form elsewhere.
- No file-content validation beyond extension and size. If abuse becomes
  a concern, add `ffprobe` to verify the file actually decodes as audio.
