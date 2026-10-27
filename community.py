"""BarksBuds community features: data layer (Oct 2026).

  * "At the run now" check-ins: a member taps "We're here" on a run page and picks the dogs with them. A check-in
    ends after CHECKIN_TTL (2 hours) or when they tap "Leaving". A member is at one run at a time (a new check-in ends
    the old one). Privacy: a check-in can be anonymous (counted in "N dogs here now", dogs not shown); the account
    default lives in users.checkins_hidden.
  * Park announcements: the site admin gives a member a "verified park account" role for specific runs
    (park_roles). Those members post announcements (closure, maintenance, rule, event, other) with an optional end
    date. Members can follow a run (run_follows); followers get announcement emails unless users.follow_emails=0.
  * Lost and found alerts: LOST or FOUND, photo or one of the poster's dogs, last seen at a run or a town/area, time
    and description. Contact goes through BarksBuds messages. One alert per member per day, auto-expire after 14
    days, the poster can mark Reunited, the admin can remove. Alert emails go to followers of nearby runs and to
    members in the same area/town (users.alert_emails), at most ALERT_MAILS_PER_DAY per recipient.
  * Dog compatibility notes: dogs.energy and dogs.compat (JSON list), see accounts.SIZES / ENERGY / COMPAT.
  * Vaccination and license reminders (PRIVATE, owners and co-owners only): dog_care rows (rabies, license, other
    vaccines with due dates). Reminder emails 30 and 7 days before (care_sent keeps them once-only).
  * Trusted local recommendations: recs (one row per business: category, name, town, area, contact) and rec_votes
    (one per member per business, with an optional note: "I use them too"). Reports go to rec_reports.
  * Birthday and gotcha-day shout-outs: dogs.gotcha_day; celebration emails logged in celebrate_sent.

Everything works on SQLite and Postgres through accounts.STORE.q (integer Unix timestamps, ISO date strings).
"""
import hashlib, hmac, json, math, re, time, unicodedata
from datetime import date, datetime, timedelta, timezone

import accounts as A

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone.utc

CHECKIN_TTL = 2 * 3600
CHECKINS_PER_HOUR = 12
ANN_KINDS = [("closure", "Closure"), ("maintenance", "Maintenance"), ("rule", "Rule change"), ("event", "Event"), ("other", "Notice")]
ALERT_TTL = 14 * 86400
ALERT_NEAR_MILES = 3.0
ALERT_MAX_RECIPIENTS = 200
ALERT_MAILS_PER_DAY = 3
REC_CATS = [("vet", "Vets"), ("groomer", "Groomers"), ("walker", "Dog walkers"), ("sitter", "Sitters"),
            ("trainer", "Trainers"), ("daycare", "Daycare"), ("store", "Pet stores")]
REC_ONE = {"vet": "Vet", "groomer": "Groomer", "walker": "Dog walker", "sitter": "Sitter", "trainer": "Trainer",
           "daycare": "Daycare", "store": "Pet store"}
