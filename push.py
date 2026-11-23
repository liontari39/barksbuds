"""Web Push for meetup reminders and run check-ins (opt-in, off by default).

VAPID keys are read from env (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CONTACT).
If they are missing, push is disabled and the UI is hidden. The private key is never
logged or returned to the client. cryptography is used so this stays off the paid-services path.
"""
import json, os, struct, threading, time, urllib.error, urllib.request
from urllib.parse import urlsplit
import base64

import accounts as A

KINDS = ("meetups", "checkins")


def _b64u(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s):
    if not s:
        return b""
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode() if isinstance(s, str) else s)


def vapid_public():
    return (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()


def vapid_contact():
    return (os.environ.get("VAPID_CONTACT") or "mailto:hello@barksbuds.app").strip()


def vapid_private():
    return (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()


def enabled():
    return bool(vapid_public() and vapid_private())


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS push_subscriptions(
        id {ID}, user_id {INT} NOT NULL, endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL, auth TEXT NOT NULL,
        meetups {INT} NOT NULL DEFAULT 0, checkins {INT} NOT NULL DEFAULT 0,
        created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""")
    store.q("CREATE INDEX IF NOT EXISTS push_subscriptions_user_idx ON push_subscriptions(user_id)")


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def user_flags(uid):
    """Whether this member has any live subscription for each kind."""
    r = one("SELECT COALESCE(MAX(meetups),0), COALESCE(MAX(checkins),0) FROM push_subscriptions WHERE user_id=:u", u=uid)
    return {"meetups": bool(r and r[0]), "checkins": bool(r and r[1])}


def save_subscription(uid, sub, kinds=None):
    """Upsert a PushSubscription JSON (endpoint, keys.p256dh, keys.auth). kinds defaults to none (still stored, flags off)."""
    if not uid or not isinstance(sub, dict):
        return False
    endpoint = (sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    p256dh, auth = (keys.get("p256dh") or "").strip(), (keys.get("auth") or "").strip()
    if not (endpoint.startswith("https://") and p256dh and auth):
        return False
    if len(endpoint) > 2048 or len(p256dh) > 200 or len(auth) > 200:
        return False
    kinds = set(kinds or [])
    meetups = 1 if "meetups" in kinds else 0
    checkins = 1 if "checkins" in kinds else 0
    t = A.now()
    existing = one("SELECT id, user_id FROM push_subscriptions WHERE endpoint=:e", e=endpoint)
    if existing:
        if existing[1] != uid:
            q("DELETE FROM push_subscriptions WHERE id=:i", i=existing[0])
        else:
            q("""UPDATE push_subscriptions SET p256dh=:p, auth=:a, meetups=:m, checkins=:c, updated_at=:t
                 WHERE endpoint=:e""", p=p256dh, a=auth, m=meetups, c=checkins, t=t, e=endpoint)
            return True
    q("""INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,meetups,checkins,created_at,updated_at)
         VALUES(:u,:e,:p,:a,:m,:c,:t,:t)""", u=uid, e=endpoint, p=p256dh, a=auth, m=meetups, c=checkins, t=t)
    return True


def drop_subscription(uid, endpoint=None):
    """Remove one endpoint or all of this member's subscriptions."""
    if endpoint:
        q("DELETE FROM push_subscriptions WHERE user_id=:u AND endpoint=:e", u=uid, e=endpoint)
    else:
        q("DELETE FROM push_subscriptions WHERE user_id=:u", u=uid)
    return True


def recipients(uid, kind):
    if kind not in KINDS:
        return []
    return [dict(id=r[0], endpoint=r[1], p256dh=r[2], auth=r[3])
            for r in q(f"SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id=:u AND {kind}=1", u=uid)]


def notify(uid, kind, title, body, url="/"):
    """Send a user-visible push to this member's subscriptions for `kind`. No-op if push is disabled."""
    if not enabled() or not uid:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "icon": "/img/icon-192.png?v=jack5"})
    n = 0
    for sub in recipients(uid, kind):
        try:
            ok, status = send(sub, payload)
        except Exception as ex:
            print(f"push: send failed ({type(ex).__name__})", flush=True)
            ok, status = False, 0
        if ok:
            n += 1
        elif status in (404, 410):
            q("DELETE FROM push_subscriptions WHERE id=:i", i=sub["id"])
    return n


