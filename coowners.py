"""Dog co-owners (Oct 2026): a dog can belong to several accounts, so couples and families share one profile.

dog_owners(dog_id, user_id, role, created_at): one 'owner' row (the primary owner, the same as dogs.user_id) plus up
to MAX_COOWNERS 'co-owner' rows. Existing dogs get their owner row at startup (idempotent).
Co-owners can edit the profile and photos, RSVP / join packs with the dog and see its portrait request. Only the
primary owner invites, revokes invites, removes co-owners and deletes the dog. A co-owner can leave.

dog_invites: an emailed invite link (token stored as a sha256 hash), valid INVITE_TTL, single use, revocable.
Accepting the link signs the person in (the link was sent to their email, like a magic link), creating the account
if needed, or adds the account that's already signed in.
"""
import secrets

import accounts as A

MAX_COOWNERS = 5
INVITE_TTL = 7 * 86400


class InviteError(Exception):
    pass


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS dog_owners(dog_id {INT} NOT NULL, user_id {INT} NOT NULL,
        role TEXT NOT NULL DEFAULT 'co-owner', created_at {INT} NOT NULL, PRIMARY KEY(dog_id, user_id))""")
    store.q("CREATE INDEX IF NOT EXISTS dog_owners_user ON dog_owners(user_id)")
    store.q(f"""CREATE TABLE IF NOT EXISTS dog_invites(id {ID}, dog_id {INT} NOT NULL, inviter_user_id {INT} NOT NULL,
        email TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, created_at {INT} NOT NULL, expires_at {INT} NOT NULL,
        accepted_at {INT}, accepted_user_id {INT}, revoked_at {INT})""")
    store.q("CREATE INDEX IF NOT EXISTS dog_invites_dog ON dog_invites(dog_id)")
    backfill(store.q)


def backfill(qf=None):
    """Idempotent: every dog's primary owner (dogs.user_id) has an 'owner' row."""
    qf = qf or A.q
    qf("""INSERT INTO dog_owners(dog_id, user_id, role, created_at)
          SELECT d.id, d.user_id, 'owner', d.created_at FROM dogs d
          WHERE NOT EXISTS (SELECT 1 FROM dog_owners o WHERE o.dog_id=d.id AND o.user_id=d.user_id)""")


def add_owner_row(dog_id, user_id):
    if not A.one("SELECT 1 FROM dog_owners WHERE dog_id=:d AND user_id=:u", d=dog_id, u=user_id):
        A.q("INSERT INTO dog_owners(dog_id,user_id,role,created_at) VALUES(:d,:u,'owner',:t)", d=dog_id, u=user_id, t=A.now())


def role(dog, user_id):
    """'owner', 'co-owner' or None for this account and dog (dict or id)."""
    if not dog or not user_id:
        return None
    d = dog if isinstance(dog, dict) else A.dog_by_id(dog)
    if not d:
        return None
    if d["user_id"] == user_id:
        return "owner"
    r = A.one("SELECT role FROM dog_owners WHERE dog_id=:d AND user_id=:u AND role='co-owner'", d=d["id"], u=user_id)
    return "co-owner" if r else None


def can_manage(dog, user_id):
    return role(dog, user_id) is not None


def dog_ids_for(user_id):
    """Ids of every dog the account owns or co-owns."""
    ids = {r[0] for r in A.q("SELECT id FROM dogs WHERE user_id=:u", u=user_id)}
    ids |= {r[0] for r in A.q("SELECT dog_id FROM dog_owners WHERE user_id=:u", u=user_id)}
    return ids


def owners_map(dog_ids):
    """{dog_id: set(user ids that own or co-own it)} for display filters (attendee lists)."""
    ids = sorted({int(i) for i in dog_ids})
    out = {i: set() for i in ids}
    if not ids:
        return out
    inn = ",".join(str(i) for i in ids)
    for d, u in A.q(f"SELECT id, user_id FROM dogs WHERE id IN ({inn})"):
        out[d].add(u)
    for d, u in A.q(f"SELECT dog_id, user_id FROM dog_owners WHERE dog_id IN ({inn})"):
        out[d].add(u)
    return out


def coowners(dog_id):
    """[{user_id, name, created_at}] of the dog's co-owners (not the primary owner), oldest first."""
    return [dict(user_id=r[0], name=r[1] or "A member", created_at=r[2]) for r in A.q(
        """SELECT o.user_id, u.display_name, o.created_at FROM dog_owners o JOIN users u ON u.id=o.user_id
           WHERE o.dog_id=:d AND o.role='co-owner' ORDER BY o.created_at, o.user_id""", d=dog_id)]


def pending_invites(dog_id):
    t = A.now()
    return [dict(id=r[0], email=r[1], created_at=r[2], expires_at=r[3]) for r in A.q(
        """SELECT id, email, created_at, expires_at FROM dog_invites WHERE dog_id=:d AND accepted_at IS NULL
           AND revoked_at IS NULL AND expires_at>:t ORDER BY id""", d=dog_id, t=t)]


