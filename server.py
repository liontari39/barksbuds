#!/usr/bin/env python3
"""BarksBuds landing page + waitlist server.

Storage:
  * DATABASE_URL set  -> PostgreSQL (via pg8000), used on Render.
  * otherwise         -> SQLite at $DATA_DIR/waitlist.db (default ./data), for local dev.
Admin (requires ADMIN_KEY env var; disabled when unset):
  GET  /admin/export.csv?key=KEY             download all signups as CSV
  POST /admin/delete?key=KEY&email=ADDRESS   remove one signup (e.g. a test row or an opt-out)
Dog run finder:
  GET  /runs       map + list page (public/runs.html, rendered with the run list for SEO)
  GET  /api/runs   dog run dataset from data-seed/dog_runs_region.json (cached, ETag, gzip)
Member accounts + dog profiles (accounts.py = data, webapp.py = pages):
  /signin, /auth, /signout          passwordless sign-in by emailed magic link
  /me, /me/profile, /me/dogs/...    owner dashboard, owner profile, dog create/edit/delete, photo uploads
  /dogs, /dogs/<slug>, /p/<id>.jpg  public browse page, dog pages, photos (stored in the database)
  /admin/reports?key=KEY            profile reports (admin)
Waitlist emails (see mailer.py; off until EMAIL_* env vars are set):
  GET  /api/config                    {"email_confirmations": true|false}
  GET  /unsubscribe?e=EMAIL&t=TOKEN   confirm page; POST removes the signup (also RFC 8058 one-click)
"""
import csv, gzip, hashlib, html, hmac, io, json, os, re, sqlite3, ssl, threading, time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs, unquote

