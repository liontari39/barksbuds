"""Pixel portraits: hand-made pixel-art portraits of members' dogs (Oct 2026, replacing the in-browser pixel maker).

An owner sends in one photo of their dog (a gallery photo, or a new upload stored as kind='request', which is never shown
publicly). That queues a portrait_requests row (status 'pending'). The BarksBuds team makes the portrait and uploads it
through the admin API: it's stored as a photos row with kind='portrait' (shown at /p/<id>, never removed through the
gallery) and becomes the dog's main picture unless the owner picked a different main picture after requesting.

One portrait per dog: while a request is pending or done no new one can be made. A rejected request (with a note shown
to the owner) frees the slot, and an admin reset deletes the request row (the portrait image itself is kept).
"""
import accounts as A

STATUSES = ("pending", "done", "rejected")
SEEDED_DONE = ("mike-lily", "mike-maggie")   # Lily and Maggie's portraits were made before the queue existed
COLS = ("id", "dog_id", "user_id", "photo_id", "status", "owner_note", "note", "avatar_at_request",
        "result_photo_id", "created_at", "completed_at")


class PortraitError(Exception):
    pass


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS portrait_requests(id {ID}, dog_id {INT} NOT NULL, user_id {INT} NOT NULL,
        photo_id {INT}, status TEXT NOT NULL DEFAULT 'pending', owner_note TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '', avatar_at_request {INT}, result_photo_id {INT},
        created_at {INT} NOT NULL, completed_at {INT})""")
    store.q("CREATE INDEX IF NOT EXISTS portrait_requests_dog ON portrait_requests(dog_id)")
    store.q("CREATE INDEX IF NOT EXISTS portrait_requests_status ON portrait_requests(status)")
    mark_seeded_done(store.q)


def _row(r):
    return dict(zip(COLS, r)) if r else None


def _sel(where, **kw):
    return [_row(r) for r in A.q(f"SELECT {','.join(COLS)} FROM portrait_requests {where}", **kw)]


def get(rid):
    rows = _sel("WHERE id=:i", i=rid)
    return rows[0] if rows else None


def latest(dog_id):
    """The dog's most recent request (any status), or None."""
    rows = _sel("WHERE dog_id=:d ORDER BY id DESC LIMIT 1", d=dog_id)
    return rows[0] if rows else None


def active(dog_id):
    """The pending or done request that holds the dog's one portrait slot, or None."""
    rows = _sel("WHERE dog_id=:d AND status IN ('pending','done') ORDER BY id DESC LIMIT 1", d=dog_id)
    return rows[0] if rows else None


def pending():
    return _sel("WHERE status='pending' ORDER BY id")


def recent(limit=200):
    return _sel("ORDER BY id DESC LIMIT :n", n=int(limit))


def done_portraits(limit=24):
    """[(dog dict, portrait photo id)] for the showcase: done portraits of visible dogs, oldest first."""
    out = []
    for r in A.q("""SELECT r.dog_id, r.result_photo_id FROM portrait_requests r JOIN dogs d ON d.id=r.dog_id
                    JOIN photos p ON p.id=r.result_photo_id
                    WHERE r.status='done' AND d.hidden=0 ORDER BY r.completed_at, r.id LIMIT :n""", n=int(limit)):
        d = A.dog_by_id(r[0])
        if d:
            out.append((d, r[1]))
    return out


def create(dog, user_id, photo_id=None, raw=None, owner_note=""):
    """Queue a request for `dog` with one of its gallery photos (photo_id) or a new upload (raw bytes). Returns the id."""
    if active(dog["id"]):
        raise PortraitError("taken")
    if raw:
        photo_id = A.add_photo(dog["id"], raw, kind="request")   # may raise A.BadImage
    elif photo_id:
        if not A.one("SELECT id FROM photos WHERE id=:p AND dog_id=:d AND kind='gallery'", p=int(photo_id), d=dog["id"]):
            raise PortraitError("photo")
    else:
        raise PortraitError("photo")
    r = A.one("""INSERT INTO portrait_requests(dog_id,user_id,photo_id,status,owner_note,avatar_at_request,created_at)
                 VALUES(:d,:u,:p,'pending',:n,:a,:t) RETURNING id""",
              d=dog["id"], u=user_id, p=int(photo_id), n=(owner_note or "")[:400], a=dog.get("avatar_photo_id"), t=A.now())
    return r[0]


def complete(rid, raw):
    """Store the finished portrait (raises A.BadImage) and mark the request done. Returns (request, made_main)."""
    req = get(rid)
    if not req or req["status"] != "pending":
        raise PortraitError("state")
    d = A.dog_by_id(req["dog_id"])
    if not d:
        raise PortraitError("dog")
    pid = A.add_photo(d["id"], raw, kind="portrait")
    cur = d.get("avatar_photo_id")
    made_main = cur == req["avatar_at_request"] or not cur
    if made_main:   # the owner didn't pick another main picture after requesting
        A.q("UPDATE dogs SET avatar_photo_id=:p, updated_at=:t WHERE id=:d", p=pid, t=A.now(), d=d["id"])
    A.q("UPDATE portrait_requests SET status='done', result_photo_id=:p, completed_at=:t WHERE id=:i", p=pid, t=A.now(), i=rid)
    return get(rid), made_main


def reject(rid, note):
    req = get(rid)
    if not req or req["status"] != "pending":
        raise PortraitError("state")
    A.q("UPDATE portrait_requests SET status='rejected', note=:n, completed_at=:t WHERE id=:i",
        n=(note or "").strip()[:400], t=A.now(), i=rid)
    return get(rid)


def reset(rid):
    """Admin reset: forget the request so the owner can send a new one. The portrait image, if any, is kept."""
    req = get(rid)
    if not req:
        raise PortraitError("state")
    A.q("DELETE FROM portrait_requests WHERE id=:i", i=rid)
    return req


def request_photo(rid):
    """(jpeg bytes, request) of the photo the owner sent in, for the admin download (works for hidden dogs too)."""
    req = get(rid)
    if not req:
        return None, None
    r = A.one("SELECT full_jpeg FROM photos WHERE id=:p AND dog_id=:d", p=req["photo_id"], d=req["dog_id"])
    return (bytes(r[0]) if r else None), req


def mark_seeded_done(qf=None):
    """Idempotent: record Lily and Maggie's existing AI portraits (their main pictures) as done requests, and make those
    images kind='portrait' so they're kept when the owner switches the main picture (A.set_avatar drops kind='avatar')."""
    qf = qf or A.q
    for key in SEEDED_DONE:
        rows = qf("SELECT id, user_id, avatar_photo_id FROM dogs WHERE seed_key=:k", k=key)
        if not rows or not rows[0][2]:
            continue
        dog_id, uid, av = rows[0]
        if qf("SELECT id FROM portrait_requests WHERE dog_id=:d LIMIT 1", d=dog_id):
            continue
        kind = qf("SELECT kind FROM photos WHERE id=:p AND dog_id=:d", p=av, d=dog_id)
        if not kind or kind[0][0] not in ("avatar", "portrait"):
            continue   # the main picture is a regular photo, not the portrait
        t = A.now()
        qf("UPDATE photos SET kind='portrait' WHERE id=:p", p=av)
        qf("""INSERT INTO portrait_requests(dog_id,user_id,photo_id,status,owner_note,note,avatar_at_request,result_photo_id,created_at,completed_at)
              VALUES(:d,:u,:p,'done','','Made before the request queue existed',:p,:p,:t,:t)""", d=dog_id, u=uid, p=av, t=t)
