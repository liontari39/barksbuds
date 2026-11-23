"""Live run safety: delayed, privacy-filtered presence, quiet hours, planned arrivals,
favorite-dog and crowd alerts, and matched small-pack suggestions.

Dogs are the face of this feature. Owners are never shown in presence lists, map badges,
or alerts. Wording never promises that a run is "safe" or a good fit.
"""
import json, threading, time
from collections import defaultdict
from datetime import datetime

import accounts as A
import community as C
import privacy as PV

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    from datetime import timezone
    ET = timezone.utc

DISPLAY_DELAY = 10 * 60
CACHE_TTL = 60
BUSY_AT = 3
QUIET_START_DEFAULT = 21 * 60  # 9:00 PM ET
QUIET_END_DEFAULT = 7 * 60     # 7:00 AM ET
PLANNED_HORIZON = 24 * 3600
QUIET_HORIZON = 7 * 86400
ARRIVE_ALERT_LEAD = 30 * 60
ALERTS_PER_KIND_HOUR = 4
STYLE_TAGS = ["Gentle", "Rough-and-tumble", "Ball-focused", "Shy", "Still learning"]
# Map both the new tags and existing play-style chips into the five mix buckets.
STYLE_BUCKETS = [
    ("Gentle", {"Gentle", "Gentle player"}),
    ("Rough-and-tumble", {"Rough-and-tumble", "Wrestler"}),
    ("Ball-focused", {"Ball-focused", "Fetcher", "Toy lover", "Chaser"}),
    ("Shy", {"Shy", "Watcher (likes to observe)"}),
    ("Still learning", {"Still learning"}),
]
ROUGH = {"Rough-and-tumble", "Wrestler"}
SOFT = {"Gentle", "Gentle player", "Shy", "Watcher (likes to observe)", "Still learning"}

q = C.q
one = C.one
now = C.now

