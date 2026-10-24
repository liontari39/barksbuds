"""Waitlist confirmation emails for BarksBuds (provider-agnostic, stdlib only).

Sending is OFF unless configured. Env vars:
  EMAIL_PROVIDER    brevo | resend | mailjet | file   (optional; guessed from the key: xkeysib- = brevo, re_ = resend)
  EMAIL_API_KEY     provider API key (mailjet: "APIKEY:SECRETKEY"). Not needed for EMAIL_PROVIDER=file.
  EMAIL_FROM        verified sender address, e.g. barksbuds.hello@gmail.com (later hello@barksbuds.com)
  EMAIL_FROM_NAME   display name (default "BarksBuds")
  EMAIL_REPLY_TO    optional reply-to address (default: EMAIL_FROM)
  UNSUBSCRIBE_SECRET optional HMAC secret for remove-me links (default: derived from ADMIN_KEY)
EMAIL_PROVIDER=file writes each message to $DATA_DIR/outbox/ instead of sending (local testing).
Emails are sent on a background thread, never block or fail a signup, and are only sent for new signups.
"""
import base64, hashlib, hmac, html, json, os, re, threading, time, urllib.error, urllib.request
from datetime import datetime
from urllib.parse import quote

API_KEY = os.environ.get("EMAIL_API_KEY", "").strip()
FROM = os.environ.get("EMAIL_FROM", "").strip()
FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "").strip() or "BarksBuds"
REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "").strip() or FROM
_prov = os.environ.get("EMAIL_PROVIDER", "").strip().lower()
if not _prov and API_KEY:
    _prov = "brevo" if API_KEY.startswith("xkeysib-") else "resend" if API_KEY.startswith("re_") else ""
PROVIDER = _prov
_secret = os.environ.get("UNSUBSCRIBE_SECRET", "") or os.environ.get("ADMIN_KEY", "")
UNSUB_KEY = hmac.new(_secret.encode(), b"barksbuds-unsubscribe-v1", hashlib.sha256).digest() if _secret else b""
OUTBOX = os.path.join(os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), "outbox")


def enabled():
    if PROVIDER == "file":
        return bool(FROM)
    return PROVIDER in ("brevo", "resend", "mailjet") and bool(API_KEY and FROM)


def status():
    if enabled():
        return f"on ({PROVIDER})"
    if PROVIDER or API_KEY or FROM:
        return "off (incomplete config: need EMAIL_API_KEY, EMAIL_FROM and a known EMAIL_PROVIDER)"
    return "off (not configured)"


def unsub_token(email):
    if not UNSUB_KEY:
        return ""
    return hmac.new(UNSUB_KEY, email.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]


def check_token(email, token):
    good = unsub_token(email)
    return bool(good and token) and hmac.compare_digest(good, token)


def _mask(email):
    user, _, dom = email.partition("@")
    return (user[:1] + "***@" + dom) if dom else "***"


def unsubscribe_url(base, email):
    t = unsub_token(email)
    if t:
        return f"{base}/unsubscribe?e={quote(email)}&t={t}"
    return f"mailto:{REPLY_TO}?subject={quote('Remove me from the BarksBuds waitlist')}" if REPLY_TO else ""


def several(dog):
    """True when the dog name field holds more than one dog, e.g. 'Lily & Maggie', 'Lily and Maggie', 'Lily, Maggie'."""
    return bool(re.search(r"\s(?:&|\+|and)\s|,|/", dog, re.I))


