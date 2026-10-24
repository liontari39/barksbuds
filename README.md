# BarksBuds landing page + waitlist

A dependency-light Python server (`server.py`) that serves `public/` and stores waitlist signups.

- **Local:** `python3 server.py` → http://localhost:8080 (SQLite at `./data/waitlist.db`, mirrored to `./data/waitlist.csv`).
- **Production (Render):** set `DATABASE_URL` (Postgres) and `ADMIN_KEY`; `render.yaml` describes the service + free database.
- `PORT` (default 8080), `DATA_DIR`, `SITE_URL` (else Render's `RENDER_EXTERNAL_URL`) are optional.

## Endpoints
- `POST /api/waitlist` — JSON `{first_name, email, dog_name, zip?}`; validates, dedupes email case-insensitively.
- `GET /healthz` — health check (also pings the database).
- `GET /admin/export.csv?key=ADMIN_KEY` — download all signups as CSV (404 without the right key).
- `POST /admin/delete?key=ADMIN_KEY&email=ADDRESS` — remove one signup.