def notify_async(uid, kind, title, body, url="/"):
    threading.Thread(target=notify, args=(uid, kind, title, body, url), daemon=True).start()


# ---------------------------------------------------------------- send (RFC 8291 + VAPID)
def send(sub, payload):
    """POST an encrypted push to `sub`. Returns (ok, http_status). Never logs keys or endpoints in full."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    endpoint = sub["endpoint"]
    aud = f"{urlsplit(endpoint).scheme}://{urlsplit(endpoint).netloc}"
    token, k_header = _vapid_jwt(aud)
    body, headers = _encrypt(payload.encode("utf-8") if isinstance(payload, str) else payload,
                             _b64d(sub["p256dh"]), _b64d(sub["auth"]))
    headers.update({
        "Authorization": f"vapid t={token}, k={k_header}",
        "TTL": "86400",
        "Urgency": "normal",
        "Content-Type": "application/octet-stream",
    })
    req = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300, resp.status
    except urllib.error.HTTPError as ex:
        return False, ex.code


def _load_private():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    raw = vapid_private()
    data = _b64d(raw)
    if len(data) == 32:
        return ec.derive_private_key(int.from_bytes(data, "big"), ec.SECP256R1())
    # PEM or PKCS8
    try:
        return serialization.load_pem_private_key(raw.encode() if raw.startswith("-----") else data, password=None)
    except ValueError:
        return serialization.load_der_private_key(data, password=None)


def _pub_bytes(key):
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _vapid_jwt(aud):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    priv = _load_private()
    pub = _pub_bytes(priv)
    header = _b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")))
    now = int(time.time())
    payload = _b64u(json.dumps({"aud": aud, "exp": now + 12 * 3600, "sub": vapid_contact()}, separators=(",", ":")))
    msg = f"{header}.{payload}".encode()
    r, s = decode_dss_signature(priv.sign(msg, ec.ECDSA(hashes.SHA256())))
    token = f"{header}.{payload}.{_b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return token, _b64u(pub)


def _encrypt(plain, receiver_pub, auth_secret):
    """aes128gcm encoding (RFC 8188 / 8291) for a Web Push payload."""
    import os as _os
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    if len(receiver_pub) != 65 or receiver_pub[0] != 4:
        raise ValueError("bad p256dh")
    local = ec.generate_private_key(ec.SECP256R1())
    local_pub = _pub_bytes(local)
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_pub)
    shared = local.exchange(ec.ECDH(), peer)
    # RFC 8291: auth_info = "WebPush: info\0" + receiver_pub + local_pub
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret,
               info=b"WebPush: info\0" + receiver_pub + local_pub).derive(shared)
    salt = _os.urandom(16)
    # RFC 8188 key and nonce from IKM, keyid = local public key
    key = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\0").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\0").derive(ikm)
    # record size 4096, 1 record; pad with a trailing 0x02 delimiter (final record)
    padded = plain + b"\x02"
    ciphertext = AESGCM(key).encrypt(nonce, padded, None)
    rs = 4096
    header = salt + struct.pack("!L", rs) + bytes([len(local_pub)]) + local_pub
    headers = {
        "Content-Encoding": "aes128gcm",
        "Content-Length": str(len(header + ciphertext)),
    }
    return header + ciphertext, headers


def generate_vapid_keypair():
    """Return (public_b64, private_b64) for local/dev use. Caller must store them safely."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = _pub_bytes(priv)
    raw = priv.private_numbers().private_value.to_bytes(32, "big")
    return _b64u(pub), _b64u(raw)
