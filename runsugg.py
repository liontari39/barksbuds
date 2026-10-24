"""BarksBuds member-suggested dog runs: suggestions, the moderation queue and approved runs merged into the map.

Members suggest a new run (or an edit / wrong-pin report for an existing one) from /runs/suggest. Each suggestion waits
in run_suggestions (status pending -> approved | rejected) until an admin reviews it at /admin/runs. Approving writes a
row to member_runs: kind 'new' (a whole run record, id "m-<suggestion id>") or kind 'edit' (field overrides for an
existing run id, merged over the static dataset; "_hidden" removes a closed run from the map). server.load_runs()
merges member_runs over data-seed/dog_runs_region.json, so /api/runs, /runs, meetups and packs all see the same list.
"""
import json, math
from datetime import datetime

import accounts as A

DAILY_LIMIT = 5                 # suggestions per member per rolling 24 hours
DUP_METERS = 150                # "is it one of these?" warning radius
MAX_NAME, MAX_NOTES, MAX_SHORT = 80, 1000, 120
COVERAGE = ("Manhattan", "Brooklyn", "Bronx", "Queens", "Staten Island", "Nassau", "Suffolk", "Westchester")
AREAS = [(a, A.AREA_LABEL.get(a, a + (" County" if a == "Westchester" else ""))) for a in COVERAGE] + [("other", "Somewhere else in the US")]
AREA_LABEL = dict(AREAS)
YNU = [("yes", "Yes"), ("no", "No"), ("unsure", "Not sure")]
SURFACES = [("", "Not sure"), ("grass", "Grass"), ("gravel", "Gravel"), ("wood chips", "Wood chips"), ("turf", "Artificial turf"),
            ("dirt", "Dirt"), ("pavement", "Pavement"), ("sand", "Sand"), ("mixed", "Mixed")]
EDIT_REASONS = [("pin", "The map pin is in the wrong spot"), ("details", "Some details are wrong or missing"),
                ("closed", "It's closed or no longer a dog run"), ("other", "Something else")]
EDIT_LABEL = dict(EDIT_REASONS)
US_STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
             "PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP").split()
FIELDS = ("name", "park", "address", "town", "county", "state", "lat", "lng", "fenced", "small_dog_area", "water", "surface",
          "hours", "notes", "source_url")
# NYC + Long Island (to Montauk) + Westchester, generously boxed. Pins outside get flagged, not refused.
COVER_BOX = (40.47, 41.37, -74.27, -71.80)
# Lower 48, Alaska, Hawaii, Puerto Rico + USVI, Guam/NMI, American Samoa: anything else isn't a US location.
US_BOXES = [(24.3, 49.5, -125.0, -66.8), (51.0, 71.6, -180.0, -129.9), (18.8, 22.4, -160.4, -154.7),
            (17.6, 18.6, -67.4, -64.5), (13.2, 20.6, 144.5, 146.1), (-14.6, -11.0, -171.2, -168.1)]
CHANGED = []                    # callbacks run after the approved set changes (server clears its /api/runs cache)

S_COLS = "id,kind,run_id,user_id,reason,data,in_coverage,dup_of,photo_w,status,reject_reason,reviewed_at,created_at"


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
        f"""CREATE TABLE IF NOT EXISTS run_suggestions(id {ID}, kind TEXT NOT NULL DEFAULT 'new', run_id TEXT NOT NULL DEFAULT '',
            user_id {INT} NOT NULL, reason TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{{}}',
            in_coverage {INT} NOT NULL DEFAULT 1, dup_of TEXT NOT NULL DEFAULT '', photo_full {BLOB}, photo_thumb {BLOB},
            photo_w {INT} NOT NULL DEFAULT 0, photo_h {INT} NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
            reject_reason TEXT NOT NULL DEFAULT '', reviewed_at {INT}, ip_hash TEXT NOT NULL DEFAULT '', created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS run_suggestions_status_idx ON run_suggestions(status, id)",
        "CREATE INDEX IF NOT EXISTS run_suggestions_user_idx ON run_suggestions(user_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS member_runs(run_id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'new', data TEXT NOT NULL,
            suggestion_id {INT}, updated_at {INT} NOT NULL)""",
    ]:
        store.q(s)


def changed():
    for fn in CHANGED:
        fn()


# ---------------------------------------------------------------- geometry + validation helpers
def meters(a_lat, a_lng, b_lat, b_lng):
    R, t = 6371000.0, math.pi / 180
    dla, dlo = (b_lat - a_lat) * t, (b_lng - a_lng) * t
    h = math.sin(dla / 2) ** 2 + math.cos(a_lat * t) * math.cos(b_lat * t) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def in_box(lat, lng, b):
    return b[0] <= lat <= b[1] and b[2] <= lng <= b[3]


