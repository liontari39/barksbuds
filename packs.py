"""BarksBuds packs: data layer (packs, memberships with dogs, the pack board, cover/post photos).

A pack is a standing group of members and their dogs, usually around one home dog run. Roles per membership:
owner (the creator, exactly one), organizer (co-organizers) and member. Owners and organizers approve join
requests, edit the pack, remove members and pin posts. Visibility "open" means anyone can join right away;
"request" means an organizer approves each request. Sample packs (is_sample=1) are labeled, send no email and
can be hidden or deleted from /admin/packs with the other samples.
"""
import hashlib, hmac, json

import accounts as A

VISIBILITY = [("open", "Open: anyone can join"), ("request", "Request to join: an organizer approves each member")]
FITS = [("all", "All dogs welcome"), ("small", "Small dogs"), ("big", "Big dogs"), ("puppies", "Puppies"), ("seniors", "Senior dogs")]
FIT_LABEL = dict(FITS)
ROLE_LABEL = {"owner": "Organizer", "organizer": "Co-organizer", "member": "Member"}
MAX_NAME, MAX_DESC, MAX_POST, MAX_COMMENT, MAX_MSG = 60, 2000, 2000, 1000, 300
MAX_PACKS_PER_USER = 10        # packs a member can create
MAX_POST_PHOTOS_PER_PACK = 500