import accounts
import mailer
import meetweb
import packweb
import pixelweb
import webapp

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(ROOT, "data")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))
SITE_URL = (os.environ.get("SITE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
COLUMNS = ["id", "first_name", "email", "dog_name", "zip", "created_at"]


class DuplicateEmail(Exception):
    pass


class SQLiteStore:
    kind = "sqlite"

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.path = os.path.join(DATA_DIR, "waitlist.db")
        self.csv_path = os.path.join(DATA_DIR, "waitlist.csv")
        self.lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS signups(
                id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE, dog_name TEXT NOT NULL,
                zip TEXT, created_at TEXT NOT NULL)""")
        self._mirror_csv()

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, first, email, dog, zp):
        with self.lock:
            try:
                with self._conn() as c:
                    c.execute("INSERT INTO signups(first_name,email,dog_name,zip,created_at) VALUES(?,?,?,?,?)",
                              (first, email, dog, zp, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            except sqlite3.IntegrityError:
                raise DuplicateEmail()
            self._mirror_csv()

    def rows(self):
        with self._conn() as c:
            return c.execute("SELECT id,first_name,email,dog_name,zip,created_at FROM signups ORDER BY id").fetchall()

    def delete(self, email):
        with self.lock:
            with self._conn() as c:
                n = c.execute("DELETE FROM signups WHERE email = ? COLLATE NOCASE", (email,)).rowcount
            self._mirror_csv()
            return n

    def ping(self):
        with self._conn() as c:
            c.execute("SELECT 1")

    def q(self, sql, **kw):
        """Run one statement with :named params; returns all rows (list of tuples)."""
        c = self._conn()
        try:
            rows = c.execute(sql, kw).fetchall()
            c.commit()
            return rows
        finally:
            c.close()

    def _mirror_csv(self):
        tmp = self.csv_path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(COLUMNS); w.writerows(self.rows())
        os.replace(tmp, self.csv_path)


class PostgresStore:
    kind = "postgres"

    def __init__(self, url):
        import pg8000.native  # noqa: F401  (imported lazily so local dev needs no deps)
        u = urlsplit(url)
        self.params = dict(user=unquote(u.username or ""), password=unquote(u.password or ""),
                           host=u.hostname, port=u.port or 5432, database=(u.path or "/").lstrip("/"),
                           timeout=15)
        q = parse_qs(u.query)
        sslmode = q.get("sslmode", ["prefer" if "." in (u.hostname or "") else "disable"])[0]
        if sslmode in ("require", "prefer", "verify-ca", "verify-full"):
            ctx = ssl.create_default_context()
            if sslmode in ("require", "prefer"):
                ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
            self.params["ssl_context"] = ctx
        self.local = threading.local()
        self._retry(lambda c: c.run("""CREATE TABLE IF NOT EXISTS signups(
            id BIGSERIAL PRIMARY KEY, first_name TEXT NOT NULL, email TEXT NOT NULL,
            dog_name TEXT NOT NULL, zip TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""))
        self._retry(lambda c: c.run("CREATE UNIQUE INDEX IF NOT EXISTS signups_email_lower_idx ON signups (lower(email))"))

    def _connect(self):
        import pg8000.native
        return pg8000.native.Connection(**self.params)

    def _retry(self, fn, attempts=3):
        """Run fn(conn) on this thread's connection, reconnecting on dropped connections."""
        import pg8000
        last = None
        for i in range(attempts):
            c = getattr(self.local, "conn", None)
            try:
                if c is None:
                    c = self.local.conn = self._connect()
                return fn(c)
            except pg8000.exceptions.DatabaseError:
                raise  # SQL-level error: don't retry
            except Exception as e:  # network / closed connection
                last = e
                try:
                    c and c.close()
                except Exception:
                    pass
                self.local.conn = None
                time.sleep(0.5 * (i + 1))
        raise last

    def add(self, first, email, dog, zp):
        import pg8000
        try:
            self._retry(lambda c: c.run(
                "INSERT INTO signups(first_name,email,dog_name,zip) VALUES(:f,:e,:d,:z)",
                f=first, e=email, d=dog, z=zp))
        except pg8000.exceptions.DatabaseError as e:
            if "23505" in str(e):  # unique_violation
                raise DuplicateEmail()
            raise

    def rows(self):
        rs = self._retry(lambda c: c.run("SELECT id,first_name,email,dog_name,zip,created_at FROM signups ORDER BY id"))
        return [(r[0], r[1], r[2], r[3], r[4], r[5].astimezone(timezone.utc).isoformat(timespec="seconds")) for r in rs]

    def delete(self, email):
        rs = self._retry(lambda c: c.run("DELETE FROM signups WHERE lower(email)=lower(:e) RETURNING id", e=email))
        return len(rs)

    def ping(self):
        self._retry(lambda c: c.run("SELECT 1"))

    def q(self, sql, **kw):
        """Run one statement with :named params; returns all rows (list of tuples)."""
        return [tuple(r) for r in (self._retry(lambda c: c.run(sql, **kw)) or [])]


STORE = None
INDEX_CACHE = {}
RUNS_PATH = os.path.join(ROOT, "data-seed", "dog_runs_region.json")
RUNS_CACHE = {}
GZ_CACHE = {}
GZ_LOCK = threading.Lock()
GZ_TYPES = (".js", ".mjs", ".css", ".json", ".webmanifest", ".txt", ".xml", ".wasm")


def load_runs():
    """Dog run dataset, read once and kept in memory with precomputed JSON, gzip and ETag."""
    if "data" not in RUNS_CACHE:
        with open(RUNS_PATH, encoding="utf-8") as f:
            runs = json.load(f)
        body = json.dumps({"count": len(runs), "updated": max((r.get("last_checked") or "") for r in runs),
                           "note": "pin_precision says how each map pin was placed: exact (mapped run), described (official location description), park-wide (whole park is off-leash) or approximate (still being verified). Blank fields are not yet confirmed.",
                           "runs": runs}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        RUNS_CACHE.update(data=runs, body=body, gz=gzip.compress(body, 9),
                          etag='"%s"' % hashlib.sha256(body).hexdigest()[:20])
    return RUNS_CACHE


def render_runs(host_url):
    """runs.html with absolute URLs plus a server-rendered run list and JSON-LD (works without JS, good for SEO)."""
    base = SITE_URL or host_url
    key = "runs:" + base
    if key not in INDEX_CACHE:
        runs = load_runs()["data"]
        main = [r for r in runs if not (r.get("type") or "").lower().startswith("off-leash area")]
        items = []
        for r in main:
            where = " · ".join(x for x in (r.get("town_or_neighborhood"), r.get("county")) if x)
            items.append('<li class="card"><div class="card-h"><span class="badge" aria-hidden="true">'
                         '<svg class="ico"><use href="#i-pin"/></svg></span><div><h2>%s</h2><p class="where">%s</p>'
                         '</div></div></li>' % (html.escape(r["name"]), html.escape(where)))
        places = []
        for r in main:
            pl = {"@type": "Place", "name": r["name"],
                  "address": {"@type": "PostalAddress", "addressLocality": r.get("town_or_neighborhood") or "",
                              "addressRegion": "NY", "addressCountry": "US"}}
            if r.get("address"):
                pl["address"]["streetAddress"] = r["address"]
            if isinstance(r.get("lat"), (int, float)):
                pl["geo"] = {"@type": "GeoCoordinates", "latitude": r["lat"], "longitude": r["lng"]}
            places.append({"@type": "ListItem", "position": len(places) + 1, "item": pl})
        ld = {"@context": "https://schema.org", "@type": "WebPage", "name": "Dog runs in NYC, Long Island and Westchester",
              "url": base + "/runs", "isPartOf": {"@type": "WebSite", "name": "BarksBuds", "url": base + "/"},
              "mainEntity": {"@type": "ItemList", "numberOfItems": len(places), "itemListElement": places}}
        ld_s = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")
        with open(os.path.join(PUBLIC, "runs.html"), encoding="utf-8") as f:
            page = f.read()
        page = (page.replace("{{SITE_URL}}", base).replace("{{RUN_COUNT}}", str(len(main)))
                .replace("{{RUN_LIST}}", "".join(items)).replace("{{JSON_LD}}", ld_s))
        body = page.encode("utf-8")
        INDEX_CACHE[key] = (body, gzip.compress(body, 9))
    return INDEX_CACHE[key]


def render_index(host_url):
    """index.html with absolute URLs for Open Graph/canonical tags."""
    base = SITE_URL or host_url
    if base not in INDEX_CACHE:
        with open(os.path.join(PUBLIC, "index.html"), encoding="utf-8") as f:
            page = f.read().replace("{{SITE_URL}}", base)
            n = sum(1 for r in load_runs()["data"] if not (r.get("type") or "").lower().startswith("off-leash area"))
            INDEX_CACHE[base] = page.replace("{{RUN_COUNT}}", str(n)).encode()
    return INDEX_CACHE[base]


class H(webapp.AppRoutes, meetweb.MeetupRoutes, packweb.PackRoutes, pixelweb.PixelRoutes, SimpleHTTPRequestHandler):
    server_version = "BarksBuds"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".webp": "image/webp",
                      ".webmanifest": "application/manifest+json", ".ico": "image/x-icon",
                      ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8",
                      ".mjs": "text/javascript", ".wasm": "application/wasm", ".tflite": "application/octet-stream"}
    sys_version = ""

    def __init__(self, *a, **k):
        super().__init__(*a, directory=PUBLIC, **k)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        p = urlsplit(self.path).path
        if p.startswith("/vendor/mediapipe/"):  # pinned third-party build; large, so cache it for a week
            self.send_header("Cache-Control", "public, max-age=604800")
        elif p.startswith(("/img/", "/vendor/")) or p == "/favicon.ico":
            self.send_header("Cache-Control", "public, max-age=86400")
        elif p in ("/runs.js", "/app.css", "/pixelpal.js", "/pixelmaker.js"):
            self.send_header("Cache-Control", "public, max-age=300")
        super().end_headers()

    def _gzip_ok(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _send_maybe_gz(self, body, gz, ctype, extra=None):
        extra = dict(extra or {}); extra["Vary"] = "Accept-Encoding"
        if self._gzip_ok():
            extra["Content-Encoding"] = "gzip"; body = gz
        return self._send(200, body, ctype, extra)

    def _static_gz(self, path):
        """Serve text assets (Leaflet, runs.js, css) gzipped when the browser allows; False to fall back."""
        if not path.endswith(GZ_TYPES) or not self._gzip_ok() or ".." in path:
            return False
        root = os.path.realpath(PUBLIC)
        fp = os.path.realpath(os.path.join(root, unquote(path).lstrip("/")))
        if not fp.startswith(root + os.sep) or not os.path.isfile(fp):
            return False
        mt = os.path.getmtime(fp)
        hit = GZ_CACHE.get(fp)
        if not hit or hit[0] != mt:
            with GZ_LOCK:  # one compression at a time (the 13 MB wasm takes ~0.5 s once, then stays cached)
                hit = GZ_CACHE.get(fp)
                if not hit or hit[0] != mt:
                    with open(fp, "rb") as f:
                        raw = f.read()
                    hit = (mt, gzip.compress(raw, 9 if len(raw) < 1_000_000 else 6)); GZ_CACHE[fp] = hit
        ctype = self.guess_type(fp)
        if ctype.startswith(("text/", "application/javascript")) and "charset" not in ctype:
            ctype += "; charset=utf-8"
        self._send(200, hit[1], ctype, {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        return True

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def _admin_ok(self, q):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        return bool(ADMIN_KEY) and hmac.compare_digest(key.encode(), ADMIN_KEY.encode())

    def _host_url(self):
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",")[0].strip()
        return f"{proto}://{self.headers.get('Host', 'localhost')}"

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        meetweb.tick(SITE_URL or self._host_url())
        if u.path == "/healthz":
            try:
                STORE.ping(); return self._json(200, {"ok": True, "store": STORE.kind})
            except Exception:
                return self._json(503, {"ok": False})
        if u.path in ("/", "/index.html"):
            self._app_reset()
            body = (render_index(self._host_url()).replace(b"{{NAV_ACCOUNT}}", webapp.nav_account_html(self.user(), "home").encode())
                    .replace(b"{{NORTH_SHORE}}", meetweb.landing_html().encode()))
            return self._send(200, body, "text/html; charset=utf-8", {"Cache-Control": "no-cache", "Vary": "Cookie"})
        if u.path in ("/runs", "/runs/", "/runs.html"):
            self._app_reset()
            body, _gz = render_runs(self._host_url())
            body = body.replace(b"{{NAV_ACCOUNT}}", webapp.nav_account_html(self.user(), "runs").encode())
            return self._send_maybe_gz(body, gzip.compress(body, 6), "text/html; charset=utf-8",
                                       {"Cache-Control": "no-cache", "Vary": "Accept-Encoding, Cookie"})
        if u.path == "/sitemap.xml":
            base = SITE_URL or self._host_url()
            lm = max((r.get("last_checked") or "") for r in load_runs()["data"]) or "2026-10-24"
            xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   f'<url><loc>{base}/</loc><lastmod>{lm}</lastmod></url>'
                   f'<url><loc>{base}/runs</loc><lastmod>{lm}</lastmod><changefreq>weekly</changefreq></url>'
                   f'<url><loc>{base}/meetups</loc><changefreq>daily</changefreq></url>'
                   + "".join(f'<url><loc>{base}{meetweb.meetup_path(m)}</loc></url>' for m in meetweb.M.upcoming(limit=500) if not m["is_sample"])
                   + f'<url><loc>{base}/packs</loc><changefreq>daily</changefreq></url>'
                   + "".join(f'<url><loc>{base}{packweb.pack_path(p)}</loc></url>' for p in packweb.P.browse() if not p["is_sample"])
                   + f'<url><loc>{base}/dogs</loc><changefreq>daily</changefreq></url>'
                   + "".join(f'<url><loc>{base}/dogs/{d["slug"]}</loc></url>' for d in accounts.browse_dogs(limit=5000))
                   + '</urlset>\n')
            return self._send(200, xml.encode(), "application/xml; charset=utf-8", {"Cache-Control": "public, max-age=600"})
        if u.path == "/api/config":
            return self._json(200, {"email_confirmations": mailer.enabled()})
        if u.path == "/unsubscribe":
            return self._unsub_page(q.get("e", [""])[0].strip().lower(), q.get("t", [""])[0].strip(), confirm=False)
        if u.path == "/api/runs":
            c = load_runs()
            hdr = {"Cache-Control": "public, max-age=3600", "ETag": c["etag"], "Access-Control-Allow-Origin": "*"}
            if c["etag"] in (self.headers.get("If-None-Match") or ""):
                self.send_response(304)
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.end_headers()
                return
            return self._send_maybe_gz(c["body"], c["gz"], "application/json; charset=utf-8", hdr)
        if self.pixel_get(u.path, q) or self.app_get(u.path, q) or self.meetup_get(u.path, q) or self.pack_get(u.path, q):
            return
        if u.path == "/admin/export.csv":
            if not self._admin_ok(q):
                return self.send_error(404)
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(COLUMNS); w.writerows(STORE.rows())
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            return self._send(200, buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="barksbuds-waitlist-{stamp}.csv"',
                               "Cache-Control": "no-store"})
        if u.path.startswith(("/data", "/admin")) or ".." in u.path:
            return self.send_error(404)
        if self._static_gz(u.path):
            return
        return super().do_GET()

    def do_POST(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if self.pixel_post(u.path, q) or self.app_post(u.path, q) or self.meetup_post(u.path, q) or self.pack_post(u.path, q):
            return
        if u.path == "/admin/delete":
            if not self._admin_ok(q):
                return self.send_error(404)
            email = q.get("email", [""])[0].strip().lower()
            if not email:
                return self._json(400, {"ok": False, "error": "email required"})
            return self._json(200, {"ok": True, "deleted": STORE.delete(email)})
        if u.path == "/unsubscribe":
            n = min(int(self.headers.get("Content-Length", 0) or 0), 2000)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            email = (form.get("e") or q.get("e", [""])[0]).strip().lower()
            token = (form.get("t") or q.get("t", [""])[0]).strip()
            one_click = form.get("List-Unsubscribe") == "One-Click"
            return self._unsub_page(email, token, confirm=True, one_click=one_click)
        if u.path != "/api/waitlist":
            return self.send_error(404)
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 10000)
            raw = self.rfile.read(n).decode("utf-8", "replace")
            if "json" in (self.headers.get("Content-Type") or ""):
                d = json.loads(raw or "{}")
                if not isinstance(d, dict):
                    raise ValueError
            else:
                d = {k: v[0] for k, v in parse_qs(raw).items()}
        except Exception:
            return self._json(400, {"ok": False, "error": "Couldn't read that form. Please try again."})
        if d.get("website"):  # honeypot field: bots fill it, people never see it
            return self._json(200, {"ok": True, "message": "Thanks!"})
        first = str(d.get("first_name", "")).strip()[:60]
        email = str(d.get("email", "")).strip().lower()[:254]
        dog = str(d.get("dog_name", "")).strip()[:60]
        zp = str(d.get("zip", "")).strip()[:10]
        errs = {}
        if not first: errs["first_name"] = "Please tell us your first name."
        if not EMAIL_RE.match(email): errs["email"] = "That email doesn't look quite right."
        if not dog: errs["dog_name"] = "What's your pup's name?"
        if zp and not ZIP_RE.match(zp): errs["zip"] = "Zip should be 5 digits (or leave it blank)."
        if errs:
            return self._json(422, {"ok": False, "errors": errs})
        try:
            STORE.add(first, email, dog, zp or None)
        except DuplicateEmail:
            return self._json(200, {"ok": True, "duplicate": True,
                                    "message": f"Good news, {first}: you're already on the list! We'll be in touch."})
        except Exception as e:
            print("signup error:", type(e).__name__, e, flush=True)
            return self._json(503, {"ok": False, "error": "Our servers are napping. Please try again in a moment."})
        print("new signup stored", flush=True)
        queued = mailer.send_welcome_async(SITE_URL or self._host_url(), first, dog, email)
        if queued:
            msg = (f"Woof! Thanks {first}, you and {dog} are on the BarksBuds waitlist. "
                   f"We're sending a welcome email to {email} (check your Promotions or spam folder if you don't see it).")
        else:
            msg = (f"Woof! Thanks {first}, you and {dog} are on the BarksBuds waitlist. "
                   "While you wait, explore the dog run map to find runs near you.")
        return self._json(201, {"ok": True, "email_sent": queued, "message": msg})

    def _unsub_page(self, email, token, confirm, one_click=False):
        """Tokenized remove-me flow. GET shows a button (so link scanners can't unsubscribe people); POST removes."""
        valid = bool(email) and mailer.check_token(email, token)
        if one_click:
            if valid:
                STORE.delete(email); print("unsubscribe: one-click removal", flush=True)
            return self._json(200 if valid else 400, {"ok": valid})
        e = html.escape
        if not valid:
            title, body = "That link didn't work", ("<p>This remove-me link is incomplete or has expired. "
                                                     "Reply to any BarksBuds email and we'll remove you by hand.</p>")
            code = 400
        elif confirm:
            STORE.delete(email); print("unsubscribe: removed via link", flush=True)
            title, body, code = "You're off the list", (f"<p><strong>{e(email)}</strong> has been removed from the BarksBuds "
                                                         "waitlist and we've deleted your details. Sorry to see you go!</p>"
                                                         '<p><a href="/">Back to BarksBuds</a> &middot; <a href="/runs">Dog run map</a></p>'), 200
        else:
            title, code = "Leave the waitlist?", 200
            body = (f"<p>This removes <strong>{e(email)}</strong> from the BarksBuds waitlist and deletes your details.</p>"
                    f'<form method="post" action="/unsubscribe"><input type="hidden" name="e" value="{e(email)}">'
                    f'<input type="hidden" name="t" value="{e(token)}"><button type="submit">Remove me</button></form>'
                    '<p class="small"><a href="/">Never mind, keep me on the list</a></p>')
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{e(title)} | BarksBuds</title><link rel="icon" href="/favicon.ico">
<style>body{{margin:0;background:#FFF8EA;font:400 17px/1.6 Nunito,system-ui,sans-serif;color:#2a2622;display:grid;place-items:center;min-height:100vh;padding:20px;box-sizing:border-box}}
main{{max-width:460px;background:#fff;border:1px solid #EADBB9;border-radius:24px;padding:32px;text-align:center}}
img{{border-radius:18px;border:3px solid #FBB321}}h1{{font:800 28px/1.15 system-ui,sans-serif;color:#141414;margin:14px 0 10px}}
a{{color:#C8201E}}button{{font:700 17px system-ui,sans-serif;background:#C8201E;color:#fff;border:0;border-radius:999px;padding:13px 26px;cursor:pointer;box-shadow:0 4px 0 #9E1714}}
.small{{font-size:15px}}</style></head><body><main><img src="/img/icon-96.webp" width="72" height="72" alt="BarksBuds">
<h1>{e(title)}</h1>{body}</main></body></html>"""
        return self._send(code, page.encode(), "text/html; charset=utf-8", {"Cache-Control": "no-store"})

    def log_message(self, fmt, *a):
        if a and ("/admin/" in str(a[0]) or "/auth?" in str(a[0])):
            a = (str(a[0]).split("?")[0] + " [query redacted]",) + a[1:]
        print("%s - %s" % (self.client_address[0], fmt % a), flush=True)


def make_store():
    if DATABASE_URL:
        for i in range(10):  # the database can take a moment to accept connections on boot
            try:
                return PostgresStore(DATABASE_URL)
            except Exception as e:
                print(f"postgres not ready ({type(e).__name__}); retrying...", flush=True)
                time.sleep(3)
        raise SystemExit("could not connect to DATABASE_URL")
    return SQLiteStore()


def init_app():
    global STORE
    STORE = make_store()
    accounts.init_schema(STORE)
    webapp.RUNS = lambda: load_runs()["data"]
    webapp.SITE_URL, webapp.ADMIN_KEY = SITE_URL, ADMIN_KEY
    return STORE


if __name__ == "__main__":
    init_app()
    print(f"BarksBuds running on 0.0.0.0:{PORT} (store: {STORE.kind}, admin: {'on' if ADMIN_KEY else 'off'}, email: {mailer.status()})", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    srv.serve_forever()
