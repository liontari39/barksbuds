"""Helpers for Puppy Pods as a kind of pack (packs.kind='puppy').

Puppy packs are home or backyard playdates for puppies under 16 weeks. Joining is
gated on a first-DHPP plus age-appropriate vaccine attestation. Exact place is
hidden until a member joins. The weekly checklist is not medical advice.
"""
from datetime import date

import accounts as A
import messages as MS
import packs as P

MAX_AGE_WEEKS = 16
MIN_CAP, MAX_CAP = 3, 5
CREATE_PER_DAY_NEW, CREATE_PER_DAY = 1, 3
JOIN_PER_DAY_NEW, JOIN_PER_DAY = 2, 8
SIZE_ORDER = [k for k, _ in A.SIZES]
BANNER = "Puppy packs are for home or backyard playdates only — never at a dog run."
VET_NOTE = "This is a socialization guide, not medical advice. Talk to your vet about what's right for your puppy."
GRAD_COPY = ("All the puppies in this pack are now 16 weeks or older. Graduate to a regular pack? "
             "Members, the board and meetup history stay. You can add a home run after.")

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


def is_puppy_pack(p):
    return bool(p) and (p.get("kind") or "regular") == "puppy"


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


def eligible_puppies(uid):
    return [d for d in A.dogs_for_user(uid) if is_puppy(d) and not d.get("hidden")]


def _caps(uid):
    new = A.is_new_account(uid)
    return (CREATE_PER_DAY_NEW if new else CREATE_PER_DAY, JOIN_PER_DAY_NEW if new else JOIN_PER_DAY)


def create_count_today(uid):
    return A.one("SELECT COUNT(*) FROM packs WHERE owner_user_id=:u AND kind='puppy' AND created_at>:s",
                 u=uid, s=A.now() - 86400)[0]


def join_count_today(uid):
    return A.one("""SELECT COUNT(*) FROM pack_members m JOIN packs p ON p.id=m.pack_id
                    WHERE m.user_id=:u AND m.role<>'owner' AND p.kind='puppy' AND m.created_at>:s""",
                 u=uid, s=A.now() - 86400)[0]


def at_create_limit(uid):
    cap, _ = _caps(uid)
    return create_count_today(uid) >= cap


def at_join_limit(uid):
    _, cap = _caps(uid)
    return join_count_today(uid) >= cap


def hidden_from(p, uid):
    """True if this member is blocked with the host or an active member."""
    if not p or not uid:
        return False
    if MS.either_blocked(uid, p["owner_user_id"]):
        return True
    for mid in P.member_ids(p["id"]):
        if mid != uid and MS.either_blocked(uid, mid):
            return True
    return False


def puppy_count(pid):
    return len(listed_dogs(pid))


def listed_dogs(pid):
    """Every dog currently listed on an active membership, including hidden profiles."""
    import json
    out, ids = [], []
    for dj, in P.q("SELECT dogs FROM pack_members WHERE pack_id=:p AND status='active'", p=pid):
        try:
            ids.extend(int(x) for x in json.loads(dj or "[]") if str(x).isdigit())
        except ValueError:
            pass
    for did in ids:
        d = A.dog_by_id(did)
        if d:
            out.append(d)
    return out


def can_graduate(p):
    if not is_puppy_pack(p):
        return False
    dogs = listed_dogs(p["id"])
    if not dogs:
        return False
    weeks = [age_weeks(d) for d in dogs]
    return all(w is not None and w >= MAX_AGE_WEEKS for w in weeks)


def graduate(pid, uid):
    p = P.get(pid)
    if not p or p["owner_user_id"] != uid or not can_graduate(p):
        return False
    P.q("UPDATE packs SET kind='regular', updated_at=:t WHERE id=:i", t=A.now(), i=pid)
    return True


def checks_of(pid, uid):
    return {(r[0], r[1]) for r in P.q("SELECT week, item_key FROM puppy_pack_checks WHERE pack_id=:p AND user_id=:u",
                                      p=pid, u=uid)}


def set_check(pid, uid, week, item_key, on=True):
    if not P.is_member(pid, uid):
        return False
    week = int(week)
    item_key = (item_key or "").strip()[:80]
    if not any(item_key == it for w, _, items in CHECKLIST if week == w for it in items):
        return False
    if on:
        P.q("""INSERT INTO puppy_pack_checks(pack_id, user_id, week, item_key, done_at)
               VALUES(:p,:u,:w,:k,:t) ON CONFLICT DO NOTHING""", p=pid, u=uid, w=week, k=item_key, t=A.now())
    else:
        P.q("DELETE FROM puppy_pack_checks WHERE pack_id=:p AND user_id=:u AND week=:w AND item_key=:k",
            p=pid, u=uid, w=week, k=item_key)
    return True


def set_attestation(pid, uid, ok=True):
    P.q("""UPDATE pack_members SET dhpp_first=:a, vaccines_age_ok=:b, attested_at=:t, updated_at=:t
           WHERE pack_id=:p AND user_id=:u""", a=1 if ok else 0, b=1 if ok else 0, t=A.now(), p=pid, u=uid)


def size_band(dogs):
    sizes = [d.get("size") for d in dogs if d.get("size")]
    return sizes[0] if sizes else ""


def join_ok(p, uid, dogs, dhpp_first, vaccines_age_ok):
    """Validate a puppy-pack join. Returns None if ok, or an error key."""
    if not is_puppy_pack(p):
        return None
    if hidden_from(p, uid):
        return "blocked"
    if not dhpp_first or not vaccines_age_ok:
        return "vaccine"
    pups = [d for d in dogs if is_puppy(d)]
    if not pups:
        return "puppy"
    if p.get("capacity") and puppy_count(p["id"]) + len(pups) > int(p["capacity"]):
        cur = P.membership(p["id"], uid)
        if not (cur and cur["status"] == "active"):
            return "full"
    band = p.get("fit")  # not the size band; we store size on first puppy via packs... use members
    # size: compare incoming puppies to existing pack dogs
    existing = listed_dogs(p["id"])
    if existing:
        ref = existing[0].get("size") or ""
        if any(not size_compatible(ref, d.get("size") or "") for d in pups):
            return "size"
    if at_join_limit(uid) and not (P.membership(p["id"], uid) and P.membership(p["id"], uid)["status"] == "active"):
        return "limit"
    return None


def suggestions(uid):
    pups = eligible_puppies(uid)
    if not pups:
        return []
    seen, out = set(), []
    packs = P.browse(kind="puppy")
    for d in pups:
        for p in packs:
            if p["id"] in seen or P.is_member(p["id"], uid) or hidden_from(p, uid):
                continue
            if p.get("capacity") and p.get("ndogs", 0) >= p["capacity"]:
                continue
            existing = listed_dogs(p["id"])
            if existing:
                if any(not size_compatible(d.get("size") or "", x.get("size") or "") for x in existing[:1]):
                    continue
                w = age_weeks(d)
                ages = [age_weeks(x) for x in existing]
                if w is not None and ages and not any(a is not None and abs(a - w) <= 4 for a in ages):
                    continue
            seen.add(p["id"])
            out.append(dict(p, match_dog=d))
    return out


def init_schema(store=None):
    """Kind, place, capacity, attestations and checks are created in packs.init_schema."""
    return


def purge_user(uid):
    P.q("DELETE FROM puppy_pack_checks WHERE user_id=:u", u=uid)


def purge_dog(dog_id):
    return
