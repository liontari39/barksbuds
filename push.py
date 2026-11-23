"""Push for meetup reminders and run check-ins (opt-in, off by default).

Web Push uses VAPID keys from env (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CONTACT).
Native iOS/Android push uses APNs/FCM env vars (see native_* helpers). If a channel's
keys are missing, that channel is off and nothing is sent on it. Private keys are never
logged or returned to the client.
"""
import json, os, struct, threading, time, urllib.error, urllib.request
from urllib.parse import urlsplit, urlencode
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
    store.q(f"""CREATE TABLE IF NOT EXISTS push_devices(
        id {ID}, user_id {INT} NOT NULL, platform TEXT NOT NULL,
        token TEXT NOT NULL UNIQUE,
        meetups {INT} NOT NULL DEFAULT 0, checkins {INT} NOT NULL DEFAULT 0,
        created_at {INT} NOT NULL, updated_at {INT} NOT NULL)""")
    store.q("CREATE INDEX IF NOT EXISTS push_devices_user_idx ON push_devices(user_id)")


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def user_flags(uid):
    """Whether this member has any live subscription or device token for each kind."""
    r = one("SELECT COALESCE(MAX(meetups),0), COALESCE(MAX(checkins),0) FROM push_subscriptions WHERE user_id=:u", u=uid)
    d = one("SELECT COALESCE(MAX(meetups),0), COALESCE(MAX(checkins),0) FROM push_devices WHERE user_id=:u", u=uid)
    return {
        "meetups": bool((r and r[0]) or (d and d[0])),
        "checkins": bool((r and r[1]) or (d and d[1])),
    }


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
    """Send a user-visible push to this member's web subscriptions and native devices.

    Web Push is skipped when VAPID keys are missing. Native (APNs/FCM) is skipped
    when those env vars are missing. Tokens stay stored either way.
    """
    if not uid:
        return 0
    n = 0
    if enabled():
        payload = json.dumps({"title": title, "body": body, "url": url, "icon": "/img/icon-192.png?v=jack5"})
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
    n += notify_devices(uid, kind, title, body, url)
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


# ---------------------------------------------------------------- native devices (APNs / FCM)
PLATFORMS = ("ios", "android")
_TOKEN_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")


def native_configured():
    """True when at least one native transport (APNs or FCM) is configured."""
    return apns_configured() or fcm_configured()


def apns_configured():
    key = (os.environ.get("APNS_KEY_P8") or os.environ.get("APNS_KEY_PATH") or "").strip()
    return bool((os.environ.get("APNS_KEY_ID") or "").strip()
                and (os.environ.get("APNS_TEAM_ID") or "").strip()
                and key)


def fcm_configured():
    if (os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or "").strip():
        return True
    return bool((os.environ.get("FCM_PROJECT_ID") or "").strip()
                and (os.environ.get("FCM_CLIENT_EMAIL") or "").strip()
                and (os.environ.get("FCM_PRIVATE_KEY") or "").strip())


def apns_topic():
    return (os.environ.get("APNS_TOPIC") or "app.barksbuds").strip() or "app.barksbuds"


def apns_production():
    v = (os.environ.get("APNS_PRODUCTION") or "").strip().lower()
    return v in ("1", "true", "yes", "prod", "production")


def _valid_token(token):
    token = (token or "").strip()
    if not (8 <= len(token) <= 4096) or any(c not in _TOKEN_CHARS for c in token):
        return ""
    return token


def save_device(uid, platform, token, kinds=None):
    """Upsert an APNs or FCM device token. kinds defaults to none (stored, flags off)."""
    if not uid:
        return False
    platform = (platform or "").strip().lower()
    if platform not in PLATFORMS:
        return False
    token = _valid_token(token)
    if not token:
        return False
    kinds = set(kinds or [])
    meetups = 1 if "meetups" in kinds else 0
    checkins = 1 if "checkins" in kinds else 0
    t = A.now()
    existing = one("SELECT id, user_id FROM push_devices WHERE token=:t", t=token)
    if existing:
        if existing[1] != uid:
            q("DELETE FROM push_devices WHERE id=:i", i=existing[0])
        else:
            q("""UPDATE push_devices SET platform=:p, meetups=:m, checkins=:c, updated_at=:t
                 WHERE token=:tok""", p=platform, m=meetups, c=checkins, t=t, tok=token)
            return True
    q("""INSERT INTO push_devices(user_id,platform,token,meetups,checkins,created_at,updated_at)
         VALUES(:u,:p,:tok,:m,:c,:t,:t)""", u=uid, p=platform, tok=token, m=meetups, c=checkins, t=t)
    return True


def drop_device(uid, token=None):
    """Remove one device token or all of this member's native devices."""
    if token:
        q("DELETE FROM push_devices WHERE user_id=:u AND token=:t", u=uid, t=token)
    else:
        q("DELETE FROM push_devices WHERE user_id=:u", u=uid)
    return True


def device_recipients(uid, kind):
    if kind not in KINDS:
        return []
    return [dict(id=r[0], platform=r[1], token=r[2])
            for r in q(f"SELECT id, platform, token FROM push_devices WHERE user_id=:u AND {kind}=1", u=uid)]


