"""BarksBuds member accounts and dog profiles: data layer.

Works on both stores from server.py (SQLite locally, PostgreSQL on Render) through STORE.q(sql, **params),
which takes :named parameters on both. Timestamps are integer Unix seconds so the SQL is portable.

Security notes
  * Magic-link sign-in tokens and session tokens are random (secrets.token_urlsafe) and only their SHA-256
    hashes are stored. Links are single-use and expire after LINK_TTL seconds.
  * Photos are re-encoded server-side (EXIF and GPS stripped, orientation applied, resized) and stored as
    bytea because Render's free disk is ephemeral.
"""
import hashlib, hmac, io, json, os, re, secrets, threading, time, unicodedata
from collections import deque
from datetime import date
from urllib.parse import urlsplit

LINK_TTL = 20 * 60                 # magic link lifetime
SESSION_TTL = 30 * 24 * 3600       # session cookie lifetime
MAX_DOGS = 6                       # dogs per owner
MAX_PHOTOS = 8                     # gallery photos per dog
MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # per original file
MAX_FAV_RUNS = 5
FULL_PX, THUMB_PX = 1600, 640

AREAS = [("Manhattan", "New York City"), ("Brooklyn", "New York City"), ("Queens", "New York City"),
         ("Bronx", "New York City"), ("Staten Island", "New York City"),
         ("Nassau", "Long Island"), ("Suffolk", "Long Island"), ("Westchester", "Westchester")]
AREA_NAMES = [a for a, _ in AREAS]
AREA_LABEL = {"Nassau": "Nassau County", "Suffolk": "Suffolk County", "Bronx": "The Bronx"}
REGIONS = {"nyc": ("New York City", ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]),
           "li": ("Long Island", ["Nassau", "Suffolk"]), "wc": ("Westchester", ["Westchester"])}
TEMPERAMENT = ["Friendly with big dogs", "Friendly with small dogs", "Loves people", "Great with kids",
               "Shy at first", "Gentle", "Chill", "High energy", "Puppy energy", "Ball obsessed",
               "Loves water", "Loves a good sniff", "Vocal", "Prefers a small group", "Still learning manners",
               "Smart", "Loyal", "Speedy", "Snuggler", "Food motivated"]
PLAY_STYLES = ["Chaser", "Wrestler", "Fetcher", "Tug-of-war fan", "Explorer and sniffer",
               "Social butterfly", "Gentle player", "Watcher (likes to observe)", "Zoomies", "Toy lover"]
SIZES = [("small", "Small (under 20 lb)"), ("medium", "Medium (20–50 lb)"),
         ("large", "Large (50–90 lb)"), ("giant", "Giant (90+ lb)")]
SEXES = [("female", "Girl"), ("male", "Boy")]
RESERVED_SLUGS = {"new", "edit", "me", "admin", "api", "browse", "search", "all", "report", "photos"}

_secret = os.environ.get("APP_SECRET", "") or os.environ.get("ADMIN_KEY", "")
SECRET = (hmac.new(_secret.encode(), b"barksbuds-app-v1", hashlib.sha256).digest() if _secret
          else secrets.token_bytes(32))

STORE = None  # set by server.py


def now():
    return int(time.time())


def sha(s):
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def ip_hash(ip):
    return hmac.new(SECRET, (ip or "").encode(), hashlib.sha256).hexdigest()[:24]


def q(sql, **kw):
    return STORE.q(sql, **kw)


def one(sql, **kw):
    rs = STORE.q(sql, **kw)
    return rs[0] if rs else None