REC_REPORT_REASONS = ["Not a real business", "Closed or moved", "Spam or advertising", "Wrong details", "Something else"]
CARE_KINDS = [("rabies", "Rabies vaccine"), ("license", "Town dog license"), ("vaccine", "Other vaccine")]
CARE_LEADS = (30, 7)
MAX_CARE = 12


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    BLOB = "BYTEA" if pg else "BLOB"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS checkins(id {ID}, user_id {INT} NOT NULL, run_id TEXT NOT NULL, dog_ids TEXT NOT NULL DEFAULT '[]',
            anon {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL, expires_at {INT} NOT NULL, left_at {INT})""",
        "CREATE INDEX IF NOT EXISTS checkins_run_idx ON checkins(run_id, expires_at)",
        "CREATE INDEX IF NOT EXISTS checkins_user_idx ON checkins(user_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS run_follows(id {ID}, user_id {INT} NOT NULL, run_id TEXT NOT NULL, created_at {INT} NOT NULL,
            UNIQUE(user_id, run_id))""",
        "CREATE INDEX IF NOT EXISTS run_follows_run_idx ON run_follows(run_id)",
        f"""CREATE TABLE IF NOT EXISTS park_roles(id {ID}, user_id {INT} NOT NULL, run_id TEXT NOT NULL, org_name TEXT NOT NULL DEFAULT '',
            created_at {INT} NOT NULL, UNIQUE(user_id, run_id))""",
        f"""CREATE TABLE IF NOT EXISTS announcements(id {ID}, run_id TEXT NOT NULL, user_id {INT}, org_name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', ends_at {INT}, removed {INT} NOT NULL DEFAULT 0,
            created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS announcements_run_idx ON announcements(run_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS lost_alerts(id {ID}, user_id {INT} NOT NULL, kind TEXT NOT NULL, dog_id {INT},
            dog_name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', run_id TEXT NOT NULL DEFAULT '',
            area TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', lat DOUBLE PRECISION, lng DOUBLE PRECISION,
            seen_at {INT} NOT NULL, status TEXT NOT NULL DEFAULT 'active', photo_full {BLOB}, photo_thumb {BLOB},
            photo_w {INT}, photo_h {INT}, created_at {INT} NOT NULL, expires_at {INT} NOT NULL, closed_at {INT})""",
        "CREATE INDEX IF NOT EXISTS lost_alerts_status_idx ON lost_alerts(status, expires_at)",
        "CREATE INDEX IF NOT EXISTS lost_alerts_user_idx ON lost_alerts(user_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS alert_mail(id {ID}, alert_id {INT} NOT NULL, user_id {INT} NOT NULL, sent_at {INT} NOT NULL,
            UNIQUE(alert_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS alert_mail_user_idx ON alert_mail(user_id, sent_at)",
        f"""CREATE TABLE IF NOT EXISTS recs(id {ID}, category TEXT NOT NULL, name TEXT NOT NULL, name_key TEXT NOT NULL,
            town TEXT NOT NULL DEFAULT '', town_key TEXT NOT NULL DEFAULT '', area TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '',
            created_by {INT}, hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL, UNIQUE(category, name_key, town_key))""",
        "CREATE INDEX IF NOT EXISTS recs_area_idx ON recs(area, category)",
        f"""CREATE TABLE IF NOT EXISTS rec_votes(id {ID}, rec_id {INT} NOT NULL, user_id {INT} NOT NULL, note TEXT NOT NULL DEFAULT '',
            created_at {INT} NOT NULL, UNIQUE(rec_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS rec_votes_user_idx ON rec_votes(user_id)",
        f"""CREATE TABLE IF NOT EXISTS rec_reports(id {ID}, rec_id {INT} NOT NULL, reporter_user_id {INT}, reason TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created_at {INT} NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS dog_care(id {ID}, dog_id {INT} NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL, created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS dog_care_dog_idx ON dog_care(dog_id)",
        f"""CREATE TABLE IF NOT EXISTS care_sent(id {ID}, care_id {INT} NOT NULL, due_date TEXT NOT NULL, lead_days {INT} NOT NULL,
            user_id {INT} NOT NULL, sent_at {INT} NOT NULL, UNIQUE(care_id, due_date, lead_days, user_id))""",
        f"""CREATE TABLE IF NOT EXISTS celebrate_sent(id {ID}, dog_id {INT} NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL,
            user_id {INT} NOT NULL, sent_at {INT} NOT NULL, UNIQUE(dog_id, kind, day, user_id))""",
        f"""CREATE TABLE IF NOT EXISTS job_runs(id {ID}, job TEXT NOT NULL, day TEXT NOT NULL, ran_at {INT} NOT NULL, UNIQUE(job, day))""",
    ]:
        store.q(s)
    cols = lambda t: ({r[0] for r in store.q(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}'")} if pg
                      else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    uc = cols("users")
    for c in ("checkins_hidden",):
        if c not in uc:
            store.q(f"ALTER TABLE users ADD COLUMN {c} {INT} NOT NULL DEFAULT 0")
    for c in ("follow_emails", "alert_emails", "celebrate_emails", "care_emails"):
        if c not in uc:
            store.q(f"ALTER TABLE users ADD COLUMN {c} {INT} NOT NULL DEFAULT 1")
    dc = cols("dogs")
    if "energy" not in dc:
        store.q("ALTER TABLE dogs ADD COLUMN energy TEXT NOT NULL DEFAULT ''")
    if "compat" not in dc:
        store.q("ALTER TABLE dogs ADD COLUMN compat TEXT NOT NULL DEFAULT '[]'")
    if "gotcha_day" not in dc:
        store.q("ALTER TABLE dogs ADD COLUMN gotcha_day TEXT NOT NULL DEFAULT ''")


# ---------------------------------------------------------------- helpers
def now():
    return int(time.time())


def today_et():
    return datetime.now(ET).date()


def key(s):
    """Normalized text for duplicate checks: 'Dr. Smith's Vet  Clinic' -> 'dr smiths vet clinic'."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def miles(a_lat, a_lng, b_lat, b_lng):
    if None in (a_lat, a_lng, b_lat, b_lng):
        return None
    R, r = 3958.8, math.pi / 180
    dla, dlo = (b_lat - a_lat) * r, (b_lng - a_lng) * r
    h = math.sin(dla / 2) ** 2 + math.cos(a_lat * r) * math.cos(b_lat * r) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def unsub_token(uid, kind):
    return hmac.new(A.SECRET, f"community-emails:{kind}:{int(uid)}".encode(), hashlib.sha256).hexdigest()[:32]


def check_unsub(uid, kind, tok):
    return (str(uid).isdigit() and kind in EMAIL_KINDS and bool(tok)
            and hmac.compare_digest(unsub_token(int(uid), kind), tok))


EMAIL_KINDS = {"follow": ("follow_emails", "Park news emails", "announcements from the dog runs you follow"),
               "alert": ("alert_emails", "Lost and found emails", "lost and found dog alerts near you"),
               "celebrate": ("celebrate_emails", "Celebration emails", "a little note on your dog's birthday and gotcha day"),
               "care": ("care_emails", "Care reminder emails", "reminders 30 and 7 days before a vaccine or license is due")}


def emails_on(uid, kind):
    r = one(f"SELECT {EMAIL_KINDS[kind][0]} FROM users WHERE id=:u", u=uid)
    return bool(r and r[0])


def set_emails(uid, kind, on):
    q(f"UPDATE users SET {EMAIL_KINDS[kind][0]}=:v WHERE id=:u", v=1 if on else 0, u=uid)


def user_row(uid):
    r = one("SELECT id, email, display_name, area, town FROM users WHERE id=:u", u=uid)
    return dict(id=r[0], email=r[1], name=r[2], area=r[3], town=r[4]) if r else None


def dog_tiles(dog_ids):
    """[{id, slug, name, photo}] for visible dogs, in the given order. photo = main picture (pixel portrait when done)."""
    ids = [int(i) for i in dog_ids if str(i).isdigit()]
    if not ids:
        return []
    rows = q("SELECT id, slug, name, avatar_photo_id, hidden FROM dogs WHERE id IN (%s)" % ",".join(str(i) for i in ids))
    by = {r[0]: r for r in rows if not r[4]}
    firsts = A.first_photos(list(by))
    return [dict(id=i, slug=by[i][1], name=by[i][2], photo=by[i][3] or firsts.get(i)) for i in ids if i in by]


# ---------------------------------------------------------------- check-ins
def active_checkin(uid, t=None):
    t = t or now()
    r = one("SELECT id, run_id, dog_ids, anon, created_at, expires_at FROM checkins WHERE user_id=:u AND left_at IS NULL AND expires_at>:t "
            "ORDER BY id DESC LIMIT 1", u=uid, t=t)
    return dict(id=r[0], run_id=r[1], dogs=json.loads(r[2] or "[]"), anon=bool(r[3]), created_at=r[4], expires_at=r[5]) if r else None


def check_in(uid, run_id, dog_ids, anon=False):
    t = now()
    q("UPDATE checkins SET left_at=:t WHERE user_id=:u AND left_at IS NULL AND expires_at>:t", u=uid, t=t)
    r = one("INSERT INTO checkins(user_id, run_id, dog_ids, anon, created_at, expires_at) VALUES(:u,:r,:d,:a,:t,:x) RETURNING id",
            u=uid, r=run_id, d=json.dumps([int(i) for i in dog_ids]), a=1 if anon else 0, t=t, x=t + CHECKIN_TTL)
    return r[0]


def leave(uid):
    t = now()
    q("UPDATE checkins SET left_at=:t WHERE user_id=:u AND left_at IS NULL AND expires_at>:t", u=uid, t=t)


def here_now(run_id, t=None):
    """Active check-ins at a run: [{user_id, name, anon, dogs:[tiles], since}] newest first."""
    t = t or now()
    rows = q("""SELECT c.user_id, u.display_name, c.dog_ids, c.anon, c.created_at FROM checkins c JOIN users u ON u.id=c.user_id
                WHERE c.run_id=:r AND c.left_at IS NULL AND c.expires_at>:t ORDER BY c.created_at DESC""", r=run_id, t=t)
    out = []
    for uid, name, dids, anon, since in rows:
        ids = json.loads(dids or "[]")
        out.append(dict(user_id=uid, name=name, anon=bool(anon), ndogs=len(ids), dogs=[] if anon else dog_tiles(ids), since=since))
    return out


def here_counts(t=None):
    """{run_id: dogs checked in now} for the run list and map badges."""
    t = t or now()
    out = {}
    for rid, dids in q("SELECT run_id, dog_ids FROM checkins WHERE left_at IS NULL AND expires_at>:t", t=t):
        out[rid] = out.get(rid, 0) + len(json.loads(dids or "[]"))
    return {k: v for k, v in out.items() if v}


def set_checkins_hidden(uid, on):
    q("UPDATE users SET checkins_hidden=:v WHERE id=:u", v=1 if on else 0, u=uid)


def checkins_hidden(uid):
    r = one("SELECT checkins_hidden FROM users WHERE id=:u", u=uid)
    return bool(r and r[0])


# ---------------------------------------------------------------- follows, park roles, announcements
def follows(uid, run_id):
    return bool(one("SELECT 1 FROM run_follows WHERE user_id=:u AND run_id=:r", u=uid, r=run_id))


def follow(uid, run_id, on=True):
    if on:
        q("INSERT INTO run_follows(user_id, run_id, created_at) VALUES(:u,:r,:t) ON CONFLICT DO NOTHING", u=uid, r=run_id, t=now())
    else:
        q("DELETE FROM run_follows WHERE user_id=:u AND run_id=:r", u=uid, r=run_id)


def followed_runs(uid):
    return [r[0] for r in q("SELECT run_id FROM run_follows WHERE user_id=:u ORDER BY created_at", u=uid)]


def follower_count(run_id):
    return one("SELECT COUNT(*) FROM run_follows WHERE run_id=:r", r=run_id)[0]


def followers(run_ids):
    if not run_ids:
        return []
    ph = ",".join(f":r{i}" for i in range(len(run_ids)))
    return sorted({r[0] for r in q(f"SELECT user_id FROM run_follows WHERE run_id IN ({ph})", **{f"r{i}": x for i, x in enumerate(run_ids)})})


def park_role(uid, run_id):
    r = one("SELECT org_name FROM park_roles WHERE user_id=:u AND run_id=:r", u=uid, r=run_id)
    return (r[0] or "Park staff") if r else None


def park_roles(uid=None):
    rows = q("""SELECT p.id, p.user_id, u.email, u.display_name, p.run_id, p.org_name, p.created_at FROM park_roles p
                LEFT JOIN users u ON u.id=p.user_id""" + (" WHERE p.user_id=:u" if uid else "") + " ORDER BY p.id", **({"u": uid} if uid else {}))
    return [dict(id=r[0], user_id=r[1], email=r[2], name=r[3], run_id=r[4], org=r[5], created_at=r[6]) for r in rows]


def grant_role(uid, run_id, org):
    q("INSERT INTO park_roles(user_id, run_id, org_name, created_at) VALUES(:u,:r,:o,:t) ON CONFLICT DO NOTHING", u=uid, r=run_id, o=org, t=now())
    q("UPDATE park_roles SET org_name=:o WHERE user_id=:u AND run_id=:r", u=uid, r=run_id, o=org)


def revoke_role(role_id):
    q("DELETE FROM park_roles WHERE id=:i", i=role_id)


ANN_COLS = "id, run_id, user_id, org_name, kind, title, body, ends_at, removed, created_at"


def _ann(r):
    return dict(zip([c.strip() for c in ANN_COLS.split(",")], r)) if r else None


def add_announcement(uid, run_id, org, kind, title, body, ends_at):
    return one("""INSERT INTO announcements(run_id, user_id, org_name, kind, title, body, ends_at, created_at)
                  VALUES(:r,:u,:o,:k,:ti,:b,:e,:t) RETURNING id""", r=run_id, u=uid, o=org, k=kind, ti=title, b=body, e=ends_at, t=now())[0]


def announcement(aid):
    return _ann(one(f"SELECT {ANN_COLS} FROM announcements WHERE id=:i", i=aid))


def announcements(run_id, current=True, limit=20):
    t = now()
    w = " AND (ends_at IS NULL OR ends_at>:t)" if current else ""
    return [_ann(r) for r in q(f"SELECT {ANN_COLS} FROM announcements WHERE run_id=:r AND removed=0{w} ORDER BY created_at DESC, id DESC LIMIT {int(limit)}",
                               r=run_id, t=t)]


def announcement_counts():
    t = now()
    return {r[0]: r[1] for r in q("SELECT run_id, COUNT(*) FROM announcements WHERE removed=0 AND (ends_at IS NULL OR ends_at>:t) GROUP BY run_id", t=t)}


def remove_announcement(aid):
    q("UPDATE announcements SET removed=1 WHERE id=:i", i=aid)


# ---------------------------------------------------------------- lost and found
ALERT_COLS = ("id, user_id, kind, dog_id, dog_name, description, run_id, area, town, lat, lng, seen_at, status, "
              "photo_w, photo_h, created_at, expires_at, closed_at")


def _alert(r):
    if not r:
        return None
    a = dict(zip([c.strip() for c in ALERT_COLS.split(",")], r))
    a["has_photo"] = bool(a["photo_w"])
    a["live"] = a["status"] == "active" and a["expires_at"] > now()
    a["state"] = a["status"] if a["status"] != "active" else ("active" if a["live"] else "expired")
    return a


def alert(aid):
    return _alert(one(f"SELECT {ALERT_COLS} FROM lost_alerts WHERE id=:i", i=aid))


def alerts_posted_since(uid, since):
    return one("SELECT COUNT(*) FROM lost_alerts WHERE user_id=:u AND created_at>:t", u=uid, t=since)[0]


def add_alert(uid, kind, dog_id, dog_name, description, run_id, area, town, lat, lng, seen_at, photo=None):
    t = now()
    full, thumb, w, h = photo if photo else (None, None, None, None)
    return one("""INSERT INTO lost_alerts(user_id, kind, dog_id, dog_name, description, run_id, area, town, lat, lng, seen_at,
                  photo_full, photo_thumb, photo_w, photo_h, created_at, expires_at)
                  VALUES(:u,:k,:d,:n,:de,:r,:a,:to,:la,:lo,:s,:pf,:pt,:pw,:ph,:t,:x) RETURNING id""",
               u=uid, k=kind, d=dog_id, n=dog_name, de=description, r=run_id, a=area, to=town, la=lat, lo=lng, s=seen_at,
               pf=full, pt=thumb, pw=w, ph=h, t=t, x=t + ALERT_TTL)[0]


def alert_photo(aid, which):
    col = "photo_full" if which == "full" else "photo_thumb"
    r = one(f"SELECT {col} FROM lost_alerts WHERE id=:i AND status<>'removed'", i=aid)
    return bytes(r[0]) if r and r[0] is not None else None


def set_alert_status(aid, status):
    q("UPDATE lost_alerts SET status=:s, closed_at=:t WHERE id=:i", s=status, t=now(), i=aid)


def live_alerts(limit=50):
    rows = q(f"SELECT {ALERT_COLS} FROM lost_alerts WHERE status='active' AND expires_at>:t ORDER BY created_at DESC LIMIT {int(limit)}", t=now())
    return [_alert(r) for r in rows]


def recent_alerts(limit=60):
    """Active alerts plus reunited ones from the last 14 days (for the /lost-found page)."""
    rows = q(f"""SELECT {ALERT_COLS} FROM lost_alerts WHERE (status='active' AND expires_at>:t) OR (status='reunited' AND closed_at>:r)
                 ORDER BY created_at DESC LIMIT {int(limit)}""", t=now(), r=now() - ALERT_TTL)
    return [_alert(r) for r in rows]


def all_alerts(limit=300):
    return [_alert(r) for r in q(f"SELECT {ALERT_COLS} FROM lost_alerts ORDER BY id DESC LIMIT {int(limit)}")]


def user_alerts(uid):
    return [_alert(r) for r in q(f"SELECT {ALERT_COLS} FROM lost_alerts WHERE user_id=:u AND status<>'removed' ORDER BY id DESC LIMIT 20", u=uid)]


def alerts_near(lat, lng, county, limit=5):
    """Live alerts near a point (ALERT_NEAR_MILES) or, for alerts without a pin, in the same county."""
    out = []
    for a in live_alerts(200):
        d = miles(lat, lng, a["lat"], a["lng"])
        if (d is not None and d <= ALERT_NEAR_MILES) or (a["lat"] is None and county and a["area"] == county):
            out.append(a)
    return out[:limit]


def alert_recipients(a, runs):
    """Member ids to email about an alert: followers of runs within ALERT_NEAR_MILES of the last-seen spot, plus
    members whose profile area matches and (when the alert names a town) whose town matches. Opted-out members,
    the poster and anyone already at ALERT_MAILS_PER_DAY today are dropped. Capped at ALERT_MAX_RECIPIENTS."""
    near = [r["id"] for r in runs if a["lat"] is not None and (miles(a["lat"], a["lng"], r.get("lat"), r.get("lng")) or 99) <= ALERT_NEAR_MILES]
    if a["run_id"] and a["run_id"] not in near:
        near.append(a["run_id"])
    ids = set(followers(near))
    if a["area"]:
        rows = q("SELECT id, town FROM users WHERE area=:a", a=a["area"])
        # towns near the last-seen spot: the alert's own town plus the towns of nearby runs ("Roslyn / North Hills" -> both)
        idx = {r["id"]: r for r in runs}
        names = [a["town"]] + [idx[i].get("town_or_neighborhood") or "" for i in near if i in idx]
        towns = {key(p) for n in names for p in re.split(r"[/,]", n or "") if key(p)}
        ids |= {r[0] for r in rows if not towns or key(r[1]) in towns}
    ids.discard(a["user_id"])
    if not ids:
        return []
    ok = {r[0] for r in q("SELECT id FROM users WHERE alert_emails=1")}
    since = now() - 86400
    busy = {r[0] for r in q("SELECT user_id FROM alert_mail WHERE sent_at>:t GROUP BY user_id HAVING COUNT(*)>=:n", t=since, n=ALERT_MAILS_PER_DAY)}
    return sorted(i for i in ids if i in ok and i not in busy)[:ALERT_MAX_RECIPIENTS]


def claim_alert_mail(aid, uid):
    before = one("SELECT COUNT(*) FROM alert_mail WHERE alert_id=:a AND user_id=:u", a=aid, u=uid)[0]
    if before:
        return False
    q("INSERT INTO alert_mail(alert_id, user_id, sent_at) VALUES(:a,:u,:t) ON CONFLICT DO NOTHING", a=aid, u=uid, t=now())
    return True


# ---------------------------------------------------------------- recommendations
def _rec(r):
    return dict(id=r[0], category=r[1], name=r[2], town=r[3], area=r[4], contact=r[5], created_by=r[6], hidden=bool(r[7]),
                created_at=r[8], votes=r[9] if len(r) > 9 else 0)


REC_COLS = "r.id, r.category, r.name, r.town, r.area, r.contact, r.created_by, r.hidden, r.created_at"


def find_rec(category, name, town):
    r = one(f"SELECT {REC_COLS} FROM recs r WHERE category=:c AND name_key=:n AND town_key=:t", c=category, n=key(name), t=key(town))
    return _rec(r) if r else None


def rec(rid):
    r = one(f"SELECT {REC_COLS}, (SELECT COUNT(*) FROM rec_votes v WHERE v.rec_id=r.id) FROM recs r WHERE r.id=:i", i=rid)
    return _rec(r) if r else None


def add_rec(uid, category, name, town, area, contact, note):
    """Recommend a business. Creates it on first mention, else adds this member's vote. Returns (rec_id, created, voted)."""
    ex = find_rec(category, name, town)
    created = False
    if not ex:
        try:
            q("""INSERT INTO recs(category, name, name_key, town, town_key, area, contact, created_by, created_at)
                 VALUES(:c,:n,:nk,:t,:tk,:a,:co,:u,:ts)""", c=category, n=name, nk=key(name), t=town, tk=key(town), a=area, co=contact, u=uid, ts=now())
            created = True
        except Exception:
            pass
        ex = find_rec(category, name, town)
    elif contact and not ex["contact"]:
        q("UPDATE recs SET contact=:c WHERE id=:i", c=contact, i=ex["id"])
    voted = vote(ex["id"], uid, note)
    return ex["id"], created, voted


def vote(rid, uid, note=""):
    if one("SELECT 1 FROM rec_votes WHERE rec_id=:r AND user_id=:u", r=rid, u=uid):
        if note:
            q("UPDATE rec_votes SET note=:n WHERE rec_id=:r AND user_id=:u", n=note, r=rid, u=uid)
        return False
    q("INSERT INTO rec_votes(rec_id, user_id, note, created_at) VALUES(:r,:u,:n,:t) ON CONFLICT DO NOTHING", r=rid, u=uid, n=note, t=now())
    return True


def unvote(rid, uid):
    q("DELETE FROM rec_votes WHERE rec_id=:r AND user_id=:u", r=rid, u=uid)
    if not one("SELECT 1 FROM rec_votes WHERE rec_id=:r", r=rid):
        q("DELETE FROM rec_reports WHERE rec_id=:r", r=rid)
        q("DELETE FROM recs WHERE id=:r", r=rid)


def my_votes(uid):
    return {r[0] for r in q("SELECT rec_id FROM rec_votes WHERE user_id=:u", u=uid)} if uid else set()


def browse_recs(areas=None, category=None, include_hidden=False, limit=200):
    where, kw = ["1=1" if include_hidden else "r.hidden=0"], {}
    if category:
        where.append("r.category=:c"); kw["c"] = category
    if areas:
        where.append("r.area IN (%s)" % ",".join(f":a{i}" for i in range(len(areas)))); kw.update({f"a{i}": a for i, a in enumerate(areas)})
    rows = q(f"""SELECT {REC_COLS}, (SELECT COUNT(*) FROM rec_votes v WHERE v.rec_id=r.id) AS n FROM recs r WHERE {' AND '.join(where)}
                 ORDER BY n DESC, r.name LIMIT {int(limit)}""", **kw)
    return [_rec(r) for r in rows]


def rec_notes(rid, limit=6):
    rows = q(f"""SELECT v.note, u.display_name, v.created_at FROM rec_votes v JOIN users u ON u.id=v.user_id
                 WHERE v.rec_id=:r AND v.note<>'' ORDER BY v.created_at DESC LIMIT {int(limit)}""", r=rid)
    return [dict(note=r[0], name=r[1], at=r[2]) for r in rows]


def report_rec(rid, uid, reason, details):
    q("INSERT INTO rec_reports(rec_id, reporter_user_id, reason, details, created_at) VALUES(:r,:u,:re,:d,:t)",
      r=rid, u=uid, re=reason, d=details, t=now())


def rec_reports(status=None):
    rows = q("""SELECT p.id, p.rec_id, p.reason, p.details, p.status, p.created_at, r.name, r.category, r.town, r.hidden
                FROM rec_reports p LEFT JOIN recs r ON r.id=p.rec_id""" + (" WHERE p.status=:s" if status else "") + " ORDER BY p.id DESC LIMIT 300",
             **({"s": status} if status else {}))
    return [dict(id=r[0], rec_id=r[1], reason=r[2], details=r[3], status=r[4], at=r[5], name=r[6], category=r[7], town=r[8], hidden=r[9]) for r in rows]


def set_rec_hidden(rid, hidden):
    q("UPDATE recs SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=rid)


def delete_rec(rid):
    for t in ("rec_votes", "rec_reports"):
        q(f"DELETE FROM {t} WHERE rec_id=:r", r=rid)
    q("DELETE FROM recs WHERE id=:r", r=rid)


def set_report_status(pid, status):
    q("UPDATE rec_reports SET status=:s WHERE id=:i", s=status, i=pid)


# ---------------------------------------------------------------- care reminders (private)
def care_items(dog_id):
    rows = q("SELECT id, kind, label, due_date FROM dog_care WHERE dog_id=:d ORDER BY due_date, id", d=dog_id)
    return [dict(id=r[0], kind=r[1], label=r[2], due=r[3]) for r in rows]


def add_care(dog_id, kind, label, due):
    t = now()
    return one("INSERT INTO dog_care(dog_id, kind, label, due_date, created_at, updated_at) VALUES(:d,:k,:l,:due,:t,:t) RETURNING id",
               d=dog_id, k=kind, l=label, due=due, t=t)[0]


def update_care(dog_id, cid, due, label=None):
    if label is None:
        q("UPDATE dog_care SET due_date=:due, updated_at=:t WHERE id=:i AND dog_id=:d", due=due, t=now(), i=cid, d=dog_id)
    else:
        q("UPDATE dog_care SET due_date=:due, label=:l, updated_at=:t WHERE id=:i AND dog_id=:d", due=due, l=label, t=now(), i=cid, d=dog_id)


def delete_care(dog_id, cid):
    q("DELETE FROM care_sent WHERE care_id IN (SELECT id FROM dog_care WHERE id=:i AND dog_id=:d)", i=cid, d=dog_id)
    q("DELETE FROM dog_care WHERE id=:i AND dog_id=:d", i=cid, d=dog_id)


def care_label(item):
    if item["kind"] == "vaccine":
        return item["label"] or "Vaccine"
    return dict(CARE_KINDS).get(item["kind"], "Reminder")


def care_due(today=None):
    """[(care item + dog_id, lead)] where due date is exactly 30 or 7 days away (or the window was missed by <=2 days)."""
    today = today or today_et()
    out = []
    for cid, dog_id, kind, label, due in q("SELECT id, dog_id, kind, label, due_date FROM dog_care"):
        try:
            dd = date.fromisoformat(due)
        except ValueError:
            continue
        left = (dd - today).days
        for lead in CARE_LEADS:
            if lead - 2 <= left <= lead and not (lead == 30 and left <= 7):
                out.append((dict(id=cid, dog_id=dog_id, kind=kind, label=label, due=due, days=left), lead))
                break
    return out


def claim_care(cid, due, lead, uid):
    if one("SELECT 1 FROM care_sent WHERE care_id=:c AND due_date=:d AND lead_days=:l AND user_id=:u", c=cid, d=due, l=lead, u=uid):
        return False
    q("INSERT INTO care_sent(care_id, due_date, lead_days, user_id, sent_at) VALUES(:c,:d,:l,:u,:t) ON CONFLICT DO NOTHING",
      c=cid, d=due, l=lead, u=uid, t=now())
    return True


# ---------------------------------------------------------------- celebrations
def _md(s):
    try:
        d = date.fromisoformat(s)
        return d.month, d.day, d.year
    except (TypeError, ValueError):
        return None


def is_today(s, today):
    md = _md(s)
    if not md:
        return False
    m, d, y = md
    if y >= today.year:
        return False  # not a past date yet
    if (m, d) == (today.month, today.day):
        return True
    # Feb 29 dates are celebrated on Feb 28 in non-leap years
    leap = today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0)
    return (m, d) == (2, 29) and not leap and (today.month, today.day) == (2, 28)


def celebrating(today=None, areas=None, limit=24):
    """Dogs with a birthday or gotcha day today: [{dog fields..., kind: 'birthday'|'gotcha', years}]."""
    today = today or today_et()
    rows = q("""SELECT d.id, d.slug, d.name, d.birthday, d.gotcha_day, d.avatar_photo_id, d.user_id, u.area, u.town
                FROM dogs d JOIN users u ON u.id=d.user_id WHERE d.hidden=0 AND (d.birthday<>'' OR d.gotcha_day<>'')""")
    out = []
    for did, slug, name, bd, gd, av, uid, area, town in rows:
        if areas and area not in areas:
            continue
        for kind, s in (("birthday", bd), ("gotcha", gd)):
            if is_today(s, today):
                out.append(dict(id=did, slug=slug, name=name, kind=kind, years=today.year - _md(s)[2], avatar=av, user_id=uid, area=area, town=town))
    firsts = A.first_photos([x["id"] for x in out])
    for x in out:
        x["photo"] = x["avatar"] or firsts.get(x["id"])
    out.sort(key=lambda x: (x["photo"] is None, x["name"].lower()))
    return out[:limit]


def claim_celebration(dog_id, kind, day, uid):
    if one("SELECT 1 FROM celebrate_sent WHERE dog_id=:d AND kind=:k AND day=:y AND user_id=:u", d=dog_id, k=kind, y=day, u=uid):
        return False
    q("INSERT INTO celebrate_sent(dog_id, kind, day, user_id, sent_at) VALUES(:d,:k,:y,:u,:t) ON CONFLICT DO NOTHING",
      d=dog_id, k=kind, y=day, u=uid, t=now())
    return True


def claim_job(job, day):
    if one("SELECT 1 FROM job_runs WHERE job=:j AND day=:d", j=job, d=day):
        return False
    try:
        q("INSERT INTO job_runs(job, day, ran_at) VALUES(:j,:d,:t)", j=job, d=day, t=now())
        return True
    except Exception:
        return False


def owners_of(dog_id):
    """Primary owner and co-owners (user ids)."""
    r = one("SELECT user_id FROM dogs WHERE id=:d", d=dog_id)
    ids = [r[0]] if r else []
    try:
        ids += [x[0] for x in q("SELECT user_id FROM dog_owners WHERE dog_id=:d", d=dog_id) if x[0] not in ids]
    except Exception:
        pass
    return ids


# ---------------------------------------------------------------- cleanup
def purge_user(uid):
    """Account deletion: everything this member created in the community features."""
    q("DELETE FROM checkins WHERE user_id=:u", u=uid)
    q("DELETE FROM run_follows WHERE user_id=:u", u=uid)
    q("DELETE FROM park_roles WHERE user_id=:u", u=uid)
    q("UPDATE announcements SET user_id=NULL WHERE user_id=:u", u=uid)
    q("DELETE FROM alert_mail WHERE user_id=:u OR alert_id IN (SELECT id FROM lost_alerts WHERE user_id=:u)", u=uid)
    q("DELETE FROM lost_alerts WHERE user_id=:u", u=uid)
    for (rid,) in q("SELECT rec_id FROM rec_votes WHERE user_id=:u", u=uid):
        unvote(rid, uid)
    q("UPDATE recs SET created_by=NULL WHERE created_by=:u", u=uid)
    q("UPDATE rec_reports SET reporter_user_id=NULL WHERE reporter_user_id=:u", u=uid)
    q("DELETE FROM care_sent WHERE user_id=:u", u=uid)
    q("DELETE FROM celebrate_sent WHERE user_id=:u", u=uid)


def purge_dog(dog_id):
    q("DELETE FROM care_sent WHERE care_id IN (SELECT id FROM dog_care WHERE dog_id=:d)", d=dog_id)
    q("DELETE FROM dog_care WHERE dog_id=:d", d=dog_id)
    q("DELETE FROM celebrate_sent WHERE dog_id=:d", d=dog_id)
    q("UPDATE lost_alerts SET dog_id=NULL WHERE dog_id=:d", d=dog_id)
    for cid, dids in q("SELECT id, dog_ids FROM checkins WHERE left_at IS NULL"):
        ids = json.loads(dids or "[]")
        if dog_id in ids:
            q("UPDATE checkins SET dog_ids=:d WHERE id=:i", d=json.dumps([i for i in ids if i != dog_id]), i=cid)