P_COLS = ("id,slug,name,area,town,run_id,description,fit,visibility,cover_photo_id,owner_user_id,is_sample,hidden,"
          "seed_key,seed_rev,created_at,updated_at")


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
        f"""CREATE TABLE IF NOT EXISTS packs(id {ID}, slug TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
            area TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', run_id TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '', fit TEXT NOT NULL DEFAULT '', visibility TEXT NOT NULL DEFAULT 'open',
            cover_photo_id {INT}, owner_user_id {INT} NOT NULL, is_sample {INT} NOT NULL DEFAULT 0,
            hidden {INT} NOT NULL DEFAULT 0, seed_key TEXT UNIQUE, seed_rev {INT} NOT NULL DEFAULT 0,
            created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS packs_area_idx ON packs(area)",
        f"""CREATE TABLE IF NOT EXISTS pack_members(id {ID}, pack_id {INT} NOT NULL, user_id {INT} NOT NULL,
            role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'active', dogs TEXT NOT NULL DEFAULT '[]',
            message TEXT NOT NULL DEFAULT '', created_at {INT} NOT NULL, updated_at {INT} NOT NULL, UNIQUE(pack_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS pack_members_user_idx ON pack_members(user_id)",
        f"""CREATE TABLE IF NOT EXISTS pack_photos(id {ID}, pack_id {INT} NOT NULL, kind TEXT NOT NULL DEFAULT 'cover',
            width {INT} NOT NULL, height {INT} NOT NULL, full_jpeg {BLOB} NOT NULL, thumb_webp {BLOB} NOT NULL,
            bytes {INT} NOT NULL, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS pack_photos_pack_idx ON pack_photos(pack_id)",
        f"""CREATE TABLE IF NOT EXISTS pack_posts(id {ID}, pack_id {INT} NOT NULL, user_id {INT} NOT NULL, body TEXT NOT NULL DEFAULT '',
            photo_id {INT}, pinned {INT} NOT NULL DEFAULT 0, hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS pack_posts_idx ON pack_posts(pack_id, id)",
        f"""CREATE TABLE IF NOT EXISTS pack_comments(id {ID}, post_id {INT} NOT NULL, pack_id {INT} NOT NULL, user_id {INT} NOT NULL,
            body TEXT NOT NULL, hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS pack_comments_idx ON pack_comments(post_id, id)",
    ]:
        store.q(s)

    def cols(t):
        return ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=t)} if pg
                else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    if "pack_emails" not in cols("users"):
        store.q(f"ALTER TABLE users ADD COLUMN pack_emails {INT} NOT NULL DEFAULT 1")
    rc = cols("reports")
    for c in ("pack_id", "post_id", "pack_comment_id"):
        if c not in rc:
            store.q(f"ALTER TABLE reports ADD COLUMN {c} {INT}")
    mc = cols("meetups")
    if "pack_id" not in mc:
        store.q(f"ALTER TABLE meetups ADD COLUMN pack_id {INT}")
    if "members_only" not in mc:
        store.q(f"ALTER TABLE meetups ADD COLUMN members_only {INT} NOT NULL DEFAULT 0")
    if "seed_rev" not in mc:
        store.q(f"ALTER TABLE meetups ADD COLUMN seed_rev {INT} NOT NULL DEFAULT 0")


# ---------------------------------------------------------------- packs
def _p(r):
    return dict(zip(P_COLS.split(","), r)) if r else None


def get(pid):
    return _p(one(f"SELECT {P_COLS} FROM packs WHERE id=:i", i=pid))


def save(owner_id, f, pid=None, seed_key=None, is_sample=0):
    """Create (owner becomes the first member, with the dogs in f['dogs']) or update a pack. Returns the id."""
    t = A.now()
    vals = dict(n=f["name"], sl=A.slugify(f["name"], 60), ar=f["area"], tw=f["town"], ru=f["run_id"], de=f["description"],
                fi=f["fit"], vi=f["visibility"], t=t)
    if pid:
        q("""UPDATE packs SET name=:n, slug=:sl, area=:ar, town=:tw, run_id=:ru, description=:de, fit=:fi, visibility=:vi,
             updated_at=:t WHERE id=:i""", i=pid, **vals)
        return pid
    r = one("""INSERT INTO packs(name,slug,area,town,run_id,description,fit,visibility,owner_user_id,is_sample,seed_key,created_at,updated_at)
               VALUES(:n,:sl,:ar,:tw,:ru,:de,:fi,:vi,:o,:sa,:sk,:t,:t) RETURNING id""",
            o=owner_id, sa=1 if is_sample else 0, sk=seed_key, **vals)
    q("""INSERT INTO pack_members(pack_id,user_id,role,status,dogs,created_at,updated_at) VALUES(:p,:u,'owner','active',:d,:t,:t)""",
      p=r[0], u=owner_id, d=json.dumps(f.get("dogs") or []), t=t)
    return r[0]


def created_by(uid):
    return one("SELECT COUNT(*) FROM packs WHERE owner_user_id=:u", u=uid)[0]


def set_hidden(pid, hidden):
    q("UPDATE packs SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=pid)


def delete(pid):
    """Delete a pack with its members, board and photos. Its meetups stay, detached from the pack."""
    q("UPDATE meetups SET pack_id=NULL, members_only=0 WHERE pack_id=:p", p=pid)
    q("DELETE FROM pack_comments WHERE pack_id=:p", p=pid)
    q("DELETE FROM pack_posts WHERE pack_id=:p", p=pid)
    q("DELETE FROM pack_photos WHERE pack_id=:p", p=pid)
    q("DELETE FROM pack_members WHERE pack_id=:p", p=pid)
    q("DELETE FROM reports WHERE pack_id=:p", p=pid)
    q("DELETE FROM packs WHERE id=:p", p=pid)


def member_counts(ids=None):
    """{pack_id: (members, dogs)} for active memberships."""
    out = {}
    for pid, dj in q("SELECT pack_id, dogs FROM pack_members WHERE status='active'"):
        if ids is not None and pid not in ids:
            continue
        m, d = out.get(pid, (0, 0))
        out[pid] = (m + 1, d + len(_dogs(dj)))
    return out


def browse(areas=None, north_shore=False, run_id=None, include_hidden=False):
    rows = [_p(r) for r in q(f"SELECT {P_COLS} FROM packs ORDER BY is_sample DESC, created_at DESC, id DESC")]
    out = []
    for p in rows:
        if p["hidden"] and not include_hidden:
            continue
        if areas and p["area"] not in areas:
            continue
        if north_shore and not is_north_shore(p):
            continue
        if run_id and p["run_id"] != run_id:
            continue
        out.append(p)
    counts = member_counts({p["id"] for p in out})
    for p in out:
        p["members"], p["ndogs"] = counts.get(p["id"], (0, 0))
    return out


def is_north_shore(p):
    import meetups as M
    hay = " ".join([p.get("town") or "", p.get("name") or ""]).lower()
    if p.get("run_id"):
        import webapp as W
        r = W.run_index().get(p["run_id"]) or {}
        hay += " " + " ".join(str(r.get(k) or "") for k in ("name", "town_or_neighborhood", "address")).lower()
    return p.get("area") in ("Nassau", "Suffolk") and any(t in hay for t in M.NORTH_SHORE)


def for_user(uid):
    """[(pack, role, status)] for a member's packs (active and pending)."""
    out = []
    for r in q(f"""SELECT {', '.join('p.' + c for c in P_COLS.split(','))}, m.role, m.status FROM packs p
                   JOIN pack_members m ON m.pack_id=p.id WHERE m.user_id=:u ORDER BY m.status, p.name""", u=uid):
        out.append((_p(r[:-2]), r[-2], r[-1]))
    return out


# ---------------------------------------------------------------- memberships
def _dogs(s):
    try:
        v = json.loads(s or "[]")
        return [int(x) for x in v if isinstance(x, int) or str(x).isdigit()]
    except ValueError:
        return []


def membership(pid, uid):
    if not uid:
        return None
    r = one("SELECT role, status, dogs, message, created_at FROM pack_members WHERE pack_id=:p AND user_id=:u", p=pid, u=uid)
    return dict(role=r[0], status=r[1], dogs=_dogs(r[2]), message=r[3], created_at=r[4]) if r else None


def is_member(pid, uid):
    m = membership(pid, uid)
    return bool(m and m["status"] == "active")


def is_organizer(pid, uid):
    m = membership(pid, uid)
    return bool(m and m["status"] == "active" and m["role"] in ("owner", "organizer"))


def join(pid, uid, dog_ids, visibility, message=""):
    """Join an open pack, or file a request. Returns the resulting status ('active' or 'pending')."""
    t = A.now()
    cur = membership(pid, uid)
    if cur:
        if cur["status"] == "active":
            q("UPDATE pack_members SET dogs=:d, updated_at=:t WHERE pack_id=:p AND user_id=:u", d=json.dumps(dog_ids), t=t, p=pid, u=uid)
            return "active"
        st = "active" if visibility == "open" else "pending"
        q("UPDATE pack_members SET dogs=:d, message=:m, status=:s, updated_at=:t WHERE pack_id=:p AND user_id=:u",
          d=json.dumps(dog_ids), m=message, s=st, t=t, p=pid, u=uid)
        return st
    st = "active" if visibility == "open" else "pending"
    q("""INSERT INTO pack_members(pack_id,user_id,role,status,dogs,message,created_at,updated_at)
         VALUES(:p,:u,'member',:s,:d,:m,:t,:t)""", p=pid, u=uid, s=st, d=json.dumps(dog_ids), m=message, t=t)
    return st


def set_dogs(pid, uid, dog_ids):
    q("UPDATE pack_members SET dogs=:d, updated_at=:t WHERE pack_id=:p AND user_id=:u", d=json.dumps(dog_ids), t=A.now(), p=pid, u=uid)


def approve(pid, uid):
    return bool(q("UPDATE pack_members SET status='active', updated_at=:t WHERE pack_id=:p AND user_id=:u AND status='pending' RETURNING id",
                  t=A.now(), p=pid, u=uid))


def remove(pid, uid):
    """Leave, deny a request, or remove a member (never the owner)."""
    q("DELETE FROM pack_members WHERE pack_id=:p AND user_id=:u AND role<>'owner'", p=pid, u=uid)


def set_role(pid, uid, role):
    assert role in ("organizer", "member")
    q("UPDATE pack_members SET role=:r, updated_at=:t WHERE pack_id=:p AND user_id=:u AND role<>'owner' AND status='active'",
      r=role, t=A.now(), p=pid, u=uid)


def transfer(pid, new_owner):
    p = get(pid)
    if not p or not is_member(pid, new_owner) or new_owner == p["owner_user_id"]:
        return False
    t = A.now()
    q("UPDATE pack_members SET role='organizer', updated_at=:t WHERE pack_id=:p AND user_id=:u", t=t, p=pid, u=p["owner_user_id"])
    q("UPDATE pack_members SET role='owner', updated_at=:t WHERE pack_id=:p AND user_id=:u", t=t, p=pid, u=new_owner)
    q("UPDATE packs SET owner_user_id=:u, updated_at=:t WHERE id=:p", u=new_owner, t=t, p=pid)
    return True


def members(pid, status="active"):
    """Members with their names and visible dogs (dicts with id, slug, name, photo), organizers first."""
    rows = q("""SELECT m.user_id, m.role, m.dogs, m.message, m.created_at, u.display_name, u.area, u.town FROM pack_members m
                JOIN users u ON u.id=m.user_id WHERE m.pack_id=:p AND m.status=:s ORDER BY
                CASE m.role WHEN 'owner' THEN 0 WHEN 'organizer' THEN 1 ELSE 2 END, m.created_at, m.id""", p=pid, s=status)
    ids = sorted({d for r in rows for d in _dogs(r[2])})
    dogs = {}
    if ids:
        for did, slug, name, av, uid, hidden in q("SELECT id, slug, name, avatar_photo_id, user_id, hidden FROM dogs WHERE id IN (%s)"
                                                   % ",".join(str(i) for i in ids)):
            dogs[did] = dict(id=did, slug=slug, name=name, avatar=av, user_id=uid, hidden=hidden)
        firsts = A.first_photos(ids)
        for d in dogs.values():
            d["photo"] = d["avatar"] or firsts.get(d["id"])
    out = []
    for uid, role, dj, msg, ts, name, area, town in rows:
        ds = [dogs[i] for i in _dogs(dj) if i in dogs and not dogs[i]["hidden"] and dogs[i]["user_id"] == uid]
        out.append(dict(user_id=uid, role=role, dogs=ds, message=msg, created_at=ts, name=name or "A member", area=area, town=town))
    return out


def organizer_ids(pid):
    return [r[0] for r in q("SELECT user_id FROM pack_members WHERE pack_id=:p AND status='active' AND role IN ('owner','organizer')", p=pid)]


def member_ids(pid):
    return [r[0] for r in q("SELECT user_id FROM pack_members WHERE pack_id=:p AND status='active'", p=pid)]


def pending_count(pid):
    return one("SELECT COUNT(*) FROM pack_members WHERE pack_id=:p AND status='pending'", p=pid)[0]


# ---------------------------------------------------------------- photos (cover + board), stored like dog photos
def add_photo(pid, raw, kind="cover", processed=None):
    """Store a photo; raw is re-encoded (EXIF/GPS stripped, resized) unless already processed with A.process_image."""
    full, thumb, w, h = processed or A.process_image(raw)
    return one("""INSERT INTO pack_photos(pack_id,kind,width,height,full_jpeg,thumb_webp,bytes,created_at)
                  VALUES(:p,:k,:w,:h,:f,:th,:b,:t) RETURNING id""",
               p=pid, k=kind, w=w, h=h, f=full, th=thumb, b=len(full) + len(thumb), t=A.now())[0]


def set_cover(pid, raw, processed=None):
    new = add_photo(pid, raw, "cover", processed)
    old = one("SELECT cover_photo_id FROM packs WHERE id=:p", p=pid)
    q("UPDATE packs SET cover_photo_id=:c, updated_at=:t WHERE id=:p", c=new, t=A.now(), p=pid)
    if old and old[0]:
        q("DELETE FROM pack_photos WHERE id=:i AND pack_id=:p", i=old[0], p=pid)
    return new


def remove_cover(pid):
    old = one("SELECT cover_photo_id FROM packs WHERE id=:p", p=pid)
    q("UPDATE packs SET cover_photo_id=NULL WHERE id=:p", p=pid)
    if old and old[0]:
        q("DELETE FROM pack_photos WHERE id=:i", i=old[0])


def photo_info(photo_id):
    """(pack_id, kind, pack hidden, post hidden or None) for access checks."""
    r = one("""SELECT ph.pack_id, ph.kind, p.hidden FROM pack_photos ph JOIN packs p ON p.id=ph.pack_id WHERE ph.id=:i""", i=photo_id)
    if not r:
        return None
    post = one("SELECT hidden FROM pack_posts WHERE photo_id=:i", i=photo_id) if r[1] == "post" else None
    return dict(pack_id=r[0], kind=r[1], pack_hidden=r[2], post_hidden=post[0] if post else None)


def photo_blob(photo_id, which):
    col = "full_jpeg" if which == "full" else "thumb_webp"
    r = one(f"SELECT {col} FROM pack_photos WHERE id=:i", i=photo_id)
    return bytes(r[0]) if r else None


def photo_size(photo_id):
    r = one("SELECT width, height FROM pack_photos WHERE id=:i", i=photo_id)
    return (r[0], r[1]) if r else (None, None)


# ---------------------------------------------------------------- board
def posts(pid, limit=50):
    rows = q("""SELECT p.id, p.user_id, p.body, p.photo_id, p.pinned, p.created_at, u.display_name FROM pack_posts p
                LEFT JOIN users u ON u.id=p.user_id WHERE p.pack_id=:p AND p.hidden=0 ORDER BY p.pinned DESC, p.id DESC LIMIT :l""",
             p=pid, l=limit)
    out = [dict(id=r[0], user_id=r[1], body=r[2], photo_id=r[3], pinned=r[4], created_at=r[5], name=r[6] or "A member", comments=[])
           for r in rows]
    by = {p["id"]: p for p in out}
    if by:
        for c in q("""SELECT c.id, c.post_id, c.user_id, c.body, c.created_at, u.display_name FROM pack_comments c
                      LEFT JOIN users u ON u.id=c.user_id WHERE c.post_id IN (%s) AND c.hidden=0 ORDER BY c.id"""
                   % ",".join(str(i) for i in by)):
            by[c[1]]["comments"].append(dict(id=c[0], post_id=c[1], user_id=c[2], body=c[3], created_at=c[4], name=c[5] or "A member"))
    return out


def post_count(pid):
    return one("SELECT COUNT(*) FROM pack_posts WHERE pack_id=:p AND hidden=0", p=pid)[0]


def add_post(pid, uid, body, photo_raw=None, processed=None):
    photo_id = add_photo(pid, photo_raw, "post", processed) if (photo_raw or processed) else None
    return one("INSERT INTO pack_posts(pack_id,user_id,body,photo_id,created_at) VALUES(:p,:u,:b,:ph,:t) RETURNING id",
               p=pid, u=uid, b=body, ph=photo_id, t=A.now())[0]


def get_post(post_id):
    r = one("SELECT id, pack_id, user_id, body, photo_id, pinned, hidden FROM pack_posts WHERE id=:i", i=post_id)
    return dict(id=r[0], pack_id=r[1], user_id=r[2], body=r[3], photo_id=r[4], pinned=r[5], hidden=r[6]) if r else None


def delete_post(post_id):
    p = get_post(post_id)
    if not p:
        return
    q("DELETE FROM pack_comments WHERE post_id=:i", i=post_id)
    q("DELETE FROM pack_posts WHERE id=:i", i=post_id)
    if p["photo_id"]:
        q("DELETE FROM pack_photos WHERE id=:i", i=p["photo_id"])


def set_pinned(post_id, pinned):
    q("UPDATE pack_posts SET pinned=:v WHERE id=:i", v=1 if pinned else 0, i=post_id)


def set_post_hidden(post_id, hidden):
    q("UPDATE pack_posts SET hidden=:v WHERE id=:i", v=1 if hidden else 0, i=post_id)


def add_comment(post_id, pid, uid, body):
    return one("INSERT INTO pack_comments(post_id,pack_id,user_id,body,created_at) VALUES(:po,:p,:u,:b,:t) RETURNING id",
               po=post_id, p=pid, u=uid, b=body, t=A.now())[0]


def get_comment(cid):
    r = one("SELECT id, post_id, pack_id, user_id, body, hidden FROM pack_comments WHERE id=:i", i=cid)
    return dict(id=r[0], post_id=r[1], pack_id=r[2], user_id=r[3], body=r[4], hidden=r[5]) if r else None


def delete_comment(cid):
    q("DELETE FROM pack_comments WHERE id=:i", i=cid)


def set_comment_hidden(cid, hidden):
    q("UPDATE pack_comments SET hidden=:v WHERE id=:i", v=1 if hidden else 0, i=cid)


def add_report(pid, post_id, cid, uid, reason, details, ip):
    q("""INSERT INTO reports(dog_id,pack_id,post_id,pack_comment_id,reporter_user_id,reason,details,ip_hash,created_at)
         VALUES(0,:p,:po,:c,:u,:r,:x,:i,:t)""", p=pid, po=post_id, c=cid, u=uid, r=reason, x=details, i=A.ip_hash(ip), t=A.now())


# ---------------------------------------------------------------- meetups of a pack
def meetups(pid, limit=20):
    import meetups as M
    return [m for m in M.upcoming(limit=500) if m.get("pack_id") == pid][:limit]


def names(ids):
    """{pack_id: (name, slug)} for badges."""
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    return {r[0]: (r[1], r[2]) for r in q("SELECT id, name, slug FROM packs WHERE id IN (%s) AND hidden=0" % ",".join(map(str, ids)))}


# ---------------------------------------------------------------- email preferences
def unsub_token(uid):
    return hmac.new(A.SECRET, f"pack-emails:{int(uid)}".encode(), hashlib.sha256).hexdigest()[:32]


def check_unsub(uid, tok):
    return str(uid).isdigit() and bool(tok) and hmac.compare_digest(unsub_token(int(uid)), tok)


def set_emails(uid, on):
    q("UPDATE users SET pack_emails=:v WHERE id=:u", v=1 if on else 0, u=uid)


def emails_on(uid):
    r = one("SELECT pack_emails FROM users WHERE id=:u", u=uid)
    return bool(r and r[0])


def contact(uid):
    r = one("SELECT email, display_name, pack_emails FROM users WHERE id=:u", u=uid)
    return (r[0], r[1] or "", bool(r[2])) if r else (None, "", False)


def purge_user(uid):
    """Account deletion: drop memberships, posts and comments; packs they own pass to a co-organizer or are deleted."""
    for (pid,) in q("SELECT id FROM packs WHERE owner_user_id=:u", u=uid):
        nxt = one("""SELECT user_id FROM pack_members WHERE pack_id=:p AND status='active' AND user_id<>:u
                     ORDER BY CASE role WHEN 'organizer' THEN 0 ELSE 1 END, created_at LIMIT 1""", p=pid, u=uid)
        if nxt:
            transfer(pid, nxt[0])
        else:
            delete(pid)
    for (post_id,) in q("SELECT id FROM pack_posts WHERE user_id=:u", u=uid):
        delete_post(post_id)
    q("DELETE FROM pack_comments WHERE user_id=:u", u=uid)
    q("DELETE FROM pack_members WHERE user_id=:u", u=uid)
