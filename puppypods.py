"""Puppy Pods: small groups of puppies under 16 weeks for home or backyard playdates.

Never at dog runs. Joining is gated on owner-entered vaccine status (first DHPP and
an age-appropriate attestation). Location stays coarse until a member joins.
"""
from datetime import date

import accounts as A
import community as C
import messages as MS

q = A.q
one = A.one
now = A.now

MAX_AGE_WEEKS = 16
MIN_CAP, MAX_CAP = 3, 5
CREATE_PER_DAY_NEW, CREATE_PER_DAY = 1, 3
JOIN_PER_DAY_NEW, JOIN_PER_DAY = 2, 8
SIZE_ORDER = [k for k, _ in A.SIZES]
REPORT_REASONS = ("Spam or not a real pod", "Safety concern", "Meeting at a dog run",
                  "Names a person without consent", "Something else")
BANNER = "Puppy Pods are for home or backyard playdates only — never at a dog run."
VET_NOTE = "This is a socialization guide, not medical advice. Talk to your vet about what's right for your puppy."

# Weekly socialization checklist. Informal, not a medical protocol.
CHECKLIST = (
    (8, "Week 8–9", (
        "Short, calm visits with one gentle, vaccinated dog in a quiet yard",
        "New household sounds at a comfortable volume",
        "A few new people, one at a time, with a way to step back",
    )),
    (10, "Week 10–11", (
        "New surfaces: grass, a patio, a towel, a low step",
        "A slightly longer backyard visit, still with close supervision",
        "Car rides or a short walk in a stroller or arms, away from dog runs",
    )),
    (12, "Week 12–13", (
        "A small, matched group in a backyard or home",
        "Gentle play, with breaks before anyone gets overwhelmed",
        "Handling paws, ears and collar for a few seconds at a time",
    )),
    (14, "Week 14–15", (
        "A little more playtime with the same familiar puppies",
        "New, calm places that are not dog runs: a friend's yard or a quiet path",
        "Practice coming when called and settling on a mat after play",
    )),
)


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS puppy_pods(id {ID}, host_user_id {INT} NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', area TEXT NOT NULL, town TEXT NOT NULL,
            place TEXT NOT NULL DEFAULT '', size_band TEXT NOT NULL DEFAULT '',
            capacity {INT} NOT NULL DEFAULT 4, hidden {INT} NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active', created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS puppy_pods_area_idx ON puppy_pods(area, status, created_at)",
        "CREATE INDEX IF NOT EXISTS puppy_pods_host_idx ON puppy_pods(host_user_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS puppy_pod_members(id {ID}, pod_id {INT} NOT NULL, user_id {INT} NOT NULL,
            dog_id {INT} NOT NULL, dhpp_first {INT} NOT NULL DEFAULT 0, vaccines_age_ok {INT} NOT NULL DEFAULT 0,
            attested_at {INT}, role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'active',
            created_at {INT} NOT NULL, UNIQUE(pod_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS puppy_pod_members_user_idx ON puppy_pod_members(user_id, status)",
        f"""CREATE TABLE IF NOT EXISTS puppy_pod_checks(id {ID}, pod_id {INT} NOT NULL, user_id {INT} NOT NULL,
            week {INT} NOT NULL, item_key TEXT NOT NULL, done_at {INT} NOT NULL,
            UNIQUE(pod_id, user_id, week, item_key))""",
        f"""CREATE TABLE IF NOT EXISTS puppy_pod_reports(id {ID}, pod_id {INT} NOT NULL, reporter_user_id {INT},
            reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
            created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS puppy_pod_reports_pod_idx ON puppy_pod_reports(pod_id, status)",
    ]:
        store.q(s)


def purge_user(uid):
    q("UPDATE puppy_pod_reports SET reporter_user_id=NULL WHERE reporter_user_id=:u", u=uid)
    ids = [r[0] for r in q("SELECT id FROM puppy_pods WHERE host_user_id=:u", u=uid)]
    for pid in ids:
        _delete_pod(pid)
    q("DELETE FROM puppy_pod_checks WHERE user_id=:u", u=uid)
    q("DELETE FROM puppy_pod_members WHERE user_id=:u", u=uid)


def purge_dog(dog_id):
    q("DELETE FROM puppy_pod_members WHERE dog_id=:d", d=dog_id)


def _delete_pod(pid):
    q("DELETE FROM puppy_pod_reports WHERE pod_id=:p", p=pid)
    q("DELETE FROM puppy_pod_checks WHERE pod_id=:p", p=pid)
    q("DELETE FROM puppy_pod_members WHERE pod_id=:p", p=pid)
    q("DELETE FROM puppy_pods WHERE id=:p", p=pid)


def age_weeks(dog, today=None):
    today = today or date.today()
    b = (dog.get("birthday") or "").strip()
    if not b:
        return None
    try:
        born = date.fromisoformat(b)
    except ValueError:
        return None
    days = (today - born).days
    if days < 0:
        return None
    return days // 7


def is_puppy(dog, today=None):
    w = age_weeks(dog, today)
    return w is not None and w < MAX_AGE_WEEKS


def size_compatible(a, b):
    if not a or not b:
        return True
    try:
        return abs(SIZE_ORDER.index(a) - SIZE_ORDER.index(b)) <= 1
    except ValueError:
        return True


def _pod(r):
    if not r:
        return None
    return dict(id=r[0], host_user_id=r[1], title=r[2], description=r[3] or "", area=r[4], town=r[5] or "",
                place=r[6] or "", size_band=r[7] or "", capacity=int(r[8] or 4), hidden=int(r[9] or 0),
                status=r[10] or "active", created_at=r[11])


POD_COLS = "id, host_user_id, title, description, area, town, place, size_band, capacity, hidden, status, created_at"


def get(pid):
    return _pod(one(f"SELECT {POD_COLS} FROM puppy_pods WHERE id=:i", i=pid))


def set_hidden(pid, hidden=True):
    q("UPDATE puppy_pods SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=pid)


def cancel(pid, uid):
    p = get(pid)
    if not p or p["host_user_id"] != uid:
        return False
    q("UPDATE puppy_pods SET status='cancelled' WHERE id=:i", i=pid)
    return True


def member_rows(pid, active_only=True):
    extra = " AND m.status='active'" if active_only else ""
    rows = q(f"""SELECT m.user_id, m.dog_id, m.dhpp_first, m.vaccines_age_ok, m.role, m.status, m.created_at,
                        u.display_name, d.name, d.slug, d.size, d.birthday, d.hidden, d.visibility
                 FROM puppy_pod_members m
                 JOIN users u ON u.id=m.user_id
                 JOIN dogs d ON d.id=m.dog_id
                 WHERE m.pod_id=:p{extra} ORDER BY CASE WHEN m.role='host' THEN 0 ELSE 1 END, m.id""", p=pid)
    out = []
    for r in rows:
        dog = dict(id=r[1], name=r[8], slug=r[9], size=r[10], birthday=r[11] or "", hidden=int(r[12] or 0),
                   visibility=r[13] or "public")
        out.append(dict(user_id=r[0], dog_id=r[1], dhpp_first=int(r[2] or 0), vaccines_age_ok=int(r[3] or 0),
                        role=r[4], status=r[5], created_at=r[6], display_name=r[7] or "", dog=dog,
                        weeks=age_weeks(dog)))
    return out


def member_of(pid, uid):
    r = one("SELECT 1 FROM puppy_pod_members WHERE pod_id=:p AND user_id=:u AND status='active'", p=pid, u=uid)
    return bool(r)


def member_count(pid):
    r = one("SELECT COUNT(*) FROM puppy_pod_members WHERE pod_id=:p AND status='active'", p=pid)
    return int(r[0] if r else 0)


def eligible_puppies(uid):
    """Owner or co-owner puppies under 16 weeks with a birthday."""
    return [d for d in A.dogs_for_user(uid) if is_puppy(d)]


def _caps(uid):
    new = A.is_new_account(uid)
    return (CREATE_PER_DAY_NEW if new else CREATE_PER_DAY, JOIN_PER_DAY_NEW if new else JOIN_PER_DAY)


def create_pod(uid, dog_id, title, area, town, place, description, capacity, dhpp_first, vaccines_age_ok):
    """Returns (pod_id, None) or (None, 'reason')."""
    if area not in A.AREA_NAMES:
        return None, "area"
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        return None, "capacity"
    if capacity < MIN_CAP or capacity > MAX_CAP:
        return None, "capacity"
    title = (title or "").strip()[:80]
    if not title:
        return None, "title"
    town = (town or "").strip()[:80]
    if not town:
        return None, "town"
    if not dhpp_first or not vaccines_age_ok:
        return None, "vaccine"
    dog = _owned_dog(uid, dog_id)
    if not dog or not is_puppy(dog):
        return None, "puppy"
    create_cap, _ = _caps(uid)
    if one("SELECT COUNT(*) FROM puppy_pods WHERE host_user_id=:u AND created_at>:s",
           u=uid, s=now() - 86400)[0] >= create_cap:
        return None, "limit"
    place = (place or "").strip()[:200]
    description = (description or "").strip()[:600]
    t = now()
    r = one("""INSERT INTO puppy_pods(host_user_id, title, description, area, town, place, size_band,
              capacity, created_at) VALUES(:h,:ti,:de,:ar,:tw,:pl,:sz,:ca,:t) RETURNING id""",
            h=uid, ti=title, de=description, ar=area, tw=town, pl=place, sz=dog.get("size") or "",
            ca=capacity, t=t)
    pid = r[0]
    q("""INSERT INTO puppy_pod_members(pod_id, user_id, dog_id, dhpp_first, vaccines_age_ok, attested_at,
         role, status, created_at) VALUES(:p,:u,:d,1,1,:t,'host','active',:t)""",
      p=pid, u=uid, d=dog_id, t=t)
    return pid, None


def _owned_dog(uid, dog_id):
    if not dog_id:
        return None
    try:
        dog_id = int(dog_id)
    except (TypeError, ValueError):
        return None
    return next((d for d in A.dogs_for_user(uid) if d["id"] == dog_id), None)


def join(uid, pid, dog_id, dhpp_first, vaccines_age_ok):
    p = get(pid)
    if not p or p["hidden"] or p["status"] != "active":
        return "missing"
    if p["host_user_id"] == uid or member_of(pid, uid):
        return "already"
    if MS.either_blocked(uid, p["host_user_id"]):
        return "blocked"
    for m in member_rows(pid):
        if MS.either_blocked(uid, m["user_id"]):
            return "blocked"
    if member_count(pid) >= p["capacity"]:
        return "full"
    if not dhpp_first or not vaccines_age_ok:
        return "vaccine"
    dog = _owned_dog(uid, dog_id)
    if not dog or not is_puppy(dog):
        return "puppy"
    if p["size_band"] and not size_compatible(p["size_band"], dog.get("size") or ""):
        return "size"
    _, join_cap = _caps(uid)
    if one("SELECT COUNT(*) FROM puppy_pod_members WHERE user_id=:u AND created_at>:s AND role!='host'",
           u=uid, s=now() - 86400)[0] >= join_cap:
        return "limit"
    prior = one("SELECT id, status FROM puppy_pod_members WHERE pod_id=:p AND user_id=:u", p=pid, u=uid)
    t = now()
    if prior:
        q("""UPDATE puppy_pod_members SET dog_id=:d, dhpp_first=1, vaccines_age_ok=1, attested_at=:t,
             status='active', created_at=:t WHERE id=:i""", d=dog_id, t=t, i=prior[0])
    else:
        q("""INSERT INTO puppy_pod_members(pod_id, user_id, dog_id, dhpp_first, vaccines_age_ok, attested_at,
             role, status, created_at) VALUES(:p,:u,:d,1,1,:t,'member','active',:t)""",
          p=pid, u=uid, d=dog_id, t=t)
    return "ok"


def leave(uid, pid):
    p = get(pid)
    if not p:
        return "missing"
    if p["host_user_id"] == uid:
        cancel(pid, uid)
        return "cancelled"
    if not member_of(pid, uid):
        return "missing"
    q("UPDATE puppy_pod_members SET status='left' WHERE pod_id=:p AND user_id=:u", p=pid, u=uid)
    return "ok"


def list_pods(uid, area=None, size=None):
    """Active, visible pods the viewer is allowed to see, newest first."""
    rows = q(f"SELECT {POD_COLS} FROM puppy_pods WHERE hidden=0 AND status='active' ORDER BY created_at DESC LIMIT 200")
    out = []
    for r in rows:
        p = _pod(r)
        if area and p["area"] != area:
            continue
        if size and p["size_band"] and not size_compatible(p["size_band"], size):
            continue
        if MS.either_blocked(uid, p["host_user_id"]):
            continue
        members = member_rows(p["id"])
        if any(MS.either_blocked(uid, m["user_id"]) for m in members):
            continue
        p["n"] = len(members)
        p["members"] = members
        p["mine"] = any(m["user_id"] == uid for m in members)
        out.append(p)
    return out


def suggestions(uid):
    pups = eligible_puppies(uid)
    if not pups:
        return []
    seen = set()
    out = []
    for d in pups:
        for p in list_pods(uid, size=d.get("size")):
            if p["id"] in seen or p["mine"] or p["n"] >= p["capacity"]:
                continue
            # age overlap: at least one member within 4 weeks
            w = age_weeks(d)
            if w is not None and p["members"]:
                if not any(m["weeks"] is not None and abs(m["weeks"] - w) <= 4 for m in p["members"]):
                    continue
            seen.add(p["id"])
            p = dict(p, match_dog=d)
            out.append(p)
    return out


def add_report(pid, uid, reason, details=""):
    p = get(pid)
    if not p or p["hidden"]:
        return None
    if reason not in REPORT_REASONS:
        reason = "Something else"
    if one("SELECT id FROM puppy_pod_reports WHERE pod_id=:p AND reporter_user_id=:u AND status='open'",
           p=pid, u=uid):
        return "already"
    r = one("""INSERT INTO puppy_pod_reports(pod_id, reporter_user_id, reason, details, created_at)
               VALUES(:p,:u,:r,:d,:t) RETURNING id""",
            p=pid, u=uid, r=reason, d=(details or "").strip()[:1000], t=now())
    return r[0] if r else None


def list_reports(limit=300):
    rows = q("""SELECT r.id, r.pod_id, r.reporter_user_id, r.reason, r.details, r.status, r.created_at,
                       p.title, p.hidden, p.host_user_id, p.status
                FROM puppy_pod_reports r JOIN puppy_pods p ON p.id=r.pod_id
                ORDER BY r.created_at DESC LIMIT :n""", n=int(limit))
    out = []
    for r in rows:
        reporter = C.user_row(r[2]) if r[2] else None
        out.append(dict(id=r[0], pod_id=r[1], reporter_user_id=r[2], reason=r[3], details=r[4] or "",
                        status=r[5], created_at=r[6], title=r[7] or "", hidden=int(r[8] or 0),
                        host_user_id=r[9], pod_status=r[10],
                        reporter_name=(reporter or {}).get("name") or ""))
    return out


def set_report_status(rid, status):
    if status in ("open", "resolved"):
        q("UPDATE puppy_pod_reports SET status=:s WHERE id=:i", s=status, i=rid)


def checks_of(pid, uid):
    return {(r[0], r[1]) for r in q("SELECT week, item_key FROM puppy_pod_checks WHERE pod_id=:p AND user_id=:u",
                                    p=pid, u=uid)}


def set_check(pid, uid, week, item_key, on=True):
    if not member_of(pid, uid):
        return False
    week = int(week)
    item_key = (item_key or "").strip()[:80]
    if not any(item_key == it for w, _, items in CHECKLIST if week == w for it in items):
        return False
    if on:
        q("""INSERT INTO puppy_pod_checks(pod_id, user_id, week, item_key, done_at)
             VALUES(:p,:u,:w,:k,:t) ON CONFLICT DO NOTHING""", p=pid, u=uid, w=week, k=item_key, t=now())
    else:
        q("DELETE FROM puppy_pod_checks WHERE pod_id=:p AND user_id=:u AND week=:w AND item_key=:k",
          p=pid, u=uid, w=week, k=item_key)
    return True


def public_loc(p):
    town = (p.get("town") or "").strip()
    area = A.AREA_LABEL.get(p["area"], p["area"]) if p.get("area") else ""
    return " · ".join(x for x in (town, area) if x)
