"""BarksBuds privacy settings: who can see each dog's profile, how findable it is, which details show, and who can
start a conversation with the owner (Oct 2026).

Model
  * dogs.visibility       public | members | pack | private   (per dog)
      public   anyone, including people who aren't signed in
      members  anyone signed in
      pack     pack-mates of an owner: members who share an active pack membership or a meetup RSVP with them
      private  only the dog's owner and co-owners
  * users.priv_search     everyone | members | none            (does the owner's dogs show in search, /dogs, galleries)
  * users.priv_index      1/0  allow search engines to index public profiles (robots noindex when 0)
  * users.priv_town / priv_birthday / priv_owner_name / priv_fav_runs / priv_celebrate   1 = show
  * users.checkins_hidden (existing column, community.py) 1 = my check-ins only count as "a dog", never named
  * users.priv_msg        everyone | pack | none                (who can start a new conversation / write to me)
  * users.priv_default_vis  visibility for dogs this member adds later

Field and search settings come from a dog's primary owner (dogs.user_id). Owners and co-owners always see everything.
A block between the viewer and any of a dog's owners makes the viewer count as signed out for that dog.

Defaults: the migration's column DEFAULTs are the *legacy* values, so every account and dog that existed before this
feature keeps looking exactly as it did (public, searchable, indexable, all details shown). Accounts created after
this feature get NEW_USER_DEFAULTS explicitly at creation (accounts.get_or_create_user).
"""
import hashlib, hmac

import accounts as A

VIS = [("public", "Public", "Anyone can see this profile, even people who aren't signed in."),
       ("members", "Members only", "Anyone signed in to BarksBuds."),
       ("pack", "Pack-mates only", "Members who are in a pack with you or RSVP'd to the same meetup."),
       ("private", "Private", "Only you and your dog's co-owners.")]
VIS_KEYS = [k for k, _, _ in VIS]
VIS_LABEL = {k: l for k, l, _ in VIS}
SEARCH = [("everyone", "Everyone", "Your dogs can show up in BarksBuds search and the Meet the dogs page for anyone allowed to see them."),
          ("members", "Signed-in members only", "People who aren't signed in won't find your dogs in search."),
          ("none", "Don't show my dogs in search", "Your dogs stay out of search, the Meet the dogs page and galleries. "
                                                    "People with the link (and permission) can still open their pages.")]
SEARCH_KEYS = [k for k, _, _ in SEARCH]
MSG = [("everyone", "Any member", "Any signed-in member can start a conversation with you."),
       ("pack", "Only my pack-mates", "Members who share a pack or meetup with you."),
       ("none", "No one", "Nobody can start a new conversation with you. People you've written to can still reply.")]
MSG_KEYS = [k for k, _, _ in MSG]
FLAGS = [("priv_town", "Show my town and area", "On your dogs' profiles, cards and search results."),
         ("priv_birthday", "Show birthday, age and gotcha day", "Hiding this also hides the birthday cake on profiles."),
         ("priv_owner_name", "Show my first name on my dogs' profiles", "Otherwise we say \u201ca BarksBuds member\u201d."),
         ("priv_fav_runs", "Show the dog runs my dogs like", "The \u201cfavorite runs\u201d list on their profiles."),
         ("priv_celebrate", "Include my dogs in birthday and gotcha-day shout-outs", "The \u201ccelebrating today\u201d cards on the homepage, Meet the dogs and Community pages.")]
FLAG_KEYS = [k for k, _, _ in FLAGS]

# what new accounts start with (privacy-friendly but still social); existing accounts keep the legacy column defaults
NEW_USER_DEFAULTS = dict(priv_default_vis="members", priv_search="everyone", priv_index=0, priv_msg="everyone")
SET_COLS = ["priv_default_vis", "priv_search", "priv_index", "priv_msg"] + FLAG_KEYS + ["checkins_hidden"]
LEGACY = dict(priv_default_vis="public", priv_search="everyone", priv_index=1, priv_msg="everyone",
              checkins_hidden=0, **{k: 1 for k in FLAG_KEYS})