_cache = {"at": 0, "raw": None}
_tick = {"at": 0, "lock": threading.Lock()}
AUTO_TICK = True


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS planned_arrivals(id {ID}, user_id {INT} NOT NULL, run_id TEXT NOT NULL,
            dog_ids TEXT NOT NULL DEFAULT '[]', arrives_at {INT} NOT NULL, created_at {INT} NOT NULL,
            cancelled_at {INT}, anon {INT} NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS planned_arrivals_run_idx ON planned_arrivals(run_id, arrives_at)",
        "CREATE INDEX IF NOT EXISTS planned_arrivals_user_idx ON planned_arrivals(user_id, arrives_at)",
        f"""CREATE TABLE IF NOT EXISTS run_quiet_windows(id {ID}, run_id TEXT NOT NULL, user_id {INT} NOT NULL,
            starts_at {INT} NOT NULL, ends_at {INT} NOT NULL, created_at {INT} NOT NULL, cancelled_at {INT})""",
        "CREATE INDEX IF NOT EXISTS run_quiet_windows_run_idx ON run_quiet_windows(run_id, starts_at)",
        f"""CREATE TABLE IF NOT EXISTS dog_favorites(user_id {INT} NOT NULL, dog_id {INT} NOT NULL,
            created_at {INT} NOT NULL, PRIMARY KEY (user_id, dog_id))""",
        "CREATE INDEX IF NOT EXISTS dog_favorites_dog_idx ON dog_favorites(dog_id)",
        f"""CREATE TABLE IF NOT EXISTS run_alert_prefs(user_id {INT} NOT NULL, run_id TEXT NOT NULL,
            crowd_threshold {INT} NOT NULL DEFAULT 0, planned_on {INT} NOT NULL DEFAULT 0,
            meetup_on {INT} NOT NULL DEFAULT 0, favorite_on {INT} NOT NULL DEFAULT 1,
            created_at {INT} NOT NULL, updated_at {INT} NOT NULL, PRIMARY KEY (user_id, run_id))""",
        "CREATE INDEX IF NOT EXISTS run_alert_prefs_run_idx ON run_alert_prefs(run_id)",
        f"""CREATE TABLE IF NOT EXISTS presence_alert_sent(id {ID}, kind TEXT NOT NULL, user_id {INT} NOT NULL,
            run_id TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', sent_at {INT} NOT NULL,
            UNIQUE(kind, user_id, run_id, subject))""",
        "CREATE INDEX IF NOT EXISTS presence_alert_sent_user_idx ON presence_alert_sent(user_id, sent_at)",
    ]:
        store.q(s)
    cols = lambda t: ({r[0] for r in store.q(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}'")} if pg
                      else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    dc = cols("dogs")
    if "checkin_alerts_ok" not in dc:
        store.q(f"ALTER TABLE dogs ADD COLUMN checkin_alerts_ok {INT} NOT NULL DEFAULT 0")
    uc = cols("users")
    if "alert_quiet_start" not in uc:
        store.q(f"ALTER TABLE users ADD COLUMN alert_quiet_start {INT}")
    if "alert_quiet_end" not in uc:
        store.q(f"ALTER TABLE users ADD COLUMN alert_quiet_end {INT}")


def purge_user(uid):
    q("DELETE FROM planned_arrivals WHERE user_id=:u", u=uid)
    q("DELETE FROM run_quiet_windows WHERE user_id=:u", u=uid)
    q("DELETE FROM dog_favorites WHERE user_id=:u", u=uid)
    q("DELETE FROM run_alert_prefs WHERE user_id=:u", u=uid)
    q("DELETE FROM presence_alert_sent WHERE user_id=:u", u=uid)


def purge_dog(dog_id):
    q("DELETE FROM dog_favorites WHERE dog_id=:d", d=dog_id)


def clear_cache():
    _cache["at"] = 0
    _cache["raw"] = None


def style_buckets(tags):
    tags = set(tags or [])
    return [label for label, group in STYLE_BUCKETS if tags & group]


def size_label(size):
    return A.SIZE_SHORT.get(size or "", "") or "Unspecified"


def _dog_rows(ids):
    ids = [int(i) for i in ids if str(i).isdigit()]
    if not ids:
        return {}
    rows = q(f"""SELECT id, slug, name, size, play_style, visibility, hidden, user_id, checkin_alerts_ok
                 FROM dogs WHERE id IN ({",".join(str(i) for i in ids)})""")
    out = {}
    for did, slug, name, size, styles, vis, hidden, uid, alerts_ok in rows:
        try:
            tags = json.loads(styles or "[]")
        except ValueError:
            tags = []
        out[did] = dict(id=did, slug=slug, name=name, size=size or "", styles=style_buckets(tags),
                        tags=tags, visibility=vis if vis in PV.VIS_KEYS else "public",
                        hidden=int(hidden or 0), user_id=uid, alerts_ok=int(alerts_ok or 0))
    return out


def _is_countable(dog, signed_in=False, blocks=None):
    if not dog or dog["hidden"]:
        return False
    if dog["user_id"] in (blocks or set()):
        return False
    vis = dog["visibility"]
    if vis == "public":
        return True
    if vis == "members":
        return bool(signed_in)
    return False


def visible_here(run_id=None, t=None, signed_in=False, blocks=None, include_own=None):
    """Visible dogs at one run or all runs, after the display delay and privacy filters.

    include_own: a user id whose own (non-anon, non-hidden) dogs appear immediately.
    """
    t = t or now()
    delay_cut = t - DISPLAY_DELAY
    params = dict(t=t, cut=delay_cut)
    run_sql = ""
    if run_id:
        run_sql = "AND c.run_id=:r"
        params["r"] = run_id
    own_sql = ""
    if include_own:
        own_sql = "OR (c.user_id=:own AND c.left_at IS NULL AND c.expires_at>:t AND c.anon=0 AND u.checkins_hidden=0)"
        params["own"] = include_own
    rows = q(f"""SELECT c.run_id, c.user_id, c.dog_ids, c.created_at FROM checkins c
                 JOIN users u ON u.id=c.user_id
                 WHERE c.left_at IS NULL AND c.expires_at>:t AND c.anon=0 AND u.checkins_hidden=0
                   AND (c.created_at<=:cut {own_sql}) {run_sql}""", **params)
    all_ids = []
    parsed = []
    for rid, uid, dids, since in rows:
        ids = json.loads(dids or "[]")
        parsed.append((rid, uid, ids, since))
        all_ids.extend(ids)
    dogs = _dog_rows(all_ids)
    out = []
    for rid, uid, ids, since in parsed:
        for did in ids:
            d = dogs.get(did)
            own = bool(include_own and uid == include_own)
            if not d or d["hidden"] or d["user_id"] in (blocks or set()):
                continue
            # Own dogs can appear on that run's page immediately, even if pack/private.
            # They still stay off the all-runs map (run_id is None).
            if not _is_countable(d, signed_in=signed_in or own, blocks=blocks):
                if not (own and run_id is not None):
                    continue
            item = dict(d, run_id=rid, since=since)
            out.append(item)
    return out


def visible_planned(run_id=None, t=None, signed_in=False, blocks=None):
    t = t or now()
    params = dict(t=t, until=t + PLANNED_HORIZON)
    run_sql = ""
    if run_id:
        run_sql = "AND p.run_id=:r"
        params["r"] = run_id
    rows = q(f"""SELECT p.id, p.run_id, p.user_id, p.dog_ids, p.arrives_at FROM planned_arrivals p
                 JOIN users u ON u.id=p.user_id
                 WHERE p.cancelled_at IS NULL AND p.anon=0 AND u.checkins_hidden=0
                   AND p.arrives_at>:t AND p.arrives_at<=:until {run_sql}
                 ORDER BY p.arrives_at""", **params)
    all_ids = []
    parsed = []
    for pid, rid, uid, dids, at in rows:
        ids = json.loads(dids or "[]")
        parsed.append((pid, rid, uid, ids, at))
        all_ids.extend(ids)
    dogs = _dog_rows(all_ids)
    out = []
    for pid, rid, uid, ids, at in parsed:
        vis = [dogs[i] for i in ids if _is_countable(dogs.get(i), signed_in=signed_in, blocks=blocks)]
        if not vis:
            continue
        out.append(dict(id=pid, run_id=rid, user_id=uid, arrives_at=at, n=len(vis), dogs=vis))
    return out


def _summarize(dogs, planned):
    """Build the public per-run payload (no owner or dog identities)."""
    runs = {}
    for d in dogs:
        slot = runs.setdefault(d["run_id"], {"n": 0, "sizes": {}, "styles": {}, "planned": []})
        slot["n"] += 1
        lab = size_label(d["size"])
        slot["sizes"][lab] = slot["sizes"].get(lab, 0) + 1
        for s in (d["styles"] or []):
            slot["styles"][s] = slot["styles"].get(s, 0) + 1
    for p in planned:
        slot = runs.setdefault(p["run_id"], {"n": 0, "sizes": {}, "styles": {}, "planned": []})
        slot["planned"].append({"at": p["arrives_at"], "label": time_label(p["arrives_at"]), "n": p["n"]})
    for slot in runs.values():
        slot["busy"] = slot["n"] >= BUSY_AT
    return runs


def time_label(ts):
    dt = datetime.fromtimestamp(int(ts), ET)
    hour = dt.strftime("%-I:%M %p").replace(" 0", " ")
    today = datetime.now(ET).date()
    if dt.date() == today:
        return hour + " ET"
    return dt.strftime("%a ") + hour + " ET"


def _raw_snapshot(t=None):
    t = t or now()
    if _cache["raw"] is not None and t - _cache["at"] < CACHE_TTL:
        return _cache["raw"]
    dogs = visible_here(t=t, signed_in=True, blocks=None)
    planned = visible_planned(t=t, signed_in=True, blocks=None)
    raw = dict(t=t, news=C.announcement_counts(), dogs=dogs, planned=planned)
    _cache["at"] = t
    _cache["raw"] = raw
    return raw


def live_payload(viewer=None, t=None):
    """JSON for /api/runs/live. here values are delayed, privacy-filtered counts.

    Members-only dogs are included only for a signed-in viewer. Blocked users' dogs
    are subtracted per request from the 60s server snapshot; they never appear in the
    client payload.
    """
    t = t or now()
    raw = _raw_snapshot(t)
    V = PV.viewer(viewer) if viewer is not None else PV.viewer(None)
    signed = bool(V.signed_in)
    blocks = V.blocks() if signed else set()
    dogs, planned = [], []
    for d in raw["dogs"]:
        if d["user_id"] in blocks:
            continue
        if d["visibility"] == "members" and not signed:
            continue
        if d["visibility"] not in ("public", "members"):
            continue
        dogs.append(d)
    for p in raw["planned"]:
        if p["user_id"] in blocks:
            continue
        vis_dogs = [x for x in p.get("dogs") or [] if _is_countable(x, signed_in=signed, blocks=blocks)]
        if not vis_dogs:
            continue
        planned.append(dict(p, n=len(vis_dogs), dogs=vis_dogs))
    summary = _summarize(dogs, planned)
    here = {rid: slot["n"] for rid, slot in summary.items() if slot["n"]}
    # Strip identities from the client payload.
    public_runs = {}
    for rid, slot in summary.items():
        public_runs[rid] = dict(n=slot["n"], busy=slot["busy"], sizes=slot["sizes"],
                                styles=slot["styles"], planned=slot["planned"])
    return {"here": here, "news": raw["news"], "runs": public_runs}


def here_list(run_id, V, t=None):
    """Dogs to show on a run page (tiles + mix). The viewer's own dogs appear immediately."""
    V = PV.viewer(V)
    uid = V.uid
    blocks = V.blocks() if uid else set()
    dogs = visible_here(run_id, t=t, signed_in=V.signed_in, blocks=blocks, include_own=uid)
    planned = visible_planned(run_id, t=t, signed_in=V.signed_in, blocks=blocks)
    mix = _summarize(dogs, planned).get(run_id) or {"n": 0, "busy": False, "sizes": {}, "styles": {}, "planned": []}
    return dogs, planned, mix


def quiet_windows(run_id, t=None):
    t = t or now()
    rows = q("""SELECT id, starts_at, ends_at FROM run_quiet_windows
                WHERE run_id=:r AND cancelled_at IS NULL AND ends_at>:t AND starts_at<:until
                ORDER BY starts_at""", r=run_id, t=t, until=t + QUIET_HORIZON)
    return [dict(id=r[0], starts_at=r[1], ends_at=r[2]) for r in rows]


def add_quiet_window(uid, run_id, starts_at, ends_at):
    starts_at, ends_at = int(starts_at), int(ends_at)
    if ends_at <= starts_at or starts_at < now() - 3600 or ends_at - starts_at > 8 * 3600:
        return None
    r = one("""INSERT INTO run_quiet_windows(run_id, user_id, starts_at, ends_at, created_at)
               VALUES(:r,:u,:s,:e,:t) RETURNING id""", r=run_id, u=uid, s=starts_at, e=ends_at, t=now())
    return r[0] if r else None


def cancel_quiet_window(uid, wid):
    q("UPDATE run_quiet_windows SET cancelled_at=:t WHERE id=:i AND user_id=:u AND cancelled_at IS NULL",
      t=now(), i=wid, u=uid)


def add_planned(uid, run_id, dog_ids, arrives_at, anon=False):
    arrives_at = int(arrives_at)
    if arrives_at < now() + 5 * 60 or arrives_at > now() + 7 * 86400:
        return None
    ids = [int(i) for i in dog_ids if str(i).isdigit()]
    if not ids:
        return None
    r = one("""INSERT INTO planned_arrivals(user_id, run_id, dog_ids, arrives_at, created_at, anon)
               VALUES(:u,:r,:d,:a,:t,:anon) RETURNING id""",
            u=uid, r=run_id, d=json.dumps(ids), a=arrives_at, t=now(), anon=1 if anon else 0)
    clear_cache()
    return r[0] if r else None


def cancel_planned(uid, pid):
    q("UPDATE planned_arrivals SET cancelled_at=:t WHERE id=:i AND user_id=:u AND cancelled_at IS NULL",
      t=now(), i=pid, u=uid)
    clear_cache()


def my_planned(uid, run_id, t=None):
    t = t or now()
    rows = q("""SELECT id, dog_ids, arrives_at FROM planned_arrivals
                WHERE user_id=:u AND run_id=:r AND cancelled_at IS NULL AND arrives_at>:t ORDER BY arrives_at""",
             u=uid, r=run_id, t=t)
    return [dict(id=r[0], dogs=json.loads(r[1] or "[]"), arrives_at=r[2]) for r in rows]


def favorite(uid, dog_id, on=True):
    if on:
        q("INSERT INTO dog_favorites(user_id, dog_id, created_at) VALUES(:u,:d,:t) ON CONFLICT DO NOTHING",
          u=uid, d=dog_id, t=now())
    else:
        q("DELETE FROM dog_favorites WHERE user_id=:u AND dog_id=:d", u=uid, d=dog_id)


def is_favorite(uid, dog_id):
    return bool(uid and one("SELECT 1 FROM dog_favorites WHERE user_id=:u AND dog_id=:d", u=uid, d=dog_id))


def favorite_ids(uid):
    return [r[0] for r in q("SELECT dog_id FROM dog_favorites WHERE user_id=:u", u=uid)] if uid else []


def favorite_dogs(uid):
    ids = favorite_ids(uid)
    if not ids:
        return []
    by = _dog_rows(ids)
    return [by[i] for i in ids if i in by and not by[i]["hidden"]]


def checkin_alerts_ok(dog_id):
    r = one("SELECT checkin_alerts_ok FROM dogs WHERE id=:i", i=dog_id)
    return bool(r and r[0])


def set_checkin_alerts_ok(dog_id, on):
    q("UPDATE dogs SET checkin_alerts_ok=:v, updated_at=:t WHERE id=:i", v=1 if on else 0, t=now(), i=dog_id)


def quiet_hours(uid):
    r = one("SELECT alert_quiet_start, alert_quiet_end FROM users WHERE id=:u", u=uid)
    start = QUIET_START_DEFAULT if not r or r[0] is None else int(r[0])
    end = QUIET_END_DEFAULT if not r or r[1] is None else int(r[1])
    return start, end


def set_quiet_hours(uid, start, end):
    start = max(0, min(23 * 60 + 59, int(start)))
    end = max(0, min(23 * 60 + 59, int(end)))
    q("UPDATE users SET alert_quiet_start=:s, alert_quiet_end=:e WHERE id=:u", s=start, e=end, u=uid)


def in_quiet_hours(uid, t=None):
    t = t or now()
    start, end = quiet_hours(uid)
    minutes = datetime.fromtimestamp(t, ET).hour * 60 + datetime.fromtimestamp(t, ET).minute
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # overnight, e.g. 21:00–07:00


def minutes_label(m):
    m = int(m)
    dt = datetime(2000, 1, 1, m // 60, m % 60)
    return dt.strftime("%-I:%M %p").lstrip()


def parse_minutes(s):
    s = (s or "").strip()
    try:
        hh, mm = s.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (TypeError, ValueError):
        pass
    return None


def alert_pref(uid, run_id):
    r = one("""SELECT crowd_threshold, planned_on, meetup_on, favorite_on FROM run_alert_prefs
               WHERE user_id=:u AND run_id=:r""", u=uid, r=run_id)
    if not r:
        return dict(crowd_threshold=0, planned_on=0, meetup_on=0, favorite_on=0, set=False)
    return dict(crowd_threshold=int(r[0] or 0), planned_on=int(r[1] or 0), meetup_on=int(r[2] or 0),
                favorite_on=int(r[3] or 0), set=True)


def save_alert_pref(uid, run_id, crowd_threshold=0, planned_on=0, meetup_on=0, favorite_on=0):
    t = now()
    crowd_threshold = max(0, min(20, int(crowd_threshold or 0)))
    q("""INSERT INTO run_alert_prefs(user_id, run_id, crowd_threshold, planned_on, meetup_on, favorite_on, created_at, updated_at)
         VALUES(:u,:r,:c,:p,:m,:f,:t,:t)
         ON CONFLICT (user_id, run_id) DO UPDATE SET crowd_threshold=:c, planned_on=:p, meetup_on=:m, favorite_on=:f, updated_at=:t""",
      u=uid, r=run_id, c=crowd_threshold, p=1 if planned_on else 0, m=1 if meetup_on else 0,
      f=1 if favorite_on else 0, t=t)


def user_alert_prefs(uid):
    rows = q("""SELECT run_id, crowd_threshold, planned_on, meetup_on, favorite_on FROM run_alert_prefs
                WHERE user_id=:u ORDER BY run_id""", u=uid)
    return [dict(run_id=r[0], crowd_threshold=int(r[1] or 0), planned_on=int(r[2] or 0),
                 meetup_on=int(r[3] or 0), favorite_on=int(r[4] or 0)) for r in rows]


def _size_band(size):
    if size in ("toy", "small"):
        return "small"
    if size in ("large", "giant"):
        return "large"
    if size == "medium":
        return "medium"
    return ""


def suggest_packs(dogs, limit=3):
    """Suggest 2–4 compatible dogs. Never claims the grouping is safe."""
    dogs = [d for d in dogs if d.get("name")]
    if len(dogs) < 2:
        return []
    used, out = set(), []
    # Prefer same size band; don't mix rough with shy/gentle/learning.
    groups = defaultdict(list)
    for d in dogs:
        rough = bool(set(d.get("styles") or []) & ROUGH) or bool(set(d.get("tags") or []) & ROUGH)
        soft = bool(set(d.get("styles") or []) & SOFT) or bool(set(d.get("tags") or []) & SOFT)
        tone = "rough" if rough and not soft else ("soft" if soft else "open")
        groups[(_size_band(d.get("size")), tone)].append(d)
    for (band, tone), members in groups.items():
        leftover = [m for m in members if m["id"] not in used]
        while len(leftover) >= 2 and len(out) < limit:
            chunk = leftover[:4]
            leftover = leftover[4:]
            if len(chunk) < 2:
                break
            for m in chunk:
                used.add(m["id"])
            if band and tone == "soft":
                why = "similar size and a gentle or shy play style"
            elif band and tone == "rough":
                why = "similar size and a more energetic play style"
            elif band:
                why = "similar size"
            else:
                why = "similar play style"
            out.append(dict(dogs=chunk, why=why))
    return out


# ---------------------------------------------------------------- alerts
def _rate_ok(uid, kind, t=None):
    t = t or now()
    n = one("SELECT COUNT(*) FROM presence_alert_sent WHERE user_id=:u AND kind=:k AND sent_at>:s",
            u=uid, k=kind, s=t - 3600)[0]
    return n < ALERTS_PER_KIND_HOUR


def _claim_alert(kind, uid, run_id, subject, t=None):
    t = t or now()
    try:
        one("""INSERT INTO presence_alert_sent(kind, user_id, run_id, subject, sent_at)
               VALUES(:k,:u,:r,:s,:t) RETURNING id""", k=kind, u=uid, r=run_id or "", s=str(subject), t=t)
        return True
    except Exception:
        return False


def _notify(uid, title, body, href):
    import push
    push.notify_async(uid, "checkins", title, body, href)


def run_href(run_id):
    import runpageweb
    r = __import__("webapp", fromlist=["run_index"]).run_index().get(run_id) if False else None
    try:
        import webapp as W
        r = W.run_index().get(run_id)
        return runpageweb.run_path(r) if r else f"/runs/{run_id}"
    except Exception:
        return f"/runs/{run_id}"


def _run_name(run_id):
    try:
        import webapp as W
        r = W.run_index().get(run_id)
        return (r or {}).get("name") or "a dog run"
    except Exception:
        return "a dog run"


def flush_alerts(base="", t=None):
    """Send due presence alerts. Favorite-dog alerts fire only when the dog's owner opted in."""
    t = t or now()
    clear_cache()
    signed_dogs = visible_here(t=t, signed_in=True)
    by_run = defaultdict(list)
    for d in signed_dogs:
        by_run[d["run_id"]].append(d)

    # Favorite dog checked in (after the delay). Opt-in is per dog, default off.
    fav_ok = [d for d in signed_dogs if d.get("alerts_ok")]
    if fav_ok:
        ids = [d["id"] for d in fav_ok]
        rows = q(f"SELECT user_id, dog_id FROM dog_favorites WHERE dog_id IN ({','.join(str(i) for i in ids)})")
        watchers = defaultdict(list)
        for uid, did in rows:
            watchers[did].append(uid)
        for d in fav_ok:
            for uid in watchers.get(d["id"], []):
                if uid == d["user_id"]:
                    continue
                V = PV.viewer(uid)
                if d["user_id"] in V.blocks():
                    continue
                prefs = user_alert_prefs(uid)
                # If the member picked runs for favorite alerts, only those runs fire.
                fav_runs = [p["run_id"] for p in prefs if p["favorite_on"]]
                if fav_runs and d["run_id"] not in fav_runs:
                    continue
                if in_quiet_hours(uid, t) or not _rate_ok(uid, "favorite", t):
                    continue
                subject = f"{d['id']}:{d['since']}"
                if not _claim_alert("favorite", uid, d["run_id"], subject, t):
                    continue
                name = _run_name(d["run_id"])
                _notify(uid, "A favorite dog is at the run",
                        f"{d['name']} checked in at {name}. This is just a heads-up, not a promise of a good match.",
                        run_href(d["run_id"]))

    # N+ dogs at a chosen run now
    for uid, run_id, thresh in q("SELECT user_id, run_id, crowd_threshold FROM run_alert_prefs WHERE crowd_threshold>=1"):
        n = len(by_run.get(run_id, []))
        # Recompute with this viewer's blocks and membership.
        V = PV.viewer(uid)
        n = len([d for d in by_run.get(run_id, []) if d["user_id"] not in V.blocks()
                 and (d["visibility"] == "public" or (d["visibility"] == "members" and V.signed_in))])
        if n < thresh:
            continue
        if in_quiet_hours(uid, t) or not _rate_ok(uid, "crowd", t):
            continue
        # One alert per "episode": subject is the threshold until the count drops (row stays).
        # Use an episode key based on a 2-hour bucket so it can fire again later in the day.
        subject = f"{thresh}:{t // (2 * 3600)}"
        if not _claim_alert("crowd", uid, run_id, subject, t):
            continue
        name = _run_name(run_id)
        _notify(uid, f"{n} dogs at {name}",
                f"{n} dogs are checked in at {name} right now. This is a count, not a promise the run is a good fit.",
                run_href(run_id))

    # Planned arrivals
    for uid, run_id in q("SELECT user_id, run_id FROM run_alert_prefs WHERE planned_on=1"):
        if in_quiet_hours(uid, t) or not _rate_ok(uid, "planned", t):
            continue
        V = PV.viewer(uid)
        upcoming = visible_planned(run_id, t=t, signed_in=True, blocks=V.blocks())
        due = [p for p in upcoming if p["arrives_at"] - ARRIVE_ALERT_LEAD <= t <= p["arrives_at"]]
        if not due:
            continue
        n = sum(p["n"] for p in due)
        # Dedup by the earliest arrival id in this window.
        subject = ",".join(str(p["id"]) for p in due)
        if not _claim_alert("planned", uid, run_id, subject, t):
            continue
        name = _run_name(run_id)
        when = time_label(min(p["arrives_at"] for p in due))
        _notify(uid, f"Dogs planning to visit {name}",
                f"{n} dog{'s' if n != 1 else ''} plan to be at {name} around {when}.",
                run_href(run_id))

    # Upcoming meetups at chosen runs (skip people already RSVP'd — they get meetup reminders)
    try:
        for uid, run_id in q("SELECT user_id, run_id FROM run_alert_prefs WHERE meetup_on=1"):
            if in_quiet_hours(uid, t) or not _rate_ok(uid, "meetup", t):
                continue
            meets = A.q("""SELECT id, title, starts_at FROM meetups
                           WHERE run_id=:r AND hidden=0 AND status='active'
                             AND COALESCE(visibility,'public')!='private'
                             AND starts_at>:t AND starts_at<=:until""",
                        r=run_id, t=t, until=t + 12 * 3600)
            for mid, title, starts in meets:
                if A.one("SELECT 1 FROM rsvps WHERE meetup_id=:m AND user_id=:u", m=mid, u=uid):
                    continue
                if not _claim_alert("meetup", uid, run_id, str(mid), t):
                    continue
                name = _run_name(run_id)
                _notify(uid, f"Meetup later at {name}",
                        f"{title} is coming up at {name} around {time_label(starts)}.",
                        f"/meetups/{mid}")
    except Exception as ex:
        print(f"runsafety: meetup alerts skipped ({type(ex).__name__})", flush=True)


def tick(base=""):
    if not AUTO_TICK:
        return
    t = time.time()
    if t - _tick["at"] < 60:
        return
    with _tick["lock"]:
        if t - _tick["at"] < 60:
            return
        _tick["at"] = t

    def go():
        try:
            flush_alerts(base)
        except Exception as ex:
            print(f"runsafety: flush failed ({type(ex).__name__})", flush=True)
    threading.Thread(target=go, daemon=True).start()
