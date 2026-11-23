"""Members-only owner cards: signed URL tokens and first-name display.

Dogs stay the face of the site. User ids are sequential, so card URLs use
/humans/<id>-<hmac> (20 hex of sha256(SECRET, "human:<id>")) and are not
enumerable without the app secret. Raw /humans/<id> is rejected.
"""
import hashlib, hmac, re

import accounts as A

TOKEN_RE = re.compile(r"^(\d+)-([0-9a-f]{20})$")


def first_name(display_name):
    """First token only — never a surname."""
    n = (display_name or "").strip()
    return n.split()[0] if n else ""


def card_sig(uid):
    return hmac.new(A.SECRET, f"human:{int(uid)}".encode(), hashlib.sha256).hexdigest()[:20]


def card_token(uid):
    uid = int(uid)
    return f"{uid}-{card_sig(uid)}"


def card_path(uid):
    return "/humans/" + card_token(uid)


def parse_token(s):
    """User id if the token is valid, else None. Compare is constant-time."""
    m = TOKEN_RE.fullmatch(s or "")
    if not m:
        return None
    uid = int(m.group(1))
    if not hmac.compare_digest(card_sig(uid), m.group(2)):
        return None
    return uid