def in_us(lat, lng):
    return any(in_box(lat, lng, b) for b in US_BOXES)


def in_coverage(county, lat, lng):
    """Inside NYC / Long Island / Westchester: the picked area is one of ours and the pin (if any) is in our box."""
    if county not in COVERAGE:
        return False
    return lat is None or in_box(lat, lng, COVER_BOX)


def near(lat, lng, runs, radius=DUP_METERS, exclude=""):
    """Runs (and still-pending suggestions) with a pin within `radius` meters, nearest first: [(name, id, meters)]."""
    out = []
    for r in runs:
        if r.get("id") != exclude and isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lng"), (int, float)):
            d = meters(lat, lng, r["lat"], r["lng"])
            if d <= radius:
                out.append((r.get("name") or "A dog run", r.get("id"), round(d)))
    for s in pending():
        d0 = s["data"]
        if s["kind"] == "new" and isinstance(d0.get("lat"), (int, float)):
            d = meters(lat, lng, d0["lat"], d0["lng"])
            if d <= radius:
                out.append((d0.get("name") or "A suggested run", f"suggestion {s['id']}", round(d)))
    return sorted(out, key=lambda x: x[2])


def same_name(name, runs):
    n = " ".join(name.lower().replace("dog run", "").replace("dog park", "").split())
    return [r for r in runs if n and len(n) > 4 and " ".join((r.get("name") or "").lower().replace("dog run", "")
                                                          .replace("dog park", "").split()) == n]


# ---------------------------------------------------------------- suggestions
def _s(r):
    d = dict(zip(S_COLS.split(","), r))
    d["data"] = json.loads(d["data"] or "{}")
    d["has_photo"] = bool(d.pop("photo_w"))
    return d


def recent_count(uid, window=86400):
    return one("SELECT COUNT(*) FROM run_suggestions WHERE user_id=:u AND created_at>:t", u=uid, t=A.now() - window)[0]


def create(uid, kind, data, run_id="", reason="", coverage=True, dup_of="", photo=None, ip_hash=""):
    full, thumb, w, h = photo or (None, None, 0, 0)
    return one(f"""INSERT INTO run_suggestions(kind,run_id,user_id,reason,data,in_coverage,dup_of,photo_full,photo_thumb,photo_w,photo_h,
                   status,ip_hash,created_at) VALUES(:k,:r,:u,:re,:d,:c,:dup,:pf,:pt,:w,:h,'pending',:ip,:t) RETURNING id""",
               k=kind, r=run_id, u=uid, re=reason, d=json.dumps(data, ensure_ascii=False), c=1 if coverage else 0, dup=dup_of,
               pf=full, pt=thumb, w=w, h=h, ip=ip_hash, t=A.now())[0]


def get(sid):
    r = one(f"SELECT {S_COLS} FROM run_suggestions WHERE id=:i", i=sid)
    return _s(r) if r else None


def pending():
    return [_s(r) for r in q(f"SELECT {S_COLS} FROM run_suggestions WHERE status='pending' ORDER BY id")]


def reviewed(limit=50):
    return [_s(r) for r in q(f"SELECT {S_COLS} FROM run_suggestions WHERE status<>'pending' ORDER BY reviewed_at DESC, id DESC LIMIT {int(limit)}")]


def for_user(uid, limit=10):
    return [_s(r) for r in q(f"SELECT {S_COLS} FROM run_suggestions WHERE user_id=:u ORDER BY id DESC LIMIT {int(limit)}", u=uid)]


def photo(sid, thumb=False):
    r = one(f"SELECT {'photo_thumb' if thumb else 'photo_full'} FROM run_suggestions WHERE id=:i", i=sid)
    return bytes(r[0]) if r and r[0] is not None else None


def reject(sid, why):
    q("UPDATE run_suggestions SET status='rejected', reject_reason=:w, reviewed_at=:t WHERE id=:i AND status='pending'",
      w=why, t=A.now(), i=sid)


def today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def county_label(v):
    """What a new run shows as its county: the borough/county, or 'City, ST' style for runs outside our area."""
    if v.get("county") in COVERAGE:
        return v["county"]
    return v.get("state") or "Elsewhere"


