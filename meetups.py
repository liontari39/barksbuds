"""BarksBuds meetups: data layer (meetups, RSVPs with dogs, waitlist, comments, reminders).

Times are stored as Unix seconds (UTC) and shown in America/New_York. Capacity counts dogs on "Going" RSVPs;
when a meetup is full new "Going" RSVPs join a first-come waitlist and are promoted automatically when spots open.
Sample meetups (is_sample=1) are clearly labeled, never send automatic emails and can be hidden or deleted from
/admin/meetups.
"""
import hashlib, hmac, json, threading
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover  (tzdata missing)
    ET = timezone(timedelta(hours=-5), "ET")

import accounts as A

FITS = [("all", "All dogs welcome"), ("small", "Small dogs"), ("big", "Big dogs"), ("puppies", "Puppies"), ("seniors", "Senior dogs")]
FIT_LABEL = dict(FITS)
DURATIONS = [30, 45, 60, 90, 120, 180]
MAX_TITLE, MAX_DESC, MAX_COMMENT = 80, 2000, 1000
MAX_CAPACITY = 200
REMIND_BEFORE = 24 * 3600          # send the reminder once a meetup is this close...
REMIND_MIN_LEAD = 3600             # ...but not when it starts in under an hour
NORTH_SHORE = ("manhasset", "great neck", "roslyn", "north hills", "port washington", "manorhaven", "sands point",
               "glen cove", "east hills", "oyster bay", "sea cliff", "glen head", "locust valley", "plandome",
               "albertson", "searingtown", "huntington", "northport", "cold spring harbor")
LOCK = threading.Lock()            # serializes RSVP changes so capacity can't be oversold (one web process)

M_COLS = ("id,host_user_id,slug,title,starts_at,duration_min,run_id,place_name,address,lat,lng,area,town,description,"
          "fit,capacity,status,is_sample,hidden,seed_key,reminder_sent_at,created_at,updated_at,pack_id,members_only,seed_rev")


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    REAL = "DOUBLE PRECISION" if pg else "REAL"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS meetups(id {ID}, host_user_id {INT} NOT NULL, slug TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, starts_at {INT} NOT NULL, duration_min {INT} NOT NULL DEFAULT 60, run_id TEXT NOT NULL DEFAULT '',
            place_name TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', lat {REAL}, lng {REAL},
            area TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            fit TEXT NOT NULL DEFAULT '', capacity {INT}, status TEXT NOT NULL DEFAULT 'active',
            is_sample {INT} NOT NULL DEFAULT 0, hidden {INT} NOT NULL DEFAULT 0, seed_key TEXT UNIQUE,
            reminder_sent_at {INT}, created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS meetups_start_idx ON meetups(starts_at)",
        "CREATE INDEX IF NOT EXISTS meetups_host_idx ON meetups(host_user_id)",
        f"""CREATE TABLE IF NOT EXISTS rsvps(id {ID}, meetup_id {INT} NOT NULL, user_id {INT} NOT NULL,
            status TEXT NOT NULL, dogs TEXT NOT NULL DEFAULT '[]', queued_at {INT}, created_at {INT} NOT NULL,
            updated_at {INT} NOT NULL, UNIQUE(meetup_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS rsvps_user_idx ON rsvps(user_id)",
        f"""CREATE TABLE IF NOT EXISTS meetup_comments(id {ID}, meetup_id {INT} NOT NULL, user_id {INT} NOT NULL,
            body TEXT NOT NULL, hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS meetup_comments_idx ON meetup_comments(meetup_id, id)",
    ]:
        store.q(s)

    def cols(t):
        return ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=t)} if pg
                else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    uc = cols("users")
    if "meetup_emails" not in uc:
        store.q(f"ALTER TABLE users ADD COLUMN meetup_emails {INT} NOT NULL DEFAULT 1")
    rc = cols("reports")
    if "meetup_id" not in rc:
        store.q(f"ALTER TABLE reports ADD COLUMN meetup_id {INT}")
    if "comment_id" not in rc:
        store.q(f"ALTER TABLE reports ADD COLUMN comment_id {INT}")


# ---------------------------------------------------------------- time helpers
def to_et(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).astimezone(ET)


def from_et(day, hhmm):
    """'2026-10-31', '10:00' (wall time in New York) -> Unix seconds, or None."""
    try:
        d = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return int(d.replace(tzinfo=ET).timestamp())


