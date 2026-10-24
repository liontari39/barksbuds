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


def _err_detail(e):
    """Short, key-free summary of a provider error response (for logs)."""
    try:
        raw = e.read(600).decode("utf-8", "replace")
        d = json.loads(raw)
        return str(d.get("message") or d.get("code") or raw)[:200]
    except Exception:
        return ""


def _send(to, subject, body, text, unsub, tag="waitlist-welcome"):
    hdrs = {}
    if unsub:
        hdrs["List-Unsubscribe"] = f"<{unsub}>"
        if unsub.startswith("http"):
            hdrs["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if PROVIDER == "file":
        os.makedirs(OUTBOX, exist_ok=True)
        stem = os.path.join(OUTBOX, datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + tag + "-" + hashlib.sha1(to.encode()).hexdigest()[:8])
        with open(stem + ".html", "w", encoding="utf-8") as f:
            f.write(body)
        with open(stem + ".tmp", "w", encoding="utf-8") as f:  # write then rename, so readers never see a partial file
            json.dump({"to": to, "from": f"{FROM_NAME} <{FROM}>", "reply_to": REPLY_TO, "subject": subject,
                       "headers": hdrs, "text": text, "tag": tag}, f, indent=1)
        os.replace(stem + ".tmp", stem + ".json")
        return "HTTP 200 (written to outbox)"
    if PROVIDER == "brevo":
        p = {"sender": {"name": FROM_NAME, "email": FROM}, "to": [{"email": to}], "subject": subject,
             "htmlContent": body, "textContent": text, "tags": [tag]}
        if hdrs:  # Brevo rejects an empty headers object
            p["headers"] = hdrs
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


def build_signin(base, link, email, minutes=20):
    """Return (subject, html, text) for a magic-link sign-in email."""
    e = html.escape
    subject = "Your BarksBuds sign-in link"
    text = f"""Hi there,

Tap the link below to sign in to BarksBuds:

{link}

This link works once and expires in {minutes} minutes.

New to BarksBuds? The same link creates your account, so you can add your dog's profile and photos.

Didn't ask for this? You can ignore this email. Nobody can sign in without the link.

See you at the dog run!
The BarksBuds team
{base}/

This email was sent to {email} because someone asked to sign in to BarksBuds with this address.
"""
    btn = ("display:inline-block;background:#C8201E;color:#ffffff;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;"
           "font-size:18px;text-decoration:none;padding:15px 30px;border-radius:999px;border-bottom:4px solid #9E1714")
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{e(subject)}</title>
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@700;800&family=Caveat+Brush&family=Nunito:wght@400;700&display=swap" rel="stylesheet">
<style>@media (max-width:620px){{.wrap{{padding:0 !important}} .card{{border-radius:0 !important}} .pad{{padding:24px 22px !important}} h1{{font-size:28px !important}}}}</style>
</head>
<body style="margin:0;padding:0;background:#FFF8EA;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">Tap to sign in. This link works once and expires in {minutes} minutes.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFF8EA;">
<tr><td class="wrap" align="center" style="padding:28px 12px;">
<table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid #EADBB9;">
<tr><td style="background:#141414;padding:22px 32px;" class="pad">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
  <td style="vertical-align:middle;"><img src="{base}/img/icon-180.png" width="52" height="52" alt="" style="display:block;border-radius:14px;border:3px solid #FBB321;"></td>
  <td style="vertical-align:middle;padding-left:14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:26px;color:#ffffff;">BarksBuds</td>
  </tr></table>
</td></tr>
<tr><td class="pad" style="padding:34px 36px 10px;font-family:Nunito,Arial,sans-serif;color:#2a2622;">
  <p style="margin:0 0 4px;font-family:'Caveat Brush',cursive;font-size:24px;color:#C8201E;">welcome back to the pack</p>
  <h1 style="margin:0 0 14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:32px;line-height:1.1;color:#141414;">Here's your sign-in link</h1>
  <p style="margin:0 0 24px;font-size:16px;line-height:1.6;">Tap the button to sign in to BarksBuds. No password needed.</p>
  <p style="margin:0 0 26px;"><a href="{e(link)}" style="{btn}">Sign in to BarksBuds &rarr;</a></p>
  <p style="margin:0 0 18px;font-size:14px;line-height:1.6;color:#625a50;">This link works once and expires in <strong>{minutes} minutes</strong>. New here? The same link creates your account, so you can add your dog's profile and photos.</p>
  <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#8a8073;">Button not working? Copy this link into your browser:</p>
  <p style="margin:0 0 26px;font-size:13px;line-height:1.5;word-break:break-all;"><a href="{e(link)}" style="color:#C8201E;">{e(link)}</a></p>
</td></tr>
<tr><td class="pad" style="padding:0 36px 30px;font-family:Nunito,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFE7A8;border-radius:18px;">
  <tr><td style="padding:16px 20px;font-size:14px;line-height:1.55;color:#2a2622;">
    <strong>Didn't ask for this?</strong> You can safely ignore this email. Nobody can sign in without the link.
  </td></tr></table>
  <p style="margin:22px 0 0;font-family:'Caveat Brush',cursive;font-size:24px;color:#C8201E;">See you at the dog run!</p>
  <p style="margin:2px 0 0;font-size:15px;color:#625a50;">The BarksBuds team</p>
</td></tr>
<tr><td class="pad" style="background:#141414;padding:20px 36px;font-family:Nunito,Arial,sans-serif;font-size:13px;line-height:1.6;color:#C9BFAF;">
  This email was sent to {e(email)} because someone asked to sign in to <a href="{base}/" style="color:#FBB321;">BarksBuds</a> with this address.
  We never sell or share your info.
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return subject, body, text


def send_signin_async(base, link, email, minutes=20):
    """Send a sign-in email on a background thread. Returns True if a send was queued."""
    if not enabled():
        print(f"email: skipped sign-in link for {_mask(email)} ({status()})", flush=True)
        return False

    def run():
        subject, body, text = build_signin(base, link, email, minutes)
        for attempt in range(3):
            try:
                result = _send(email, subject, body, text, "", tag="signin")
                print(f"email: sign-in link sent to {_mask(email)} via {PROVIDER} ({result})", flush=True)
                return
            except urllib.error.HTTPError as e:
                print(f"email: {PROVIDER} HTTP {e.code} for sign-in to {_mask(email)}: {_err_detail(e)}", flush=True)
                if not (e.code == 429 or e.code >= 500):
                    return
            except Exception as e:
                print(f"email: sign-in send error for {_mask(email)}: {type(e).__name__}", flush=True)
            time.sleep(2 * (attempt + 1))
        print(f"email: gave up on sign-in link for {_mask(email)}", flush=True)

    threading.Thread(target=run, name="signin-email", daemon=True).start()
    return True


# ---------------------------------------------------------------- meetup emails
MEETUP_ALLOW = {a.strip().lower() for a in os.environ.get("MEETUP_EMAIL_ALLOWLIST", "").split(",") if a.strip()}
# Pack emails use PACK_EMAIL_ALLOWLIST when set, otherwise the meetup allowlist (so testing limits cover both).
PACK_ALLOW = {a.strip().lower() for a in os.environ.get("PACK_EMAIL_ALLOWLIST", "").split(",") if a.strip()} or MEETUP_ALLOW
# Run-suggestion notices (to the site owner) use RUNS_EMAIL_ALLOWLIST when set, otherwise the pack/meetup allowlist.
RUNS_ALLOW = {a.strip().lower() for a in os.environ.get("RUNS_EMAIL_ALLOWLIST", "").split(",") if a.strip()} or PACK_ALLOW


def and_list(xs):
    xs = list(xs)
    return " and ".join(xs) if len(xs) < 3 else ", ".join(xs[:-1]) + " and " + xs[-1]


def send_async(to, subject, body, text, unsub, tag):
    """Generic fire-and-forget send with retries. Returns True if queued. MEETUP_EMAIL_ALLOWLIST (optional, comma separated)
    limits meetup-* emails to those addresses, for testing."""
    if not enabled():
        print(f"email: skipped {tag} for {_mask(to)} ({status()})", flush=True)
        return False
    if tag.startswith("meetup") and MEETUP_ALLOW and to.strip().lower() not in MEETUP_ALLOW:
        print(f"email: {tag} for {_mask(to)} not sent (not on MEETUP_EMAIL_ALLOWLIST)", flush=True)
        return False
    if tag.startswith("runs") and RUNS_ALLOW and to.strip().lower() not in RUNS_ALLOW:
        print(f"email: {tag} for {_mask(to)} not sent (not on the runs email allowlist)", flush=True)
        return False
    if tag.startswith("pack") and PACK_ALLOW and to.strip().lower() not in PACK_ALLOW:
        print(f"email: {tag} for {_mask(to)} not sent (not on the pack email allowlist)", flush=True)
        return False

    def run():
        for attempt in range(3):
            try:
                result = _send(to, subject, body, text, unsub, tag=tag)
                print(f"email: {tag} sent to {_mask(to)} via {PROVIDER} ({result})", flush=True)
                return
            except urllib.error.HTTPError as e:
                print(f"email: {PROVIDER} HTTP {e.code} for {tag} to {_mask(to)}: {_err_detail(e)}", flush=True)
                if not (e.code == 429 or e.code >= 500):
                    return
            except Exception as e:
                print(f"email: {tag} send error for {_mask(to)}: {type(e).__name__}", flush=True)
            time.sleep(2 * (attempt + 1))
        print(f"email: gave up on {tag} for {_mask(to)}", flush=True)

    threading.Thread(target=run, name=tag, daemon=True).start()
    return True


def build_meetup(base, kind, m, name="", status="", dogs=None, who="", who_dogs=None, counts="", unsub=""):
    """Return (subject, html, text) for a meetup email.
    kind: confirm | promoted | host | cancel | reminder. m: meetup dict with title, when, where, url, ics, gcal, directions."""
    e = html.escape
    dogs, who_dogs = dogs or [], who_dogs or []
    t = m["title"]
    hi = f"Hi {name}," if name else "Hi there,"
    dl = and_list(dogs)
    wdl = and_list(who_dogs)
    status_word = {"going": "Going", "maybe": "Maybe", "waitlist": "On the waitlist"}.get(status, status)
    if kind == "confirm":
        if status == "waitlist":
            subject, eyebrow, heading = f"You're on the waitlist for {t}", "almost there", "You're on the waitlist"
            intro = "This meetup is full right now. If a spot opens up we'll move you to Going automatically and email you."
        elif status == "maybe":
            subject, eyebrow, heading = f"You're a maybe for {t}", "maybe see you there", "You're marked as Maybe"
            intro = "We'll send a reminder the day before. Switch to Going any time if you can make it."
        else:
            subject, eyebrow, heading = f"You're going to {t}", "see you there", "You're going!"
            intro = "Your spot is saved. We'll send a reminder the day before."
    elif kind == "promoted":
        subject, eyebrow, heading = f"A spot opened up: you're going to {t}", "good news", "You're off the waitlist"
        intro = "A spot opened up, so you've been moved from the waitlist to Going."
    elif kind == "host":
        subject = f"{who or 'A member'} RSVP'd {status_word} to {t}"
        eyebrow, heading = "new rsvp", f"{who or 'A member'} RSVP'd {status_word}"
        intro = (f"Bringing {wdl}." if wdl else "") + (f" {counts}" if counts else "")
    elif kind == "cancel":
        subject, eyebrow, heading = f"Cancelled: {t} on {m['when_short']}", "change of plans", "This meetup was cancelled"
        intro = "The host cancelled this meetup, so your RSVP no longer applies. Sorry about that! Find another meetup near you below."
    elif kind == "reminder":
        subject, eyebrow, heading = f"Tomorrow: {t} at {m['time_short']}", "see you tomorrow", "Your meetup is tomorrow"
        intro = "A quick reminder about your meetup. Bring water and a leash for the walk in."
    else:
        raise ValueError(kind)
    rows = [("When", m["when"]), ("Where", m["where"])]
    if dl and kind in ("confirm", "promoted", "reminder"):
        rows.append(("Your dogs", dl))
    if kind in ("confirm", "promoted", "reminder") and status:
        rows.append(("Your RSVP", "Going" if kind == "promoted" else status_word))
    if kind == "host" and counts:
        rows.append(("RSVPs so far", counts))
    button = ("See other meetups", base + "/meetups") if kind == "cancel" else ("View the meetup", m["url"])
    links = [] if kind == "cancel" else [("Add to calendar (.ics)", m["ics"]), ("Google Calendar", m["gcal"])]
    if kind in ("confirm", "promoted", "reminder") and m.get("directions"):
        links.append(("Directions", m["directions"]))
    if kind in ("confirm", "promoted", "reminder"):
        links.append(("Change or cancel your RSVP", m["url"] + "#rsvp"))
    why = {"host": "you're hosting this meetup on BarksBuds"}.get(kind, "you RSVP'd to this meetup on BarksBuds")
    text = f"{hi}\n\n{heading}. {intro}\n\n{t}\n" + "".join(f"{k}: {v}\n" for k, v in rows) + \
        f"\n{button[0]}: {button[1]}\n" + "".join(f"{k}: {v}\n" for k, v in links) + \
        f"\nSee you at the dog run!\nThe BarksBuds team\n\nYou're getting this because {why}.\n" + \
        (f"Turn off meetup emails: {unsub}\n" if unsub else "") + f"Email preferences: {base}/me#emails\n"
    btn = ("display:inline-block;background:#C8201E;color:#ffffff;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;"
           "font-size:17px;text-decoration:none;padding:14px 26px;border-radius:999px;border-bottom:4px solid #9E1714")
    trs = "".join(f'<tr><td style="padding:8px 0;border-top:1px solid #EADBB9;font-size:14px;color:#625a50;width:110px;vertical-align:top;">{e(k)}</td>'
                  f'<td style="padding:8px 0;border-top:1px solid #EADBB9;font-size:15px;color:#141414;font-weight:700;">{e(v)}</td></tr>' for k, v in rows)
    lk = " &middot; ".join(f'<a href="{e(u)}" style="color:#C8201E;font-weight:700;">{e(k)}</a>' for k, u in links)
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{e(subject)}</title>
<style>@media (max-width:620px){{.wrap{{padding:0 !important}} .card{{border-radius:0 !important}} .pad{{padding:24px 22px !important}} h1{{font-size:27px !important}}}}</style>
</head><body style="margin:0;padding:0;background:#FFF8EA;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(t)} · {e(m["when"])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFF8EA;"><tr><td class="wrap" align="center" style="padding:28px 12px;">
<table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid #EADBB9;">
<tr><td style="background:#141414;padding:20px 32px;" class="pad"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="vertical-align:middle;"><img src="{base}/img/icon-180.png" width="48" height="48" alt="" style="display:block;border-radius:13px;border:3px solid #FBB321;"></td>
<td style="vertical-align:middle;padding-left:14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:25px;color:#ffffff;">BarksBuds</td></tr></table></td></tr>
<tr><td class="pad" style="padding:32px 36px 8px;font-family:Nunito,Arial,sans-serif;color:#2a2622;">
<p style="margin:0 0 4px;font-family:'Caveat Brush',cursive;font-size:23px;color:#C8201E;">{e(eyebrow)}</p>
<h1 style="margin:0 0 12px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:31px;line-height:1.1;color:#141414;">{e(heading)}</h1>
<p style="margin:0 0 6px;font-size:16px;line-height:1.6;">{e(hi)}</p>
<p style="margin:0 0 18px;font-size:16px;line-height:1.6;">{e(intro)}</p>
<h2 style="margin:0 0 6px;font-family:'Baloo 2',Arial,sans-serif;font-size:21px;color:#141414;">{e(t)}</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px;">{trs}</table>
<p style="margin:0 0 18px;"><a href="{e(button[1])}" style="{btn}">{e(button[0])} &rarr;</a></p>
<p style="margin:0 0 26px;font-size:14px;line-height:1.7;">{lk}</p>
<p style="margin:0;font-family:'Caveat Brush',cursive;font-size:23px;color:#C8201E;">See you at the dog run!</p>
<p style="margin:2px 0 26px;font-size:15px;color:#625a50;">The BarksBuds team</p></td></tr>
<tr><td class="pad" style="background:#141414;padding:18px 36px;font-family:Nunito,Arial,sans-serif;font-size:13px;line-height:1.6;color:#C9BFAF;">
You're getting this because {e(why)}. We never sell or share your info.<br>
{f'<a href="{e(unsub)}" style="color:#FBB321;">Turn off meetup emails</a> &middot; ' if unsub else ''}<a href="{base}/me#emails" style="color:#FBB321;">Email preferences</a>
</td></tr></table></td></tr></table></body></html>"""
    return subject, body, text


# ---------------------------------------------------------------- pack emails
def build_pack(base, kind, p, name="", who="", who_dogs=None, message="", meetup=None, unsub=""):
    """Return (subject, html, text) for a pack email.
    kind: request (to organizers) | approved (to the member) | meetup (new pack meetup, to members).
    p: dict with name, url, where; meetup: dict with title, when, where, url, host (for kind=meetup)."""
    e = html.escape
    who_dogs = who_dogs or []
    n = p["name"]
    hi = f"Hi {name}," if name else "Hi there,"
    rows, links = [], []
    if kind == "request":
        subject = f"{who or 'A member'} asked to join {n}"
        eyebrow, heading = "new join request", f"{who or 'A member'} wants to join"
        intro = f"{who or 'A member'} asked to join {n}" + (f" with {and_list(who_dogs)}" if who_dogs else "") + \
            ". As an organizer you can approve or decline the request from the pack's members page."
        rows = [("Pack", n)] + ([("Dogs", and_list(who_dogs))] if who_dogs else []) + ([("Note", message)] if message else [])
        button = ("Review the request", p["url"] + "/members")
        why = "you organize this pack on BarksBuds"
    elif kind == "approved":
        subject = f"You're in: welcome to {n}"
        eyebrow, heading = "welcome to the pack", "Your request was approved"
        intro = f"An organizer approved your request, so you're now a member of {n}. Say hi on the pack board and check out the next pack meetup."
        rows = [("Pack", n), ("Where", p["where"])]
        button = ("Visit the pack", p["url"])
        why = "you asked to join this pack on BarksBuds"
    elif kind == "meetup":
        m = meetup
        subject = f"New {n} meetup: {m['title']} on {m['when_short']}"
        eyebrow, heading = "new pack meetup", "Your pack is meeting up"
        intro = f"{m.get('host') or 'A pack member'} is hosting a new meetup for {n}. RSVP with your dogs so everyone knows who's coming."
        rows = [("Meetup", m["title"]), ("When", m["when"]), ("Where", m["where"])]
        if m.get("members_only"):
            rows.append(("Who", "Pack members only"))
        button = ("RSVP on BarksBuds", m["url"] + "#rsvp")
        links = [("Add to calendar (.ics)", m["ics"]), ("Google Calendar", m["gcal"]), ("Visit the pack", p["url"])]
        why = "you're a member of this pack on BarksBuds"
    else:
        raise ValueError(kind)
    text = f"{hi}\n\n{heading}. {intro}\n\n" + "".join(f"{k}: {v}\n" for k, v in rows) + \
        f"\n{button[0]}: {button[1]}\n" + "".join(f"{k}: {v}\n" for k, v in links) + \
        f"\nSee you at the dog run!\nThe BarksBuds team\n\nYou're getting this because {why}.\n" + \
        (f"Turn off pack emails: {unsub}\n" if unsub else "") + f"Email preferences: {base}/me#emails\n"
    btn = ("display:inline-block;background:#C8201E;color:#ffffff;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;"
           "font-size:17px;text-decoration:none;padding:14px 26px;border-radius:999px;border-bottom:4px solid #9E1714")
    trs = "".join(f'<tr><td style="padding:8px 0;border-top:1px solid #EADBB9;font-size:14px;color:#625a50;width:110px;vertical-align:top;">{e(k)}</td>'
                  f'<td style="padding:8px 0;border-top:1px solid #EADBB9;font-size:15px;color:#141414;font-weight:700;white-space:pre-line;">{e(v)}</td></tr>' for k, v in rows)
    lk = " &middot; ".join(f'<a href="{e(u)}" style="color:#C8201E;font-weight:700;">{e(k)}</a>' for k, u in links)
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{e(subject)}</title>
<style>@media (max-width:620px){{.wrap{{padding:0 !important}} .card{{border-radius:0 !important}} .pad{{padding:24px 22px !important}} h1{{font-size:27px !important}}}}</style>
</head><body style="margin:0;padding:0;background:#FFF8EA;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(intro[:140])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFF8EA;"><tr><td class="wrap" align="center" style="padding:28px 12px;">
<table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;background:#ffffff;border-radius:24px;overflow:hidden;border:1px solid #EADBB9;">
<tr><td style="background:#141414;padding:20px 32px;" class="pad"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="vertical-align:middle;"><img src="{base}/img/icon-180.png" width="48" height="48" alt="" style="display:block;border-radius:13px;border:3px solid #FBB321;"></td>
<td style="vertical-align:middle;padding-left:14px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:25px;color:#ffffff;">BarksBuds</td></tr></table></td></tr>
<tr><td class="pad" style="padding:32px 36px 8px;font-family:Nunito,Arial,sans-serif;color:#2a2622;">
<p style="margin:0 0 4px;font-family:'Caveat Brush',cursive;font-size:23px;color:#C8201E;">{e(eyebrow)}</p>
<h1 style="margin:0 0 12px;font-family:'Baloo 2',Arial,sans-serif;font-weight:800;font-size:31px;line-height:1.1;color:#141414;">{e(heading)}</h1>
<p style="margin:0 0 6px;font-size:16px;line-height:1.6;">{e(hi)}</p>
<p style="margin:0 0 18px;font-size:16px;line-height:1.6;">{e(intro)}</p>
<h2 style="margin:0 0 6px;font-family:'Baloo 2',Arial,sans-serif;font-size:21px;color:#141414;">{e(n)}</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 24px;">{trs}</table>
<p style="margin:0 0 18px;"><a href="{e(button[1])}" style="{btn}">{e(button[0])} &rarr;</a></p>
{f'<p style="margin:0 0 26px;font-size:14px;line-height:1.7;">{lk}</p>' if lk else ''}
<p style="margin:0;font-family:'Caveat Brush',cursive;font-size:23px;color:#C8201E;">See you at the dog run!</p>
<p style="margin:2px 0 26px;font-size:15px;color:#625a50;">The BarksBuds team</p></td></tr>
<tr><td class="pad" style="background:#141414;padding:18px 36px;font-family:Nunito,Arial,sans-serif;font-size:13px;line-height:1.6;color:#C9BFAF;">
You're getting this because {e(why)}. We never sell or share your info.<br>
{f'<a href="{e(unsub)}" style="color:#FBB321;">Turn off pack emails</a> &middot; ' if unsub else ''}<a href="{base}/me#emails" style="color:#FBB321;">Email preferences</a>
</td></tr></table></td></tr></table></body></html>"""
    return subject, body, text
