"""Helpers for the BarksBuds native app (Capacitor): CORS origins, well-known
App Links / Associated Domains files, and cookie SameSite policy.

The supported WebView mode loads https://barksbuds.app (or BARKSBUDS_SERVER_URL)
as a first-party origin, so the existing SameSite=Lax session cookies work.
Third-party / local-origin mode (capacitor://localhost talking to the API) is
opt-in via APP_COOKIE_SAMESITE=none and still uses the CSRF token.

Well-known files stay 404 until Mike adds the env vars after creating store
accounts. This module never prints those values.
"""
import json
import os
from urllib.parse import urlsplit

# Official app origins. A random website cannot set these Origin values.
DEFAULT_ORIGINS = (
    "capacitor://localhost",
    "ionic://localhost",
    "https://localhost",
    "http://localhost",
    "https://localhost:443",
    "http://localhost:80",
)


def server_url():
    return (os.environ.get("BARKSBUDS_SERVER_URL") or os.environ.get("SITE_URL") or "https://barksbuds.app").strip().rstrip("/")


def cookie_samesite():
    """Lax by default (first-party WebView). 'none' requires Secure."""
    v = (os.environ.get("APP_COOKIE_SAMESITE") or "Lax").strip().lower()
    if v == "none":
        return "None"
    return "Lax"


def extra_origins():
    raw = (os.environ.get("CAPACITOR_ORIGINS") or "").strip()
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        p = part.strip().rstrip("/")
        if p:
            out.append(p)
    return out


def allowed_origins():
    return list(DEFAULT_ORIGINS) + extra_origins()


def origin_allowed(origin, host=""):
    """True when Origin is first-party (matches Host) or a listed Capacitor origin."""
    if not origin or origin == "null":
        return False
    origin = origin.strip()
    if host and urlsplit(origin).netloc == host:
        return True
    return origin.rstrip("/") in allowed_origins()


def cors_headers(origin, host="", existing=None):
    """Return headers to merge when the request Origin may use credentials."""
    headers = dict(existing or {})
    if not origin_allowed(origin, host):
        return headers
    headers["Access-Control-Allow-Origin"] = origin
    headers["Access-Control-Allow-Credentials"] = "true"
    headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token, X-Requested-With"
    headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    headers["Access-Control-Max-Age"] = "86400"
    vary = headers.get("Vary", "")
    if "Origin" not in [p.strip() for p in vary.split(",") if p.strip()]:
        headers["Vary"] = (vary + ", Origin").strip(", ").lstrip(", ")
    return headers


def ios_team_id():
    return (os.environ.get("IOS_TEAM_ID") or "").strip()


def ios_bundle_id():
    return (os.environ.get("IOS_BUNDLE_ID") or "app.barksbuds").strip() or "app.barksbuds"


def android_package():
    return (os.environ.get("ANDROID_PACKAGE") or "app.barksbuds").strip() or "app.barksbuds"


def android_cert_fps():
    """SHA-256 cert fingerprints, colon-optional hex, from a comma/space/newline list."""
    raw = (os.environ.get("ANDROID_CERT_SHA256") or "").strip()
    if not raw:
        return []
    out = []
    for part in raw.replace(";", ",").replace("\n", ",").split(","):
        hexish = "".join(ch for ch in part.strip().upper() if ch in "0123456789ABCDEF")
        if len(hexish) == 64:
            out.append(":".join(hexish[i:i + 2] for i in range(0, 64, 2)))
    return out


def apple_app_site_association():
    """JSON bytes, or None if Team ID is not configured."""
    team = ios_team_id()
    if not team:
        return None
    app_id = f"{team}.{ios_bundle_id()}"
    body = {
        "applinks": {
            "apps": [],
            "details": [{
                "appID": app_id,
                "paths": [
                    "/auth", "/auth/*",
                    "/signin", "/signin/*",
                    "/me", "/me/*",
                    "/runs", "/runs/*",
                    "/meetups", "/meetups/*",
                    "/dogs", "/dogs/*",
                    "/",
                ],
            }],
        },
        "webcredentials": {"apps": [app_id]},
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def assetlinks():
    """JSON bytes, or None if no signing-cert fingerprints are configured."""
    fps = android_cert_fps()
    if not fps:
        return None
    body = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": android_package(),
            "sha256_cert_fingerprints": fps,
        },
    }]
    return json.dumps(body, separators=(",", ":")).encode("utf-8")
