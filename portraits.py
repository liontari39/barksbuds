"""Pixel portraits: hand-made pixel-art portraits of members' dogs (Oct 2026, replacing the in-browser pixel maker).

An owner sends in 1 to 3 reference photos of their dog (any mix of gallery photos and new uploads; uploads are stored as
kind='request' and never shown publicly). The photos are listed in portrait_request_photos (request_id, n = 1..3, photo_id);
portrait_requests.photo_id stays the first one (older requests had only that column and are backfilled). That queues a portrait_requests row (status 'pending'). The BarksBuds team makes the portrait and uploads it
through the admin API: it's stored as a photos row with kind='portrait' (shown at /p/<id>, never removed through the
gallery) and becomes the dog's main picture unless the owner picked a different main picture after requesting.

One portrait per dog: while a request is pending or done no new one can be made. A rejected request (with a note shown
to the owner) frees the slot, and an admin reset deletes the request row (the portrait image itself is kept).
"""
import accounts as A

STATUSES = ("pending", "done", "rejected")
MAX_PHOTOS = 3
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
    store.q(f"""CREATE TABLE IF NOT EXISTS portrait_request_photos(request_id {INT} NOT NULL, n {INT} NOT NULL,
        photo_id {INT} NOT NULL, PRIMARY KEY(request_id, n))""")
    _backfill(store.q)
    mark_seeded_done(store.q)


def _backfill(qf):
    """Idempotent migration: a request made before multi-photo requests gets its single photo_id as photo 1."""
    qf("""INSERT INTO portrait_request_photos(request_id, n, photo_id)
          SELECT r.id, 1, r.photo_id FROM portrait_requests r WHERE r.photo_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM portrait_request_photos x WHERE x.request_id=r.id)""")


def _row(r):
    return dict(zip(COLS, r)) if r else None


def photo_ids(rid):
    """The request's reference photo ids in order (photo 1 first)."""
    ids = [r[0] for r in A.q("SELECT photo_id FROM portrait_request_photos WHERE request_id=:i ORDER BY n", i=rid)]
    if not ids:
        r = A.one("SELECT photo_id FROM portrait_requests WHERE id=:i", i=rid)
        ids = [r[0]] if r and r[0] else []
    return ids


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


def create(dog, user_id, photo_ids=(), raws=(), owner_note="", photo_id=None, raw=None):
    """Queue a request for `dog` with 1 to MAX_PHOTOS reference photos: its gallery photos (photo_ids, in order) and/or
    new uploads (raws, bytes; stored as kind='request'). Returns the id. Raises PortraitError "taken" (the dog already
    has a pending or done request), "photo" (none, or not one of the dog's gallery photos) or "many" (more than 3), or
    A.BadImage for an unreadable upload (nothing is saved then). photo_id/raw: single-photo shorthand."""
    if active(dog["id"]):
        raise PortraitError("taken")
    ids = []
    for p in list(photo_ids or ()) + ([photo_id] if photo_id else []):
        p = int(p)
        if p not in ids:
            ids.append(p)
    raws = [x for x in list(raws or ()) + ([raw] if raw else []) if x]
    if not ids and not raws:
        raise PortraitError("photo")
    if len(ids) + len(raws) > MAX_PHOTOS:
        raise PortraitError("many")
    for p in ids:
        if not A.one("SELECT id FROM photos WHERE id=:p AND dog_id=:d AND kind='gallery'", p=p, d=dog["id"]):
            raise PortraitError("photo")
    added = []
    try:
        for x in raws:
            added.append(A.add_photo(dog["id"], x, kind="request"))   # may raise A.BadImage
    except Exception:
        for p in added:   # all or nothing
            A.q("DELETE FROM photos WHERE id=:p AND kind='request'", p=p)
        raise
    all_ids = ids + added
    r = A.one("""INSERT INTO portrait_requests(dog_id,user_id,photo_id,status,owner_note,avatar_at_request,created_at)
                 VALUES(:d,:u,:p,'pending',:n,:a,:t) RETURNING id""",
              d=dog["id"], u=user_id, p=all_ids[0], n=(owner_note or "")[:400], a=dog.get("avatar_photo_id"), t=A.now())
    for n, p in enumerate(all_ids, 1):
        A.q("INSERT INTO portrait_request_photos(request_id,n,photo_id) VALUES(:i,:n,:p)", i=r[0], n=n, p=p)
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
    A.q("DELETE FROM portrait_request_photos WHERE request_id=:i", i=rid)
    A.q("DELETE FROM portrait_requests WHERE id=:i", i=rid)
    return req


def request_photo(rid, n=1):
    """(jpeg bytes, request) of reference photo n (1-based) the owner sent in, for the admin download (works for hidden
    dogs too). (None, req) when there's no such photo."""
    req = get(rid)
    if not req:
        return None, None
    ids = photo_ids(rid)
    if not 1 <= n <= len(ids):
        return None, req
    r = A.one("SELECT full_jpeg FROM photos WHERE id=:p AND dog_id=:d", p=ids[n - 1], d=req["dog_id"])
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
        _backfill(qf)
