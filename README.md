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

## Waitlist welcome emails

`mailer.py` sends a branded welcome email (HTML + plain text) on a background thread after each *new* signup.
It never blocks or fails a signup, never sends on duplicate signups, and is **off until configured**:

| Env var | Example | Notes |
|---|---|---|
| `EMAIL_API_KEY` | `xkeysib-…` | Brevo key (Resend `re_…` also auto-detected; Mailjet uses `KEY:SECRET` + `EMAIL_PROVIDER=mailjet`) |
| `EMAIL_FROM` | `barksbuds.hello@gmail.com` | Must be a verified sender (later `hello@barksbuds.com`) |
| `EMAIL_FROM_NAME` | `BarksBuds` | Optional |
| `EMAIL_REPLY_TO` | | Optional, defaults to `EMAIL_FROM` |
| `EMAIL_PROVIDER` | `brevo` | Optional; `file` writes emails to `$DATA_DIR/outbox/` for local testing |

`GET /api/config` reports `{"email_confirmations": true|false}`, and the thank-you message only mentions an email when one is being sent.
Every email has a tokenized remove-me link (`/unsubscribe?e=…&t=…`, HMAC keyed from `ADMIN_KEY` or `UNSUBSCRIBE_SECRET`)
plus RFC 8058 one-click `List-Unsubscribe` headers; removing deletes the signup.
Render's free plan blocks outbound SMTP, so only HTTPS email APIs work there.