def build(base, first, dog, email):
    """Return (subject, html, text, unsubscribe_url) for the welcome email. Works for one dog or several."""
    e = html.escape
    multi = several(dog)
    verb = "are" if multi else "is"
    profile = f"Profiles for {dog}" if multi else f"A profile for {dog}"
    runs, home, share = f"{base}/runs", f"{base}/", f"{base}/#join"
    unsub = unsubscribe_url(base, email)
    subject = f"Welcome to the pack, {first}! {dog} {verb} on the BarksBuds list"
    share_mail = "mailto:?subject=" + quote("Join me on BarksBuds") + "&body=" + quote(
        f"I just joined the BarksBuds waitlist with {dog}. It's a new community for dog people, "
        f"with a map of every dog run around NYC, Long Island and Westchester: {home}")
    text = f"""Hi {first},

Woof! You and {dog} are on the BarksBuds waitlist.

BarksBuds is a new local network for dog people: find the best dog runs near you, meet the regulars, and turn "see you at the park" into real meetups and playdates.

Explore the dog run map now (NYC, Long Island & Westchester): {runs}

What's coming
- Meetups and playdates at your favorite run, starting on the North Shore
- {profile}, with photos and the friends they make
- Tips and recommendations from dog people you trust

Know someone whose dog needs more friends? Share BarksBuds: {home}

See you at the dog run!
The BarksBuds team

Our logo is inspired by Jack, a Cairn terrier who lived to 17.

You're getting this because {email} joined the waitlist at {home}
Remove me from the list: {unsub}
"""
    btn = ("display:inline-block;background:#FBB321;color:#141414;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;"
           "font-size:17px;text-decoration:none;padding:14px 26px;border-radius:999px;border-bottom:4px solid #C98A0C")
    li = "padding:10px 0;border-top:1px solid #EADBB9;font-size:15px;line-height:1.5;color:#2a2622"
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(subject)}</title>
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@700;800&family=Caveat+Brush&family=Nunito:wght@400;700&display=swap" rel="stylesheet">
<style>@media (max-width:620px){{.wrap{{padding:0 !important}} .card{{border-radius:0 !important}} .pad{{padding:24px 22px !important}} h1{{font-size:28px !important}}}}</style>
</head>
<body style="margin:0;padding:0;background:#FFF8EA;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">You and {e(dog)} are on the list. Here's the dog run map while you wait.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFF8EA;">
<tr><td class="wrap" align="center" style="padding:28px 12px;">
<table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid #EADBB9;">
<tr><td style="background:#141414;padding:22px 32px;" class="pad">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
  <td style="vertical-align:middle;"><img src="{base}/img/icon-180.png" width="52" height="52" alt="" style="display:block;border-radius:14px;border:3px solid #FBB321;"></td>
  <td style="vertical-align:middle;padding-left:14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:26px;color:#ffffff;">BarksBuds</td>
  </tr></table>
</td></tr>
<tr><td class="pad" style="padding:34px 36px 8px;font-family:Nunito,Arial,sans-serif;color:#2a2622;">
  <p style="margin:0 0 4px;font-family:'Caveat Brush',cursive;font-size:24px;color:#C8201E;">welcome to the pack</p>
  <h1 style="margin:0 0 14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:32px;line-height:1.1;color:#141414;">Woof, {e(first)}! You and {e(dog)} are on the list.</h1>
  <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">BarksBuds is a new local network for dog people. Find the best dog runs near you, meet the regulars, and turn &ldquo;see you at the park&rdquo; into real meetups and playdates.</p>
  <p style="margin:0 0 22px;font-size:16px;line-height:1.6;">While you wait, our <strong>dog run map is already live</strong>, with fenced runs, small-dog areas and hours across NYC, Long Island &amp; Westchester.</p>
  <p style="margin:0 0 30px;"><a href="{runs}" style="{btn}">Find a dog run near you &rarr;</a></p>
</td></tr>
<tr><td class="pad" style="padding:0 36px 8px;font-family:Nunito,Arial,sans-serif;">
  <h2 style="margin:0 0 6px;font-family:'Baloo 2',Arial,sans-serif;font-size:21px;color:#141414;">What's coming</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td style="{li}">&#128197;&nbsp; <strong>Meetups &amp; playdates</strong> at your favorite run, starting on the North Shore</td></tr>
  <tr><td style="{li}">&#128062;&nbsp; <strong>{e(profile)}</strong>, with photos and the friends they make</td></tr>
  <tr><td style="{li}">&#128172;&nbsp; <strong>Tips &amp; recs</strong> from dog people you trust</td></tr>
  </table>
</td></tr>
<tr><td class="pad" style="padding:22px 36px 30px;font-family:Nunito,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFE7A8;border-radius:18px;">
  <tr><td style="padding:20px 22px;font-size:15px;line-height:1.55;color:#2a2622;">
    <strong style="font-family:'Baloo 2',Arial,sans-serif;font-size:18px;color:#141414;">Know a dog who needs more friends?</strong><br>
    The more neighbors join, the sooner meetups open near you. <a href="{e(share_mail)}" style="color:#C8201E;font-weight:700;">Invite a friend</a> or share <a href="{home}" style="color:#C8201E;font-weight:700;">{e(home.split('//')[-1].rstrip('/'))}</a>.
  </td></tr></table>
  <p style="margin:24px 0 0;font-family:'Caveat Brush',cursive;font-size:24px;color:#C8201E;">See you at the dog run!</p>
  <p style="margin:2px 0 0;font-size:15px;color:#625a50;">The BarksBuds team</p>