# ---------------------------------------------------------------- schema (additive, safe to re-run on SQLite and Postgres)
def init_schema(store):
    pg = store.kind == "postgres"
    INT = "BIGINT" if pg else "INTEGER"

    def cols(t):
        return ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=t)} if pg
                else {r[1] for r in store.q(f"PRAGMA table_info({t})")})
    dc = cols("dogs")
    if "visibility" not in dc:
        store.q("ALTER TABLE dogs ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'")
    uc = cols("users")
    for c, ddl in [("priv_default_vis", "TEXT NOT NULL DEFAULT 'public'"), ("priv_search", "TEXT NOT NULL DEFAULT 'everyone'"),
                   ("priv_index", f"{INT} NOT NULL DEFAULT 1"), ("priv_msg", "TEXT NOT NULL DEFAULT 'everyone'")] + \
                  [(k, f"{INT} NOT NULL DEFAULT 1") for k in FLAG_KEYS]:
        if c not in uc:
            store.q(f"ALTER TABLE users ADD COLUMN {c} {ddl}")


def new_user_sql():
    """(column list, values list) fragments for INSERT INTO users, so new accounts get NEW_USER_DEFAULTS atomically."""
    return ",".join(NEW_USER_DEFAULTS), ",".join(f":pv_{k}" for k in NEW_USER_DEFAULTS), {f"pv_{k}": v for k, v in NEW_USER_DEFAULTS.items()}


def set_legacy_defaults(uid):
    """Used by seed.py: the site's own demo account (Lily and Maggie) stays fully public, as before."""
    A.q("UPDATE users SET " + ",".join(f"{k}=:{k}" for k in LEGACY) + " WHERE id=:u", u=uid, **LEGACY)


# ---------------------------------------------------------------- settings
def settings(uid):
    return settings_map([uid]).get(uid) or dict(LEGACY)


def settings_map(uids):
    ids = sorted({int(u) for u in uids if u})
    if not ids:
        return {}
    rows = A.q(f"SELECT id,{','.join(SET_COLS)} FROM users WHERE id IN ({','.join(map(str, ids))})")
    out = {}
    for r in rows:
        s = dict(zip(SET_COLS, r[1:]))
        for k in FLAG_KEYS + ["priv_index", "checkins_hidden"]:
            s[k] = int(s[k] or 0)
        if s["priv_default_vis"] not in VIS_KEYS:
            s["priv_default_vis"] = "members"
        if s["priv_search"] not in SEARCH_KEYS:
            s["priv_search"] = "members"
        if s["priv_msg"] not in MSG_KEYS:
            s["priv_msg"] = "everyone"
        out[r[0]] = s
    return out


def save_settings(uid, s):
    vals = {k: s[k] for k in SET_COLS if k in s}
    if vals:
        A.q("UPDATE users SET " + ",".join(f"{k}=:{k}" for k in vals) + " WHERE id=:u", u=uid, **vals)


def set_visibility(dog_id, vis):
    if vis in VIS_KEYS:
        A.q("UPDATE dogs SET visibility=:v, updated_at=:t WHERE id=:i", v=vis, t=A.now(), i=dog_id)


def default_vis(uid):
    return settings(uid)["priv_default_vis"]


# ---------------------------------------------------------------- the viewer
class Viewer:
    """Who is looking (uid None = signed out). Caches pack-mates and blocks for one request."""

    def __init__(self, uid=None):
        self.uid = int(uid) if uid else None
        self._mates = None
        self._blocks = None

    @property
    def signed_in(self):
        return bool(self.uid)

    def packmates(self):
        if self._mates is None:
            if not self.uid:
                self._mates = set()
            else:
                s = set()
                for (u,) in A.q("""SELECT DISTINCT b.user_id FROM pack_members a JOIN pack_members b ON b.pack_id=a.pack_id
                                   JOIN packs p ON p.id=a.pack_id
                                   WHERE a.user_id=:u AND a.status='active' AND b.status='active' AND p.hidden=0""", u=self.uid):
                    s.add(u)
                for (u,) in A.q("""SELECT DISTINCT b.user_id FROM rsvps a JOIN rsvps b ON b.meetup_id=a.meetup_id
                                   JOIN meetups m ON m.id=a.meetup_id
                                   WHERE a.user_id=:u AND m.hidden=0 AND a.status IN ('going','maybe','waitlist')
                                   AND b.status IN ('going','maybe','waitlist')""", u=self.uid):
                    s.add(u)
                s.discard(self.uid)
                self._mates = s
        return self._mates

    def blocks(self):
        """Members this viewer blocked or was blocked by."""
        if self._blocks is None:
            if not self.uid:
                self._blocks = set()
            else:
                self._blocks = {r[0] for r in A.q("SELECT blocked_id FROM user_blocks WHERE blocker_id=:u", u=self.uid)} | \
                               {r[0] for r in A.q("SELECT blocker_id FROM user_blocks WHERE blocked_id=:u", u=self.uid)}
        return self._blocks

    def is_packmate(self, uid):
        return bool(self.uid) and uid in self.packmates()


