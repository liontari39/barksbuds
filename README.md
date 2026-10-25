# BarksBuds landing page + waitlist

A dependency-light Python server (`server.py`) that serves `public/` and stores waitlist signups.

- **Local:** `python3 server.py` → http://localhost:8080 (SQLite at `./data/waitlist.db`, mirrored to `./data/waitlist.csv`).
- **Production (Render):** set `DATABASE_URL` (Postgres) and `ADMIN_KEY`; `render.yaml` describes the service + free database.
- `PORT` (default 8080), `DATA_DIR`, `SITE_URL` (else Render's `RENDER_EXTERNAL_URL`) are optional.

## Endpoints
- `POST /api/waitlist` — JSON `{first_name, email, dog_name, zip?}`; validates, dedupes email case-insensitively.
- `GET /api/runs` — all dog runs (static data plus approved member suggestions) with an ETag.
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

## Packs

Packs are regular groups of dogs and their people (`packs.py` data layer, `packweb.py` routes).

- `/packs` lists packs with region filters and a North Shore highlight. `/packs/new` starts one, and `/packs/<id>-<slug>` is the pack page (OG tags use the cover photo; an old slug 301-redirects).
- Fields: name, area and town, optional home run, description, fit, a cover photo (resized, EXIF-stripped, stored in the database) and visibility, which is *open* or *request to join*.
- Roles: the owner and co-organizers edit the pack, approve or deny requests, remove members and pin posts. Only the owner can promote or demote, transfer ownership or delete the pack, and the owner must transfer ownership before leaving.
- Members join with selected dogs. The pack page shows member dogs, member count, upcoming pack meetups and the home run.
- Pack meetups: `meetups.pack_id` (prefilled from `/meetups/new?pack=<id>` with the home run), badged on `/meetups`, with an optional members-only RSVP. New pack meetups notify members.
- Board (members only): posts with an optional photo, comments, pinning and reports. Reports appear in `/admin/reports` with hide actions. Posting is rate-limited.
- Discovery: "Packs near you" on `/me`, and "Packs that call this run home" on `/runs` (`/api/packs`).
- Emails: join request (to organizers), approved and new pack meetup. They are sent only to addresses in `PACK_EMAIL_ALLOWLIST` (falling back to `MEETUP_EMAIL_ALLOWLIST`). Members can opt out on `/me`, and each email has an unsubscribe link (`/emails/packs`, which supports one-click). Sample packs never send email.
- Admin (`?key=` ADMIN_KEY): `/admin/packs` hides or deletes packs and removes all sample packs and meetups at launch. `POST /admin/packs/test-email` (`id`, `kind`=request|approved|meetup) sends a "[Test]" email to the pack owner.
- Sign-in keeps a safe, same-site `next` path. For example, "Host a meetup here" returns the member to the host form with the run preselected.

## Suggest a run

Members help grow the dog run map (`runsugg.py` data layer, `runsweb.py` routes, `public/suggest.js`).

- **Where to start:** a "+ Suggest a run" button on `/runs` (signed-out visitors go through sign-in first), a "Know a dog run here?" popup when you tap an empty spot on the map (the pin is prefilled), and "Suggest an edit" and "Report wrong pin" links on every run card.
- **The form (`/runs/suggest`, sign-in required):** name, park, area and town, then an address and/or a pin you tap and drag on a Leaflet map (or "Use my location"). It also asks fenced, small-dog area and water (yes/no/not sure), surface, hours, notes, an optional photo (resized, EXIF/GPS stripped), a source link and whether to credit you by display name. "Somewhere else in the US" plus a state is allowed. Pins outside the US are rejected, and anything outside NYC, Long Island and Westchester is flagged.
- **Edits:** `?edit=<run id>` (`&pin=1` for a wrong pin) asks what needs fixing (the pin, some details, closed, something else) and records only the changed fields.
- **Safety:** CSRF, 5 suggestions per member per day (stored in the DB) plus an IP limit, everything escaped, and a duplicate warning when a pin is within about 150 m of a listed run or a pending suggestion. The warning has to be confirmed before a new run is sent.
- **Status:** members see their recent suggestions on the form and a status page at `/runs/suggest/s/<id>`, which shows the reason if a suggestion was declined.
- **Moderation (`/admin/runs?key=ADMIN_KEY`):** the queue shows flags, the pin, the photo and the source.
  - New runs can be edited before approval, with pin precision `member` (as dropped) or `exact` (confirmed) and optional credit. They go live as `m-<id>` in the `member_runs` table and are merged with the static data in `/api/runs`, `/runs`, the sitemap and meetup/pack run pickers.
  - Edits show a diff with per-field apply boxes, or "remove from the map" for closed runs.
  - Rejecting needs a reason.
  - The "Member changes" table can remove a member run or revert an edit.
- **Email:** each new suggestion emails `RUN_SUGGEST_EMAIL`, which defaults to the single address on the runs/pack/meetup allowlist. It goes only to addresses on `RUNS_EMAIL_ALLOWLIST` (falling back to `PACK_EMAIL_ALLOWLIST`, then `MEETUP_EMAIL_ALLOWLIST`), and the admin key is never included.
- There is no geocoding (no paid APIs). A run suggested with only an address goes live without a pin unless the admin adds coordinates.

## Co-owners (shared dogs)

A dog can belong to several accounts (partners, family, a dog walker). Code: `coowners.py` (data) and `coownweb.py` (pages).

- `dog_owners(dog_id, user_id, role)`: one `owner` row (the main owner, same as `dogs.user_id`) plus up to 5 `co-owner`
  rows. Existing dogs get their owner row at startup (idempotent backfill).
- The main owner invites by email from the dog's edit page ("Co-owners" panel). The email (tag `coowner-invite`, sent through
  the normal mailer from `EMAIL_FROM`) links to `/invite/<token>`. The token is stored hashed, works once, expires after 7 days
  and can be cancelled. Open invites count toward the cap of 5. Each account can send 10 invites a day.
