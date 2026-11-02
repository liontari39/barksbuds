"""BarksBuds photo feed: data layer (posts with up to 4 photos, tagged dogs, an optional dog run, likes, comments).

Who can see a post: the strictest of every tagged dog's profile visibility (public / members / pack / private, from
/me/privacy) and the poster's optional per-post override, which may only be equal or stricter. Hidden posts (admin)
and posts of hidden dogs are only visible to the poster. Members who block each other (either direction) never see
or interact with each other's posts. The feed, homepage and run pages ("list" places) also honor each owner's
search setting; the post page and the dog's own profile follow plain visibility. See photoweb.py for the pages.
"""
import accounts as A
import privacy as PV

MAX_PHOTOS = 4
MAX_CAPTION = 300
MAX_COMMENT = 500
PAGE = 10
RANK = {"public": 0, "members": 1, "pack": 2, "private": 3}
OVERRIDES = [("", "Same as my dog's profile"), ("members", "Signed-in members"), ("pack", "Pack-mates only"),
             ("private", "Only me and my dog's co-owners")]
OVR_KEYS = [k for k, _ in OVERRIDES]


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    BLOB = "BYTEA" if pg else "BLOB"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS photo_posts(id {ID}, user_id {INT} NOT NULL, caption TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '', vis TEXT NOT NULL DEFAULT '', hidden {INT} NOT NULL DEFAULT 0,
            created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS photo_posts_user_idx ON photo_posts(user_id)",
        "CREATE INDEX IF NOT EXISTS photo_posts_run_idx ON photo_posts(run_id)",
        f"""CREATE TABLE IF NOT EXISTS photo_post_dogs(post_id {INT} NOT NULL, dog_id {INT} NOT NULL, PRIMARY KEY(post_id, dog_id))""",
        "CREATE INDEX IF NOT EXISTS photo_post_dogs_dog_idx ON photo_post_dogs(dog_id)",
        f"""CREATE TABLE IF NOT EXISTS feed_photos(id {ID}, post_id {INT} NOT NULL, position {INT} NOT NULL DEFAULT 0,
            width {INT} NOT NULL, height {INT} NOT NULL, full_jpeg {BLOB} NOT NULL, thumb_webp {BLOB} NOT NULL,
            bytes {INT} NOT NULL, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS feed_photos_post_idx ON feed_photos(post_id, position)",
        f"""CREATE TABLE IF NOT EXISTS photo_likes(post_id {INT} NOT NULL, user_id {INT} NOT NULL, created_at {INT} NOT NULL,
            PRIMARY KEY(post_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS photo_likes_user_idx ON photo_likes(user_id)",
        f"""CREATE TABLE IF NOT EXISTS photo_comments(id {ID}, post_id {INT} NOT NULL, user_id {INT} NOT NULL, body TEXT NOT NULL,
            hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS photo_comments_idx ON photo_comments(post_id, id)",
    ]:
        store.q(s)

    def cols(t):
        return ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=t)} if pg
                else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    rc = cols("reports")
    for c in ("photo_post_id", "photo_comment_id"):
        if c not in rc:
            store.q(f"ALTER TABLE reports ADD COLUMN {c} {INT}")


# ---------------------------------------------------------------- posts
P_COLS = "id, user_id, caption, run_id, vis, hidden, created_at, updated_at"


def _p(r):
    return dict(zip([c.strip() for c in P_COLS.split(",")], r)) if r else None


def create(uid, dog_ids, run_id, caption, vis, processed):
    """processed: [(full_jpeg, thumb_webp, w, h), ...] already validated by A.process_image."""
    t = A.now()
    pid = A.one("""INSERT INTO photo_posts(user_id,caption,run_id,vis,hidden,created_at,updated_at)
                   VALUES(:u,:c,:r,:v,0,:t,:t) RETURNING id""", u=uid, c=caption, r=run_id or "", v=vis if vis in OVR_KEYS else "", t=t)[0]
    for d in sorted(set(dog_ids)):
        q("INSERT INTO photo_post_dogs(post_id,dog_id) VALUES(:p,:d)", p=pid, d=d)
    for i, (full, thumb, w, h) in enumerate(processed[:MAX_PHOTOS]):
        q("""INSERT INTO feed_photos(post_id,position,width,height,full_jpeg,thumb_webp,bytes,created_at)
             VALUES(:p,:i,:w,:h,:f,:th,:b,:t)""", p=pid, i=i, w=w, h=h, f=full, th=thumb, b=len(full) + len(thumb), t=t)
    return pid


def get(pid):
    return _p(A.one(f"SELECT {P_COLS} FROM photo_posts WHERE id=:i", i=pid))


def many(pids):
    pids = [int(x) for x in pids]
    if not pids:
        return {}
    return {r[0]: _p(r) for r in q(f"SELECT {P_COLS} FROM photo_posts WHERE id IN ({','.join(map(str, pids))})")}


def recent(before=None, limit=40, dog_id=None, run_id=None, user_id=None):
    """Newest-first post dicts (unfiltered by privacy) with id < before."""
    w, kw = ["1=1"], {"n": int(limit)}
    if before:
        w.append("p.id < :b"); kw["b"] = int(before)
    if dog_id:
        w.append("p.id IN (SELECT post_id FROM photo_post_dogs WHERE dog_id=:d)"); kw["d"] = int(dog_id)
    if run_id:
        w.append("p.run_id = :r"); kw["r"] = run_id
    if user_id:
        w.append("p.user_id = :u"); kw["u"] = int(user_id)
    cols = ", ".join("p." + c.strip() for c in P_COLS.split(","))
    return [_p(r) for r in q(f"SELECT {cols} FROM photo_posts p WHERE {' AND '.join(w)} ORDER BY p.id DESC LIMIT :n", **kw)]


def dogs_of(pids):
    """{post_id: [dog_id, ...]}"""
    pids = [int(x) for x in pids]
    out = {p: [] for p in pids}
    if pids:
        for p, d in q(f"SELECT post_id, dog_id FROM photo_post_dogs WHERE post_id IN ({','.join(map(str, pids))}) ORDER BY dog_id"):
            out.setdefault(p, []).append(d)
    return out


def photos_of(pids):
    """{post_id: [{id, width, height}, ...]} in order."""
    pids = [int(x) for x in pids]
    out = {p: [] for p in pids}
    if pids:
        for i, p, w, h in q(f"SELECT id, post_id, width, height FROM feed_photos WHERE post_id IN ({','.join(map(str, pids))}) ORDER BY post_id, position, id"):
            out.setdefault(p, []).append(dict(id=i, width=w, height=h))
    return out


def counts(pids, uid=None):
    """({post_id: likes}, {post_id: visible comment count}, {post_ids liked by uid})"""
    pids = [int(x) for x in pids]
    if not pids:
        return {}, {}, set()
    ids = ",".join(map(str, pids))
    likes = {p: n for p, n in q(f"SELECT post_id, COUNT(*) FROM photo_likes WHERE post_id IN ({ids}) GROUP BY post_id")}
    coms = {p: n for p, n in q(f"SELECT post_id, COUNT(*) FROM photo_comments WHERE post_id IN ({ids}) AND hidden=0 GROUP BY post_id")}
    mine = {p for (p,) in q(f"SELECT post_id FROM photo_likes WHERE user_id=:u AND post_id IN ({ids})", u=uid)} if uid else set()
    return likes, coms, mine


def update(pid, caption, vis):
    q("UPDATE photo_posts SET caption=:c, vis=:v, updated_at=:t WHERE id=:i", c=caption, v=vis if vis in OVR_KEYS else "", t=A.now(), i=pid)


def set_hidden(pid, hidden):
    q("UPDATE photo_posts SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=pid)


def delete(pid):
    q("DELETE FROM photo_comments WHERE post_id=:i", i=pid)
    q("DELETE FROM photo_likes WHERE post_id=:i", i=pid)
    q("DELETE FROM feed_photos WHERE post_id=:i", i=pid)
    q("DELETE FROM photo_post_dogs WHERE post_id=:i", i=pid)
    q("DELETE FROM reports WHERE photo_post_id=:i", i=pid)
    q("DELETE FROM photo_posts WHERE id=:i", i=pid)


def count_recent_by(uid, since):
    return A.one("SELECT COUNT(*) FROM photo_posts WHERE user_id=:u AND created_at>=:s", u=uid, s=since)[0]


# ---------------------------------------------------------------- photos
def photo_post(photo_id):
    r = A.one("SELECT post_id FROM feed_photos WHERE id=:i", i=photo_id)
    return r[0] if r else None


def photo_blob(photo_id, which):
    col = "full_jpeg" if which == "full" else "thumb_webp"
    r = A.one(f"SELECT {col} FROM feed_photos WHERE id=:i", i=photo_id)
    return bytes(r[0]) if r else None


# ---------------------------------------------------------------- likes
def toggle_like(pid, uid):
    if A.one("SELECT 1 FROM photo_likes WHERE post_id=:p AND user_id=:u", p=pid, u=uid):
        q("DELETE FROM photo_likes WHERE post_id=:p AND user_id=:u", p=pid, u=uid)
        on = False
    else:
        q("INSERT INTO photo_likes(post_id,user_id,created_at) VALUES(:p,:u,:t) ON CONFLICT DO NOTHING", p=pid, u=uid, t=A.now())
        on = True
    return on, A.one("SELECT COUNT(*) FROM photo_likes WHERE post_id=:p", p=pid)[0]


# ---------------------------------------------------------------- comments
def comments(pid):
    return [dict(id=r[0], user_id=r[1], body=r[2], hidden=r[3], created_at=r[4], name=r[5] or "") for r in q(
        """SELECT c.id, c.user_id, c.body, c.hidden, c.created_at, u.display_name FROM photo_comments c
           LEFT JOIN users u ON u.id=c.user_id WHERE c.post_id=:p ORDER BY c.id""", p=pid)]


def add_comment(pid, uid, body):
    return A.one("INSERT INTO photo_comments(post_id,user_id,body,hidden,created_at) VALUES(:p,:u,:b,0,:t) RETURNING id",
                 p=pid, u=uid, b=body, t=A.now())[0]


def get_comment(cid):
    r = A.one("SELECT id, post_id, user_id, body, hidden FROM photo_comments WHERE id=:i", i=cid)
    return dict(id=r[0], post_id=r[1], user_id=r[2], body=r[3], hidden=r[4]) if r else None


def delete_comment(cid):
    q("DELETE FROM reports WHERE photo_comment_id=:i", i=cid)
    q("DELETE FROM photo_comments WHERE id=:i", i=cid)


def set_comment_hidden(cid, hidden):
    q("UPDATE photo_comments SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=cid)


def add_report(post_id, cid, uid, reason, details, ip):
    q("""INSERT INTO reports(dog_id,photo_post_id,photo_comment_id,reporter_user_id,reason,details,ip_hash,created_at)
         VALUES(0,:p,:c,:u,:r,:x,:i,:t)""", p=post_id, c=cid, u=uid, r=reason, x=details, i=A.ip_hash(ip), t=A.now())


# ---------------------------------------------------------------- privacy
def strictest(post, metas):
    """The post's effective audience key: the strictest of the tagged dogs' visibility and the override."""
    keys = [m["visibility"] for m in metas] + ([post["vis"]] if post.get("vis") else [])
    return max(keys or ["private"], key=lambda k: RANK.get(k, 3))


def _owners(metas):
    s = set()
    for m in metas:
        s |= m["owners"]
    return s


def can_see(post, dog_ids, V, meta=None):
    """Plain visibility (post page, the dog's own profile, photo files)."""
    V = PV.viewer(V)
    if not post:
        return False
    if V.uid and V.uid == post["user_id"]:
        return True
    meta = PV._meta(dog_ids) if meta is None else meta
    ms = [meta.get(d) for d in dog_ids]
    if post["hidden"] or not ms or any(m is None for m in ms):
        return False
    owners = _owners(ms)
    if V.uid and ((owners | {post["user_id"]}) & V.blocks()):
        return False  # blocked either way: no seeing, liking or commenting
    if V.uid and V.uid in owners:
        return True  # co-owners of a tagged dog
    if not all(PV._allowed(m, V) for m in ms):
        return False
    ov = post.get("vis") or ""
    if ov == "members":
        return V.signed_in
    if ov == "pack":
        return V.signed_in and bool((owners | {post["user_id"]}) & V.packmates())
    if ov == "private":
        return False
    return True


def visible(posts, V, purpose="view"):
    """Filter post dicts for viewer V, keeping order. purpose 'list' also honors the search setting of the poster
    and of each tagged dog's owner (the poster and the dogs' owners always see their own)."""
    V = PV.viewer(V)
    posts = [p for p in posts if p]
    if not posts:
        return []
    dmap = dogs_of([p["id"] for p in posts])
    meta = PV._meta({d for ds in dmap.values() for d in ds})
    out = [p for p in posts if can_see(p, dmap.get(p["id"], []), V, meta)]
    if purpose == "list" and out:
        uids = {p["user_id"] for p in out} | {meta[d]["user_id"] for p in out for d in dmap[p["id"]] if d in meta}
        st = PV.settings_map(list(uids))
        keep = []
        for p in out:
            ms = [meta[d] for d in dmap[p["id"]]]
            if V.uid and (V.uid == p["user_id"] or V.uid in _owners(ms)):
                keep.append(p); continue
            ok = True
            for u in {p["user_id"]} | {m["user_id"] for m in ms}:
                s = st.get(u) or PV.LEGACY
                if not (s["priv_search"] == "everyone" or (s["priv_search"] == "members" and V.signed_in)):
                    ok = False
            if ok:
                keep.append(p)
        out = keep
    return out


def is_public(post, dog_ids, meta=None):
    return can_see(post, dog_ids, PV.SIGNED_OUT, meta)


def indexable(post, dog_ids, meta=None):
    """Search engines may index the post page: visible signed out, and every owner involved allows indexing."""
    meta = PV._meta(dog_ids) if meta is None else meta
    if not is_public(post, dog_ids, meta):
        return False
    uids = {post["user_id"]} | {meta[d]["user_id"] for d in dog_ids if d in meta}
    st = PV.settings_map(list(uids))
    return all(bool((st.get(u) or PV.LEGACY)["priv_index"]) and (st.get(u) or PV.LEGACY)["priv_search"] == "everyone" for u in uids)


def page(V, before=None, dog_id=None, run_id=None, purpose="list", limit=PAGE):
    """(posts, next_before) for the feed: scans newest-first in batches until `limit` visible posts are found."""
    got, cur = [], before
    for _ in range(25):
        batch = recent(before=cur, limit=60, dog_id=dog_id, run_id=run_id)
        if not batch:
            return got, None
        for p in visible(batch, V, purpose):
            got.append(p)
            if len(got) == limit:
                return got, p["id"]
        cur = batch[-1]["id"]
    return got, (cur if got else None)


def sitemap(limit=2000):
    out = []
    for p in recent(limit=limit):
        ds = dogs_of([p["id"]])[p["id"]]
        if indexable(p, ds):
            out.append(p)
    return out


# ---------------------------------------------------------------- account / dog deletion
def purge_user(uid):
    for (pid,) in q("SELECT id FROM photo_posts WHERE user_id=:u", u=uid):
        delete(pid)
    q("DELETE FROM reports WHERE photo_comment_id IN (SELECT id FROM photo_comments WHERE user_id=:u)", u=uid)
    q("DELETE FROM photo_comments WHERE user_id=:u", u=uid)
    q("DELETE FROM photo_likes WHERE user_id=:u", u=uid)


def purge_dog(dog_id):
    """Untag the dog; posts left with no dogs are deleted with it (a post always shows at least one dog)."""
    pids = [r[0] for r in q("SELECT post_id FROM photo_post_dogs WHERE dog_id=:d", d=dog_id)]
    q("DELETE FROM photo_post_dogs WHERE dog_id=:d", d=dog_id)
    for pid in pids:
        if not A.one("SELECT 1 FROM photo_post_dogs WHERE post_id=:p", p=pid):
            delete(pid)