</td></tr>
<tr><td class="pad" style="background:#141414;padding:20px 36px;font-family:Nunito,Arial,sans-serif;font-size:13px;line-height:1.6;color:#C9BFAF;">
  Our logo is inspired by Jack, a Cairn terrier who lived to 17.<br>
  You're getting this because {e(email)} joined the BarksBuds waitlist. We never sell or share your info.<br>
  {f'<a href="{e(unsub)}" style="color:#FBB321;">Remove me from the list</a>' if unsub else ''}
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, body, text, unsub


def _post(url, payload, headers):
    """POST JSON; returns 'HTTP <code>' plus the provider's message id when it gives one."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "BarksBuds/1.0", **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        code, raw = r.status, r.read(4000)
    mid = ""
    try:
        d = json.loads(raw or b"{}")
        mid = d.get("messageId") or d.get("id") or ""  # brevo / resend
        if not mid and d.get("Messages"):  # mailjet
            mid = str(d["Messages"][0].get("To", [{}])[0].get("MessageUUID", ""))
    except Exception:
        pass
    return f"HTTP {code}" + (f", id {mid}" if mid else "")


def _send(to, subject, body, text, unsub):
    hdrs = {}
    if unsub:
        hdrs["List-Unsubscribe"] = f"<{unsub}>"
        if unsub.startswith("http"):
            hdrs["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if PROVIDER == "file":
        os.makedirs(OUTBOX, exist_ok=True)
        stem = os.path.join(OUTBOX, datetime.now().strftime("%Y%m%d-%H%M%S-") + hashlib.sha1(to.encode()).hexdigest()[:8])
        with open(stem + ".html", "w", encoding="utf-8") as f:
            f.write(body)
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump({"to": to, "from": f"{FROM_NAME} <{FROM}>", "reply_to": REPLY_TO, "subject": subject,
                       "headers": hdrs, "text": text}, f, indent=1)
        return "HTTP 200 (written to outbox)"
    if PROVIDER == "brevo":
        p = {"sender": {"name": FROM_NAME, "email": FROM}, "to": [{"email": to}], "subject": subject,
             "htmlContent": body, "textContent": text, "headers": hdrs, "tags": ["waitlist-welcome"]}
        if REPLY_TO:
            p["replyTo"] = {"email": REPLY_TO}
        return _post("https://api.brevo.com/v3/smtp/email", p, {"api-key": API_KEY})
    if PROVIDER == "resend":
        p = {"from": f"{FROM_NAME} <{FROM}>", "to": [to], "subject": subject, "html": body, "text": text, "headers": hdrs}
        if REPLY_TO:
            p["reply_to"] = REPLY_TO
        return _post("https://api.resend.com/emails", p, {"Authorization": "Bearer " + API_KEY})
    if PROVIDER == "mailjet":
        m = {"From": {"Email": FROM, "Name": FROM_NAME}, "To": [{"Email": to}], "Subject": subject,
             "HTMLPart": body, "TextPart": text, "Headers": hdrs}
        if REPLY_TO:
            m["ReplyTo"] = {"Email": REPLY_TO}
        auth = base64.b64encode(API_KEY.encode()).decode()
        return _post("https://api.mailjet.com/v3.1/send", {"Messages": [m]}, {"Authorization": "Basic " + auth})
    raise RuntimeError("unknown provider")


_sent = set()
_lock = threading.Lock()


def send_welcome_async(base, first, dog, email):
    """Fire-and-forget welcome email. Returns True if a send was queued."""
    if not enabled():
        print(f"email: skipped welcome for {_mask(email)} ({status()})", flush=True)
        return False
    key = email.strip().lower()
    with _lock:
        if key in _sent:  # belt and braces: duplicates never reach here, but never double-send in one process
            return False
        _sent.add(key)

    def run():
        subject, body, text, unsub = build(base, first, dog, email)
        for attempt in range(3):
            try:
                result = _send(email, subject, body, text, unsub)
                print(f"email: welcome sent to {_mask(email)} via {PROVIDER} ({result})", flush=True)
                return
            except urllib.error.HTTPError as e:
                retry = e.code == 429 or e.code >= 500
                detail = ""
                try:
                    detail = e.read(300).decode("utf-8", "replace").replace(API_KEY, "***") if API_KEY else ""
                except Exception:
                    pass
                print(f"email: {PROVIDER} HTTP {e.code} for {_mask(email)} {detail}".rstrip(), flush=True)
                if not retry:
                    return
            except Exception as e:
                print(f"email: send error for {_mask(email)}: {type(e).__name__}", flush=True)
            time.sleep(2 * (attempt + 1))
        print(f"email: gave up on welcome for {_mask(email)}", flush=True)

    threading.Thread(target=run, name="welcome-email", daemon=True).start()
    return True