def _hour(dt):
    h = dt.strftime("%I").lstrip("0")
    return h + (dt.strftime(":%M") if dt.minute else "") + " " + dt.strftime("%p")


def when_text(ts, duration=None, short=False):
    """'Sat, Oct 31 · 10 AM–11 AM ET' (or a short 'Sat, Oct 31, 10 AM')."""
    s = to_et(ts)
    day = s.strftime("%a, %b ") + str(s.day)
    if short:
        return f"{day}, {_hour(s)}"
    if duration:
        e = to_et(int(ts) + int(duration) * 60)
        return f"{day} · {_hour(s)}–{_hour(e)} ET"
    return f"{day} · {_hour(s)} ET"


def duration_text(m):
    m = int(m)
    if m < 60:
        return f"{m} minutes"
    h, r = divmod(m, 60)
    return (f"{h} hour" + ("s" if h > 1 else "")) + (f" {r} min" if r else "")


def week_window(now=None):
    n = now or A.now()
    return n, n + 7 * 86400


def weekend_window(now=None):
    """The current weekend if today is Sat/Sun, otherwise the next one (New York time)."""
    n = now or A.now()
    d = to_et(n)
    sat = (d - timedelta(days=(d.weekday() - 5) % 7)) if d.weekday() >= 5 else d + timedelta(days=5 - d.weekday())
    start = sat.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    return max(int(start.timestamp()), n - 6 * 3600), int(end.timestamp())


# ---------------------------------------------------------------- meetups
def _m(r):
    if not r:
        return None
    m = dict(zip(M_COLS.split(","), r))
    m["ends_at"] = m["starts_at"] + m["duration_min"] * 60
    return m


def get(mid):
    m = _m(one(f"SELECT {M_COLS} FROM meetups WHERE id=:i", i=mid))
    if m:
        h = A.owner_public(m["host_user_id"])
        m["host_name"] = h["display_name"] or "a BarksBuds member"
    return m


def is_north_shore(m):
    hay = " ".join([m.get("town") or "", m.get("place_name") or "", m.get("address") or ""]).lower()
    return m.get("area") in ("Nassau", "Suffolk") and any(t in hay for t in NORTH_SHORE)


def save(host_id, f, mid=None, seed_key=None, is_sample=0):
    t = A.now()
    vals = dict(ti=f["title"], st=f["starts_at"], du=f["duration_min"], ru=f["run_id"], pn=f["place_name"], ad=f["address"],
                la=f["lat"], ln=f["lng"], ar=f["area"], tw=f["town"], de=f["description"], fi=f["fit"], ca=f["capacity"],
                sl=A.slugify(f["title"], 60), pk=f.get("pack_id") or None, mo=1 if f.get("pack_id") and f.get("members_only") else 0, t=t)
    if mid:
        old = get(mid)
        moved = old and old["starts_at"] != f["starts_at"]
        q("""UPDATE meetups SET title=:ti,starts_at=:st,duration_min=:du,run_id=:ru,place_name=:pn,address=:ad,lat=:la,lng=:ln,
             area=:ar,town=:tw,description=:de,fit=:fi,capacity=:ca,slug=:sl,pack_id=:pk,members_only=:mo,updated_at=:t""" +
          (",reminder_sent_at=NULL" if moved and not (old and old["is_sample"]) else "") + " WHERE id=:i", i=mid, **vals)
        return mid, promote(mid)
    r = one("""INSERT INTO meetups(host_user_id,slug,title,starts_at,duration_min,run_id,place_name,address,lat,lng,area,town,
               description,fit,capacity,is_sample,seed_key,reminder_sent_at,pack_id,members_only,created_at,updated_at)
               VALUES(:h,:sl,:ti,:st,:du,:ru,:pn,:ad,:la,:ln,:ar,:tw,:de,:fi,:ca,:sa,:sk,:rs,:pk,:mo,:t,:t) RETURNING id""",
            h=host_id, sa=1 if is_sample else 0, sk=seed_key, rs=(t if is_sample else None), **vals)
    return r[0], []