SIGNED_OUT = Viewer(None)


def viewer(v):
    """Accept a Viewer, a user id, a user dict or None."""
    if isinstance(v, Viewer):
        return v
    if isinstance(v, dict):
        return Viewer(v.get("id"))
    return Viewer(v)


# ---------------------------------------------------------------- dog access
def _meta(ids):
    ids = sorted({int(i) for i in ids if str(i).isdigit()})
    if not ids:
        return {}
    import coowners as CO
    own = CO.owners_map(ids)
    out = {}
    for did, uid, vis, hidden in A.q(f"SELECT id, user_id, visibility, hidden FROM dogs WHERE id IN ({','.join(map(str, ids))})"):
        owners = {o["user_id"] if isinstance(o, dict) else o for o in (own.get(did) or [])} | {uid}
        out[did] = dict(id=did, user_id=uid, visibility=vis if vis in VIS_KEYS else "public", hidden=int(hidden or 0), owners=owners)
    return out


def _allowed(m, V):
    if m["hidden"]:
        return False
    if V.uid and V.uid in m["owners"]:
        return True
    vis = m["visibility"]
    if V.uid and (m["owners"] & V.blocks()):
        return vis == "public"  # blocked: treated as signed out
    if vis == "public":
        return True
    if vis == "members":
        return V.signed_in
    if vis == "pack":
        return V.signed_in and bool(m["owners"] & V.packmates())
    return False


def is_owner(d, V):
    V = viewer(V)
    if not V.uid:
        return False
    m = _meta([d["id"]]).get(d["id"])
    return bool(m and V.uid in m["owners"])


def can_view(d, V):
    """May viewer V open dog d's profile (and see its photos)? d is a dog dict or an id."""
    V = viewer(V)
    did = d if isinstance(d, int) else d["id"]
    m = _meta([did]).get(did)
    return bool(m and _allowed(m, V))


def visible_ids(ids, V, purpose="view"):
    """The subset of dog ids viewer V may see. purpose: 'view' (profile, member lists, check-ins),
    'list' (search, /dogs, galleries: also honors the owner's search setting) or 'celebrate'."""
    V = viewer(V)
    meta = _meta(ids)
    ok = {i for i, m in meta.items() if _allowed(m, V)}
    if purpose in ("list", "celebrate") and ok:
        st = settings_map([meta[i]["user_id"] for i in ok])
        keep = set()
        for i in ok:
            s = st.get(meta[i]["user_id"]) or LEGACY
            if purpose == "list":
                if s["priv_search"] == "everyone" or (s["priv_search"] == "members" and V.signed_in):
                    keep.add(i)
            elif s["priv_celebrate"]:
                keep.add(i)
        ok = keep
    return ok


def filter_tiles(tiles, V, purpose="view"):
    """Drop dog tiles/dicts (anything with an 'id') the viewer may not see, keeping order."""
    tiles = list(tiles or [])
    if not tiles:
        return tiles
    ok = visible_ids([t["id"] for t in tiles], V, purpose)
    return [t for t in tiles if t["id"] in ok]


def filter_people(people, V):
    """For pack member lists, RSVP lists and check-ins: each person's 'dogs' list keeps only dogs V may see.
    The person stays (their counts are unchanged); callers show a neutral label when no dog is left."""
    allids = [t["id"] for p in people for t in (p.get("dogs") or [])]
    ok = visible_ids(allids, V) if allids else set()
    for p in people:
        p["dogs"] = [t for t in (p.get("dogs") or []) if t["id"] in ok]
    return people


def redact(d, V, st=None):
    """Copy of dog dict d with the fields its owner hid blanked for viewer V (owners see everything).
    Works for browse dicts (town/area/owner_name) and plain dog dicts."""
    V = viewer(V)
    d = dict(d)
    if V.uid and is_owner(d, V):
        return d
    st = st or settings(d["user_id"])
    if not st["priv_town"]:
        for k in ("town", "area"):
            if k in d:
                d[k] = ""
    if not st["priv_birthday"]:
        for k in ("birthday", "gotcha_day"):
            if k in d:
                d[k] = ""
        if "birth_year" in d:
            d["birth_year"] = None
    if not st["priv_fav_runs"] and "fav_runs" in d:
        d["fav_runs"] = []
    if not st["priv_owner_name"] and "owner_name" in d:
        d["owner_name"] = ""
    return d