def notify_devices(uid, kind, title, body, url="/"):
    """Send to native devices. No-op when APNs/FCM env is missing or there are no tokens."""
    if not uid or kind not in KINDS:
        return 0
    recs = device_recipients(uid, kind)
    if not recs:
        return 0
    n = 0
    for dev in recs:
        try:
            ok, status = send_device(dev, title, body, url)
        except Exception as ex:
            print(f"push: native send failed ({type(ex).__name__})", flush=True)
            ok, status = False, 0
        if ok:
            n += 1
        elif status in (404, 410):
            q("DELETE FROM push_devices WHERE id=:i", i=dev["id"])
    return n


def send_device(dev, title, body, url="/"):
    """Dispatch one native notification. Returns (ok, http_status). Never logs the token."""
    platform = dev.get("platform")
    if platform == "ios":
        if not apns_configured():
            return False, 0
        return send_apns(dev["token"], title, body, url)
    if platform == "android":
        if not fcm_configured():
            return False, 0
        return send_fcm(dev["token"], title, body, url)
    return False, 0


def _load_p8():
    """Load the APNs .p8 private key from APNS_KEY_PATH or APNS_KEY_P8. Never logs it."""
    from cryptography.hazmat.primitives import serialization
    path = (os.environ.get("APNS_KEY_PATH") or "").strip()
    raw = (os.environ.get("APNS_KEY_P8") or "").strip()
    if path:
        data = Path_read(path)
    elif raw:
        data = raw.replace("\\n", "\n").encode() if "BEGIN" in raw else raw.encode()
        if b"BEGIN" not in data:
            # Treat as raw PEM body without headers.
            data = b"-----BEGIN PRIVATE KEY-----\n" + raw.encode() + b"\n-----END PRIVATE KEY-----\n"
    else:
        raise ValueError("no APNs key")
    return serialization.load_pem_private_key(data, password=None)


def Path_read(path):
    with open(path, "rb") as f:
        return f.read()


def _apns_jwt():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_id = (os.environ.get("APNS_KEY_ID") or "").strip()
    team = (os.environ.get("APNS_TEAM_ID") or "").strip()
    priv = _load_p8()
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")))
    payload = _b64u(json.dumps({"iss": team, "iat": now}, separators=(",", ":")))
    msg = f"{header}.{payload}".encode()
    r, s = decode_dss_signature(priv.sign(msg, ec.ECDSA(hashes.SHA256())))
    return f"{header}.{payload}.{_b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def send_apns(token, title, body, url="/"):
    """POST one alert to APNs. Requires HTTP/2 (optional httpx). Returns (ok, status)."""
    try:
        import httpx
    except ImportError:
        print("push: APNs skipped (install httpx with HTTP/2 to enable sending)", flush=True)
        return False, 0
    host = "api.push.apple.com" if apns_production() else "api.sandbox.push.apple.com"
    payload = json.dumps({
        "aps": {"alert": {"title": title, "body": body}, "sound": "default", "badge": 1},
        "url": url,
    })
    headers = {
        "authorization": f"bearer {_apns_jwt()}",
        "apns-topic": apns_topic(),
        "apns-push-type": "alert",
        "apns-priority": "10",
        "content-type": "application/json",
    }
    url_ = f"https://{host}/3/device/{token}"
    try:
        with httpx.Client(http2=True, timeout=10) as client:
            resp = client.post(url_, content=payload.encode("utf-8"), headers=headers)
        return 200 <= resp.status_code < 300, resp.status_code
    except Exception as ex:
        print(f"push: APNs request failed ({type(ex).__name__})", flush=True)
        return False, 0


def _fcm_account():
    """Return a service-account dict, or raise. Never logs the private key."""
    path = (os.environ.get("FCM_SERVICE_ACCOUNT_FILE") or "").strip()
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data.get("private_key") or not data.get("client_email"):
            raise ValueError("bad FCM service account file")
        return data
    return {
        "project_id": (os.environ.get("FCM_PROJECT_ID") or "").strip(),
        "client_email": (os.environ.get("FCM_CLIENT_EMAIL") or "").strip(),
        "private_key": (os.environ.get("FCM_PRIVATE_KEY") or "").replace("\\n", "\n").strip(),
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def _fcm_access_token(account):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = int(time.time())
    token_uri = account.get("token_uri") or "https://oauth2.googleapis.com/token"
    header = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")))
    claim = _b64u(json.dumps({
        "iss": account["client_email"],
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }, separators=(",", ":")))
    msg = f"{header}.{claim}".encode()
    key = serialization.load_pem_private_key(account["private_key"].encode(), password=None)
    sig = _b64u(key.sign(msg, padding.PKCS1v15(), hashes.SHA256()))
    assertion = f"{header}.{claim}.{sig}"
    data = urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    req = urllib.request.Request(token_uri, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        out = json.loads(resp.read().decode())
    tok = out.get("access_token")
    if not tok:
        raise ValueError("no FCM access token")
    return tok


def send_fcm(token, title, body, url="/"):
    """POST one FCM HTTP v1 message. Returns (ok, status). Never logs the token."""
    account = _fcm_account()
    project = (account.get("project_id") or os.environ.get("FCM_PROJECT_ID") or "").strip()
    if not project:
        return False, 0
    access = _fcm_access_token(account)
    payload = json.dumps({
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {"url": url},
            "android": {"priority": "HIGH"},
        }
    })
    endpoint = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    req = urllib.request.Request(endpoint, data=payload.encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json; charset=utf-8",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300, resp.status
    except urllib.error.HTTPError as ex:
        return False, ex.code