def as_form(m, days=0):
    """A meetup as a field dict (optionally shifted by whole days, keeping the New York wall-clock time)."""
    s = to_et(m["starts_at"]) + timedelta(days=days)
    st = int(s.replace(tzinfo=None).replace(tzinfo=ET).timestamp()) if days else m["starts_at"]
    return dict(title=m["title"], starts_at=st, duration_min=m["duration_min"], run_id=m["run_id"], place_name=m["place_name"],
                address=m["address"], lat=m["lat"], lng=m["lng"], area=m["area"], town=m["town"], description=m["description"],
                fit=m["fit"], capacity=m["capacity"], pack_id=m.get("pack_id"), members_only=m.get("members_only"))


def duplicate_next_week(m):
    mid, _ = save(m["host_user_id"], as_form(m, days=7), is_sample=m["is_sample"])
    return mid


def cancel(mid):
    """Cancel; returns the RSVP rows to notify [(user_id, status)]."""
    q("UPDATE meetups SET status='cancelled', updated_at=:t WHERE id=:i AND status='active'", t=A.now(), i=mid)
    return [(r[0], r[1]) for r in q("SELECT user_id, status FROM rsvps WHERE meetup_id=:m", m=mid)]


def delete(mid):
    q("DELETE FROM rsvps WHERE meetup_id=:m", m=mid)
    q("DELETE FROM meetup_comments WHERE meetup_id=:m", m=mid)
    q("DELETE FROM reports WHERE meetup_id=:m", m=mid)
    q("DELETE FROM meetups WHERE id=:m", m=mid)


def set_hidden(mid, hidden):
    q("UPDATE meetups SET hidden=:h WHERE id=:m", h=1 if hidden else 0, m=mid)


def upcoming(areas=None, start=None, end=None, run_id=None, north_shore=False, limit=200):
    """Active, visible meetups that haven't ended, soonest first."""
    n = A.now()
    rows = q(f"SELECT {M_COLS} FROM meetups WHERE status='active' AND hidden=0 AND starts_at>:a ORDER BY starts_at, id",
             a=n - 6 * 3600)
    out = []
    for r in rows:
        m = _m(r)
        if m["ends_at"] <= n:
            continue
        if areas and m["area"] not in areas:
            continue
        if start is not None and m["ends_at"] <= start:
            continue
        if end is not None and m["starts_at"] >= end:
            continue
        if run_id and m["run_id"] != run_id:
            continue
        if north_shore and not is_north_shore(m):
            continue
        out.append(m)
        if len(out) >= limit:
            break
    hosts = {}
    for m in out:
        if m["host_user_id"] not in hosts:
            hosts[m["host_user_id"]] = A.owner_public(m["host_user_id"])["display_name"] or "a BarksBuds member"
        m["host_name"] = hosts[m["host_user_id"]]
    return out


def for_user(uid):
    """(hosting, attending) upcoming lists for the dashboard."""
    n = A.now()
    host = [_m(r) for r in q(f"SELECT {M_COLS} FROM meetups WHERE host_user_id=:u AND starts_at>:a ORDER BY starts_at", u=uid, a=n - 6 * 3600)]
    att = []
    for r in q(f"""SELECT {', '.join('m.' + c for c in M_COLS.split(','))}, r.status FROM meetups m JOIN rsvps r ON r.meetup_id=m.id
                   WHERE r.user_id=:u AND m.starts_at>:a ORDER BY m.starts_at""", u=uid, a=n - 6 * 3600):
        m = _m(r[:-1]); m["my_status"] = r[-1]; att.append(m)
    return [m for m in host if m["ends_at"] > n], [m for m in att if m["ends_at"] > n]


# ---------------------------------------------------------------- RSVPs
def _dogs(s):
    try:
        v = json.loads(s or "[]")
        return [int(x) for x in v if isinstance(x, int) or str(x).isdigit()]
    except ValueError:
        return []


def rsvp_of(mid, uid):
    r = one("SELECT id,status,dogs,queued_at,created_at FROM rsvps WHERE meetup_id=:m AND user_id=:u", m=mid, u=uid)
    return dict(id=r[0], status=r[1], dogs=_dogs(r[2]), queued_at=r[3], created_at=r[4]) if r else None


def going_dogs(mid, exclude_user=None):
    n = 0
    for uid, dogs in q("SELECT user_id, dogs FROM rsvps WHERE meetup_id=:m AND status='going'", m=mid):
        if uid != exclude_user:
            n += len(_dogs(dogs))
    return n