# ---------------------------------------------------------------- schema
def init_schema(store):
    global STORE
    STORE = store
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    BLOB = "BYTEA" if pg else "BLOB"
    INT = "BIGINT" if pg else "INTEGER"
    ddl = [
        f"""CREATE TABLE IF NOT EXISTS users(id {ID}, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '',
            area TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
            waitlist_id {INT}, created_at {INT} NOT NULL, last_login_at {INT})""",
        f"""CREATE TABLE IF NOT EXISTS login_tokens(id {ID}, token_hash TEXT NOT NULL UNIQUE, email TEXT NOT NULL,
            ip_hash TEXT NOT NULL DEFAULT '', created_at {INT} NOT NULL, expires_at {INT} NOT NULL, used_at {INT})""",
        "CREATE INDEX IF NOT EXISTS login_tokens_email_idx ON login_tokens(email, created_at)",
        "CREATE INDEX IF NOT EXISTS login_tokens_ip_idx ON login_tokens(ip_hash, created_at)",
        f"""CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id {INT} NOT NULL,
            created_at {INT} NOT NULL, expires_at {INT} NOT NULL, last_seen {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id)",
        f"""CREATE TABLE IF NOT EXISTS dogs(id {ID}, user_id {INT} NOT NULL, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            breed TEXT NOT NULL DEFAULT '', birthday TEXT NOT NULL DEFAULT '', birth_year {INT}, sex TEXT NOT NULL DEFAULT '',
            size TEXT NOT NULL DEFAULT '', temperament TEXT NOT NULL DEFAULT '[]', play_style TEXT NOT NULL DEFAULT '[]',
            vaccinated {INT} NOT NULL DEFAULT 0, fav_runs TEXT NOT NULL DEFAULT '[]', bio TEXT NOT NULL DEFAULT '',
            avatar_photo_id {INT}, hidden {INT} NOT NULL DEFAULT 0, seed_key TEXT UNIQUE,
            created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS dogs_user_idx ON dogs(user_id)",
        f"""CREATE TABLE IF NOT EXISTS photos(id {ID}, dog_id {INT} NOT NULL, kind TEXT NOT NULL DEFAULT 'gallery',
            position {INT} NOT NULL DEFAULT 0, width {INT} NOT NULL, height {INT} NOT NULL,
            full_jpeg {BLOB} NOT NULL, thumb_webp {BLOB} NOT NULL, bytes {INT} NOT NULL, sha TEXT NOT NULL DEFAULT '',
            created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS photos_dog_idx ON photos(dog_id, kind, position)",
        f"""CREATE TABLE IF NOT EXISTS reports(id {ID}, dog_id {INT} NOT NULL, reporter_user_id {INT}, reason TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '', ip_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
            created_at {INT} NOT NULL)""",
    ]
    for s in ddl:
        store.q(s)
    # additive migrations (safe to re-run)
    cols = ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name='dogs'")} if pg
            else {r[1] for r in store.q("PRAGMA table_info(dogs)")})
    if "website" not in cols:
        store.q("ALTER TABLE dogs ADD COLUMN website TEXT NOT NULL DEFAULT ''")
    if "seed_rev" not in cols:
        store.q(f"ALTER TABLE dogs ADD COLUMN seed_rev {INT} NOT NULL DEFAULT 0")
    import meetups
    meetups.init_schema(store)


# ---------------------------------------------------------------- rate limiting (in-memory, per process)
class Limiter:
    def __init__(self):
        self.hits, self.lock = {}, threading.Lock()

    def allow(self, key, limit, window):
        t = time.time()
        with self.lock:
            d = self.hits.setdefault(key, deque())
            while d and d[0] <= t - window:
                d.popleft()
            if len(d) >= limit:
                return False
            d.append(t)
            if len(self.hits) > 20000:  # keep memory bounded
                self.hits = {k: v for k, v in self.hits.items() if v and v[-1] > t - 3600}
            return True


LIMITER = Limiter()


# ---------------------------------------------------------------- magic links + sessions
class RateLimited(Exception):
    pass


def create_login_token(email, ip):
    """Return a raw token for a new single-use sign-in link, or raise RateLimited."""
    t, ih = now(), ip_hash(ip)
    by_email = one("SELECT COUNT(*) FROM login_tokens WHERE email=:e AND created_at>:t", e=email, t=t - 3600)[0]
    recent = one("SELECT COUNT(*) FROM login_tokens WHERE email=:e AND created_at>:t", e=email, t=t - 45)[0]
    by_ip = one("SELECT COUNT(*) FROM login_tokens WHERE ip_hash=:i AND created_at>:t", i=ih, t=t - 3600)[0]
    if by_email >= 5 or recent >= 1 or by_ip >= 20:
        raise RateLimited()
    raw = secrets.token_urlsafe(32)
    q("INSERT INTO login_tokens(token_hash,email,ip_hash,created_at,expires_at) VALUES(:h,:e,:i,:c,:x)",
      h=sha(raw), e=email, i=ih, c=t, x=t + LINK_TTL)
    if secrets.randbelow(20) == 0:  # opportunistic cleanup
        q("DELETE FROM login_tokens WHERE created_at<:t", t=t - 7 * 86400)
        q("DELETE FROM sessions WHERE expires_at<:t", t=t)
    return raw


def peek_login_token(raw):
    """'ok' | 'used' | 'expired' | 'invalid' without consuming."""
    if not raw or len(raw) > 100:
        return "invalid"
    r = one("SELECT expires_at, used_at FROM login_tokens WHERE token_hash=:h", h=sha(raw))
    if not r:
        return "invalid"
    if r[1] is not None:
        return "used"
    return "ok" if r[0] > now() else "expired"


def consume_login_token(raw):
    """Atomically mark the token used. Returns the email or None."""
    if not raw or len(raw) > 100:
        return None
    t = now()
    r = one("UPDATE login_tokens SET used_at=:t WHERE token_hash=:h AND used_at IS NULL AND expires_at>:t RETURNING email",
            t=t, h=sha(raw))
    return r[0] if r else None


def get_or_create_user(email):
    """Find or create the account; new accounts are linked to (and prefilled from) a waitlist signup."""
    u = one("SELECT id FROM users WHERE email=:e", e=email)
    if u:
        q("UPDATE users SET last_login_at=:t WHERE id=:i", t=now(), i=u[0])
        return u[0], False
    wl = one("SELECT id, first_name FROM signups WHERE lower(email)=:e", e=email)
    try:
        r = one("INSERT INTO users(email,display_name,waitlist_id,created_at,last_login_at) VALUES(:e,:n,:w,:t,:t) RETURNING id",
                e=email, n=(wl[1][:40] if wl else ""), w=(wl[0] if wl else None), t=now())
        return r[0], True
    except Exception:  # lost a race with a parallel sign-in
        u = one("SELECT id FROM users WHERE email=:e", e=email)
        if u:
            return u[0], False
        raise


def create_session(user_id):
    raw, t = secrets.token_urlsafe(32), now()
    q("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen) VALUES(:h,:u,:t,:x,:t)",
      h=sha(raw), u=user_id, t=t, x=t + SESSION_TTL)
    return raw


def session_user(raw):
    if not raw or len(raw) > 100:
        return None
    t = now()
    r = one("""SELECT u.id,u.email,u.display_name,u.area,u.town,u.bio,u.waitlist_id,s.last_seen FROM sessions s
               JOIN users u ON u.id=s.user_id WHERE s.token_hash=:h AND s.expires_at>:t""", h=sha(raw), t=t)
    if not r:
        return None
    if t - r[7] > 3600:
        q("UPDATE sessions SET last_seen=:t WHERE token_hash=:h", t=t, h=sha(raw))
    return dict(id=r[0], email=r[1], display_name=r[2], area=r[3], town=r[4], bio=r[5], waitlist_id=r[6])


def end_session(raw):
    if raw:
        q("DELETE FROM sessions WHERE token_hash=:h", h=sha(raw))


def update_profile(user_id, display_name, area, town, bio):
    q("UPDATE users SET display_name=:n, area=:a, town=:t, bio=:b WHERE id=:i",
      n=display_name, a=area, t=town, b=bio, i=user_id)


def waitlist_dog_name(waitlist_id):
    if not waitlist_id:
        return ""
    r = one("SELECT dog_name FROM signups WHERE id=:i", i=waitlist_id)
    return r[0] if r else ""


def delete_user(user_id):
    import meetups
    meetups.purge_user(user_id)
    for (dog_id,) in q("SELECT id FROM dogs WHERE user_id=:u", u=user_id):
        delete_dog(dog_id)
    q("DELETE FROM sessions WHERE user_id=:u", u=user_id)
    q("DELETE FROM users WHERE id=:u", u=user_id)


# ---------------------------------------------------------------- dogs
DOG_COLS = ("id,user_id,slug,name,breed,birthday,birth_year,sex,size,temperament,play_style,vaccinated,"
            "fav_runs,bio,avatar_photo_id,hidden,created_at,updated_at,website,seed_rev")


def _dog(r):
    if not r:
        return None
    d = dict(zip(DOG_COLS.split(","), r))
    for k in ("temperament", "play_style", "fav_runs"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except ValueError:
            d[k] = []
    return d


def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")
    return s or "pup"


def unique_slug(name):
    base = slugify(name)
    if base in RESERVED_SLUGS:
        base += "-pup"
    taken = {r[0] for r in q("SELECT slug FROM dogs WHERE slug=:b OR slug LIKE :p", b=base, p=base + "-%")}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def dog_by_slug(slug):
    return _dog(one(f"SELECT {DOG_COLS} FROM dogs WHERE slug=:s", s=slug))


def dog_by_id(dog_id):
    return _dog(one(f"SELECT {DOG_COLS} FROM dogs WHERE id=:i", i=dog_id))


def dogs_for_user(user_id):
    return [_dog(r) for r in q(f"SELECT {DOG_COLS} FROM dogs WHERE user_id=:u ORDER BY created_at, id", u=user_id)]


def browse_dogs(areas=None, limit=60):
    rows = q(f"""SELECT {', '.join('d.' + c for c in DOG_COLS.split(','))}, u.display_name, u.area, u.town
                 FROM dogs d JOIN users u ON u.id=d.user_id WHERE d.hidden=0 ORDER BY d.created_at DESC, d.id DESC""")
    out = []
    for r in rows:
        d = _dog(r[:len(DOG_COLS.split(","))])
        d["owner_name"], d["area"], d["town"] = r[-3], r[-2], r[-1]
        if areas and d["area"] not in areas:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def owner_public(user_id):
    r = one("SELECT display_name, area, town FROM users WHERE id=:i", i=user_id)
    return dict(display_name=r[0], area=r[1], town=r[2]) if r else dict(display_name="", area="", town="")


def save_dog(user_id, f, dog_id=None, seed_key=None):
    """Insert or update from a validated field dict. Returns the dog id."""
    t = now()
    vals = dict(n=f["name"], b=f["breed"], bd=f["birthday"], by=f["birth_year"], sx=f["sex"], sz=f["size"],
                tm=json.dumps(f["temperament"]), ps=json.dumps(f["play_style"]), v=1 if f["vaccinated"] else 0,
                fr=json.dumps(f["fav_runs"]), bio=f["bio"], w=f.get("website", ""), t=t)
    if dog_id:
        q("""UPDATE dogs SET name=:n,breed=:b,birthday=:bd,birth_year=:by,sex=:sx,size=:sz,temperament=:tm,play_style=:ps,
             vaccinated=:v,fav_runs=:fr,bio=:bio,website=:w,updated_at=:t WHERE id=:i AND user_id=:u""", i=dog_id, u=user_id, **vals)
        return dog_id
    for attempt in range(3):
        try:
            r = one("""INSERT INTO dogs(user_id,slug,name,breed,birthday,birth_year,sex,size,temperament,play_style,vaccinated,
                       fav_runs,bio,website,seed_key,created_at,updated_at) VALUES(:u,:s,:n,:b,:bd,:by,:sx,:sz,:tm,:ps,:v,:fr,:bio,:w,:sk,:t,:t)
                       RETURNING id""", u=user_id, s=unique_slug(f["name"]), sk=seed_key, **vals)
            return r[0]
        except Exception:
            if attempt == 2:
                raise


def delete_dog(dog_id):
    q("DELETE FROM photos WHERE dog_id=:d", d=dog_id)
    q("DELETE FROM reports WHERE dog_id=:d", d=dog_id)
    q("DELETE FROM dogs WHERE id=:d", d=dog_id)


def age_text(d, today=None):
    today = today or date.today()
    if d.get("birthday"):
        try:
            y, m, dd = map(int, d["birthday"].split("-"))
            months = (today.year - y) * 12 + today.month - m - (1 if today.day < dd else 0)
        except ValueError:
            months = None
        if months is not None and months >= 0:
            if months < 12:
                return "%d month%s old" % (max(months, 1), "" if months == 1 else "s")
            return "%d year%s old" % (months // 12, "" if months // 12 == 1 else "s")
    if d.get("birth_year"):
        yrs = today.year - int(d["birth_year"])
        if yrs <= 0:
            return "Under a year old"
        return "%d year%s old" % (yrs, "" if yrs == 1 else "s")
    return ""


def age_years_value(d, today=None):
    """For the edit form: the age field when no exact birthday was given."""
    if d.get("birthday") or not d.get("birth_year"):
        return ""
    return str(max((today or date.today()).year - int(d["birth_year"]), 0))


# ---------------------------------------------------------------- photos
class BadImage(Exception):
    pass


ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}


def sniff(raw):
    h = raw[:16]
    return (h.startswith(b"\xff\xd8\xff") or h.startswith(b"\x89PNG\r\n\x1a\n")
            or (h[:4] == b"RIFF" and h[8:12] == b"WEBP") or h[:6] in (b"GIF87a", b"GIF89a"))


def process_image(raw, square=False):
    """Validate and re-encode an upload. Returns (full_jpeg, thumb_webp, width, height). Strips EXIF/GPS."""
    from PIL import Image, ImageOps
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise BadImage("Photos can be up to %d MB." % (MAX_UPLOAD_BYTES // 1024 // 1024))
    if not sniff(raw):
        raise BadImage("That file isn't a JPEG, PNG, WebP or GIF photo.")
    Image.MAX_IMAGE_PIXELS = 60_000_000
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ALLOWED_FORMATS:
            raise BadImage("That file isn't a JPEG, PNG, WebP or GIF photo.")
        if im.format in ("JPEG", "MPO"):
            im.draft("RGB", (FULL_PX * 2, FULL_PX * 2))  # decode big phone photos at reduced scale
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
    except BadImage:
        raise
    except Exception:
        raise BadImage("We couldn't read that photo. Try a JPEG or PNG.")
    if min(im.size) < 120:
        raise BadImage("That photo is too small. Please use one at least 120 pixels wide.")
    if square:
        s = min(im.size)
        im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    full = im.copy()
    full.thumbnail((FULL_PX, FULL_PX), Image.LANCZOS)
    b1 = io.BytesIO()
    full.save(b1, "JPEG", quality=84, optimize=True, progressive=True)  # no exif= argument: metadata is dropped
    th = im.copy()
    th.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    b2 = io.BytesIO()
    th.save(b2, "WEBP", quality=80, method=5)
    return b1.getvalue(), b2.getvalue(), full.width, full.height


def gallery(dog_id):
    return [dict(id=r[0], width=r[1], height=r[2]) for r in
            q("SELECT id,width,height FROM photos WHERE dog_id=:d AND kind='gallery' ORDER BY position, id", d=dog_id)]


def photo_count(dog_id):
    return one("SELECT COUNT(*) FROM photos WHERE dog_id=:d AND kind='gallery'", d=dog_id)[0]


def add_photo(dog_id, raw, kind="gallery"):
    full, thumb, w, h = process_image(raw, square=(kind == "avatar"))
    pos = one("SELECT COALESCE(MAX(position),0)+1 FROM photos WHERE dog_id=:d", d=dog_id)[0]
    r = one("""INSERT INTO photos(dog_id,kind,position,width,height,full_jpeg,thumb_webp,bytes,sha,created_at)
               VALUES(:d,:k,:p,:w,:h,:f,:th,:b,:s,:t) RETURNING id""",
            d=dog_id, k=kind, p=pos, w=w, h=h, f=full, th=thumb, b=len(full) + len(thumb), s=sha(raw), t=now())
    return r[0]


def photo_blob(photo_id, which):
    col = "full_jpeg" if which == "full" else "thumb_webp"
    r = one(f"""SELECT p.{col} FROM photos p JOIN dogs d ON d.id=p.dog_id WHERE p.id=:i AND d.hidden=0""", i=photo_id)
    return bytes(r[0]) if r else None


def delete_photo(dog_id, photo_id):
    q("DELETE FROM photos WHERE id=:p AND dog_id=:d", p=photo_id, d=dog_id)
    q("UPDATE dogs SET avatar_photo_id=NULL WHERE id=:d AND avatar_photo_id=:p", d=dog_id, p=photo_id)


def set_avatar(dog_id, photo_id):
    if one("SELECT id FROM photos WHERE id=:p AND dog_id=:d", p=photo_id, d=dog_id):
        old = one("SELECT avatar_photo_id FROM dogs WHERE id=:d", d=dog_id)
        q("UPDATE dogs SET avatar_photo_id=:p, updated_at=:t WHERE id=:d", p=photo_id, d=dog_id, t=now())
        if old and old[0] and old[0] != photo_id:  # drop a replaced avatar-only image
            q("DELETE FROM photos WHERE id=:o AND kind='avatar'", o=old[0])
        return True
    return False


def cover_and_avatar(d, photos=None):
    """(cover photo id, avatar photo id) for display."""
    photos = gallery(d["id"]) if photos is None else photos
    cover = photos[0]["id"] if photos else None
    return cover, d.get("avatar_photo_id") or cover


def first_photos(dog_ids):
    """{dog_id: first gallery photo id} for a list of dogs."""
    ids = sorted({int(i) for i in dog_ids})
    if not ids:
        return {}
    out = {}
    rows = q("SELECT dog_id, id FROM photos WHERE kind='gallery' AND dog_id IN (%s) ORDER BY position DESC, id DESC"
             % ",".join(str(i) for i in ids))
    for did, pid in rows:
        out[did] = pid  # last write wins = lowest position
    return out


def storage_stats():
    r = one("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM photos")
    return dict(photos=r[0], bytes=int(r[1]))


# ---------------------------------------------------------------- reports
REPORT_REASONS = ["Not a real dog profile or spam", "Inappropriate photo or text", "Uses my photos without permission",
                  "Safety concern", "Something else"]


def add_report(dog_id, user_id, reason, details, ip):
    q("INSERT INTO reports(dog_id,reporter_user_id,reason,details,ip_hash,created_at) VALUES(:d,:u,:r,:x,:i,:t)",
      d=dog_id, u=user_id, r=reason, x=details, i=ip_hash(ip), t=now())


def list_reports():
    """Rows: id, ts, reason, details, status, dog slug, dog name, dog hidden, dog id,
    meetup id, meetup title, meetup slug, meetup hidden, comment id, comment body, comment hidden."""
    return q("""SELECT r.id, r.created_at, r.reason, r.details, r.status, d.slug, d.name, d.hidden, d.id,
                       m.id, m.title, m.slug, m.hidden, c.id, c.body, c.hidden
                FROM reports r LEFT JOIN dogs d ON d.id=r.dog_id LEFT JOIN meetups m ON m.id=r.meetup_id
                LEFT JOIN meetup_comments c ON c.id=r.comment_id ORDER BY r.status='open' DESC, r.id DESC LIMIT 300""")


def set_report_status(report_id, status):
    q("UPDATE reports SET status=:s WHERE id=:i", s=status, i=report_id)


def set_dog_hidden(dog_id, hidden):
    q("UPDATE dogs SET hidden=:h WHERE id=:d", h=1 if hidden else 0, d=dog_id)


def clean_website(url):
    """Return a normalized http(s) URL, '' for blank, or None when invalid."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url and re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/|$)", url):
        url = "https://" + url
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname or len(url) > 200 \
            or p.username or p.password or any(c in url for c in ' "<>\'\\') or any(ord(c) < 33 for c in url):
        return None
    return url