def approve_new(s, v, precision, credit_name):
    """v: the admin-reviewed fields. Returns the new run id."""
    rid = f"m-{s['id']}"
    has_ll = isinstance(v.get("lat"), (int, float))
    run = {"id": rid, "name": v["name"], "park": v.get("park") or "", "town_or_neighborhood": v.get("town") or "",
           "county": county_label(v), "type": "Fenced dog run" if v.get("fenced") == "yes" else "Dog run", "operator": "",
           "address": v.get("address") or "", "lat": v["lat"] if has_ll else None, "lng": v["lng"] if has_ll else None,
           "coord_source": ("Location confirmed by BarksBuds" if precision == "exact" else "Pin placed by a BarksBuds member") if has_ll else "",
           "fenced": v.get("fenced") if v.get("fenced") in ("yes", "no") else "",
           "small_dog_area": v.get("small_dog_area") if v.get("small_dog_area") in ("yes", "no") else "", "small_dog_weight_limit": "",
           "water": v.get("water") if v.get("water") in ("yes", "no") else "", "shade": "", "surface": v.get("surface") or "",
           "seating": "", "residency_permit_rules": "", "fees": "", "hours": v.get("hours") or "", "notes": v.get("notes") or "",
           "source_url": v.get("source_url") or "", "source_url_2": "", "last_checked": today(),
           "pin_precision": precision if has_ll else "", "member_suggested": True}
    if credit_name:
        run["added_by"] = credit_name
    if s["has_photo"]:
        run["photo"] = f"/runs/photo/{s['id']}.jpg"
    q("INSERT INTO member_runs(run_id,kind,data,suggestion_id,updated_at) VALUES(:r,'new',:d,:s,:t)",
      r=rid, d=json.dumps(run, ensure_ascii=False), s=s["id"], t=A.now())
    q("UPDATE run_suggestions SET status='approved', reviewed_at=:t, run_id=:r WHERE id=:i", t=A.now(), r=rid, i=s["id"])
    changed()
    return rid


EDITABLE = ("name", "park", "address", "town_or_neighborhood", "lat", "lng", "fenced", "small_dog_area", "water", "surface",
            "hours", "notes", "source_url", "pin_precision", "coord_source")


def approve_edit(s, changes, credit_name="", hide=False):
    """changes: {run field: new value} chosen by the admin. Merged over any earlier approved edits of the same run."""
    rid = s["run_id"]
    row = one("SELECT kind, data FROM member_runs WHERE run_id=:r", r=rid)
    if row and row[0] == "new":      # editing a member-added run: update the record itself
        d = json.loads(row[1]); d.update(changes)
        if credit_name and not d.get("added_by"):
            d["added_by"] = credit_name
        d["last_checked"] = today()
        if hide:
            d["_hidden"] = True
        q("UPDATE member_runs SET data=:d, updated_at=:t WHERE run_id=:r", d=json.dumps(d, ensure_ascii=False), t=A.now(), r=rid)
    else:
        d = json.loads(row[1]) if row else {}
        d.update(changes)
        if credit_name:
            d["edited_by"] = credit_name
        d["last_checked"] = today()
        if hide:
            d["_hidden"] = True
        if row:
            q("UPDATE member_runs SET data=:d, updated_at=:t WHERE run_id=:r", d=json.dumps(d, ensure_ascii=False), t=A.now(), r=rid)
        else:
            q("INSERT INTO member_runs(run_id,kind,data,suggestion_id,updated_at) VALUES(:r,'edit',:d,:s,:t)",
              r=rid, d=json.dumps(d, ensure_ascii=False), s=s["id"], t=A.now())
    q("UPDATE run_suggestions SET status='approved', reviewed_at=:t WHERE id=:i", t=A.now(), i=s["id"])
    changed()


def member_runs():
    return [dict(run_id=r[0], kind=r[1], data=json.loads(r[2]), suggestion_id=r[3], updated_at=r[4])
            for r in q("SELECT run_id,kind,data,suggestion_id,updated_at FROM member_runs ORDER BY updated_at DESC")]


def remove(run_id):
    """Undo an approval: drop a member-added run, or revert all approved edits to a listed run."""
    q("DELETE FROM member_runs WHERE run_id=:r", r=run_id)
    changed()


def merge(static):
    """Static dataset + approved member runs/edits -> the list the map uses."""
    try:
        rows = member_runs()
    except Exception as e:  # never take the map down over this table
        print("member runs unavailable:", type(e).__name__, flush=True)
        return list(static)
    over = {m["run_id"]: m["data"] for m in rows if m["kind"] == "edit"}
    new = sorted((m["data"] for m in rows if m["kind"] == "new" and not m["data"].get("_hidden")),
                 key=lambda d: int(d["id"][2:]) if d["id"][2:].isdigit() else 0)
    out = []
    for r in static:
        o = over.get(r["id"])
        if o:
            if o.get("_hidden"):
                continue
            r = dict(r); r.update({k: v for k, v in o.items() if not k.startswith("_")})
        out.append(r)
    return out + new
