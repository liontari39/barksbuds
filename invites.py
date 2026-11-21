"""Per-partner invite links (?ref=<partner>) with sign-up attribution. OFF unless INVITES_ENABLED=1.

How it works when enabled:
- A visitor lands on any page with ?ref=<slug>, where <slug> is a partner listed in INVITE_PARTNERS
  (env: "slug=Display name;slug2=Other name"). We set a first-party cookie bb_ref (30 days, HttpOnly, SameSite=Lax).
  Unknown or malformed refs are ignored. The first partner wins; a later ?ref doesn't overwrite it.
- When that visitor creates a new account (first magic-link sign-in), we store one row in signup_refs
  (user id, partner slug, when they first landed, when they signed up) and clear the cookie. Existing members are never attributed.
- GET /admin/invites (X-Admin-Key or ?key=) returns sign-up counts per partner. No emails or names are exposed.

Database: one new table, created only when the flag is on (additive; nothing existing is altered).
While INVITES_ENABLED is off (the default) this module does nothing and touches no tables.
"""
import os
import re
import time

COOKIE = "bb_ref"
COOKIE_TTL = 30 * 24 * 3600
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
STORE = None


def enabled():
    return os.environ.get("INVITES_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def partners():
    out = {}
    for part in os.environ.get("INVITE_PARTNERS", "").split(";"):
        slug, _, name = part.partition("=")
        slug = slug.strip().lower()
        if SLUG_RE.match(slug):
            out[slug] = name.strip() or slug
    return out


def valid_ref(ref):
    ref = (ref or "").strip().lower()
    return ref if enabled() and SLUG_RE.match(ref) and ref in partners() else ""


def init_schema(store):
    """Additive only: CREATE TABLE/INDEX IF NOT EXISTS. Called at startup only when the flag is on."""
    global STORE
    STORE = store
    if not enabled():
        return False
    INT = "BIGINT" if store.kind == "postgres" else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS signup_refs(user_id {INT} PRIMARY KEY, ref TEXT NOT NULL,
        landed_at {INT}, created_at {INT} NOT NULL)""")
    store.q("CREATE INDEX IF NOT EXISTS signup_refs_ref_idx ON signup_refs(ref)")
    return True


def cookie_value(ref, landed_at=None):
    return f"{ref}.{int(landed_at or time.time())}"


def parse_cookie(val):
    ref, _, ts = (val or "").partition(".")
    ref = valid_ref(ref)
    try:
        ts = int(ts)
    except ValueError:
        ts = None
    return ref, ts


def cookie_from_header(header):
    from http.cookies import SimpleCookie
    try:
        c = SimpleCookie(); c.load(header or "")
        return c[COOKIE].value if COOKIE in c else ""
    except Exception:
        return ""


def record_signup(user_id, cookie_val):
    """Attribute a brand-new account to a partner. Returns the partner slug or ''."""
    if not enabled() or STORE is None:
        return ""
    ref, landed = parse_cookie(cookie_val)
    if not ref:
        return ""
    if STORE.q("SELECT user_id FROM signup_refs WHERE user_id=:u", u=user_id):
        return ""
    STORE.q("INSERT INTO signup_refs(user_id, ref, landed_at, created_at) VALUES(:u, :r, :l, :t)",
            u=user_id, r=ref, l=landed, t=int(time.time()))
    return ref


def counts():
    if not enabled() or STORE is None:
        return {}
    return {r[0]: int(r[1]) for r in STORE.q("SELECT ref, COUNT(*) FROM signup_refs GROUP BY ref ORDER BY ref")}