def create_invite(dog, inviter_id, email):
    """Returns the raw token (only ever put in the emailed link). Raises InviteError:
    'owner' (only the primary owner invites), 'self', 'already' (already an owner), 'pending' (open invite to that
    email), 'full' (MAX_COOWNERS co-owners + open invites)."""
    email = (email or "").strip().lower()
    if role(dog, inviter_id) != "owner":
        raise InviteError("owner")
    me = A.one("SELECT email FROM users WHERE id=:u", u=inviter_id)
    if me and me[0].lower() == email:
        raise InviteError("self")
    u = A.one("SELECT id FROM users WHERE email=:e", e=email)
    if u and can_manage(dog, u[0]):
        raise InviteError("already")
    open_ = pending_invites(dog["id"])
    if any(i["email"] == email for i in open_):
        raise InviteError("pending")
    if len(coowners(dog["id"])) + len(open_) >= MAX_COOWNERS:
        raise InviteError("full")
    raw, t = secrets.token_urlsafe(32), A.now()
    A.q("""INSERT INTO dog_invites(dog_id,inviter_user_id,email,token_hash,created_at,expires_at)
           VALUES(:d,:u,:e,:h,:t,:x)""", d=dog["id"], u=inviter_id, e=email, h=A.sha(raw), t=t, x=t + INVITE_TTL)
    return raw


def peek(raw):
    """(state, invite dict) with state 'ok', 'used', 'revoked', 'expired' or 'bad'."""
    if not raw or len(raw) > 100:
        return "bad", None
    r = A.one("""SELECT id, dog_id, inviter_user_id, email, expires_at, accepted_at, revoked_at FROM dog_invites
                 WHERE token_hash=:h""", h=A.sha(raw))
    if not r:
        return "bad", None
    inv = dict(id=r[0], dog_id=r[1], inviter_user_id=r[2], email=r[3], expires_at=r[4])
    if r[5]:
        return "used", inv
    if r[6]:
        return "revoked", inv
    if r[4] <= A.now() or not A.dog_by_id(r[1]):
        return "expired", inv
    return "ok", inv


def accept(raw, user_id):
    """Use the invite for this account: adds it as a co-owner (nothing to add when it already owns the dog).
    Returns the dog. Raises InviteError(state) when the link can't be used, or 'full'."""
    state, inv = peek(raw)
    if state != "ok":
        raise InviteError(state)
    d = A.dog_by_id(inv["dog_id"])
    if not can_manage(d, user_id) and len(coowners(d["id"])) >= MAX_COOWNERS:
        raise InviteError("full")
    t = A.now()
    if not A.q("""UPDATE dog_invites SET accepted_at=:t, accepted_user_id=:u WHERE id=:i AND accepted_at IS NULL
                  AND revoked_at IS NULL RETURNING id""", t=t, u=user_id, i=inv["id"]):
        raise InviteError("used")   # lost a race with a second click
    if not can_manage(d, user_id):
        A.q("INSERT INTO dog_owners(dog_id,user_id,role,created_at) VALUES(:d,:u,'co-owner',:t)", d=d["id"], u=user_id, t=t)
    return d


def revoke(dog_id, invite_id):
    return bool(A.q("""UPDATE dog_invites SET revoked_at=:t WHERE id=:i AND dog_id=:d AND accepted_at IS NULL
                       AND revoked_at IS NULL RETURNING id""", t=A.now(), i=invite_id, d=dog_id))


def remove(dog_id, user_id):
    """Remove a co-owner (or a co-owner leaving). The primary owner can't be removed this way."""
    return bool(A.q("DELETE FROM dog_owners WHERE dog_id=:d AND user_id=:u AND role='co-owner' RETURNING user_id", d=dog_id, u=user_id))


def purge_dog(dog_id):
    A.q("DELETE FROM dog_owners WHERE dog_id=:d", d=dog_id)
    A.q("DELETE FROM dog_invites WHERE dog_id=:d", d=dog_id)


def purge_user(user_id):
    """Account deletion: drop co-ownerships and the user's sent invites. Dogs they're the primary owner of go to their
    longest-standing co-owner when there is one (returns those dog ids); the rest are deleted by A.delete_user."""
    kept = []
    for (dog_id,) in A.q("SELECT id FROM dogs WHERE user_id=:u", u=user_id):
        heir = A.one("SELECT user_id FROM dog_owners WHERE dog_id=:d AND role='co-owner' ORDER BY created_at, user_id LIMIT 1", d=dog_id)
        if heir:
            A.q("UPDATE dogs SET user_id=:h WHERE id=:d", h=heir[0], d=dog_id)
            A.q("UPDATE dog_owners SET role='owner' WHERE dog_id=:d AND user_id=:h", d=dog_id, h=heir[0])
            A.q("DELETE FROM dog_owners WHERE dog_id=:d AND user_id=:u", d=dog_id, u=user_id)
            A.q("UPDATE dog_invites SET revoked_at=:t WHERE dog_id=:d AND accepted_at IS NULL AND revoked_at IS NULL", t=A.now(), d=dog_id)
            kept.append(dog_id)
    A.q("DELETE FROM dog_owners WHERE user_id=:u AND role='co-owner'", u=user_id)
    A.q("UPDATE dog_invites SET revoked_at=:t WHERE inviter_user_id=:u AND accepted_at IS NULL AND revoked_at IS NULL", t=A.now(), u=user_id)
    return kept
