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

## Member accounts and dog profiles

- **Sign in** at `/signin` with an emailed magic link (no passwords). Links are single-use, expire after 20 minutes,
  and only a SHA-256 hash of the token is stored. Sessions use a `Secure; HttpOnly; SameSite=Lax` cookie (30 days),
  requests are rate-limited per email and per IP, and every form is CSRF-protected.
  New accounts are linked to an existing waitlist signup with the same email.
- **Owners** set a display name, area (NYC boroughs, Nassau, Suffolk, Westchester), town and short bio at `/me/profile`.
- **Dogs** (up to 6 per account): name, breed, birthday or age, sex, size, personality tags, play style, self-reported
  vaccination badge, up to 5 favorite runs from the run map, bio and up to 8 photos. Photos are re-encoded server-side
  (EXIF/location stripped, 1600px JPEG + 640px WebP) and stored in Postgres.
- **Public pages**: `/dogs` (browse with area filter) and `/dogs/<slug>` (with Open Graph tags). Owner emails are never shown.
- **Reports**: anyone can report a profile; review them at `/admin/reports?key=ADMIN_KEY` (resolve, hide or unhide).
- Code: `accounts.py` (data layer), `webapp.py` (pages and routes), `public/app.css` (styles), `seed.py` (first profiles).

Tests (SQLite, and Postgres when `TEST_DATABASE_URL` is set):

    python3 -m unittest discover -s tests -v

## Meetups

Members can host meetups at a dog run from the runs data (pinned, with directions) or at a custom address, and RSVP
Going/Maybe with their dogs. Capacity counts dogs marked Going; extra RSVPs join a waitlist and are promoted first-in,
first-out when a spot opens. Pages: `/meetups` (filters: `area`, `region`, `ns=1` for the North Shore, `when=week|weekend`,
`view=map`), `/meetups/<id>-<slug>` (Open Graph tags, `.ics`, Google Calendar, directions, attendee comments),
`/meetups/new`, and `/admin/meetups?key=...` for hiding/deleting meetups (including bulk hide/delete of sample meetups).
Code: `meetups.py` (data), `meetweb.py` (pages/routes), email templates in `mailer.py`.

Emails (Brevo, async): RSVP confirmation, host notice, waitlist promotion, cancellation and a day-before reminder.
Each has an unsubscribe link (`/emails/meetups`, also RFC 8058 one-click) and members can toggle meetup emails on `/me`.
Sample meetups (`is_sample=1`, e.g. the seeded one) never send emails or reminders.

* `MEETUP_EMAIL_ALLOWLIST` (optional, comma-separated): when set, meetup emails go only to these addresses (testing).
* `MEETUP_AUTO_REMINDERS=0` disables the in-process reminder check.

Reminders: Render's free plan sleeps when idle, so there is no always-on scheduler. While the app is awake, any request
(including Render's health checks) triggers a reminder check at most every 10 minutes. For reliable timing, also call
`POST /admin/meetups/reminders` hourly from any scheduler, with the admin key in an `X-Admin-Key` header (or a `key`
form field). It sends reminders for meetups starting in 1 to 24 hours, at most once per meetup, and returns JSON.
`POST /admin/meetups/test-email` (`key`, `id`, `kind`=confirm|host|promoted|cancel|reminder) sends one "[Test]" copy of
an email type to that meetup's host only.
