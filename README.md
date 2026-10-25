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

## Pixel pals

Members can turn a photo of their dog into a crisp pixel-art sprite (`public/pixelpal.js` pipeline, `public/pixelmaker.js` UI, `pixelweb.py` routes). It is free to run: all image work happens in the visitor's browser, with no paid APIs.

- Maker: `/me/dogs/<id>/pixel` (owner only). It's linked as "Make my pixel pal" on the dog's page, the edit page and the dashboard card. Members pick one of the dog's photos or upload one. The photo never leaves the device, and only the finished PNG sprite is uploaded.
- Background removal: MediaPipe Tasks Vision 1.1.1 with the MagicTouch interactive segmenter (both Apache-2.0, vendored in `public/vendor/mediapipe/` with LICENSE and NOTICE, served gzipped with week-long caching). Members tap the dog to select it and tap again to add missed parts. Keep and erase brushes and a crop box handle the rest. If the model can't load (an old browser without WebAssembly SIMD), the maker switches to these manual tools.
- Pipeline (`PixelPal.render`, DOM-free and unit-tested in node):
  1. Tight crop and edge-preserving smoothing.
  2. Area-average to a 32, 48 or 64 px grid, with a tone remap for very dark or light coats and emphasis on small dark features such as eyes and nose.
  3. OKLab k-means palette (8–24 colors, plus accent colors for small vivid details like a red tag), with a saturation and contrast boost, light/shadow shading and optional ordered dither.
  4. Stray-pixel cleanup, a 1-px dark or soft outline and an optional ground shadow.
  5. A transparent or brand-color backdrop.
  6. Nearest-neighbor upscale.
- Styles: the maker offers exactly two, in a big two-option picker with preview thumbnails (`public/img/style-*.png`). Size, detail, colors, outline, face, mouth, eyes and big-head controls live under an **Adjust** expander. Classic, Retro 8-bit and Soft stay in `PixelPal.PRESETS` in code only.
- **Game Sprite** (`game`, the default; the photo-detailed cel path): 48 px by default (32/64 under Adjust), 6 base colors with cel highlight/shadow tones, one dark ink outline, ground shadow, chibi big head 1, blush and a little "ω" smile.
  - Eyes: `eyes: "friendly"` draws a dark pupil with a white shine and no colored iris ring on light coats (the amber ring looked scary on Maggie). Dark coats keep the original eye, which is why Lily's sprite looks the way it does. "Ringed" is an Adjust option.
  - The Adjust **Detail** slider's middle step is exactly the preset; lower merges more, higher keeps more photo texture.
- **Chunky** (`chunky`, `toon: true`, its own `renderToon` path): a cute, extra-chunky, classic game-character look, modeled on the sprites in the Maggie the Merle "Floor Vacuum" game (used only as a style reference, never as output). It builds the sprite from a few flat shapes and hand-drawn stamps instead of copying photo detail:
  - Size: 32 px by default; Small (24 px) and Large (40 px) are also offered.
  - Chibi build (`chibi`, 0–1.5): before pixelation, a bulge warp grows the head (more on full-body photos with a small head), and `stubby` squeezes the body and legs below and beside it.
  - Color: about 8–12 colors in total, including the outline. The coat is split into 1–3 big flat regions (`regularize` merges small islands), each with a base, a shadow and a top-left highlight tone. Black coats become cool charcoal with a soft blue-grey highlight and a sparse curl hint. Merle coats get a few chunky spots where the photo is darkest, never on the face. Dark eye-band "masks" on light coats are cleared so the face stays friendly.
  - Silhouette: rounded (`roundAlpha` fills notches, cuts square corners and drops 1-px nubs), with one dark ink outline tinted to the coat.
  - Face stamps (the **Eyes** and **Nose** tools mark points; `PixelPal.guessFace` tries a guess first): small dark dot eyes with one 1-px white shine (or **Happy (^ ^)**), a cream muzzle, a rounded nose, tongue or smile, and soft blush.
  - Accent: a small vivid red spot that isn't right under the nose (a collar tag) becomes a clear 3×3 red heart (2 px at 24 px).
- Saving: `POST /me/dogs/<id>/pixel` (CSRF, owner only, 30/hour) accepts only square 16–128 px PNGs up to 200 KB with visible pixels. The server re-encodes the sprite (dropping all metadata) and stores it in the `photos` table as `kind='pixel'`, with `dogs.pixel_photo_id` and `dogs.pixel_primary`. "Use as avatar" makes the sprite the profile picture; the other save button keeps the photo. The edit page can switch between them, download or remove the sprite.
- Images: `/px/<id>-1x.png` (native size; displayed with `image-rendering: pixelated`), `/px/<id>.png` (≥512 px nearest-neighbor download) and `/px/<id>-og.png` (1200×630 share card, used as og:image when the sprite is the profile picture). Hidden dogs' sprites return 404.
- Where sprites show: dog cards (as the image, or a small badge), a Photo/Pixel toggle and a "pixel pal" panel on the dog page, and meetup attendee and pack member lists when the sprite is the profile picture.
- Showcase: a "Pixel Pals" section on the landing page (`pixelweb.landing_html()`, `{{PIXEL_PALS}}` in `index.html`, static before/after art in `public/img/pp-*`) and a public `/pixel-pals` page (how it works plus a gallery of every public dog with a sprite; og:image is a sprite share card; in the nav, mobile menu, footers and sitemap). "Make your pixel pal" goes to `/pixel-pals/start`: sign in first, then the dog's maker, a chooser if there are several dogs, or "Add a dog" if there are none.
- Nudge: right after a member adds a dog's first photos (`?m=created`/`?m=photos` on the edit page), a dog with photos but no sprite gets a big "Now make <name> a pixel pal!" card instead of the plain panel.
- `seed.py` sets Lily's sprite to `sprites/lily-cartoon-48.png` and Maggie's to `sprites/maggie-new-A-48.png` (Game Sprite from Mike's grey-bed photo `dogs/maggie-3.jpg`, made with the maker's cutout and the game preset at saturation 0.8 / contrast 1.4 so the merle reads; it replaces the earlier cream-rug `sprites/maggie-sprite-48.png`, and the comparison is `sprites/maggie-new-compare.png`). It only swaps a sprite while the dog still has one of the older seeded files (`pixel_replaces`), so an owner-made sprite is never overwritten, and a seeded file never replaces itself. `pixel_primary=True` makes the sprite the avatar only at the moment the seed adds or swaps it, so an owner who switches back to the photo stays switched.