def spots_left(m):
    if not m.get("capacity"):
        return None
    return max(m["capacity"] - going_dogs(m["id"]), 0)


class Full(Exception):
    pass


def set_rsvp(m, uid, status, dog_ids):
    """Create or change an RSVP. status is 'going' or 'maybe'; returns (final_status, previous_status, promoted_user_ids).
    A 'going' RSVP that doesn't fit joins the waitlist; an existing 'going' RSVP that adds dogs past capacity raises Full."""
    assert status in ("going", "maybe")
    t = A.now()
    with LOCK:
        cur = rsvp_of(m["id"], uid)
        prev = cur["status"] if cur else None
        final, queued = status, None
        if status == "going" and m.get("capacity"):
            used = going_dogs(m["id"], exclude_user=uid)
            if used + len(dog_ids) > m["capacity"]:
                if prev == "going":
                    raise Full(max(m["capacity"] - used, 0))
                final = "waitlist"
                queued = cur["queued_at"] if (cur and cur["queued_at"] and prev == "waitlist") else t
        dj = json.dumps(dog_ids)
        if cur:
            q("UPDATE rsvps SET status=:s, dogs=:d, queued_at=:qa, updated_at=:t WHERE id=:i", s=final, d=dj, qa=queued, t=t, i=cur["id"])
        else:
            q("INSERT INTO rsvps(meetup_id,user_id,status,dogs,queued_at,created_at,updated_at) VALUES(:m,:u,:s,:d,:qa,:t,:t)",
              m=m["id"], u=uid, s=final, d=dj, qa=queued, t=t)
        promoted = _promote_locked(m["id"]) if prev == "going" else []
    return final, prev, promoted


def cancel_rsvp(m, uid):
    """Remove an RSVP; returns (previous_status, promoted_user_ids)."""
    with LOCK:
        cur = rsvp_of(m["id"], uid)
        if not cur:
            return None, []
        q("DELETE FROM rsvps WHERE id=:i", i=cur["id"])
        promoted = _promote_locked(m["id"]) if cur["status"] == "going" else []
    return cur["status"], promoted


def promote(mid):
    with LOCK:
        return _promote_locked(mid)


def _promote_locked(mid):
    m = _m(one(f"SELECT {M_COLS} FROM meetups WHERE id=:i", i=mid))
    if not m or m["status"] != "active":
        return []
    used = going_dogs(mid)
    out = []
    for rid, uid, dogs in q("SELECT id, user_id, dogs FROM rsvps WHERE meetup_id=:m AND status='waitlist' ORDER BY queued_at, id", m=mid):
        n = len(_dogs(dogs))
        if not m["capacity"] or used + n <= m["capacity"]:
            q("UPDATE rsvps SET status='going', queued_at=NULL, updated_at=:t WHERE id=:i", t=A.now(), i=rid)
            used += n
            out.append(uid)
    return out


def attendees(mid):
    """{'going': [...], 'maybe': [...], 'waitlist': [...]} of dicts with user name and visible dogs."""
    rows = q("""SELECT r.user_id, r.status, r.dogs, u.display_name FROM rsvps r JOIN users u ON u.id=r.user_id
                WHERE r.meetup_id=:m ORDER BY COALESCE(r.queued_at, r.created_at), r.id""", m=mid)
    ids = sorted({d for r in rows for d in _dogs(r[2])})
    dogs = {}
    if ids:
        for did, slug, name, av, uid, hidden in q("SELECT id, slug, name, avatar_photo_id, user_id, hidden FROM dogs WHERE id IN (%s)"
                                                   % ",".join(str(i) for i in ids)):
            dogs[did] = dict(id=did, slug=slug, name=name, avatar=av, user_id=uid, hidden=hidden)
        firsts = A.first_photos(ids)
        for d in dogs.values():
            d["photo"] = d["avatar"] or firsts.get(d["id"])
    out = {"going": [], "maybe": [], "waitlist": []}
    for uid, st, dj, name in rows:
        ds = [dogs[i] for i in _dogs(dj) if i in dogs and not dogs[i]["hidden"] and dogs[i]["user_id"] == uid]
        out.setdefault(st, []).append(dict(user_id=uid, name=name or "A member", dogs=ds, ndogs=len(_dogs(dj))))
    return out


