#!/usr/bin/env python3
"""BarksBuds landing page + waitlist server.

Storage:
  * DATABASE_URL set  -> PostgreSQL (via pg8000), used on Render.
  * otherwise         -> SQLite at $DATA_DIR/waitlist.db (default ./data), for local dev.
Admin (requires ADMIN_KEY env var; disabled when unset):
  GET  /admin/export.csv?key=KEY             download all signups as CSV
  POST /admin/delete?key=KEY&email=ADDRESS   remove one signup (e.g. a test row or an opt-out)
"""
import csv, hmac, io, json, os, re, sqlite3, ssl, threading, time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs, unquote

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


STORE = None
INDEX_CACHE = {}


def render_index(host_url):
    """index.html with absolute URLs for Open Graph/canonical tags."""
    base = SITE_URL or host_url
    if base not in INDEX_CACHE:
        with open(os.path.join(PUBLIC, "index.html"), encoding="utf-8") as f:
            INDEX_CACHE[base] = f.read().replace("{{SITE_URL}}", base).encode()
    return INDEX_CACHE[base]


class H(SimpleHTTPRequestHandler):
    server_version = "BarksBuds"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".webp": "image/webp",
                      ".webmanifest": "application/manifest+json", ".ico": "image/x-icon",
                      ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}
    sys_version = ""

    def __init__(self, *a, **k):
        super().__init__(*a, directory=PUBLIC, **k)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        p = urlsplit(self.path).path
        if p.startswith("/img/") or p == "/favicon.ico":
            self.send_header("Cache-Control", "public, max-age=86400")
        super().end_headers()

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
        if u.path == "/healthz":
            try:
                STORE.ping(); return self._json(200, {"ok": True, "store": STORE.kind})
            except Exception:
                return self._json(503, {"ok": False})
        if u.path in ("/", "/index.html"):
            return self._send(200, render_index(self._host_url()), "text/html; charset=utf-8",
                              {"Cache-Control": "no-cache"})
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
        return super().do_GET()

    def do_POST(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if u.path == "/admin/delete":
            if not self._admin_ok(q):
                return self.send_error(404)
            email = q.get("email", [""])[0].strip().lower()
            if not email:
                return self._json(400, {"ok": False, "error": "email required"})
            return self._json(200, {"ok": True, "deleted": STORE.delete(email)})
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
        return self._json(201, {"ok": True,
                                "message": f"Woof! Thanks {first}, you and {dog} are on the BarksBuds waitlist. We'll email you when we open the gates."})

    def log_message(self, fmt, *a):
        if a and "/admin/" in str(a[0]):
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


if __name__ == "__main__":
    STORE = make_store()
    print(f"BarksBuds running on 0.0.0.0:{PORT} (store: {STORE.kind}, admin: {'on' if ADMIN_KEY else 'off'})", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    srv.serve_forever()