def directory(V, areas=None, match=None, limit=60):
    """Dogs for /dogs, search and the sitemap: allowed for V, findable per the owner's search setting, fields redacted.
    Area filtering uses the redacted area, so a hidden town never matches an area filter."""
    V = viewer(V)
    rows = A.browse_dogs(limit=10 ** 6)
    ok = visible_ids([d["id"] for d in rows], V, "list")
    st = settings_map([d["user_id"] for d in rows if d["id"] in ok])
    out = []
    for d in rows:
        if d["id"] not in ok:
            continue
        d = redact(d, V, st.get(d["user_id"]))
        if areas and d.get("area") not in areas:
            continue
        if match and not match(d):
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def indexable(d, st=None):
    """Should search engines index this dog page (and list it in the sitemap)?"""
    st = st or settings(d["user_id"])
    return (not d.get("hidden") and (d.get("visibility") or "public") == "public"
            and bool(st["priv_index"]) and st["priv_search"] == "everyone")


def sitemap_dogs(limit=5000):
    rows = A.browse_dogs(limit=10 ** 6)
    st = settings_map([d["user_id"] for d in rows])
    return [d for d in rows if indexable(d, st.get(d["user_id"]) or LEGACY)][:limit]


def can_celebrate(d, V, kind):
    """Show dog d in a 'celebrating today' card / page for V?"""
    V = viewer(V)
    if not can_view(d, V):
        return False
    st = settings(d["user_id"])
    if not st["priv_celebrate"]:
        return False
    return bool(st["priv_birthday"])  # both birthdays and gotcha days are dates the owner chose to show or hide


def filter_celebrations(items, V, areas=None):
    """items from community.celebrating(): keep those V may see and whose owner allows shout-outs and dates.
    With an area filter, owners who hide their town/area aren't matched by area."""
    if not items:
        return items
    V = viewer(V)
    ok = visible_ids([x["id"] for x in items], V, "celebrate")
    st = settings_map([x["user_id"] for x in items])
    out = []
    for x in items:
        s = st.get(x["user_id"]) or LEGACY
        if x["id"] in ok and s["priv_birthday"] and (not areas or s["priv_town"]):
            out.append(x)
    return out


def checkin_hidden_users(uids):
    st = settings_map(uids)
    return {u for u, s in st.items() if s["checkins_hidden"]}


# ---------------------------------------------------------------- photos
def photo_dog(pid):
    r = A.one("SELECT dog_id FROM photos WHERE id=:i", i=pid)
    return r[0] if r else None


def photo_sig(pid):
    """Signature for photo links that are opened without a session (emails, admin tools, invite pages)."""
    return hmac.new(A.SECRET, f"photo:{int(pid)}".encode(), hashlib.sha256).hexdigest()[:20]


def photo_sig_ok(pid, k):
    return bool(k) and hmac.compare_digest(photo_sig(pid), str(k))


def signed_photo(pid, ext="webp", base=""):
    return f"{base}/p/{int(pid)}.{ext}?k={photo_sig(pid)}"


def public_dog(dog_id):
    m = _meta([dog_id]).get(dog_id)
    return bool(m and not m["hidden"] and m["visibility"] == "public")


# ---------------------------------------------------------------- messaging
def _has_written(sender, other):
    """Has `sender` already written to `other` (in their conversation)?"""
    lo, hi = sorted((int(sender), int(other)))
    return bool(A.one("""SELECT 1 FROM messages m JOIN conversations c ON c.id=m.conversation_id
                         WHERE c.user_lo=:lo AND c.user_hi=:hi AND m.sender_id=:s LIMIT 1""", lo=lo, hi=hi, s=sender))


def can_message(sender, recipient, V=None):
    """May `sender` write to `recipient` per the recipient's 'who can message me' setting? (Blocks are checked
    separately by messages.either_blocked.) A recipient who already wrote to the sender can always be answered."""
    if not sender or not recipient or sender == recipient:
        return False
    mode = settings(recipient)["priv_msg"]
    if mode == "everyone":
        return True
    if _has_written(recipient, sender):
        return True
    if mode == "pack":
        return (V if isinstance(V, Viewer) and V.uid == sender else Viewer(sender)).is_packmate(recipient)
    return False


MSG_CLOSED = "This member isn't accepting new messages right now."