# ---------------------------------------------------------------- comments
def comments(mid):
    return [dict(id=r[0], user_id=r[1], body=r[2], created_at=r[3], name=r[4] or "A member")
            for r in q("""SELECT c.id, c.user_id, c.body, c.created_at, u.display_name FROM meetup_comments c
                          LEFT JOIN users u ON u.id=c.user_id WHERE c.meetup_id=:m AND c.hidden=0 ORDER BY c.id""", m=mid)]


def comment_count(mid):
    return one("SELECT COUNT(*) FROM meetup_comments WHERE meetup_id=:m AND hidden=0", m=mid)[0]


def add_comment(mid, uid, body):
    return one("INSERT INTO meetup_comments(meetup_id,user_id,body,created_at) VALUES(:m,:u,:b,:t) RETURNING id",
               m=mid, u=uid, b=body, t=A.now())[0]


def get_comment(cid):
    r = one("SELECT id, meetup_id, user_id, body, hidden FROM meetup_comments WHERE id=:i", i=cid)
    return dict(id=r[0], meetup_id=r[1], user_id=r[2], body=r[3], hidden=r[4]) if r else None


def delete_comment(cid):
    q("DELETE FROM meetup_comments WHERE id=:i", i=cid)


def set_comment_hidden(cid, hidden):
    q("UPDATE meetup_comments SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=cid)


def add_report(mid, cid, uid, reason, details, ip):
    q("""INSERT INTO reports(dog_id,meetup_id,comment_id,reporter_user_id,reason,details,ip_hash,created_at)
         VALUES(0,:m,:c,:u,:r,:x,:i,:t)""", m=mid, c=cid, u=uid, r=reason, x=details, i=A.ip_hash(ip), t=A.now())


# ---------------------------------------------------------------- email preferences + recipients
def unsub_token(uid):
    return hmac.new(A.SECRET, f"meetup-emails:{int(uid)}".encode(), hashlib.sha256).hexdigest()[:32]


def check_unsub(uid, tok):
    return str(uid).isdigit() and bool(tok) and hmac.compare_digest(unsub_token(int(uid)), tok)


def set_emails(uid, on):
    q("UPDATE users SET meetup_emails=:v WHERE id=:u", v=1 if on else 0, u=uid)


def emails_on(uid):
    r = one("SELECT meetup_emails FROM users WHERE id=:u", u=uid)
    return bool(r and r[0])


def contact(uid):
    """(email, display_name, wants_meetup_emails) for a member."""
    r = one("SELECT email, display_name, meetup_emails FROM users WHERE id=:u", u=uid)
    return (r[0], r[1] or "", bool(r[2])) if r else (None, "", False)


def dog_names(ids):
    if not ids:
        return []
    names = {r[0]: r[1] for r in q("SELECT id, name FROM dogs WHERE id IN (%s)" % ",".join(str(int(i)) for i in ids))}
    return [names[i] for i in ids if i in names]


def reminders_due(now=None):
    n = now or A.now()
    return [r[0] for r in q("""SELECT id FROM meetups WHERE status='active' AND hidden=0 AND is_sample=0 AND reminder_sent_at IS NULL
                               AND starts_at>:a AND starts_at<=:b ORDER BY starts_at""", a=n + REMIND_MIN_LEAD, b=n + REMIND_BEFORE)]


def claim_reminder(mid):
    """Atomically mark the reminder as sent; True for exactly one caller."""
    return bool(q("UPDATE meetups SET reminder_sent_at=:t WHERE id=:i AND reminder_sent_at IS NULL RETURNING id", t=A.now(), i=mid))


def reminder_recipients(mid):
    return [(r[0], r[1]) for r in q("SELECT user_id, status FROM rsvps WHERE meetup_id=:m AND status IN ('going','maybe')", m=mid)]


def purge_user(uid):
    """Account deletion: drop the member's RSVPs (promoting waitlisted members), comments and hosted meetups."""
    for (mid,) in q("SELECT meetup_id FROM rsvps WHERE user_id=:u", u=uid):
        m = _m(one(f"SELECT {M_COLS} FROM meetups WHERE id=:i", i=mid))
        if m:
            cancel_rsvp(m, uid)
    q("DELETE FROM rsvps WHERE user_id=:u", u=uid)
    q("DELETE FROM meetup_comments WHERE user_id=:u", u=uid)
    for (mid,) in q("SELECT id FROM meetups WHERE host_user_id=:u", u=uid):
        delete(mid)