- `/invite/<token>` shows a confirmation; accepting (a POST, so link scanners can't) signs the person in as the invited email
  (creating the account if needed), or adds the account that's already signed in.
- Co-owners can edit the profile and photos, RSVP to meetups and join packs with the dog, and see/request its pixel portrait.
  There's still one profile and one portrait per dog. Only the main owner can invite, cancel invites, remove co-owners and
  delete the dog. A co-owner can leave (`/me/dogs/<id>/leave`). Co-owned dogs show on `/me` with a "Co-owner" badge and
  don't count toward `MAX_DOGS`.
- When a main owner deletes their account, each dog with a co-owner passes to the longest-standing co-owner; dogs without one
  are deleted as before.

## Pixel Pals (hand-made portraits)

There's no in-browser maker. Members request a pixel-art portrait and the team makes it by hand with AI, one per dog (`portraits.py`, tables `portrait_requests` and `portrait_request_photos`).

- **Member side:** the "Get a pixel portrait" panel sits on `/me/dogs/<id>/edit#portrait-panel` and on the owner's view of the dog page. The owner sends 1 to 3 reference photos, any mix of gallery photos (checkboxes) and new uploads (`POST /me/dogs/<id>/portrait`, repeated `photo_id` fields and `photo` files). The panel says: "Add up to 3 photos. Best results: one full-body shot (standing, facing the camera) plus a clear close-up of the face, in good light. More angles help us get markings and ears just right." Uploads are stored as `kind='request'` and never served publicly. If any upload is bad, or there are more than 3 photos, nothing is saved. The photos are kept in order in `portrait_request_photos(request_id, n, photo_id)`, and `portrait_requests.photo_id` stays photo 1. Older single-photo requests are backfilled at startup. While a request is pending or done, the panel shows its status. A finished portrait is stored as `kind='portrait'`, can't be deleted from the gallery, and the owner can switch the main picture between it and photos.
- **Emails:** every request emails hello@barksbuds.app ("New pixel portrait request: <name>"; the body says how many reference photos were sent). The owner's ready/rejected emails go through the `MEETUP_EMAIL_ALLOWLIST` gate.
- **Admin** (header `X-Admin-Key`, a wrong key returns 404):
  - `GET /admin/portraits` HTML queue
  - `GET /admin/portraits/pending` and `GET /admin/portraits/<id>` JSON, with `photo_count`, `photo_ids` and `photo_urls` (plus `photo_url` for photo 1)
  - `GET /admin/portraits/<id>/photo/<n>.jpg` for reference photo n (1..3); `/admin/portraits/<id>/photo.jpg` is an alias for photo 1
  - `POST /admin/portraits/<id>/complete` multipart `image`. It becomes the main picture unless the owner changed it after requesting.
  - `POST /admin/portraits/<id>/reject` field `note`, shown to the owner. This frees the slot.
  - `POST /admin/portraits/<id>/reset` deletes the request and keeps the images.
- **Helper:** `python3 scripts/portraits.py [--url URL] list | fetch <id> | complete <id> <image.png> | reject <id> <note> | reset <id>`. It reads `.admin_key` without printing it. `fetch` saves `photo-1.jpg`…`photo-N.jpg`, `photo.jpg` (a copy of photo 1) and `request.json` to `/workspace/barksbuds-assets/portrait-requests/<id>/`.
- **Showcase:** `/pixel-pals` and the homepage section list done portraits. Lily's and Maggie's seeded AI portraits are marked done automatically (`mark_seeded_done`).
- The old 48 px maker sprites (`kind='pixel'`) stay stored and served at `/px/...`, but they aren't shown (`accounts.SHOW_OLD_SPRITES = False`). Old maker URLs redirect to the edit panel.
