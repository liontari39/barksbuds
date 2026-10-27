"""BarksBuds member pages: magic-link sign-in, owner dashboard, dog profiles, reports.

Mixed into server.H. Every page is server-rendered with escaped output; every POST checks a CSRF token
(an HMAC of the bb_csrf cookie) plus the Origin header when the browser sends one.
"""
import hashlib, hmac, html, re, secrets, unicodedata
from datetime import date, datetime, timezone
from email.parser import BytesParser
from email.policy import HTTP
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, urlsplit

import accounts as A
import coowners as CO
import mailer

e = html.escape
RUNS = lambda: []       # set by server.py: returns the dog run list
SITE_URL = ""            # set by server.py
ADMIN_KEY = ""           # set by server.py
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SESSION_COOKIE, CSRF_COOKIE = "bb_session", "bb_csrf"
MAX_FORM = 40_000
MAX_UPLOAD_REQUEST = 40 * 1024 * 1024

ICONS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.6"/></symbol>
<symbol id="i-paw" viewBox="0 0 24 24"><circle cx="6" cy="10" r="2"/><circle cx="10" cy="5.5" r="2"/><circle cx="14" cy="5.5" r="2"/><circle cx="18" cy="10" r="2"/><path d="M12 11c-3 0-6 4.5-6 7a3 3 0 0 0 3 3c1.2 0 2-.6 3-.6s1.8.6 3 .6a3 3 0 0 0 3-3c0-2.5-3-7-6-7z"/></symbol>
<symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M4 7l8 6 8-6"/></symbol>
<symbol id="i-lock" viewBox="0 0 24 24"><rect x="4" y="10.5" width="16" height="10.5" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>
<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></symbol>
<symbol id="i-cake" viewBox="0 0 24 24"><path d="M4 21h16M5 21v-7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v7M5 16c2.3 1.3 4.7 1.3 7 0s4.7-1.3 7 0M12 12V8M12 5.5v.01"/></symbol>
<symbol id="i-ruler" viewBox="0 0 24 24"><path d="M3 17L17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/></symbol>
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 20s-7.5-4.6-9-9.2C2 7.6 4.2 5 7 5c2 0 3.3 1.1 5 3 1.7-1.9 3-3 5-3 2.8 0 5 2.6 4 5.8-1.5 4.6-9 9.2-9 9.2z"/></symbol>
<symbol id="i-camera" viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></symbol>
<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 9v4M12 16.5v.01M10.3 3.9L2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></symbol>
<symbol id="i-link" viewBox="0 0 24 24"><path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/></symbol>
<symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></symbol>
<symbol id="i-cal" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18M8 14h3"/></symbol>
<symbol id="i-chat" viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/></symbol>
<symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/></symbol>
<symbol id="i-nav" viewBox="0 0 24 24"><path d="M3 11l18-8-8 18-2-8z"/></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
<symbol id="i-tree" viewBox="0 0 24 24"><path d="M12 3l-6 8h3.5L5 17h14l-4.5-6H18z"/><path d="M12 17v4"/></symbol>
<symbol id="i-dog" viewBox="0 0 24 24"><path d="M10 5.2C9.2 3.8 7.4 3 6 3.5 4.5 4 3.5 6 4 8l1 3M14 5.2c.8-1.4 2.6-2.2 4-1.7 1.5.5 2.5 2.5 2 4.5l-1 3"/><path d="M8 14.5c0 3 1.8 5.5 4 5.5s4-2.5 4-5.5S14.2 6 12 6s-4 5.5-4 8.5z"/><path d="M11 16h2"/></symbol>
</svg>"""

FLASH = {"welcome": "You're signed in. Welcome to BarksBuds!", "signedin": "You're signed in.",
         "saved": "Saved.", "profile": "Your profile is saved.", "created": "Profile created! Now add a few photos.",
         "photos": "Photos added.", "photo_deleted": "Photo removed.", "avatar": "Profile picture updated.",
         "portrait": "Thanks! Your pixel portrait request is in. Our team usually finishes within a day.",
         "deleted": "That dog profile was deleted.", "reported": "Thanks. Our team will take a look.",
         "signedout": "You're signed out. See you at the dog run!",
         "left": "Done. You're no longer a co-owner of that dog."}
PHOTO_ERR = {"type": "That file isn't a JPEG, PNG, WebP or GIF photo.", "big": "Photos can be up to 12 MB each.",
             "toobig": "That upload was too big. Try a few photos at a time (up to 40 MB per upload).",
             "count": f"Each dog can have up to {A.MAX_PHOTOS} photos. Remove one to add another.",
             "none": "Choose at least one photo to upload.", "small": "That photo is too small.",
             "read": "We couldn't read that photo. Try a JPEG or PNG."}


def clean(s, n, multiline=False):
    s = unicodedata.normalize("NFC", str(s or ""))
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    s = s.replace("\t", " ")
    if multiline:
        s = re.sub(r"\n{3,}", "\n\n", s.replace("\r", ""))
        s = "\n".join(line.rstrip() for line in s.split("\n"))
    else:
        s = re.sub(r"\s+", " ", s)
    return s.strip()[:n]


def area_label(a):
    return A.AREA_LABEL.get(a, a)


def where_text(town, area):
    if town and area and town.lower() != area.lower():
        return f"{town}, {area_label(area)}"
    return town or area_label(area)


MENU_LINKS = [("/dogs", "Dogs"), ("/meetups", "Meetups"), ("/packs", "Packs"), ("/runs", "Dog runs"), ("/trails", "Trails"), ("/pixel-pals", "Pixel Pals"), ("/tips", "Tips"), ("/community", "Community")]
MENU_JS = ("<script>(function(){var d=document.querySelector('details.mmenu');if(!d)return;var s=d.querySelector('summary');"
           "function sync(){s.setAttribute('aria-expanded',d.open?'true':'false')}d.addEventListener('toggle',sync);sync();"
           "document.addEventListener('click',function(ev){if(d.open&&!d.contains(ev.target))d.open=false});"
           "document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&d.open){d.open=false;s.focus()}})})();</script>")


def mobile_menu_html(user, active=""):
    """Hamburger menu shown at 920px and below (styles: .mmenu in app.css, index.html and runs.html)."""
    li = "".join(f'<li><a href="{h}"{" aria-current=page" if active and h == "/" + active else ""}>{t}</a></li>' for h, t in MENU_LINKS)
    n = unread_count(user)
    li += (f'<li class="mm-acct"><a href="/messages"{" aria-current=page" if active == "messages" else ""}>Messages'
           + (f' <span class="mm-badge">{n if n < 100 else "99+"}<span class="sr-only"> unread</span></span>' if n else "") + '</a></li>'
           '<li><a href="/me">My dogs</a></li>' if user else
           '<li class="mm-acct"><a href="/signin">Sign in</a></li><li><a href="/signin">Join BarksBuds</a></li>')
    return (f'<details class="mmenu"><summary aria-label="Menu" aria-controls="mmenu-list"><span class="mm-bars" aria-hidden="true"><i></i><i></i><i></i></span></summary>'
            f'<nav aria-label="Menu" id="mmenu-list"><ul>{li}</ul></nav></details>{MENU_JS}')


def unread_count(user):
    """Unread direct messages for the nav badge (0 when signed out or if the lookup fails)."""
    if not user:
        return 0
    if "_unread" not in user:
        try:
            import messages
            user["_unread"] = messages.unread_total(user["id"])
        except Exception as ex:  # never break a page over the badge
            print(f"messages: unread count failed: {type(ex).__name__}", flush=True)
            user["_unread"] = 0
    return user["_unread"]


NAV_CHAT_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z"/>'
                '<path d="M8.5 11h7M8.5 14h4"/></svg>')


def nav_msgs_html(user, active=""):
    n = unread_count(user)
    lab = f"Messages, {n} unread" if n else "Messages"
    badge = f'<span class="nbadge" aria-hidden="true">{n if n < 100 else "99+"}</span>' if n else ""
    return (f'<a class="navmsg" href="/messages" aria-label="{lab}" title="Messages"'
            f'{" aria-current=page" if active == "messages" else ""}>{NAV_CHAT_SVG}{badge}</a>')


def nav_account_html(user, active=""):
    if user:
        return (nav_msgs_html(user, active) + '<a class="btn btn-gold" href="/me"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg>My dogs</a>'
                + mobile_menu_html(user, active))
    return ('<a class="nav-signin" href="/signin">Sign in</a>'
            '<a class="btn" href="/signin">Join<span class="hide-xs"> BarksBuds</span></a>' + mobile_menu_html(user, active))


def safe_next(nxt):
    """A same-site path to return to after sign-in, or ''. Rejects absolute/protocol-relative URLs and auth pages."""
    nxt = (nxt or "").strip()
    if not nxt or len(nxt) > 400 or not nxt.startswith("/") or nxt.startswith(("//", "/\\")) or "\\" in nxt:
        return ""
    if any(ord(c) < 33 or ord(c) == 127 for c in nxt):
        return ""
    try:
        sp = urlsplit(nxt)
    except ValueError:
        return ""
    if sp.scheme or sp.netloc or sp.path.startswith(("/signin", "/auth", "/signout", "/admin")):
        return ""
    return nxt


def run_index():
    return {r["id"]: r for r in RUNS()}


class Form:
    def __init__(self, fields=None, files=None):
        self.fields, self.files = fields or {}, files or []

    def get(self, k, default=""):
        v = self.fields.get(k)
        return v[0] if v else default

    def getlist(self, k):
        return self.fields.get(k, [])


def C_is_today(iso, today):
    import community
    return community.is_today(iso, today)


class AppRoutes:
    # ------------------------------------------------------------ plumbing
    def _app_reset(self):
        self._out_cookies, self._ck, self._user_cache = [], None, False

    def _cookies(self):
        if self._ck is None:
            self._ck = {}
            try:
                c = SimpleCookie(); c.load(self.headers.get("Cookie") or "")
                self._ck = {k: v.value for k, v in c.items()}
            except Exception:
                pass
        return self._ck

    def _secure(self):
        if self._host_url().startswith("https://"):
            return True
        return SITE_URL.startswith("https://") and urlsplit(SITE_URL).netloc == (self.headers.get("Host") or "")

    def _set_cookie(self, name, value, max_age=None):
        parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if self._secure():
            parts.append("Secure")
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        self._out_cookies.append("; ".join(parts))

    def _base(self):
        return SITE_URL or self._host_url()

    def _client_ip(self):
        cf = (self.headers.get("CF-Connecting-IP") or "").strip()
        xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return cf or xff or self.client_address[0]

    def user(self):
        if self._user_cache is False:
            self._user_cache = A.session_user(self._cookies().get(SESSION_COOKIE))
        return self._user_cache

    def csrf_token(self):
        c = self._cookies().get(CSRF_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", c):
            c = secrets.token_urlsafe(24)
            self._cookies()[CSRF_COOKIE] = c
            self._set_cookie(CSRF_COOKIE, c, max_age=365 * 86400)
        return hmac.new(A.SECRET, c.encode(), hashlib.sha256).hexdigest()[:40]

    def csrf_field(self):
        return f'<input type="hidden" name="csrf" value="{self.csrf_token()}">'

    def csrf_ok(self, form):
        origin = self.headers.get("Origin")
        if origin:
            if origin == "null" or urlsplit(origin).netloc != (self.headers.get("Host") or ""):
                return False
        c = self._cookies().get(CSRF_COOKIE, "")
        tok = form.get("csrf")
        if not c or not tok:
            return False
        good = hmac.new(A.SECRET, c.encode(), hashlib.sha256).hexdigest()[:40]
        return hmac.compare_digest(good, tok)

    def read_form(self, limit=MAX_FORM):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > limit:
            return None
        raw = self.rfile.read(n) if n > 0 else b""
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1", "replace")
                                                      + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
            fields, files = {}, []
            if msg.is_multipart():
                for part in msg.iter_parts():
                    name = part.get_param("name", header="content-disposition") or ""
                    data = part.get_payload(decode=True) or b""
                    fn = part.get_filename()
                    if fn is not None:
                        if data:
                            files.append((name, fn, data))
                    else:
                        fields.setdefault(name, []).append(data.decode("utf-8", "replace"))
            return Form(fields, files)
        return Form(parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True))

    def _emit(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        for c in self._out_cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, loc, code=303):
        self._emit(code, b"", "text/plain", {"Location": loc, "Cache-Control": "no-store"})

    def need_login(self, nxt=None):
        """Send a signed-out visitor to sign in, coming back here afterwards (GET pages, or the page a form was on)."""
        if nxt is None:
            if self.command in ("GET", "HEAD"):
                nxt = self.path
            else:
                ref = urlsplit(self.headers.get("Referer") or "")
                nxt = (ref.path + ("?" + ref.query if ref.query else "")) if ref.netloc == (self.headers.get("Host") or "") else ""
        nxt = safe_next(nxt)
        return self.redirect("/signin" + ("?next=" + quote(nxt, safe="") if nxt else ""))

    def signin_href(self, nxt):
        nxt = safe_next(nxt)
        return "/signin" + ("?next=" + quote(nxt, safe="") if nxt else "")

    # ------------------------------------------------------------ layout
    def page(self, title, body, *, code=200, desc="", canonical="", og=None, index=False, active="", scripts="", flash=""):
        u = self.user()
        base = self._base()
        links = [("/runs", "Dog run map", "runs"), ("/trails", "Trails", "trails"), ("/meetups", "Meetups", "meetups"), ("/packs", "Packs", "packs"), ("/dogs", "Dogs", "dogs"),
                 ("/pixel-pals", "Pixel Pals", "pixel-pals"), ("/tips", "Tips", "tips"), ("/community", "Community", "community")]
        nav = "".join(f'<li><a href="{h}"{" aria-current=page" if a and a == active else ""}>{t}</a></li>'
                      for h, t, a in links)
        meta = [f'<meta name="robots" content="{"index,follow" if index else "noindex"}">']
        if desc:
            meta.append(f'<meta name="description" content="{e(desc)}">')
        if canonical:
            meta.append(f'<link rel="canonical" href="{e(base + canonical)}">')
        if og:
            od = og.get("desc", desc)
            meta += ['<meta property="og:site_name" content="BarksBuds">',
                     f'<meta property="og:type" content="{e(og.get("type", "website"))}">',
                     f'<meta property="og:title" content="{e(og["title"])}">',
                     f'<meta property="og:description" content="{e(od)}">',
                     f'<meta property="og:url" content="{e(base + canonical)}">',
                     f'<meta property="og:image" content="{e(og["image"])}">',
                     '<meta name="twitter:card" content="summary_large_image">',
                     f'<meta name="twitter:title" content="{e(og["title"])}">',
                     f'<meta name="twitter:description" content="{e(od)}">',
                     f'<meta name="twitter:image" content="{e(og["image"])}">']
            if og.get("w"):
                meta += [f'<meta property="og:image:width" content="{og["w"]}">',
                         f'<meta property="og:image:height" content="{og["h"]}">']
            if og.get("alt"):
                meta.append(f'<meta property="og:image:alt" content="{e(og["alt"])}">')
        fl = (f'<div class="wrap" style="padding-top:20px"><p class="flash" role="status"><svg class="ico" aria-hidden="true">'
              f'<use href="#i-check"/></svg>{e(flash)}</p></div>') if flash else ""
        acct = ('<li><a href="/me">My dogs</a></li>' if u else '<li><a href="/signin">Sign in</a></li>')
        doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | BarksBuds</title>
{chr(10).join(meta)}
<meta name="theme-color" content="#FBB321">
<link rel="icon" href="/favicon.ico?v=jack4" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/img/icon-32.png?v=jack4">
<link rel="apple-touch-icon" href="/img/icon-180.png?v=jack3"><link rel="manifest" href="/site.webmanifest">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Caveat+Brush&family=Nunito:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/app.css?v=17">
</head><body>
{ICONS}
<a class="skip" href="#main">Skip to content</a>
<header class="nav"><div class="wrap">
<a class="brand" href="/" aria-label="BarksBuds home"><img src="/img/icon-nav-40.png?v=jack4" srcset="/img/icon-nav-40.png?v=jack4 1x, /img/icon-nav-80.png?v=jack4 2x, /img/icon-nav-120.png?v=jack4 3x" width="40" height="40" alt="">BarksBuds</a>
<nav aria-label="Main"><ul class="nav-links">{nav}</ul></nav>
{nav_account_html(u, active)}
</div></header>
<main id="main">{fl}{body}</main>
<footer><div class="wrap">
<div class="top"><div><a class="brand" href="/"><img src="/img/icon-nav-40.png?v=jack4" srcset="/img/icon-nav-40.png?v=jack4 1x, /img/icon-nav-80.png?v=jack4 2x, /img/icon-nav-120.png?v=jack4 3x" width="40" height="40" alt="" loading="lazy">BarksBuds</a><p class="tag script">A group of friends that love their dogs</p></div>
<nav aria-label="Footer"><ul><li><a href="/runs">Dog run map</a></li><li><a href="/trails">Trails</a></li><li><a href="/meetups">Meetups</a></li><li><a href="/packs">Packs</a></li><li><a href="/dogs">Dogs</a></li><li><a href="/pixel-pals">Pixel Pals</a></li><li><a href="/tips">Tips</a></li><li><a href="/community">Community</a></li>{acct}<li><a href="/signin">Join BarksBuds</a></li></ul></nav></div>
<div class="bottom"><p>Made with love in Manhasset, NY &middot; <a href="mailto:hello@barksbuds.app">hello@barksbuds.app</a></p><p><a href="/privacy">Privacy</a> &middot; <a href="/terms">Terms</a> &middot; &copy; {date.today().year} BarksBuds</p></div>
</div></footer>
{scripts}
</body></html>"""
        cache = "no-store" if (u or code != 200 or not index) else "no-cache"
        self._emit(code, doc, headers={"Cache-Control": cache, "Vary": "Cookie"})

    def msg_page(self, title, html_body, code=200, icon="i-paw"):
        body = f"""<div class="authwrap"><div class="authcard">
<span class="mailicon"><svg class="ico" aria-hidden="true"><use href="#{icon}"/></svg></span>
<h1>{e(title)}</h1>{html_body}</div></div>"""
        return self.page(title, body, code=code)

    def flash_from(self, q):
        return FLASH.get(q.get("m", [""])[0], "")

    # ------------------------------------------------------------ routing
    def app_get(self, path, q):
        self._app_reset()
        if self.coown_get(path, q):
            return True
        if path == "/signin":
            nxt = safe_next(q.get("next", [""])[0])
            if self.user():
                self.redirect(nxt or "/me")
            else:
                self.signin_page(flash=self.flash_from(q), nxt=nxt)
            return True
        if path == "/auth":
            self.auth_page(q.get("t", [""])[0], q.get("next", [""])[0]); return True
        if path in ("/me", "/me/"):
            self.dashboard(q); return True
        if path == "/me/profile":
            self.profile_page(); return True
        if path == "/me/delete":
            self.delete_account_page(); return True
        if path == "/me/dogs/new":
            self.dog_form_page(None, q=q); return True
        m = re.fullmatch(r"/me/dogs/(\d+)/(edit|delete)", path)
        if m:
            d = self.own_dog(int(m.group(1)))
            if d is not None:
                if m.group(2) == "edit":
                    self.dog_form_page(d, q=q)
                else:
                    self.delete_dog_page(d)
            return True
        if path in ("/dogs", "/dogs/"):
            self.browse_page(q); return True
        m = re.fullmatch(r"/dogs/([a-z0-9-]{1,60})/?", path)
        if m:
            self.dog_page(m.group(1), q); return True
        m = re.fullmatch(r"/p/(\d+)\.(jpg|webp)", path)
        if m:
            self.photo(int(m.group(1)), m.group(2)); return True
        if path == "/admin/reports":
            self.admin_reports(q); return True
        return False

    def app_post(self, path, q):
        self._app_reset()
        if self.coown_post(path, q):
            return True
        routes = [(r"/signin", self.post_signin), (r"/auth", self.post_auth), (r"/signout", self.post_signout),
                  (r"/me/profile", self.post_profile), (r"/me/delete", self.post_delete_account),
                  (r"/me/dogs/new", self.post_dog), (r"/me/dogs/(\d+)/edit", self.post_dog),
                  (r"/me/dogs/(\d+)/delete", self.post_delete_dog), (r"/me/dogs/(\d+)/photos", self.post_photos),
                  (r"/me/dogs/(\d+)/photos/(\d+)/(delete|avatar)", self.post_photo_action),
                  (r"/dogs/([a-z0-9-]{1,60})/report", self.post_report), (r"/admin/reports", self.post_admin_reports),
                  (r"/admin/seed", self.post_admin_seed)]
        for pat, fn in routes:
            m = re.fullmatch(pat, path)
            if m:
                fn(*m.groups())
                return True
        return False

    def csrf_fail(self):
        return self.msg_page("Please try that again", '<p class="sub">Your session timed out or the form was opened in another tab. '
                             'Go back, refresh the page and try once more.</p><p><a class="btn" href="/me">Continue</a></p>',
                             code=403, icon="i-lock")

    def _form_or_fail(self, limit=MAX_FORM):
        f = self.read_form(limit)
        if f is None:
            self.msg_page("That was too big", "<p class=\"sub\">That form was larger than we accept. Please try again.</p>", code=413)
            return None
        if not self.csrf_ok(f):
            self.csrf_fail()
            return None
        return f

    # ------------------------------------------------------------ sign in
    def signin_page(self, email="", err="", code=200, flash="", nxt=""):
        nxt = safe_next(nxt)
        fine = ('<p class="fine"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg><span>No passwords to remember. '
                "We'll email you a link that signs you in. New to BarksBuds? The same link creates your free account. "
                "We never show your email on the site.</span></p>")
        inv = ' aria-invalid="true" aria-describedby="err-email"' if err else ""
        body = f"""<div class="authwrap"><div class="authcard">
<img class="logo" src="/img/icon-192.webp?v=jack3" width="84" height="84" alt="">
<span class="eyebrow">welcome to the pack</span>
<h1>Sign in to BarksBuds</h1>
<p class="sub">{"Sign in to continue. We'll bring you right back." if nxt else "Create your dog's profile, add photos and pick your favorite runs."}</p>
<form method="post" action="/signin" novalidate>
{self.csrf_field()}{f'<input type="hidden" name="next" value="{e(nxt)}">' if nxt else ''}
<div class="hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></div>
<div class="field"><label for="email">Your email</label>
<input id="email" name="email" type="email" inputmode="email" autocomplete="email" required maxlength="254" value="{e(email)}" placeholder="you@example.com"{inv}>
<span class="err" id="err-email" role="alert">{e(err)}</span></div>
<button class="btn" type="submit"><svg class="ico" aria-hidden="true"><use href="#i-mail"/></svg>Email me a sign-in link</button>
</form>{fine}</div></div>"""
        return self.page("Sign in", body, code=code, canonical="/signin", flash=flash,
                         desc="Sign in to BarksBuds with a link sent to your email. No password needed.")

    def post_signin(self):
        f = self._form_or_fail()
        if f is None:
            return
        email = f.get("email").strip().lower()[:254]
        nxt = safe_next(f.get("next"))
        if f.get("website"):
            return self.sent_page(email)
        if not EMAIL_RE.match(email):
            return self.signin_page(email, "That email doesn't look quite right.", code=422, nxt=nxt)
        if not A.LIMITER.allow("signin-ip:" + self._client_ip(), 10, 600):
            return self.signin_page(email, "Too many sign-in requests. Please wait a few minutes and try again.", code=429, nxt=nxt)
        try:
            raw = A.create_login_token(email, self._client_ip())
        except A.RateLimited:
            return self.signin_page(email, "We just sent a link to that address. Check your inbox (and spam), "
                                    "or wait a minute and try again.", code=429, nxt=nxt)
        link = f"{self._base()}/auth?t={raw}" + (f"&next={quote(nxt, safe='')}" if nxt else "")
        queued = mailer.send_signin_async(self._base(), link, email, A.LINK_TTL // 60)
        print(f"signin: link requested for {mailer._mask(email)} (email {'queued' if queued else 'not sent'})", flush=True)
        if not queued:
            return self.msg_page("Email is taking a nap", "<p class=\"sub\">We couldn't send sign-in emails just now. "
                                 "Please try again in a little while.</p>", code=503, icon="i-mail")
        return self.sent_page(email)

    def sent_page(self, email):
        return self.msg_page("Check your email", f"""<p class="sub">We sent a sign-in link to <strong>{e(email)}</strong>.
Tap it to sign in. It works once and expires in {A.LINK_TTL // 60} minutes.</p>
<div class="notice small" style="text-align:left"><strong>Don't see it?</strong> Give it a minute, then check your spam or Promotions folder.
It comes from hello@barksbuds.app.</div>
<p class="small"><a href="/signin">Use a different email or send another link</a></p>""", icon="i-mail")

    def auth_page(self, raw, nxt=""):
        nxt = safe_next(nxt)
        state = A.peek_login_token(raw)
        if state != "ok":
            why = {"used": ("This link was already used", "Each sign-in link works once. Request a fresh one below."),
                   "expired": ("This link has expired", f"Sign-in links expire after {A.LINK_TTL // 60} minutes. Request a fresh one below.")}
            t, msg = why.get(state, ("That link didn't work", "The sign-in link is incomplete. Request a fresh one below."))
            return self.msg_page(t, f'<p class="sub">{e(msg)}</p><p><a class="btn" href="/signin">Get a new link</a></p>',
                                 code=400, icon="i-lock")
        body = f"""<div class="authwrap"><div class="authcard">
<img class="logo" src="/img/icon-192.webp?v=jack3" width="84" height="84" alt="">
<h1>Signing you in…</h1><p class="sub">One moment. If nothing happens, tap the button.</p>
<form id="authf" method="post" action="/auth">{self.csrf_field()}<input type="hidden" name="t" value="{e(raw)}">{f'<input type="hidden" name="next" value="{e(nxt)}">' if nxt else ''}
<button class="btn" type="submit">Continue to BarksBuds</button></form></div></div>"""
        js = "<script>document.getElementById('authf').submit()</script>"
        return self.page("Signing in", body, scripts=js)

    def post_auth(self):
        f = self._form_or_fail()
        if f is None:
            return
        if not A.LIMITER.allow("auth-ip:" + self._client_ip(), 30, 600):
            return self.msg_page("Slow down a little", "<p class=\"sub\">Too many attempts. Please wait a few minutes.</p>", code=429)
        email = A.consume_login_token(f.get("t"))
        nxt = safe_next(f.get("next"))
        if not email:
            return self.auth_page(f.get("t"), nxt)
        uid, new = A.get_or_create_user(email)
        old = self._cookies().get(SESSION_COOKIE)
        if old:
            A.end_session(old)
        self._set_cookie(SESSION_COOKIE, A.create_session(uid), max_age=A.SESSION_TTL)
        print(f"signin: {'new account' if new else 'signed in'} user {uid}", flush=True)
        if nxt:
            return self.redirect(nxt)
        return self.redirect("/me?m=" + ("welcome" if new else "signedin"))

    def post_signout(self):
        f = self._form_or_fail()
        if f is None:
            return
        A.end_session(self._cookies().get(SESSION_COOKIE))
        self._set_cookie(SESSION_COOKIE, "", max_age=0)
        return self.redirect("/signin?m=signedout")

    # ------------------------------------------------------------ dashboard + owner profile
    def dashboard(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        dogs = A.dogs_for_user(u["id"])
        firsts = A.first_photos([d["id"] for d in dogs])
        cards = []
        owned = sum(1 for d in dogs if d["user_id"] == u["id"])  # MAX_DOGS counts only dogs you're the main owner of
        for d in dogs:
            pid = d.get("avatar_photo_id") or firsts.get(d["id"])  # the chosen main picture, else the first photo
            ph = (self.card_ph(d, pid) if pid or (d.get("pixel_photo_id") and A.SHOW_OLD_SPRITES) else
                  '<div class="ph empty"><svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg></div>')
            meta = " · ".join(x for x in (d["breed"], A.age_text(d)) if x)
            hidden = '<p class="err">Hidden by our team while we review a report.</p>' if d["hidden"] else ""
            co = ' <span class="badge">Co-owner</span>' if d["user_id"] != u["id"] else ""
            cards.append(f"""<article class="dcard">{ph}<div class="bd"><h3>{e(d["name"])}{co}</h3><p class="meta">{e(meta) or "&nbsp;"}</p>{hidden}
<div class="acts"><a class="btn btn-sm" href="/me/dogs/{d["id"]}/edit">Edit profile</a><a class="btn btn-ghost btn-sm" href="/dogs/{e(d["slug"])}">View page</a></div>
<p class="small" style="margin:10px 0 0"><a href="/me/dogs/{d["id"]}/care"><svg class="ico" aria-hidden="true"><use href="#i-shield"/></svg> Care reminders</a></p></div></article>""")
        if owned < A.MAX_DOGS:
            hint = ""
            wl = A.waitlist_dog_name(u.get("waitlist_id"))
            if wl and not dogs:
                hint = f'<p class="small muted">You told us about {e(wl)} when you joined the waitlist.</p>'
            cards.append(f"""<a class="dcard add" href="/me/dogs/new"><span class="plus" aria-hidden="true">+</span><h3>Add a dog</h3>
<p class="meta">Name, breed, personality, favorite runs and photos.</p>{hint}</a>""")
        incomplete = ""
        if not u["display_name"] or not u["area"]:
            incomplete = ('<div class="notice"><strong>Finish your profile.</strong> Add your first name and area so other '
                          'dog owners know who they\'re meeting. <a href="/me/profile">Complete your profile</a></div>')
        name = u["display_name"] or "there"
        wh = where_text(u["town"], u["area"])
        add_btn = "" if owned >= A.MAX_DOGS else '<a class="btn btn-gold" href="/me/dogs/new">+ Add a dog</a>'
        body = f"""<section class="phead"><div class="wrap"><div class="mehead"><div><span class="eyebrow">my dogs</span>
<h1>Hi, {e(name)}!</h1><p class="lead">{e(wh) or "Welcome to BarksBuds."}</p></div>{add_btn}</div></div></section>
<section class="section"><div class="wrap">{incomplete}
<div class="dgrid">{''.join(cards)}</div>
<div class="acctgrid" style="margin-top:44px">
<div class="panel"><h2>Your profile</h2>
<dl class="kv"><dt>Name</dt><dd>{e(u["display_name"]) or "Not set"}</dd><dt>Area</dt><dd>{e(wh) or "Not set"}</dd>
<dt>About</dt><dd>{e(u["bio"]) or "Not set"}</dd></dl>
<a class="btn btn-ghost btn-sm" href="/me/profile">Edit profile</a></div>
<div class="panel"><h2>Account</h2>
<dl class="kv"><dt>Email</dt><dd>{e(u["email"])}</dd></dl>
<p class="small muted">Only you can see your email. It's never shown on your profile or your dogs' pages.</p>
{self.email_prefs_html(u)}{self.pack_email_prefs_html(u)}{self.message_email_prefs_html(u)}{self.community_prefs_html(u)}
<div class="formfoot"><form method="post" action="/signout">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit">Sign out</button></form>
<a class="small" href="/me/delete">Delete my account</a></div></div>
</div>{self.packs_dashboard(u)}{self.meetups_dashboard(u)}</div></section>"""
        return self.page("My dogs", body, flash=self.flash_from(q))

    def area_select(self, current, name="area"):
        opts = ['<option value="">Choose your area</option>']
        groups = {}
        for a, g in A.AREAS:
            groups.setdefault(g, []).append(a)
        for g, items in groups.items():
            opts.append(f'<optgroup label="{e(g)}">' + "".join(
                f'<option value="{e(a)}"{" selected" if a == current else ""}>{e(area_label(a))}</option>' for a in items) + "</optgroup>")
        return f'<select id="{name}" name="{name}" required>{"".join(opts)}</select>'

    def town_datalist(self):
        towns = sorted({r.get("town_or_neighborhood") for r in RUNS() if r.get("town_or_neighborhood")} | {"Manhasset"})
        return '<datalist id="towns">' + "".join(f'<option value="{e(t)}">' for t in towns) + "</datalist>"

    def profile_page(self, vals=None, errs=None, code=200):
        u = self.user()
        if not u:
            return self.need_login()
        v = vals or u
        errs = errs or {}
        inv = lambda k: ' aria-invalid="true"' if errs.get(k) else ""
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">about you</span><h1>Your profile</h1>
<p class="lead">This is what other members see next to your dogs. Your email always stays private.</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel" method="post" action="/me/profile" novalidate>{self.csrf_field()}
{'<p class="formerr" role="alert">Please fix the highlighted fields.</p>' if errs else ''}
<div class="field"><label for="display_name">First name or nickname</label>
<input id="display_name" name="display_name" type="text" maxlength="40" required autocomplete="given-name" value="{e(v.get("display_name", ""))}"{inv("display_name")}>
<span class="err">{e(errs.get("display_name", ""))}</span><span class="help">Shown publicly, e.g. "Mike" or "Lily's mom".</span></div>
<div class="row2"><div class="field"><label for="area">Area</label>{self.area_select(v.get("area", ""))}
<span class="err">{e(errs.get("area", ""))}</span></div>
<div class="field"><label for="town">Town or neighborhood <span class="opt">(optional)</span></label>
<input id="town" name="town" type="text" maxlength="60" list="towns" value="{e(v.get("town", ""))}" placeholder="e.g. Manhasset, Park Slope">{self.town_datalist()}</div></div>
<div class="field"><label for="bio">A little about you <span class="opt">(optional)</span></label>
<textarea id="bio" name="bio" maxlength="300" rows="3" placeholder="Weekend dog run regular, always up for a group walk.">{e(v.get("bio", ""))}</textarea></div>
<div class="formfoot"><button class="btn" type="submit">Save profile</button><a href="/me">Cancel</a></div>
</form></div></section>"""
        return self.page("Your profile", body, code=code)

    def post_profile(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        v = dict(display_name=clean(f.get("display_name"), 40), area=f.get("area").strip(),
                 town=clean(f.get("town"), 60), bio=clean(f.get("bio"), 300, multiline=True))
        errs = {}
        if not v["display_name"]:
            errs["display_name"] = "Please add a first name or nickname."
        if v["area"] not in A.AREA_NAMES:
            errs["area"] = "Please choose your area."
        if errs:
            return self.profile_page(v, errs, code=422)
        A.update_profile(u["id"], v["display_name"], v["area"], v["town"], v["bio"])
        return self.redirect("/me?m=profile")

    def delete_account_page(self):
        u = self.user()
        if not u:
            return self.need_login()
        return self.msg_page("Delete your account?", f"""<p class="sub">This permanently deletes your profile, all of your dogs' profiles and their photos.
It can't be undone. Dogs you share with a co-owner stay on BarksBuds with them.</p><form method="post" action="/me/delete">{self.csrf_field()}
<label class="switch" style="text-align:left;margin-bottom:16px"><input type="checkbox" name="confirm" value="yes" required><span>Yes, delete my account and all my dogs' profiles.</span></label>
<button class="btn" type="submit">Delete my account</button></form><p class="small" style="margin-top:14px"><a href="/me">Keep my account</a></p>""", icon="i-alert")

    def post_delete_account(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        if f.get("confirm") != "yes":
            return self.delete_account_page()
        A.delete_user(u["id"])
        self._set_cookie(SESSION_COOKIE, "", max_age=0)
        self._user_cache = None
        print(f"account: user {u['id']} deleted their account", flush=True)
        return self.msg_page("Your account is deleted", '<p class="sub">Your profile, dogs and photos are gone. Thanks for being part of the pack.</p>'
                             '<p><a class="btn" href="/">Back to BarksBuds</a></p>')

    # ------------------------------------------------------------ dogs: owner side
    def own_dog(self, dog_id, primary=False):
        """The dog when the signed-in account owns or co-owns it (primary=True: only the primary owner), else a 404 page."""
        u = self.user()
        if not u:
            self.need_login()
            return None
        d = A.dog_by_id(dog_id)
        role = CO.role(d, u["id"]) if d else None
        if d:
            d["my_role"] = role  # 'owner' (primary) or 'co-owner'
        if not d or not role or (primary and role != "owner"):
            self.msg_page("Dog not found", '<p class="sub">We couldn\'t find that dog on your account.</p>'
                          '<p><a class="btn" href="/me">My dogs</a></p>', code=404)
            return None
        return d

    def run_picker(self, chosen):
        groups = {}
        for r in RUNS():
            if (r.get("type") or "").lower().startswith("off-leash area"):
                continue
            groups.setdefault(r.get("county") or "Other", []).append(r)
        out = []
        for county in [a for a in A.AREA_NAMES if a in groups] + [c for c in groups if c not in A.AREA_NAMES]:
            out.append(f'<h4>{e(area_label(county))}</h4>')
            for r in sorted(groups[county], key=lambda r: r["name"]):
                hay = (r["name"] + " " + (r.get("town_or_neighborhood") or "") + " " + county).lower()
                out.append(f'<label data-hay="{e(hay)}"><input type="checkbox" name="runs" value="{e(r["id"])}" data-name="{e(r["name"])}"'
                           f'{" checked" if r["id"] in chosen else ""}><span>{e(r["name"])}<small>{e(r.get("town_or_neighborhood") or "")}</small></span></label>')
        return "".join(out)

    def dog_form_page(self, d, vals=None, errs=None, code=200, q=None):
        u = self.user()
        if not u:
            return self.need_login()
        q = q or {}
        if d is None and A.owned_dog_count(u["id"]) >= A.MAX_DOGS:
            return self.msg_page("That's a full pack", f'<p class="sub">Each account can have up to {A.MAX_DOGS} dogs.</p>'
                                 '<p><a class="btn" href="/me">My dogs</a></p>')
        errs = errs or {}
        src = vals or d or {}
        get = lambda k, dflt="": src.get(k, dflt) if src else dflt
        age_val = vals.get("age", "") if vals else (A.age_years_value(d) if d else "")

        def ticks(name, options, chosen):
            return "".join(f'<label class="tick"><input type="checkbox" name="{name}" value="{e(o)}"{" checked" if o in chosen else ""}>'
                           f'<span>{e(o)}</span></label>' for o in options)

        def radios(name, options, cur, none_label):
            r = [f'<label class="tick"><input type="radio" name="{name}" value=""{" checked" if not cur else ""}><span>{none_label}</span></label>']
            r += [f'<label class="tick"><input type="radio" name="{name}" value="{e(k)}"{" checked" if k == cur else ""}><span>{e(lab)}</span></label>'
                  for k, lab in options]
            return "".join(r)

        def compat_ticks(chosen):
            return "".join(f'<label class="tick"><input type="checkbox" name="compat" value="{k}"{" checked" if k in chosen else ""}>'
                           f'<span>{e(lab)}</span></label>' for k, lab in A.COMPAT)

        is_new = d is None
        action = "/me/dogs/new" if is_new else f"/me/dogs/{d['id']}/edit"
        err = lambda k: f'<span class="err">{e(errs.get(k, ""))}</span>'
        inv = lambda k: ' aria-invalid="true"' if errs.get(k) else ""
        photos_html = "" if is_new else (self.photo_manager(d, q.get("pe", [""])[0]) + self.portrait_panel(d, q) + self.coowner_panel(d, q)
                                         + self.care_panel(d))
        title = "Add a dog" if is_new else f"Edit {d['name']}"
        dn = e(d["name"]) if d else ""
        lead = ("Tell the pack about your dog. You can add photos on the next step." if is_new else
                f'Changes show up on <a href="/dogs/{e(d["slug"])}">{dn}\'s public page</a> right away.')
        delete_link = "" if is_new or CO.role(d, u["id"]) != "owner" else f'<a class="small" href="/me/dogs/{d["id"]}/delete">Delete this profile</a>'
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">{'new pup' if is_new else 'dog profile'}</span><h1>{e(title)}</h1>
<p class="lead">{lead}</p></div></section>
<section class="section"><div class="wrap narrow">
{photos_html}
<form class="panel" method="post" action="{action}" novalidate id="dogform">{self.csrf_field()}
<h2>About {dn or 'your dog'}</h2>
{'<p class="formerr" role="alert">Please fix the highlighted fields.</p>' if errs else ''}
<div class="row2"><div class="field"><label for="name">Name</label><input id="name" name="name" type="text" maxlength="40" required value="{e(get("name"))}"{inv("name")}>{err("name")}</div>
<div class="field"><label for="breed">Breed <span class="opt">(optional)</span></label><input id="breed" name="breed" type="text" maxlength="60" value="{e(get("breed"))}" placeholder="e.g. Standard Poodle mix"></div></div>
<div class="row2"><div class="field"><label for="birthday">Birthday <span class="opt">(optional)</span></label><input id="birthday" name="birthday" type="date" value="{e(get("birthday"))}" max="{date.today().isoformat()}"{inv("birthday")}>{err("birthday")}</div>
<div class="field"><label for="age">Or age in years <span class="opt">(optional)</span></label><input id="age" name="age" type="number" min="0" max="30" inputmode="numeric" value="{e(str(age_val))}"{inv("age")}>{err("age")}<span class="help">Used when you don't know the exact birthday.</span></div></div>
<div class="field"><label for="gotcha_day">Gotcha day <span class="opt">(optional: the day they came home)</span></label><input id="gotcha_day" name="gotcha_day" type="date" value="{e(get("gotcha_day"))}" max="{date.today().isoformat()}"{inv("gotcha_day")}>{err("gotcha_day")}<span class="help">We'll celebrate {dn or 'your dog'} on the homepage on their birthday and gotcha day.</span></div>
<div class="field"><fieldset class="checks-grid"><legend>Sex</legend>{radios("sex", A.SEXES, get("sex"), "Not saying")}</fieldset></div>
<div class="field"><fieldset class="checks-grid"><legend>Size</legend>{radios("size", A.SIZES, get("size"), "Not saying")}</fieldset></div>
<div class="field"><fieldset class="checks-grid"><legend>Energy</legend>{radios("energy", A.ENERGY, get("energy"), "Not saying")}</fieldset></div>
<div class="field"><fieldset class="checks-grid"><legend>Around other dogs <span class="opt">(helps others plan a good first meeting)</span></legend>{compat_ticks(get("compat", []) or [])}</fieldset></div>
<div class="field"><fieldset class="checks-grid"><legend>Personality <span class="opt">(pick up to 6)</span></legend>{ticks("temperament", A.TEMPERAMENT, get("temperament", []) or [])}</fieldset>{err("temperament")}</div>
<div class="field"><fieldset class="checks-grid"><legend>Play style <span class="opt">(pick up to 3)</span></legend>{ticks("play_style", A.PLAY_STYLES, get("play_style", []) or [])}</fieldset>{err("play_style")}</div>
<div class="field"><label class="switch"><input type="checkbox" name="vaccinated" value="1"{" checked" if get("vaccinated") else ""}><span><b>Vaccinations are up to date</b><br><span class="small muted">Self-reported by you. Shown as a badge on the public page.</span></span></label></div>
<div class="field"><span class="lab" id="runs-lab">Favorite dog runs <span class="opt">(up to {A.MAX_FAV_RUNS})</span></span>
<div class="runpick" role="group" aria-labelledby="runs-lab"><input class="rp-search" type="search" placeholder="Search runs by name or town" aria-label="Search dog runs" hidden>
<div class="rp-chosen" aria-live="polite"></div><div class="rp-list">{self.run_picker(set(get("fav_runs", []) or []))}</div></div>{err("runs")}</div>
<div class="field"><label for="website">Website or social link <span class="opt">(optional)</span></label><input id="website" name="website" type="url" inputmode="url" maxlength="200" placeholder="https://instagram.com/yourdog" value="{e(get("website"))}"{inv("website")}>{err("website")}<span class="help">Shown on {dn or 'your dog'}'s public page. Must start with http:// or https://.</span></div>
<div class="field"><label for="bio">Bio <span class="opt">(optional)</span></label><textarea id="bio" name="bio" maxlength="600" rows="4" placeholder="Favorite toy, best trick, what makes them happiest at the run…">{e(get("bio"))}</textarea></div>
<div class="formfoot"><button class="btn" type="submit">{'Create profile' if is_new else 'Save changes'}</button><a href="/me">Cancel</a><span class="spacer"></span>{delete_link}</div>
</form></div></section>"""
        js = """<script>
(function(){var box=document.querySelector('.runpick');if(box){var s=box.querySelector('.rp-search'),list=box.querySelector('.rp-list'),chosen=box.querySelector('.rp-chosen'),MAX=%d;
s.hidden=false;var cbs=[].slice.call(list.querySelectorAll('input'));
function draw(){chosen.innerHTML='';var on=cbs.filter(function(c){return c.checked});on.forEach(function(c){var b=document.createElement('button');b.type='button';b.textContent=c.dataset.name;b.setAttribute('aria-label','Remove '+c.dataset.name);b.onclick=function(){c.checked=false;draw()};chosen.appendChild(b)});
cbs.forEach(function(c){c.disabled=!c.checked&&on.length>=MAX})}
cbs.forEach(function(c){c.addEventListener('change',draw)});draw();
s.addEventListener('input',function(){var v=s.value.trim().toLowerCase();list.querySelectorAll('label').forEach(function(l){l.hidden=!!v&&l.dataset.hay.indexOf(v)<0});
list.querySelectorAll('h4').forEach(function(h){var n=h.nextElementSibling,any=false;while(n&&n.tagName==='LABEL'){if(!n.hidden)any=true;n=n.nextElementSibling}h.hidden=!any})});}
function cap(sel,max){var bs=[].slice.call(document.querySelectorAll(sel));function f(){var n=bs.filter(function(b){return b.checked}).length;bs.forEach(function(b){b.disabled=!b.checked&&n>=max})}bs.forEach(function(b){b.addEventListener('change',f)});f()}
cap('input[name=temperament]',6);cap('input[name=play_style]',3);
var up=document.getElementById('upf');if(up){up.addEventListener('submit',function(ev){var fi=up.querySelector('input[type=file]'),tot=0,big=false;[].forEach.call(fi.files,function(x){tot+=x.size;if(x.size>12*1024*1024)big=true});
var m=up.querySelector('.err');if(!fi.files.length){ev.preventDefault();m.textContent='Choose at least one photo to upload.';return}
if(big){ev.preventDefault();m.textContent='Photos can be up to 12 MB each.';return}if(tot>38*1024*1024){ev.preventDefault();m.textContent='That is a lot at once. Try a few photos at a time.';return}
var b=up.querySelector('button');b.disabled=true;b.textContent='Uploading…'})}
})();
</script>""" % A.MAX_FAV_RUNS
        return self.page(title, body, code=code, scripts=js, flash=self.flash_from(q))

    def photo_manager(self, d, perr=""):
        photos = A.gallery(d["id"])
        _, avatar = A.cover_and_avatar(d, photos)
        items = []
        for i, p in enumerate(photos):
            badges = []
            if i == 0:
                badges.append('<span class="badge">Cover</span>')
            if p["id"] == avatar:
                badges.append('<span class="badge">Profile pic</span>')
            mk = "<span></span>" if p["id"] == avatar else (
                f'<form method="post" action="/me/dogs/{d["id"]}/photos/{p["id"]}/avatar">{self.csrf_field()}'
                f'<button class="linkbtn" type="submit">Make profile pic</button></form>')
            items.append(f"""<div class="pitem"><img src="/p/{p["id"]}.webp" alt="Photo {i + 1} of {e(d["name"])}" loading="lazy">
<div class="pa"><span>{' '.join(badges) or '&nbsp;'}</span></div><div class="pa">{mk}
<form method="post" action="/me/dogs/{d["id"]}/photos/{p["id"]}/delete" onsubmit="return confirm('Remove this photo?')">{self.csrf_field()}<button class="linkbtn" type="submit">Remove</button></form></div></div>""")
        left = A.MAX_PHOTOS - len(photos)
        av_html = ""
        if d.get("avatar_photo_id") and d["avatar_photo_id"] not in [p["id"] for p in photos]:
            av_html = (f'<div class="avatarpick" style="margin-bottom:18px"><img class="av" src="/p/{d["avatar_photo_id"]}.webp" alt="" width="72" height="72">'
                       f'<p class="small muted" style="margin:0">This is {e(d["name"])}\'s profile picture. Pick "Make profile pic" on any photo to change it.</p></div>')
        if left > 0:
            upload = f"""<form id="upf" method="post" action="/me/dogs/{d["id"]}/photos" enctype="multipart/form-data">{self.csrf_field()}
<div class="drop"><svg class="ico" aria-hidden="true" style="width:34px;height:34px;color:var(--red)"><use href="#i-camera"/></svg>
<label for="photos"><b>Add photos</b> <span class="muted small">(JPEG, PNG or WebP, up to 12 MB each, {left} more allowed)</span></label>
<input id="photos" name="photos" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple required>
<span class="err" role="alert">{e(PHOTO_ERR.get(perr, ""))}</span>
<button class="btn btn-sm" type="submit">Upload</button>
<span class="small muted">We remove location data and other hidden info from every photo.</span></div></form>"""
        else:
            upload = (f'<p class="notice small">{e(d["name"])} has {A.MAX_PHOTOS} photos, the most we allow for now. Remove one to add another.</p>'
                      + (f'<p class="err">{e(PHOTO_ERR.get(perr, ""))}</p>' if perr else ""))
        grid = f'<div class="pgrid">{"".join(items)}</div>' if items else ""
        return f"""<div class="panel" id="photos-panel"><h2>Photos</h2><p class="hint">The first photo is the cover on {e(d["name"])}'s page.</p>
{av_html}{grid}{upload}</div>"""


    def parse_dog(self, f):
        v = dict(name=clean(f.get("name"), 40), breed=clean(f.get("breed"), 60), birthday=f.get("birthday").strip()[:10],
                 age=f.get("age").strip()[:3], sex=f.get("sex"), size=f.get("size"),
                 temperament=[t for t in A.TEMPERAMENT if t in f.getlist("temperament")],
                 play_style=[t for t in A.PLAY_STYLES if t in f.getlist("play_style")],
                 vaccinated=f.get("vaccinated") == "1", bio=clean(f.get("bio"), 600, multiline=True),
                 website=f.get("website").strip()[:300], energy=f.get("energy"),
                 compat=[k for k, _ in A.COMPAT if k in f.getlist("compat")], gotcha_day=f.get("gotcha_day").strip()[:10])
        runs = run_index()
        picked = []
        for r in f.getlist("runs"):
            if r in runs and r not in picked:
                picked.append(r)
        v["fav_runs"] = picked
        errs = {}
        if not v["name"]:
            errs["name"] = "What's your dog's name?"
        site = A.clean_website(v["website"])
        if site is None:
            errs["website"] = "Please enter a full web address starting with http:// or https:// (or leave it blank)."
        else:
            v["website"] = site
        v["birth_year"] = None
        if v["birthday"]:
            bd = None
            if DATE_RE.match(v["birthday"]):
                try:
                    bd = date.fromisoformat(v["birthday"])
                except ValueError:
                    bd = None
            if not bd or bd > date.today() or bd.year < date.today().year - 30:
                errs["birthday"] = "Please enter a real birthday (or leave it blank)."
            v["age"] = ""
        elif v["age"]:
            if not v["age"].isdigit() or int(v["age"]) > 30:
                errs["age"] = "Age should be a number from 0 to 30."
            else:
                v["birth_year"] = date.today().year - int(v["age"])
        if v["gotcha_day"]:
            gd = None
            if DATE_RE.match(v["gotcha_day"]):
                try:
                    gd = date.fromisoformat(v["gotcha_day"])
                except ValueError:
                    gd = None
            if not gd or gd > date.today() or gd.year < date.today().year - 30:
                errs["gotcha_day"] = "Please enter a real date (or leave it blank)."
        if v["energy"] not in ("", *[k for k, _ in A.ENERGY]):
            v["energy"] = ""
        if v["sex"] not in ("", *[k for k, _ in A.SEXES]):
            v["sex"] = ""
        if v["size"] not in ("", *[k for k, _ in A.SIZES]):
            v["size"] = ""
        if len(v["temperament"]) > 6:
            errs["temperament"] = "Pick up to 6."
        if len(v["play_style"]) > 3:
            errs["play_style"] = "Pick up to 3."
        if len(picked) > A.MAX_FAV_RUNS:
            errs["runs"] = f"Pick up to {A.MAX_FAV_RUNS} favorite runs."
        return v, errs

    def post_dog(self, dog_id=None):
        u = self.user()
        if not u:
            return self.need_login()
        d = None
        if dog_id:
            d = self.own_dog(int(dog_id))
            if d is None:
                return
        elif A.owned_dog_count(u["id"]) >= A.MAX_DOGS:
            return self.dog_form_page(None)
        f = self._form_or_fail()
        if f is None:
            return
        v, errs = self.parse_dog(f)
        if errs:
            return self.dog_form_page(d, vals=v, errs=errs, code=422)
        new_id = A.save_dog(u["id"], v, dog_id=d["id"] if d else None)
        if d:
            return self.redirect(f"/me/dogs/{new_id}/edit?m=saved")
        print(f"dogs: user {u['id']} created dog {new_id}", flush=True)
        return self.redirect(f"/me/dogs/{new_id}/edit?m=created#photos-panel")

    def delete_dog_page(self, d):
        return self.msg_page(f"Delete {d['name']}'s profile?", f"""<p class="sub">This removes {e(d["name"])}'s page and all of their photos. It can't be undone.</p>
<form method="post" action="/me/dogs/{d["id"]}/delete">{self.csrf_field()}<button class="btn" type="submit">Delete {e(d["name"])}'s profile</button></form>
<p class="small" style="margin-top:14px"><a href="/me/dogs/{d["id"]}/edit">Keep it</a></p>""", icon="i-alert")

    def post_delete_dog(self, dog_id):
        d = self.own_dog(int(dog_id), primary=True)
        if d is None:
            return
        if self._form_or_fail() is None:
            return
        A.delete_dog(d["id"])
        print(f"dogs: dog {d['id']} deleted by owner", flush=True)
        return self.redirect("/me?m=deleted")

    def post_photos(self, dog_id):
        d = self.own_dog(int(dog_id))
        if d is None:
            return
        back = f"/me/dogs/{d['id']}/edit"
        f = self.read_form(MAX_UPLOAD_REQUEST)
        if f is None:
            return self.redirect(back + "?pe=toobig#photos-panel")
        if not self.csrf_ok(f):
            return self.csrf_fail()
        files = [x for x in f.files if x[0] == "photos"]
        if not files:
            return self.redirect(back + "?pe=none#photos-panel")
        if not A.LIMITER.allow(f"upload:{self.user()['id']}", 40, 3600):
            return self.redirect(back + "?pe=count#photos-panel")
        added, err = 0, ""
        for _, _fn, data in files:
            if A.photo_count(d["id"]) >= A.MAX_PHOTOS:
                err = "count"
                break
            try:
                A.add_photo(d["id"], data)
                added += 1
            except A.BadImage as ex:
                s = str(ex)
                err = "big" if "MB" in s else "small" if "small" in s else "type" if "isn't" in s else "read"
        print(f"photos: dog {d['id']} +{added}" + (f" ({err})" if err else ""), flush=True)
        if err:
            return self.redirect(back + f"?pe={err}" + ("&m=photos" if added else "") + "#photos-panel")
        return self.redirect(back + "?m=photos#photos-panel")

    def post_photo_action(self, dog_id, photo_id, action):
        d = self.own_dog(int(dog_id))
        if d is None:
            return
        if self._form_or_fail() is None:
            return
        if action == "delete":
            A.delete_photo(d["id"], int(photo_id))
            return self.redirect(f"/me/dogs/{d['id']}/edit?m=photo_deleted#photos-panel")
        A.set_avatar(d["id"], int(photo_id))
        return self.redirect(f"/me/dogs/{d['id']}/edit?m=avatar#photos-panel")

    # ------------------------------------------------------------ dogs: public side
    @staticmethod
    def card_ph(d, pid, alt=""):
        """Card image: the pixel pal when it's the avatar (or there's no photo), else the photo with a small sprite badge."""
        px = d.get("pixel_photo_id") if A.SHOW_OLD_SPRITES else None  # old maker sprites aren't shown
        if px and (d.get("pixel_primary") or not pid):
            return (f'<div class="ph pxph"><img src="/px/{px}-1x.png" alt="{e(alt and alt + ", pixel art")}" loading="lazy"></div>')
        if pid:
            badge = f'<img class="pxbadge" src="/px/{px}-1x.png" alt="" width="52" height="52" loading="lazy">' if px else ""
            return f'<div class="ph"><img src="/p/{pid}.webp" alt="{e(alt)}" loading="lazy">{badge}</div>'
        return '<div class="ph empty"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></div>'

    def dog_card(self, d, pid):
        ph = self.card_ph(d, pid, d["name"])
        meta = " · ".join(x for x in (d["breed"], A.age_text(d)) if x)
        wh = where_text(d["town"], d["area"])
        loc = f'<p class="where"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>{e(wh)}</p>' if wh else ""
        return (f'<a class="dcard" href="/dogs/{e(d["slug"])}">{ph}<div class="bd"><h3>{e(d["name"])}</h3>'
                f'<p class="meta">{e(meta) or "&nbsp;"}</p>{loc}</div></a>')

    def browse_page(self, q):
        area = q.get("area", [""])[0]
        region = q.get("region", [""])[0]
        areas, label, canon = None, "all areas", "/dogs"
        if area in A.AREA_NAMES:
            areas, label, canon = [area], area_label(area), "/dogs?area=" + quote(area)
        elif region in A.REGIONS:
            (label, areas), canon = A.REGIONS[region], "/dogs?region=" + region
        fsize = q.get("size", [""])[0]
        fsize = fsize if fsize in dict(A.SIZES) else ""
        fen = q.get("energy", [""])[0]
        fen = fen if fen in dict(A.ENERGY) else ""
        fcp = [k for k, _ in A.COMPAT if k in q.get("compat", []) and k not in ("rough", "shy")]
        filtered = bool(fsize or fen or fcp)

        def match(d):
            return ((not fsize or d.get("size") == fsize) and (not fen or d.get("energy") == fen)
                    and all(k in (d.get("compat") or []) for k in fcp))
        dogs = A.browse_dogs(areas, match=match if filtered else None)
        firsts = A.first_photos([d["id"] for d in dogs])
        cards = [self.dog_card(d, d.get("avatar_photo_id") or firsts.get(d["id"])) for d in dogs]  # main picture first
        cur = lambda on: ' aria-current="page"' if on else ""
        chips = [f'<li><a href="/dogs"{cur(not areas)}>All areas</a></li>']
        chips += [f'<li><a href="/dogs?region={k}"{cur(region == k and area not in A.AREA_NAMES)}>{e(v[0])}</a></li>' for k, v in A.REGIONS.items()]
        chips.append('<li class="sep" aria-hidden="true"></li>')
        chips += [f'<li><a href="/dogs?area={quote(a)}"{cur(area == a)}>{e(area_label(a))}</a></li>' for a in A.AREA_NAMES if a != "Westchester"]
        add = "/me/dogs/new" if self.user() else self.signin_href("/me/dogs/new")
        grid = (f'<div class="dgrid">{"".join(cards)}</div>' if cards else
                f'<div class="empty"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg><h2>No dogs in {e(label)} yet</h2>'
                f'<p class="muted">Be the first! Create a profile for your dog and invite your dog run friends.</p><a class="btn" href="{add}">Add your dog</a></div>')
        if filtered and not cards:
            grid = (f'<div class="empty"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg><h2>No matches yet</h2>'
                    f'<p class="muted">No dogs in {e(label)} match those filters. Try fewer filters.</p>'
                    f'<a class="btn btn-ghost" href="{e(canon)}">Clear filters</a></div>')
        opt = lambda items, cur, none: f'<option value="">{none}</option>' + "".join(
            f'<option value="{k}"{" selected" if k == cur else ""}>{e(v)}</option>' for k, v in items)
        keep = (f'<input type="hidden" name="area" value="{e(area)}">' if area in A.AREA_NAMES else
                f'<input type="hidden" name="region" value="{e(region)}">' if region in A.REGIONS else "")
        cticks = "".join(f'<label class="tick"><input type="checkbox" name="compat" value="{k}"{" checked" if k in fcp else ""}><span>{e(v)}</span></label>'
                         for k, v in A.COMPAT if k not in ("rough", "shy"))
        filt = (f'<form class="dfilt" method="get" action="/dogs" aria-label="Filter dogs">{keep}'
                f'<div class="field"><label for="fsize">Size</label><select id="fsize" name="size">{opt(A.SIZES, fsize, "Any size")}</select></div>'
                f'<div class="field"><label for="fen">Energy</label><select id="fen" name="energy">{opt(A.ENERGY, fen, "Any energy")}</select></div>'
                f'<fieldset class="checks-grid" style="border:0;padding:0;margin:0"><legend class="sr-only">Good with</legend>{cticks}</fieldset>'
                f'<button class="btn btn-sm" type="submit">Filter</button>'
                + (f'<a class="small" href="{e(canon)}">Clear</a>' if filtered else "") + '</form>')
        try:
            import communityweb
            celeb = communityweb.celebrating_html(areas)
        except Exception:
            celeb = ""
        n = len(dogs)
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">meet the pack</span><h1>Dogs on BarksBuds</h1>
<p class="lead">Say hi to the dogs of NYC, Long Island and Westchester. Add your own pup and pick their favorite runs.</p></div></section>
<section class="section"><div class="wrap"><nav aria-label="Filter by area"><ul class="filters">{''.join(chips)}</ul></nav>{filt}{celeb}{grid}
<p class="small muted" style="margin-top:28px">{n} dog{'s' if n != 1 else ''}{' matching' if filtered else ''} in {e(label)}. <a href="{add}">Add your dog</a></p>
</div></section>"""
        title = "Dogs" + (f" in {label}" if areas else " near you")
        return self.page(title, body, index=True, active="dogs", canonical=canon,
                         desc="Meet dogs and dog owners across NYC, Long Island and Westchester on BarksBuds, and find your dog's next best friend.",
                         og={"title": "Dogs on BarksBuds", "image": self._base() + "/img/og-image.jpg?v=jack3", "w": 1200, "h": 630})

    def dog_page(self, slug, q):
        d = A.dog_by_slug(slug)
        u = self.user()
        is_owner = bool(d and u and CO.can_manage(d, u["id"]))  # owner or co-owner
        if not d or (d["hidden"] and not is_owner):
            return self.msg_page("We couldn't find that dog", '<p class="sub">This profile may have been removed.</p>'
                                 '<p><a class="btn" href="/dogs">Meet the dogs</a></p>', code=404)
        owner = A.owner_public(d["user_id"])
        photos = A.gallery(d["id"])
        cover, avatar = A.cover_and_avatar(d, photos)
        age = A.age_text(d)
        sex = dict(A.SEXES).get(d["sex"], "")
        size = dict(A.SIZES).get(d["size"], "")
        wh = where_text(owner["town"], owner["area"])
        fact = lambda ico, txt, cls="": f'<li{cls}><svg class="ico" aria-hidden="true"><use href="#{ico}"/></svg>{txt}</li>'
        facts = []
        if age:
            facts.append(fact("i-cake", e(age)))
        if sex:
            facts.append(fact("i-heart", e(sex)))
        if size:
            facts.append(fact("i-ruler", e(size)))
        if wh:
            facts.append(fact("i-pin", e(wh)))
        if d["vaccinated"]:
            facts.append(fact("i-shield", 'Vaccinated <span class="small" style="opacity:.75">(owner-reported)</span>',
                              ' class="ok" title="Self-reported by the owner"'))
        alt = f'{d["name"]}, ' + (d["breed"] or "a dog")
        cov = (f'<div class="cover"><img src="/p/{cover}.jpg" alt="{e(alt)}" fetchpriority="high"></div>' if cover else
               '<div class="cover empty"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></div>')
        px = d.get("pixel_photo_id") if A.SHOW_OLD_SPRITES else None  # old maker sprites aren't shown
        av_photo = f'<img class="av" src="/p/{avatar}.webp" width="92" height="92" alt="{e(d["name"])}"' if avatar else ""
        av_pixel = f'<img class="av pxav" src="/px/{px}-1x.png" width="92" height="92" alt="{e(d["name"])}, pixel art"' if px else ""
        show_px = bool(px and (d.get("pixel_primary") or not avatar))
        if av_photo and av_pixel:  # both: a little Photo / Pixel switch
            av = (f'<div class="avsw">{av_photo} data-v="photo"{" hidden" if show_px else ""}>{av_pixel} data-v="pixel"{"" if show_px else " hidden"}>'
                  f'<div class="avtog" role="group" aria-label="Profile picture style">'
                  f'<button type="button" data-v="photo" aria-pressed="{"false" if show_px else "true"}">Photo</button>'
                  f'<button type="button" data-v="pixel" aria-pressed="{"true" if show_px else "false"}">Pixel</button></div></div>')
        else:
            av = (av_pixel or av_photo) + ">" if (av_pixel or av_photo) else ""
        runs = run_index()
        fav = [runs[r] for r in d["fav_runs"] if r in runs]
        side, main = [], []
        if fav:
            li = []
            for r in fav:
                sm = " · ".join(x for x in (r.get("town_or_neighborhood"), area_label(r.get("county") or "")) if x)
                li.append(f'<li><a href="/runs?q={quote(r["name"])}"><span class="ic"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg></span>'
                          f'<span>{e(r["name"])}<small>{e(sm)}</small></span></a></li>')
            side.append(f'<div class="panel"><h2>Favorite runs</h2><ul class="runlist">{"".join(li)}</ul></div>')
        if px:
            dl = (f'<p style="margin:14px 0 0"><a class="btn btn-ghost btn-sm" href="/px/{px}.png" download="{e(d["slug"])}-pixel-pal.png">Download PNG</a></p>'
                  if is_owner else "")
            side.insert(0, f'<div class="panel pxshow"><h2>{e(d["name"])}\'s pixel pal</h2><div class="pxstage">'
                           f'<img src="/px/{px}-1x.png" width="192" height="192" alt="{e(d["name"])} as pixel art" loading="lazy"></div>{dl}</div>')
        if is_owner:  # "Get a pixel portrait" / its status; only the owner sees it
            side.insert(0, self.portrait_panel(d, compact=True))
        chips = []
        if d.get("size"):
            chips.append(f'<li class="sz">{e(A.SIZE_SHORT.get(d["size"], ""))}</li>')
        if d.get("energy"):
            chips.append(f'<li class="en">{e(dict(A.ENERGY).get(d["energy"], ""))}</li>')
        for k, lab in A.COMPAT:
            if k in (d.get("compat") or []):
                chips.append(f'<li{" class=warn" if k in ("rough", "shy") else ""}>{e(lab)}</li>')
        if chips:
            side.insert(0, f'<div class="panel" id="compat"><h2>Meeting other dogs</h2><ul class="chips">{"".join(chips)}</ul>'
                           f'<p class="small muted" style="margin:12px 0 0">Shared by {e(d["name"])}\'s human to help plan a good first hello.</p></div>')
        today = date.today()
        for kind, when in (("birthday", d.get("birthday")), ("gotcha", d.get("gotcha_day"))):
            if when and C_is_today(when, today):
                lab = "birthday" if kind == "birthday" else "gotcha day"
                main.insert(0, f'<div class="panel celebnote"><h2><svg class="ico" aria-hidden="true"><use href="#i-cake"/></svg> '
                               f'It\'s {e(d["name"])}\'s {lab} today!</h2><p style="margin:0"><a class="btn btn-gold btn-sm" '
                               f'href="/celebrate/{e(d["slug"])}{"?k=gotcha" if kind == "gotcha" else ""}">See the celebration card</a></p></div>')
        if d.get("birthday"):
            try:
                facts.insert(1 if age else 0, fact("i-cake", "Birthday " + e(date.fromisoformat(d["birthday"]).strftime("%b %-d"))))
            except ValueError:
                pass
        if d.get("gotcha_day"):
            try:
                facts.append(fact("i-heart", "Gotcha day " + e(date.fromisoformat(d["gotcha_day"]).strftime("%b %-d"))))
            except ValueError:
                pass
        if d["play_style"]:
            side.append('<div class="panel"><h2>Play style</h2><ul class="taglist dark">' + "".join(f"<li>{e(t)}</li>" for t in d["play_style"]) + "</ul></div>")
        if d["bio"]:
            main.append(f'<div class="panel"><h2>About {e(d["name"])}</h2><p class="bio">{e(d["bio"])}</p></div>')
        if d["temperament"]:
            main.append('<div class="panel"><h2>Personality</h2><ul class="taglist">' + "".join(f"<li>{e(t)}</li>" for t in d["temperament"]) + "</ul></div>")
        if photos:
            main.append('<div class="panel"><h2>Photos</h2><div class="gallery">' + "".join(
                f'<a href="/p/{p["id"]}.jpg" data-full="/p/{p["id"]}.jpg"><img src="/p/{p["id"]}.webp" alt="{e(d["name"])}, photo {i + 1}" loading="lazy"></a>'
                for i, p in enumerate(photos)) + "</div></div>")
        if not main:
            main.append(f'<div class="panel"><p class="muted" style="margin:0">{e(d["name"])}\'s profile is just getting started.</p></div>')
        site_line = ""
        if d.get("website") and A.clean_website(d["website"]):
            host = urlsplit(d["website"]).hostname or ""
            host = host[4:] if host.startswith("www.") else host
            site_line = (f'<p class="owner"><svg class="ico" aria-hidden="true" style="color:var(--red)"><use href="#i-link"/></svg>'
                         f'<a href="{e(d["website"])}" rel="nofollow noopener noreferrer ugc" target="_blank">{e(host)}</a></p>')
        owner_line = (f'<p class="owner"><svg class="ico" aria-hidden="true" style="color:var(--red)"><use href="#i-user"/></svg>'
                      f'<span>{e(d["name"])}\'s human: <b>{e(owner["display_name"] or "a BarksBuds member")}</b></span></p>')
        edit = (f'<p class="ownacts"><a class="btn btn-gold btn-sm" href="/me/dogs/{d["id"]}/edit">Edit {e(d["name"])}\'s profile</a></p>'
                if is_owner else "")
        if not is_owner:  # Message the owner (and any co-owners); signed-out visitors are sent to sign in first
            humans = [(d["user_id"], owner["display_name"])] + [(c["user_id"], c["name"]) for c in CO.coowners(d["id"])]
            btns = [self.message_button(uid, f"Message {nm}" if nm else f"Message {d['name']}'s human") for uid, nm in humans]
            btns = [b for b in btns if b]
            if btns:
                edit = f'<p class="ownacts msgacts">{"".join(btns)}</p>'
        hidden_note = ('<div class="wrap" style="padding-top:20px"><p class="formerr">This profile is hidden from the public while our team reviews a report.</p></div>'
                       if d["hidden"] else "")
        reasons = "".join(f'<option>{e(r)}</option>' for r in A.REPORT_REASONS)
        report = "" if is_owner else f"""<details class="report"><summary>Report this profile</summary>
<form method="post" action="/dogs/{e(d["slug"])}/report">{self.csrf_field()}
<div class="field"><label for="reason">What's wrong?</label><select id="reason" name="reason">{reasons}</select></div>
<div class="field"><label for="details">Details <span class="opt">(optional)</span></label><textarea id="details" name="details" maxlength="1000" rows="3"></textarea></div>
<button class="btn btn-sm" type="submit">Send report</button><p class="small muted" style="margin:10px 0 0">Reports go to the BarksBuds team, not to the owner.</p></form></details>"""
        sub = " · ".join(x for x in (d["breed"],) if x)
        if d["bio"]:
            desc = d["bio"] if len(d["bio"]) <= 158 else d["bio"][:155].rsplit(" ", 1)[0] + "…"
        else:
            desc = f"Meet {d['name']}" + (f", a {d['breed']}" if d["breed"] else "") + (f" in {wh}" if wh else "") + ", on BarksBuds."
        og_title = d["name"] + (f", {d['breed']}" if d["breed"] else "") + (f" in {wh}" if wh else "")
        og = {"title": og_title, "desc": desc, "type": "profile", "alt": f"Photo of {d['name']}",
              "image": self._base() + (f"/p/{cover}.jpg" if cover else "/img/og-image.jpg?v=jack3")}
        og.update(w=photos[0]["width"], h=photos[0]["height"]) if cover else og.update(w=1200, h=630)
        if px and (d.get("pixel_primary") or not cover):  # share card with the sprite
            og.update(image=self._base() + f"/px/{px}-og.png", w=1200, h=630, alt=f"{d['name']} as pixel art")
        cta = "/me/dogs/new" if u else self.signin_href("/me/dogs/new")
        body = f"""{hidden_note}<section class="dhero"><div class="wrap">{cov}<div>
<div class="who">{av}<div><span class="eyebrow" style="margin:0">meet</span><h1 class="dname">{e(d["name"])}</h1></div></div>
{f'<p class="dsub">{e(sub)}</p>' if sub else ''}
<ul class="facts">{''.join(facts)}</ul>{owner_line}{site_line}{edit}</div></div></section>
<section class="section" style="padding-top:40px"><div class="wrap"><div class="dgrid2"><div>{''.join(main)}</div><div>{''.join(side)}
<div class="panel" style="background:var(--black);color:#E9E1D3;box-shadow:6px 6px 0 var(--red)"><h2 style="color:#fff">Bring your pup</h2>
<p>Give your dog a profile, pick their favorite runs and meet the regulars.</p><a class="btn btn-gold btn-sm" href="{cta}">Add your dog</a></div></div></div>
{report}</div></section>
<dialog class="lb" aria-label="Photo"><button class="x" type="button" aria-label="Close">&times;</button><img alt=""></dialog>"""
        js = """<script>(function(){var sw=document.querySelector('.avsw');if(sw){sw.querySelectorAll('.avtog button').forEach(function(b){b.addEventListener('click',function(){
sw.querySelectorAll('img.av').forEach(function(i){i.hidden=i.dataset.v!==b.dataset.v});sw.querySelectorAll('.avtog button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false')})})})}})();
(function(){var dl=document.querySelector('dialog.lb');if(!dl||!dl.showModal)return;var im=dl.querySelector('img');
document.querySelectorAll('.gallery a').forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();im.src=a.dataset.full;im.alt=a.querySelector('img').alt;dl.showModal()})});
dl.addEventListener('click',function(ev){if(ev.target===dl||ev.target.classList.contains('x'))dl.close()})})();</script>"""
        return self.page(og_title, body, index=not d["hidden"], canonical=f"/dogs/{d['slug']}", desc=desc, og=og,
                         scripts=js, active="dogs", flash=self.flash_from(q))

    def post_report(self, slug):
        d = A.dog_by_slug(slug)
        if not d:
            return self.msg_page("We couldn't find that dog", "", code=404)
        f = self._form_or_fail()
        if f is None:
            return
        reason = f.get("reason") if f.get("reason") in A.REPORT_REASONS else "Something else"
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            u = self.user()
            A.add_report(d["id"], u["id"] if u else None, reason, clean(f.get("details"), 1000, multiline=True), self._client_ip())
            print(f"reports: new report on dog {d['id']}", flush=True)
        return self.redirect(f"/dogs/{d['slug']}?m=reported")

    def photo(self, pid, ext):
        etag = '"p%d%s"' % (pid, ext)
        hdr = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": etag}
        if etag in (self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            for k, v in hdr.items():
                self.send_header(k, v)
            self.end_headers()
            return
        blob = A.photo_blob(pid, "full" if ext == "jpg" else "thumb")
        if blob is None:
            return self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"})
        return self._emit(200, blob, "image/jpeg" if ext == "jpg" else "image/webp", hdr)

    # ------------------------------------------------------------ admin (behind ADMIN_KEY)
    def _admin_key_ok(self, key):
        return bool(ADMIN_KEY) and bool(key) and hmac.compare_digest(key.encode(), ADMIN_KEY.encode())

    def admin_reports(self, q):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        rows = A.list_reports()
        st = A.storage_stats()
        users = A.one("SELECT COUNT(*) FROM users")[0]
        ndogs = A.one("SELECT COUNT(*) FROM dogs")[0]
        tr = []
        for (rid, ts, reason, details, status, slug, name, hidden, dog_id, mid, mtitle, mslug, mhidden, cid, cbody, chidden,
             pid, pname, pslug, phidden, poid, pobody, pohidden, pcid, pcbody, pchidden) in rows:
            when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            acts = []
            pairs = [("resolve", "Mark resolved") if status == "open" else ("reopen", "Reopen")]
            if pcid:
                pairs.append(("unhide_pcomment", "Unhide comment") if pchidden else ("hide_pcomment", "Hide comment"))
            elif poid:
                pairs.append(("unhide_post", "Unhide post") if pohidden else ("hide_post", "Hide post"))
            elif pid:
                pairs.append(("unhide_pack", "Unhide pack") if phidden else ("hide_pack", "Hide pack"))
            elif cid:
                pairs.append(("unhide_comment", "Unhide comment") if chidden else ("hide_comment", "Hide comment"))
            elif mid:
                pairs.append(("unhide_meetup", "Unhide meetup") if mhidden else ("hide_meetup", "Hide meetup"))
            elif dog_id:
                pairs.append(("unhide", "Unhide profile") if hidden else ("hide", "Hide profile"))
            for act, lab in pairs:
                acts.append(f'<form method="post" action="/admin/reports" style="display:inline"><input type="hidden" name="key" value="{e(key)}">'
                            f'<input type="hidden" name="id" value="{rid}"><input type="hidden" name="dog" value="{dog_id or ""}">'
                            f'<input type="hidden" name="meetup" value="{mid or ""}"><input type="hidden" name="comment" value="{cid or ""}">'
                            f'<input type="hidden" name="pack" value="{pid or ""}"><input type="hidden" name="post" value="{poid or ""}">'
                            f'<input type="hidden" name="pcomment" value="{pcid or ""}">'
                            f'<input type="hidden" name="action" value="{act}"><button class="linkbtn" type="submit">{lab}</button></form>')
            if pid or poid or pcid:
                plink = f'<a href="/packs/{pid}-{e(pslug or "")}">{e(pname or "")}</a>' if pname else "(deleted pack)"
                if pcid:
                    what = f'Comment in pack {plink}: <q>{e((pcbody or "")[:160])}</q>' + (" <b>(hidden)</b>" if pchidden else "")
                elif poid:
                    what = f'Post in pack {plink}: <q>{e((pobody or "")[:160])}</q>' + (" <b>(hidden)</b>" if pohidden else "")
                else:
                    what = f'Pack {plink}' + (" <b>(hidden)</b>" if phidden else "")
            elif cid or mid:
                mlink = f'<a href="/meetups/{mid}-{e(mslug or "")}">{e(mtitle or "")}</a>' if mtitle else "(deleted meetup)"
                if cid:
                    what = f'Comment on {mlink}: <q>{e((cbody or "")[:160])}</q>' + (" <b>(hidden)</b>" if chidden else "")
                else:
                    what = f'Meetup {mlink}' + (" <b>(hidden)</b>" if mhidden else "")
            else:
                what = (f'<a href="/dogs/{e(slug)}">{e(name)}</a>' if slug else "(deleted)") + (" <b>(hidden)</b>" if hidden else "")
            tr.append(f"<tr><td>{rid}</td><td>{when}</td><td>{what}</td><td>{e(reason)}</td>"
                      f"<td style='white-space:pre-line'>{e(details)}</td><td>{e(status)}</td><td>{' · '.join(acts)}</td></tr>")
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">admin</span><h1>Reports</h1>
<p class="lead">{users} member{'s' if users != 1 else ''} · {ndogs} dog profile{'s' if ndogs != 1 else ''} · {st['photos']} photos using {st['bytes'] / 1048576:.1f} MB of database storage.</p></div></section>
<section class="section"><div class="wrap"><div style="overflow-x:auto"><table class="t"><thead><tr><th>#</th><th>When</th><th>What</th><th>Reason</th><th>Details</th><th>Status</th><th>Actions</th></tr></thead>
<tbody>{''.join(tr) or '<tr><td colspan="7">No reports yet.</td></tr>'}</tbody></table></div></div></section>"""
        return self.page("Admin: reports", body)

    def post_admin_reports(self):
        f = self.read_form()
        if f is None or not self._admin_key_ok(f.get("key")):
            return self._emit(404, b"Not found", "text/plain")
        act, rid, dog = f.get("action"), f.get("id"), f.get("dog")
        if act in ("resolve", "reopen") and rid.isdigit():
            A.set_report_status(int(rid), "resolved" if act == "resolve" else "open")
        elif act in ("hide", "unhide") and dog.isdigit():
            A.set_dog_hidden(int(dog), act == "hide")
        elif act in ("hide_meetup", "unhide_meetup") and f.get("meetup").isdigit():
            import meetups
            meetups.set_hidden(int(f.get("meetup")), act == "hide_meetup")
        elif act in ("hide_comment", "unhide_comment") and f.get("comment").isdigit():
            import meetups
            meetups.set_comment_hidden(int(f.get("comment")), act == "hide_comment")
        elif act in ("hide_pack", "unhide_pack", "hide_post", "unhide_post", "hide_pcomment", "unhide_pcomment"):
            import packs
            fld = {"pack": "pack", "post": "post", "pcomment": "pcomment"}[act.split("_", 1)[1]]
            val = f.get(fld)
            if val.isdigit():
                {"pack": packs.set_hidden, "post": packs.set_post_hidden, "pcomment": packs.set_comment_hidden}[fld](int(val), act.startswith("hide"))
        print(f"admin: report action {act}", flush=True)
        return self.redirect("/admin/reports?key=" + quote(f.get("key")))

    def post_admin_seed(self):
        """Admin-only: run seed.py's idempotent seed with uploaded photos (used when the DB isn't reachable directly)."""
        f = self.read_form(MAX_UPLOAD_REQUEST)
        if f is None or not self._admin_key_ok(f.get("key")):
            return self._emit(404, b"Not found", "text/plain")
        import seed
        files = {fn: data for name, fn, data in f.files if name == "file"}
        log = []
        seed.run(lambda rel: files.get(rel), log=log.append)
        print("admin: seed run (" + str(len(files)) + " files)", flush=True)
        return self._emit(200, ("\n".join(log) + "\n").encode(), "text/plain; charset=utf-8", {"Cache-Control": "no-store"})
