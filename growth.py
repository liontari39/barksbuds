"""Member invite links and helper bits for share previews and run flyers.

Invite links are always on. A visitor who opens /join/<id>-<hmac> (or any page with ?inv=)
gets a first-party cookie. When they create a new account we store one row attributing
that signup to the inviter. We never record visits or emails — only completed signups —
and the inviter only sees a count, never names or emails. Existing members are not counted.
The link is HMAC'd so member ids are not enumerable.
"""
import hmac, re, time

import accounts as A

COOKIE = "bb_inv"
COOKIE_TTL = 30 * 24 * 3600
TOKEN_RE = re.compile(r"^(\d+)-([0-9a-f]{20})$")


def invite_sig(uid):
    return hmac.new(A.SECRET, f"invite:{int(uid)}".encode(), "sha256").hexdigest()[:20]


def invite_token(uid):
    return f"{int(uid)}-{invite_sig(uid)}"


def invite_path(uid):
    return "/join/" + invite_token(uid)


def parse_token(token):
    m = TOKEN_RE.fullmatch((token or "").strip().lower())
    if not m:
        return None
    uid = int(m.group(1))
    if not hmac.compare_digest(m.group(2), invite_sig(uid)):
        return None
    return uid


def init_schema(store):
    INT = "BIGINT" if store.kind == "postgres" else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS member_invite_signups(
        user_id {INT} PRIMARY KEY, inviter_id {INT} NOT NULL, created_at {INT} NOT NULL)""")
    store.q("CREATE INDEX IF NOT EXISTS member_invite_signups_inviter_idx ON member_invite_signups(inviter_id)")


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def cookie_value(uid):
    return invite_token(uid)


def parse_cookie(val):
    return parse_token(val or "")


def cookie_from_header(header):
    from http.cookies import SimpleCookie
    try:
        c = SimpleCookie(); c.load(header or "")
        return c[COOKIE].value if COOKIE in c else ""
    except Exception:
        return ""


def record_signup(user_id, cookie_val):
    """Attribute a brand-new account to a member invite. Returns the inviter id or None."""
    inviter = parse_cookie(cookie_val)
    if not inviter or inviter == user_id:
        return None
    if not one("SELECT id FROM users WHERE id=:i", i=inviter):
        return None
    if one("SELECT user_id FROM member_invite_signups WHERE user_id=:u", u=user_id):
        return None
    q("INSERT INTO member_invite_signups(user_id, inviter_id, created_at) VALUES(:u,:i,:t)",
      u=user_id, i=inviter, t=int(time.time()))
    return inviter


def signup_count(inviter_id):
    r = one("SELECT COUNT(*) FROM member_invite_signups WHERE inviter_id=:i", i=inviter_id)
    return int(r[0] if r else 0)


def qr_svg(url, scale=8):
    """Inline SVG QR code for a public URL. No labels, just the code."""
    import segno
    return segno.make(url, error="m").svg_inline(scale=scale, border=2)
