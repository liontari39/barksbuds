"""BarksBuds community features (Oct 2026): the /community hub, lost and found alerts, trusted local recommendations,
private care reminders, birthday / gotcha day celebrations, community email preferences and the daily job.

Routes:
  GET  /community                              hub: dogs at the runs now, lost and found, celebrating today, recommendations
  GET  /lost-found[?kind=lost|found]           live alerts (plus recently reunited)
  GET/POST /lost-found/new                     post an alert (sign-in; max one per member per 24 hours)
  GET  /lost-found/<id>                        shareable alert page (contact through BarksBuds messages only)
  GET  /lost-found/<id>/og.png                 1200x630 share image
  GET  /lost-found/<id>/photo.(jpg|webp)       the alert's own photo (re-encoded, EXIF stripped)
  POST /lost-found/<id>/reunited | /remove     the poster closes the alert
  GET/POST /admin/lost?key=KEY                 admin: every alert, remove
  GET  /recommendations[?area=&cat=]           trusted local businesses, by area and category
  POST /recommendations/new                    recommend (or "I use them too" if it's already listed)
  POST /recommendations/<id>/vote | /unvote | /report
  GET/POST /admin/recs?key=KEY                 admin: reports and listings (hide, unhide, delete, resolve)
  GET/POST /me/dogs/<id>/care                  PRIVATE care reminders (owner and co-owners only)
  GET  /celebrate/<slug>[?k=gotcha]            shareable birthday / gotcha day card
  GET  /celebrate/<slug>.png[?k=gotcha]        its 1200x630 share image
  POST /me/community-emails                    email preferences + check-in privacy
  GET/POST /emails/community?u=&k=&t=          one-click unsubscribe (k = follow | alert | celebrate | care)
  POST /admin/jobs/daily                       daily job (X-Admin-Key header or key field): care reminders, celebration emails
Emails go through mailer.send_async with tags starting "community-" (gated by COMMUNITY_EMAIL_ALLOWLIST).
"""
import html, io, json, os, re, threading, time
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

import accounts as A
import community as C
import mailer
import webapp as W
from webapp import clean

e = html.escape
AUTO_JOBS = os.environ.get("COMMUNITY_AUTO_JOBS", "1") == "1"
JOB_HOUR = 8  # ET: the opportunistic tick runs the daily job after this hour
_tick = {"at": 0, "lock": threading.Lock()}
PHONE_RE = re.compile(r"^\+?1?[\s.-]?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})$")

W.FLASH.update({
    "alert_posted": "Your alert is live. We're letting members nearby know.", "alert_reunited": "So happy for you! The alert is marked reunited.",
    "alert_removed": "Alert removed.", "rec_added": "Thanks! Your recommendation is up.", "rec_voted": "Thanks! We counted you in.",
    "rec_unvoted": "Removed your recommendation.", "rec_reported": "Thanks. The BarksBuds team will take a look.",
    "care_saved": "Saved. We'll email you 30 and 7 days before it's due.", "care_deleted": "Reminder removed.",
    "community_emails": "Email settings saved.",
})


# ---------------------------------------------------------------- helpers
def run_path(r):
    import runpageweb
    return runpageweb.run_path(r)


def ago(ts):
    s = max(0, C.now() - ts)
    if s < 3600:
        return f"{max(1, s // 60)} min ago"
    if s < 86400:
        return f"{s // 3600} hr ago"
    return f"{s // 86400} day{'s' if s >= 172800 else ''} ago"


def when_et(ts):
    return datetime.fromtimestamp(ts, C.ET).strftime("%a, %b %-d at %-I:%M %p") if ts else ""


def nice_date(iso):
    try:
        return date.fromisoformat(iso).strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return iso or ""


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def alert_path(a):
    return f"/lost-found/{a['id']}"


def alert_name(a):
    return a["dog_name"] or "a dog"


def alert_headline(a):
    return f"{'Lost' if a['kind'] == 'lost' else 'Found'}: {alert_name(a)}"


def alert_where(a):
    r = W.run_index().get(a["run_id"]) if a["run_id"] else None
    place = f"near {r['name']}" if r else ""
    town = ", ".join(x for x in (a["town"], W.area_label(a["area"]) if a["area"] else "") if x)
    return " · ".join(x for x in (place, town) if x) or "Location not given"


def alert_photo_id(a):
    """(src for a small image, src for a big image) or (None, None)."""
    if a["has_photo"]:
        return f"/lost-found/{a['id']}/photo.webp", f"/lost-found/{a['id']}/photo.jpg"
    if a["dog_id"]:
        t = C.dog_tiles([a["dog_id"]])
        if t and t[0]["photo"]:
            return f"/p/{t[0]['photo']}.webp", f"/p/{t[0]['photo']}.jpg"
    return None, None


def alert_mini(a):
    small, _ = alert_photo_id(a)
    img = f'<img src="{small}" alt="" loading="lazy" width="56" height="56">' if small else '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></span>'
    return (f'<a class="lfmin k-{a["kind"]}" href="{alert_path(a)}">{img}<span><b><span class="lfk">{"LOST" if a["kind"] == "lost" else "FOUND"}</span> {e(alert_name(a))}</b>'
            f'<small>{e(alert_where(a))} · {e(ago(a["created_at"]))}</small></span></a>')


def alert_card(a):
    small, _ = alert_photo_id(a)
    img = f'<img src="{small}" alt="" loading="lazy">' if small else '<div class="noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></div>'
    st = {"reunited": '<span class="badge gold">Reunited</span>', "expired": '<span class="badge">Expired</span>'}.get(a["state"], "")
    return (f'<a class="dcard lfcard k-{a["kind"]}" href="{alert_path(a)}"><div class="ph">{img}<span class="lfk">{"LOST" if a["kind"] == "lost" else "FOUND"}</span></div>'
            f'<div class="bd"><h3>{e(alert_name(a))} {st}</h3><p class="meta">{e(alert_where(a))}</p>'
            f'<p class="where">Last seen {e(when_et(a["seen_at"]))}</p></div></a>')


def celeb_path(d):
    return f"/celebrate/{d['slug']}" + ("?k=gotcha" if d.get("kind") == "gotcha" else "")


def celeb_label(x):
    if x["kind"] == "gotcha":
        return f"{ordinal(x['years'])} gotcha day" if x["years"] >= 1 else "Gotcha day"
    return f"{ordinal(x['years'])} birthday" if x["years"] >= 1 else "Birthday"


def celebrating_html(areas=None, title="Celebrating today", compact=False):
    xs = C.celebrating(areas=areas)
    if not xs:
        return ""
    tiles = "".join(f'<li><a href="{e(celeb_path(x))}">{A.tile_img(x, 72)}<span>{e(x["name"])}</span><small>{e(celeb_label(x))}</small></a></li>' for x in xs)
    return (f'<div class="celeb{" compact" if compact else ""}"><h2><svg class="ico" aria-hidden="true"><use href="#i-cake"/></svg>{e(title)}</h2>'
            f'<ul class="mdogs">{tiles}</ul></div>')


def lost_banner_html():
    try:
        return _lost_banner_html()
    except Exception as ex:  # never break the homepage
        print(f"community: banner skipped ({type(ex).__name__})", flush=True)
        return ""


def _lost_banner_html():
    xs = C.live_alerts(3)
    if not xs:
        return ""
    a = xs[0]
    more = f' <a class="lfmore" href="/lost-found">+{len(xs) - 1} more</a>' if len(xs) > 1 else ""
    return (f'<div class="lfbanner k-{a["kind"]}" role="region" aria-label="Lost and found alert"><div class="wrap">'
            f'<svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg><p><b>{"LOST DOG" if a["kind"] == "lost" else "FOUND DOG"}:</b> '
            f'{e(alert_name(a))}, {e(alert_where(a))} · {e(ago(a["created_at"]))}</p>'
            f'<a class="btn btn-sm" href="{alert_path(a)}">See alert</a>{more}</div></div>')


def community_home_html():
    """Homepage block under the pixel pals: celebrations (when any) and three small entry points."""
    try:
        return _community_home_html()
    except Exception as ex:  # never break the homepage
        print(f"community: homepage block skipped ({type(ex).__name__})", flush=True)
        return ""


def _community_home_html():
    cel = celebrating_html(compact=True)
    nh = sum(C.here_counts().values())
    nl = len(C.live_alerts(50))
    here = f"{nh} dog{'s' if nh != 1 else ''} checked in right now" if nh else "Check in when you get to the run"
    lost = f"{nl} active alert{'s' if nl != 1 else ''}" if nl else "Alerts for dogs nearby"
    return f"""<section class="section commhome" id="community"><div class="wrap">{cel}
<div class="commlinks">
<a class="commlink" href="/runs"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg><span><b>At the run now</b><small>{here}</small></span></a>
<a class="commlink" href="/lost-found"><svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg><span><b>Lost and found</b><small>{lost}</small></span></a>
<a class="commlink" href="/recommendations"><svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg><span><b>Local favorites</b><small>Vets, groomers and walkers members use</small></span></a>
</div></div></section>"""


def _wrap(font, text, width, n):
    lines, cur = [], ""
    for w in (text or "").split():
        t = (cur + " " + w).strip()
        if font.getlength(t) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    lines.append(cur)
    out = [l for l in lines if l][:n]
    return [l if font.getlength(l) <= width else l[:max(3, int(len(l) * width / font.getlength(l)) - 1)] for l in out]


def og_card(photo, title, sub, tag, accent=(200, 32, 30)):
    """1200x630 share image: the photo in a rounded frame on the brand cream, a tag pill, title and subtitle."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    Wd, Ht = 1200, 630
    im = Image.new("RGB", (Wd, Ht), (255, 248, 234))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, Ht - 22, Wd, Ht], fill=(251, 179, 33))
    box = (60, 60, 570, 570)
    pasted = False
    if photo:
        try:
            p = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
            mask = Image.new("L", p.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, p.size[0] - 1, p.size[1] - 1], radius=40, fill=255)
            im.paste(p, box[:2], mask)
            pasted = True
        except Exception:
            pasted = False
    if not pasted:
        dr.rounded_rectangle(box, radius=40, fill=(255, 231, 168))
    dr.rounded_rectangle(box, radius=40, outline=(20, 20, 20), width=6)
    try:
        ft, f1, f2 = ImageFont.load_default(40), ImageFont.load_default(68), ImageFont.load_default(34)
    except Exception:
        ft = f1 = f2 = ImageFont.load_default()
    x = 620
    tw = int(ft.getlength(tag))
    dr.rounded_rectangle([x, 110, x + tw + 48, 170], radius=30, fill=accent)
    dr.text((x + 24, 118), tag, font=ft, fill=(255, 255, 255))
    y = 210
    for ln in _wrap(f1, title, 540, 3):
        dr.text((x, y), ln, font=f1, fill=(20, 20, 20)); y += 80
    for ln in _wrap(f2, sub, 540, 3):
        dr.text((x, y + 10), ln, font=f2, fill=(98, 90, 80)); y += 44
    dr.text((x, 530), "barksbuds.app", font=f2, fill=(200, 32, 30))
    out = io.BytesIO(); im.save(out, "PNG", optimize=True)
    return out.getvalue()


def unsub_url(base, uid, kind):
    return f"{base}/emails/community?u={uid}&k={kind}&t={C.unsub_token(uid, kind)}"


def nice_contact(c):
    if not c:
        return ""
    if c.startswith("http"):
        host = re.sub(r"^www\.", "", c.split("://", 1)[1].split("/", 1)[0])
        return f'<a href="{e(c)}" target="_blank" rel="nofollow ugc noopener">{e(host)}</a>'
    digits = re.sub(r"\D", "", c)[-10:]
    return f'<a href="tel:+1{digits}">{e(c)}</a>'


def clean_contact(s):
    """Website (normalized) or a US phone number '(516) 555-0134'; '' blank; None invalid."""
    s = (s or "").strip()
    if not s:
        return ""
    m = PHONE_RE.match(s)
    if m:
        return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
    return A.clean_website(s)


def area_chips(base_qs, cur_area, key="area"):
    cur = lambda on: ' aria-current="page"' if on else ""
    out = [f'<li><a href="?{urlencode({k: v for k, v in base_qs.items() if v and k != key})}"{cur(not cur_area)}>All areas</a></li>']
    for a in A.AREA_NAMES:
        qs = dict(base_qs); qs[key] = a
        out.append(f'<li><a href="?{urlencode({k: v for k, v in qs.items() if v})}"{cur(cur_area == a)}>{e(W.area_label(a))}</a></li>')
    return "".join(out)


# ---------------------------------------------------------------- daily job
def send_care_reminders(base, today=None):
    sent = 0
    for item, lead in C.care_due(today):
        d = A.dog_by_id(item["dog_id"])
        if not d:
            continue
        label = C.care_label(item)
        due = date.fromisoformat(item["due"])
        when = "today" if item["days"] == 0 else f"in {item['days']} day{'s' if item['days'] != 1 else ''}"
        for uid in C.owners_of(d["id"]):
            if not C.emails_on(uid, "care") or not C.claim_care(item["id"], item["due"], lead, uid):
                continue
            m = C.user_row(uid)
            if not m:
                continue
            un = unsub_url(base, uid, "care")
            subject, body, text = mailer.build_community(
                base, subject=f"{d['name']}'s {label.lower()} is due {when}", eyebrow="care reminder",
                heading=f"{d['name']}'s {label.lower()} is due {due.strftime('%b %-d')}", name=m["name"],
                paras=[f"A friendly reminder: {d['name']}'s {label.lower()} is due on {due.strftime('%A, %B %-d, %Y')} ({when}).",
                       "Once it's done, update the date so we can remind you next time."],
                button="Update the date", url=f"{base}/me/dogs/{d['id']}/care",
                why="You're getting this because you set a care reminder on BarksBuds. Only you and your dog's co-owners can see these dates.",
                unsub=un, unsub_label="Turn off care reminder emails")
            if mailer.send_async(m["email"], subject, body, text, un, "community-care"):
                sent += 1
    return sent


def send_celebrations(base, today=None):
    today = today or C.today_et()
    sent = 0
    for x in C.celebrating(today, limit=500):
        for uid in C.owners_of(x["id"]):
            if not C.emails_on(uid, "celebrate") or not C.claim_celebration(x["id"], x["kind"], today.isoformat(), uid):
                continue
            m = C.user_row(uid)
            if not m:
                continue
            un = unsub_url(base, uid, "celebrate")
            what = celeb_label(x).lower()
            img = f"{base}/p/{x['photo']}.webp" if x.get("photo") else ""
            subject, body, text = mailer.build_community(
                base, subject=f"Happy {what}, {x['name']}!", eyebrow="it's a big day", heading=f"Happy {what}, {x['name']}!",
                name=m["name"], image=img,
                paras=[f"Everyone at BarksBuds is wishing {x['name']} a wonderful {what}. Extra treats are officially approved.",
                       f"{x['name']} is in today's \"Celebrating today\" spotlight. Share the card with friends!"],
                button="See the celebration card", url=base + celeb_path(x),
                why="You're getting this because your dog's birthday or gotcha day is on BarksBuds.",
                unsub=un, unsub_label="Turn off celebration emails")
            if mailer.send_async(m["email"], subject, body, text, un, "community-celebrate"):
                sent += 1
    return sent


def run_daily(base, today=None):
    t0 = time.time()
    out = {"care_reminders": send_care_reminders(base, today), "celebration_emails": send_celebrations(base, today)}
    C.q("DELETE FROM checkins WHERE expires_at<:t", t=C.now() - 30 * 86400)  # old check-ins aren't needed
    out["seconds"] = round(time.time() - t0, 2)
    print(f"community: daily job {json.dumps(out)}", flush=True)
    return out


def tick(base):
    """Called on page loads (like meetweb.tick): once a day after JOB_HOUR ET, run the daily job in a thread."""
    if not AUTO_JOBS or time.time() - _tick["at"] < 3600:
        return
    with _tick["lock"]:
        if time.time() - _tick["at"] < 3600:
            return
        _tick["at"] = time.time()
    if datetime.now(C.ET).hour < JOB_HOUR:
        return

    def go():
        try:
            if C.claim_job("daily", C.today_et().isoformat()):
                run_daily(base)
        except Exception as ex:
            print(f"community: daily job failed: {type(ex).__name__}", flush=True)
    threading.Thread(target=go, daemon=True).start()


# ---------------------------------------------------------------- routes
class CommunityRoutes:
    def community_get(self, path, q):
        routes = [(r"/community/?", self.community_hub), (r"/lost-found/?", self.lost_list), (r"/lost-found/new", self.lost_form),
                  (r"/lost-found/(\d+)", self.lost_page), (r"/lost-found/(\d+)/og\.png", self.lost_og),
                  (r"/lost-found/(\d+)/photo\.(jpg|webp)", self.lost_photo), (r"/admin/lost", self.admin_lost),
                  (r"/recommendations/?", self.recs_page), (r"/admin/recs", self.admin_recs),
                  (r"/me/dogs/(\d+)/care", self.care_page), (r"/celebrate/([a-z0-9-]+)\.png", self.celebrate_og),
                  (r"/celebrate/([a-z0-9-]+)", self.celebrate_page), (r"/emails/community", self.community_unsub_page)]
        return self._cdispatch(routes, path, q)

    def community_post(self, path, q):
        routes = [(r"/lost-found/new", self.post_lost), (r"/lost-found/(\d+)/(reunited|remove)", self.post_lost_close),
                  (r"/admin/lost", self.post_admin_lost), (r"/recommendations/new", self.post_rec),
                  (r"/recommendations/(\d+)/(vote|unvote|report)", self.post_rec_action), (r"/admin/recs", self.post_admin_recs),
                  (r"/me/dogs/(\d+)/care", self.post_care), (r"/me/community-emails", self.post_community_prefs),
                  (r"/emails/community", self.post_community_unsub), (r"/admin/jobs/daily", self.post_daily_job)]
        return self._cdispatch(routes, path, q)

    def _cdispatch(self, routes, path, q):
        for pat, fn in routes:
            m = re.fullmatch(pat, path)
            if m:
                self._app_reset()
                fn(*[int(g) if g.isdigit() else g for g in m.groups()], q)
                return True
        return False

    # ------------------------------------------------------------ hub
    def community_hub(self, q):
        u = self.user()
        areas = [u["area"]] if u and u.get("area") else None
        runs = W.run_index()
        counts = sorted(C.here_counts().items(), key=lambda x: -x[1])[:6]
        busy = "".join(f'<li><a href="{e(run_path(runs[rid]))}"><b>{e(runs[rid]["name"])}</b><span class="hereb">{n} dog{"s" if n != 1 else ""} here now</span></a></li>'
                       for rid, n in counts if rid in runs)
        busy_html = (f'<ul class="busy">{busy}</ul>' if busy else '<p class="muted" style="margin:0">Nobody is checked in right now. '
                     'Open a run\'s page and tap <b>We\'re here</b> when you arrive.</p>')
        mine = ""
        if u:
            fr = [runs[r] for r in C.followed_runs(u["id"]) if r in runs]
            if fr:
                mine = ('<div class="panel"><h2>Runs you follow</h2><ul class="busy">' + "".join(
                    f'<li><a href="{e(run_path(r))}"><b>{e(r["name"])}</b><span class="small muted">{e(r.get("town_or_neighborhood") or "")}</span></a></li>' for r in fr)
                    + '</ul></div>')
        lost = C.live_alerts(4)
        lost_html = (f'<div class="lfmini">{"".join(alert_mini(a) for a in lost)}</div>' if lost else
                     '<p class="muted" style="margin:0 0 12px">No active alerts. Fingers crossed it stays that way.</p>')
        recs = C.browse_recs(areas)[:4]
        recs_html = ('<ul class="busy">' + "".join(
            f'<li><a href="/recommendations?{urlencode({"area": r["area"], "cat": r["category"]})}#r{r["id"]}"><b>{e(r["name"])}</b>'
            f'<span class="small muted">{e(C.REC_ONE.get(r["category"], ""))} · {e(r["town"])} · {r["votes"]} member{"s" if r["votes"] != 1 else ""}</span></a></li>' for r in recs) + "</ul>"
            if recs else '<p class="muted" style="margin:0 0 12px">No recommendations here yet. Who do you trust with your dog?</p>')
        cel = celebrating_html(areas)
        where = f" in {e(W.area_label(areas[0]))}" if areas else ""
        rq = "?area=" + quote(areas[0]) if areas else ""
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">community</span><h1>Your local dog community</h1>
<p class="lead">Who's at the run, lost and found alerts, birthdays and the vets, groomers and walkers members trust.</p></div></section>
<section class="section"><div class="wrap">{cel}
<div class="dgrid2"><div>
<div class="panel"><h2>At the runs now</h2>{busy_html}<p class="small" style="margin:12px 0 0"><a href="/runs">Find a run</a></p></div>
<div class="panel"><h2>Lost and found</h2>{lost_html}<div class="racts"><a class="btn btn-sm" href="/lost-found/new">Post an alert</a><a class="btn btn-ghost btn-sm" href="/lost-found">All alerts</a></div></div>
</div><div>
<div class="panel"><h2>Local favorites{where}</h2>{recs_html}<div class="racts"><a class="btn btn-sm" href="/recommendations{rq}">Browse recommendations</a></div></div>
{mine}</div></div></div></section>"""
        self.page("Community", body, index=True, active="community", canonical="/community",
                  desc="BarksBuds community: dogs at the run now, lost and found alerts, birthdays and trusted local vets, groomers and walkers.")

    # ------------------------------------------------------------ lost and found
    def lost_list(self, q):
        kind = q.get("kind", [""])[0]
        xs = [a for a in C.recent_alerts() if not kind or a["kind"] == kind]
        live = [a for a in xs if a["live"]]
        done = [a for a in xs if a["state"] == "reunited"]
        cur = lambda on: ' aria-current="page"' if on else ""
        chips = (f'<li><a href="/lost-found"{cur(not kind)}>All</a></li><li><a href="/lost-found?kind=lost"{cur(kind == "lost")}>Lost</a></li>'
                 f'<li><a href="/lost-found?kind=found"{cur(kind == "found")}>Found</a></li>')
        grid = (f'<div class="dgrid">{"".join(alert_card(a) for a in live)}</div>' if live else
                '<div class="empty"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg><h2>No active alerts</h2>'
                '<p class="muted">Good news: every dog we know about is home. If yours is missing, post an alert right away.</p></div>')
        reunited = (f'<h2 style="margin-top:36px">Recently reunited</h2><div class="dgrid">{"".join(alert_card(a) for a in done)}</div>' if done else "")
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">lost and found</span><h1>Lost and found dogs</h1>
<p class="lead">Alerts from members near you. Contact goes through BarksBuds messages, so nobody's email or phone is shown.</p>
<div class="racts"><a class="btn" href="/lost-found/new"><svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg>Post a lost or found alert</a></div></div></section>
<section class="section"><div class="wrap"><nav aria-label="Filter alerts"><ul class="filters">{chips}</ul></nav>{grid}{reunited}
<p class="small muted" style="margin-top:28px">Alerts end on their own after 14 days. Also call your local animal control and nearby vets.</p></div></section>"""
        self.page("Lost and found dogs", body, index=True, active="community", canonical="/lost-found", flash=self.flash_from(q),
                  desc="Lost and found dog alerts from BarksBuds members in NYC, Long Island and Westchester.")

    def lost_form(self, q, vals=None, errs=None, code=200):
        u = self.user()
        if not u:
            return self.need_login()
        v = vals or {"kind": q.get("kind", ["lost"])[0], "run": q.get("run", [""])[0], "area": u.get("area") or "", "town": u.get("town") or "",
                     "seen": datetime.now(C.ET).strftime("%Y-%m-%dT%H:%M")}
        errs = errs or {}
        dogs = A.dogs_for_user(u["id"])
        home = v.get("area") or u.get("area")
        runs = sorted(W.RUNS(), key=lambda r: (r.get("county") != home, r.get("county") or "", r["name"]))
        ropts = '<option value="">Not at a dog run / not sure</option>' + "".join(
            f'<option value="{e(r["id"])}"{" selected" if r["id"] == v.get("run") else ""}>{e(r["name"])} ({e(r.get("town_or_neighborhood") or W.area_label(r.get("county") or ""))})</option>' for r in runs)
        dopts = '<option value="">Not one of my dogs</option>' + "".join(
            f'<option value="{d["id"]}"{" selected" if str(d["id"]) == str(v.get("dog", "")) else ""}>{e(d["name"])}</option>' for d in dogs)
        err = lambda k: f'<span class="err">{e(errs.get(k, ""))}</span>'
        chk = lambda k: " checked" if v.get("kind", "lost") == k else ""
        top = ('<p class="formerr" role="alert">' + e(errs.get("_", "Please fix the highlighted fields.")) + '</p>') if errs else ""
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">lost and found</span><h1>Post an alert</h1>
<p class="lead">We'll show it on the homepage and nearby run pages, and email members who follow runs nearby or live in the area.</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel" method="post" action="/lost-found/new" enctype="multipart/form-data" novalidate>{self.csrf_field()}
{top}
<fieldset class="checks-grid" style="margin-bottom:16px"><legend>What happened?</legend>
<label class="tick"><input type="radio" name="kind" value="lost"{chk("lost")}><span>My dog is lost</span></label>
<label class="tick"><input type="radio" name="kind" value="found"{chk("found")}><span>I found a dog</span></label></fieldset>
<div class="row2"><div class="field"><label for="dog">Which dog? <span class="opt">(for lost dogs)</span></label><select id="dog" name="dog">{dopts}</select>
<span class="help">We'll use their profile photo.</span></div>
<div class="field"><label for="dog_name">Dog's name <span class="opt">(if known)</span></label>
<input id="dog_name" name="dog_name" maxlength="40" value="{e(v.get("dog_name", ""))}">{err("dog_name")}</div></div>
<div class="field"><label for="photo">Photo <span class="opt">(optional if you picked your dog)</span></label><input id="photo" name="photos" type="file" accept="image/*">{err("photo")}</div>
<div class="field"><label for="run">Last seen near a dog run</label><select id="run" name="run">{ropts}</select></div>
<div class="row2"><div class="field"><label for="area">Area</label>{self.area_select(v.get("area", ""))}{err("area")}</div>
<div class="field"><label for="town">Town or neighborhood</label><input id="town" name="town" maxlength="60" list="towns" value="{e(v.get("town", ""))}">{self.town_datalist()}</div></div>
<div class="field"><label for="seen">Last seen</label><input id="seen" name="seen" type="datetime-local" value="{e(v.get("seen", ""))}">{err("seen")}</div>
<div class="field"><label for="description">Description</label><textarea id="description" name="description" rows="4" maxlength="1200" required
placeholder="Color, size, collar, which way they ran, whether they'll come to strangers...">{e(v.get("description", ""))}</textarea>{err("description")}
<span class="help">Don't include your phone or address. Members contact you through BarksBuds messages.</span></div>
<div class="formfoot"><button class="btn" type="submit">Post alert</button><a href="/lost-found">Cancel</a></div>
<p class="small muted" style="margin:12px 0 0">One alert per member per day. Alerts end after 14 days, or sooner when you mark the dog reunited.</p>
</form></div></section>"""
        self.page("Post a lost or found alert", body, code=code, active="community")

    def post_lost(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail(A.MAX_UPLOAD_BYTES + 200_000)
        if f is None:
            return
        v = {k: f.get(k).strip() for k in ("kind", "dog", "dog_name", "run", "area", "town", "seen", "description")}
        errs = {}
        kind = v["kind"] if v["kind"] in ("lost", "found") else "lost"
        dog = None
        if v["dog"].isdigit():
            dog = next((d for d in A.dogs_for_user(u["id"]) if d["id"] == int(v["dog"])), None)
        name = clean(v["dog_name"], 40) or (dog["name"] if dog else "")
        if kind == "lost" and not name:
            errs["dog_name"] = "Add your dog's name, or pick them from your dogs."
        desc = clean(v["description"], 1200, multiline=True)
        if len(desc) < 10:
            errs["description"] = "Add a short description so people can recognize the dog."
        run = W.run_index().get(v["run"]) if v["run"] else None
        area = v["area"] if v["area"] in A.AREA_NAMES else (run.get("county") if run else "")
        if not area:
            errs["area"] = "Pick the area."
        try:
            seen = int(datetime.strptime(v["seen"], "%Y-%m-%dT%H:%M").replace(tzinfo=C.ET).timestamp()) if v["seen"] else C.now()
        except ValueError:
            seen = None
        if seen is None or seen > C.now() + 3600 or seen < C.now() - 30 * 86400:
            errs["seen"] = "Pick when the dog was last seen (within the last 30 days)."
        photo = None
        up = [x for x in f.files if x[0] == "photos" and x[2]]
        if up:
            try:
                photo = A.process_image(up[0][2])
            except A.BadImage as ex:
                errs["photo"] = str(ex)
        v["kind"] = kind
        if errs:
            return self.lost_form(q, v, errs, 422)
        if C.alerts_posted_since(u["id"], C.now() - 86400) >= 1 or not A.LIMITER.allow(f"alert-ip:{self._client_ip()}", 3, 86400):
            return self.lost_form(q, v, {"_": "You can post one alert per day. If something changed, close your current alert or message the BarksBuds team."}, 429)
        aid = C.add_alert(u["id"], kind, dog["id"] if dog else None, name, desc, run["id"] if run else "", area,
                          clean(v["town"], 60) or (run.get("town_or_neighborhood") if run else ""), run.get("lat") if run else None,
                          run.get("lng") if run else None, seen, photo)
        print(f"lostfound: alert {aid} ({kind}) posted", flush=True)
        a = C.alert(aid)
        threading.Thread(target=notify_alert, args=(a, self._base()), daemon=True).start()
        return self.redirect(alert_path(a) + "?m=alert_posted")

    def lost_page(self, aid, q):
        a = C.alert(aid)
        if not a or a["status"] == "removed":
            return self.msg_page("Alert not found", '<p class="sub">It may have been removed.</p><p><a class="btn" href="/lost-found">Lost and found</a></p>', code=404, icon="i-alert")
        u = self.user()
        base = self._base()
        _, big = alert_photo_id(a)
        mine = bool(u and u["id"] == a["user_id"])
        poster = C.user_row(a["user_id"]) or {"name": "A member"}
        img = (f'<img class="lfphoto" src="{big}" alt="Photo of {e(alert_name(a))}">' if big else
               '<div class="lfphoto noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></div>')
        state = {"reunited": '<p class="notice ok"><b>Reunited!</b> This dog is home. Thank you to everyone who helped.</p>',
                 "expired": '<p class="notice">This alert has ended. Message the poster if you have news.</p>'}.get(a["state"], "")
        r = W.run_index().get(a["run_id"]) if a["run_id"] else None
        run_link = f'<p class="small"><a href="{e(run_path(r))}">{e(r["name"])} run page</a></p>' if r else ""
        contact = "" if mine else self.message_button(a["user_id"], f"Message {poster['name'] or 'the poster'}", cls="btn msgbtn")
        owner = ""
        if mine and a["live"]:
            owner = (f'<div class="racts"><form method="post" action="/lost-found/{a["id"]}/reunited">{self.csrf_field()}<button class="btn btn-gold btn-sm" type="submit">'
                     f'<svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg>Mark reunited</button></form>'
                     f'<form method="post" action="/lost-found/{a["id"]}/remove">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit">Remove alert</button></form></div>')
        share = base + alert_path(a)
        stext = quote(f"{alert_headline(a)} ({alert_where(a)}). Please share: {share}")
        h1 = alert_name(a) if a["dog_name"] else ("Have you seen this dog?" if a["kind"] == "lost" else "A dog was found")
        body = f"""<section class="section lfpage"><div class="wrap"><div class="lfgrid">
<div>{img}</div><div>
<span class="lfk big k-{a["kind"]}">{"LOST DOG" if a["kind"] == "lost" else "FOUND DOG"}</span>
<h1>{e(h1)}</h1>{state}
<dl class="kv"><dt>Last seen</dt><dd>{e(alert_where(a))}</dd><dt>When</dt><dd>{e(when_et(a["seen_at"]))}</dd>
<dt>Posted by</dt><dd>{e(poster["name"] or "A member")} · {e(ago(a["created_at"]))}</dd></dl>
<p class="bio">{e(a["description"])}</p>{run_link}
<div class="racts">{contact}<a class="btn btn-ghost btn-sm" href="sms:?&amp;body={stext}">Text this alert</a>
<a class="btn btn-ghost btn-sm" href="mailto:?subject={quote(alert_headline(a))}&amp;body={stext}">Email it</a></div>
<div class="field" style="margin-top:14px"><label for="sharelink">Share link</label><input id="sharelink" type="text" readonly onfocus="this.select()" value="{e(share)}"></div>
<p class="small muted">Contact happens through BarksBuds messages. Never send money to anyone claiming to have a dog.</p>{owner}
</div></div></div></section>"""
        desc = f"{alert_headline(a)}. Last seen {alert_where(a)}, {when_et(a['seen_at'])}. {a['description'][:140]}"
        self.page(alert_headline(a), body, index=a["live"], canonical=alert_path(a), desc=desc, active="community", flash=self.flash_from(q),
                  og={"title": alert_headline(a) + " · BarksBuds", "image": f"{base}/lost-found/{a['id']}/og.png?v={a['closed_at'] or 0}",
                      "w": 1200, "h": 630, "alt": alert_headline(a)})

    def lost_og(self, aid, q):
        a = C.alert(aid)
        if not a or a["status"] == "removed":
            return self._emit(404, b"Not found", "text/plain")
        photo = None
        if a["has_photo"]:
            photo = C.alert_photo(aid, "full")
        elif a["dog_id"]:
            t = C.dog_tiles([a["dog_id"]])
            photo = A.photo_blob(t[0]["photo"], "full") if t and t[0]["photo"] else None
        reunited = a["state"] == "reunited"
        tag = "REUNITED" if reunited else ("LOST DOG" if a["kind"] == "lost" else "FOUND DOG")
        title = a["dog_name"] if a["dog_name"] else ("Have you seen this dog?" if a["kind"] == "lost" else "Found a dog")
        png = og_card(photo, title, f"Last seen {alert_where(a)}", tag, (200, 32, 30) if a["kind"] == "lost" and not reunited else (196, 132, 0))
        self._emit(200, png, "image/png", headers={"Cache-Control": "public, max-age=3600"})

    def lost_photo(self, aid, ext, q):
        b = C.alert_photo(aid, "full" if ext == "jpg" else "thumb")
        if not b:
            return self._emit(404, b"Not found", "text/plain")
        self._emit(200, b, "image/jpeg" if ext == "jpg" else "image/webp", headers={"Cache-Control": "public, max-age=86400"})

    def post_lost_close(self, aid, what, q):
        u = self.user()
        if not u:
            return self.need_login()
        if self._form_or_fail() is None:
            return
        a = C.alert(aid)
        if not a or a["user_id"] != u["id"] or a["status"] == "removed":
            return self.msg_page("Alert not found", "", code=404, icon="i-alert")
        C.set_alert_status(aid, "reunited" if what == "reunited" else "removed")
        print(f"lostfound: alert {aid} {what}", flush=True)
        return self.redirect(alert_path(a) + "?m=alert_reunited" if what == "reunited" else "/lost-found?m=alert_removed")

    def _admin_doc(self, title, inner, flash=""):
        doc = (f'<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<title>{e(title)}</title><body style="font:15px system-ui;padding:20px;max-width:1200px"><h1>{e(title)}</h1>'
               f'{f"<p><b>{e(flash)}</b></p>" if flash else ""}{inner}</body>')
        self._emit(200, doc, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    def _admin_from_form(self):
        f = self.read_form()
        key = (f.get("key") if f else "") or self.headers.get("X-Admin-Key", "")
        if f is None or not self._admin_key_ok(key):
            self._emit(404, b"Not found", "text/plain")
            return None, None
        return f, key

    def admin_lost(self, q, flash=""):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        hid = f'<input type="hidden" name="key" value="{e(key)}">'
        rows = "".join(f'<tr><td><a href="{alert_path(a)}">{a["id"]}</a></td><td>{e(a["kind"])}</td><td>{e(alert_name(a))}</td><td>{e(alert_where(a))}</td>'
                       f'<td>{e(a["description"][:200])}</td><td>{e(a["state"])}</td><td>{e(when_et(a["created_at"]))}</td><td>'
                       + ("" if a["status"] == "removed" else f'<form method="post" action="/admin/lost">{hid}<input type="hidden" name="id" value="{a["id"]}"><button type="submit">Remove</button></form>')
                       + "</td></tr>" for a in C.all_alerts())
        inner = (f'<table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>#</th><th>Kind</th><th>Dog</th><th>Where</th><th>Description</th>'
                 f'<th>State</th><th>Posted</th><th></th></tr>{rows}</table>' if rows else "<p>No alerts yet.</p>")
        self._admin_doc("Lost and found alerts", inner, flash)

    def post_admin_lost(self, q):
        f, key = self._admin_from_form()
        if f is None:
            return
        if f.get("id").isdigit():
            C.set_alert_status(int(f.get("id")), "removed")
            print(f"lostfound: admin removed alert {f.get('id')}", flush=True)
        return self.admin_lost({"key": [key]}, "Removed.")

    # ------------------------------------------------------------ recommendations
    def recs_page(self, q, vals=None, errs=None, code=200):
        u = self.user()
        area = q.get("area", [""])[0]
        area = area if area in A.AREA_NAMES else ""
        cat = q.get("cat", [""])[0]
        cat = cat if cat in C.REC_ONE else ""
        recs = C.browse_recs([area] if area else None, cat or None)
        mine = C.my_votes(u["id"]) if u else set()
        cur = lambda on: ' aria-current="page"' if on else ""
        cchips = [f'<li><a href="?{urlencode({"area": area} if area else {})}"{cur(not cat)}>Everything</a></li>']
        cchips += [f'<li><a href="?{urlencode({k: v for k, v in (("area", area), ("cat", c)) if v})}"{cur(cat == c)}>{e(lbl)}</a></li>' for c, lbl in C.REC_CATS]
        reasons = "".join(f'<label class="tick"><input type="radio" name="reason" value="{e(r)}"{" checked" if i == 0 else ""}><span>{e(r)}</span></label>'
                          for i, r in enumerate(C.REC_REPORT_REASONS))
        cards = []
        for r in recs:
            nh = "".join(f'<blockquote>{e(n["note"])}<cite>{e(n["name"] or "A member")}</cite></blockquote>' for n in C.rec_notes(r["id"], 3))
            n = r["votes"]
            if u and r["id"] in mine:
                vb = (f'<form method="post" action="/recommendations/{r["id"]}/unvote">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit" aria-pressed="true">'
                      f'<svg class="ico" aria-hidden="true"><use href="#i-check"/></svg>You use them · Undo</button></form>')
            elif u:
                vb = (f'<form method="post" action="/recommendations/{r["id"]}/vote">{self.csrf_field()}<button class="btn btn-sm" type="submit">'
                      f'<svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg>I use them too</button></form>')
            else:
                vb = f'<a class="btn btn-sm" href="{e(self.signin_href("/recommendations"))}"><svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg>I use them too</a>'
            rep = (f'<details class="rep"><summary>Report</summary><form method="post" action="/recommendations/{r["id"]}/report">{self.csrf_field()}'
                   f'<fieldset class="checks-grid">{reasons}</fieldset><div class="field"><label for="d{r["id"]}">Details <span class="opt">(optional)</span></label>'
                   f'<textarea id="d{r["id"]}" name="details" rows="2" maxlength="500"></textarea></div><button class="btn btn-ghost btn-sm" type="submit">Send report</button></form></details>') if u else ""
            where = e(r["town"]) + (", " + e(W.area_label(r["area"])) if r["area"] else "") + (" · " + nice_contact(r["contact"]) if r["contact"] else "")
            cards.append(f"""<article class="panel rec" id="r{r["id"]}"><div class="rech"><div><span class="badge">{e(C.REC_ONE.get(r["category"], ""))}</span>
<h3>{e(r["name"])}</h3><p class="small muted" style="margin:0">{where}</p></div>
<p class="recn"><b>{n}</b><small>member{"s" if n != 1 else ""} use{"s" if n == 1 else ""} them</small></p></div>{nh}
<div class="racts">{vb}{rep}</div></article>""")
        what = C.REC_ONE.get(cat, "business").lower()
        empty = (f'<div class="empty"><svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg><h2>No recommendations {"in " + e(W.area_label(area)) if area else "yet"}</h2>'
                 f'<p class="muted">Know a great {e(what)}? Members only add places they actually use, so the list starts empty and grows honestly.</p></div>')
        v = vals or {"category": cat, "area": area or (u.get("area") if u else ""), "town": (u.get("town") if u else "") or ""}
        errs = errs or {}
        err = lambda k: f'<span class="err">{e(errs.get(k, ""))}</span>'
        copts = "".join(f'<option value="{c}"{" selected" if v.get("category") == c else ""}>{e(C.REC_ONE[c])}</option>' for c, _ in C.REC_CATS)
        top = ('<p class="formerr" role="alert">' + e(errs.get("_", "Please fix the highlighted fields.")) + '</p>') if errs else ""
        if u:
            form = f"""<form class="panel" id="add" method="post" action="/recommendations/new" novalidate>{self.csrf_field()}<h2>Recommend a local business</h2>{top}
<div class="row2"><div class="field"><label for="category">Type</label><select id="category" name="category">{copts}</select></div>
<div class="field"><label for="name">Business name</label><input id="name" name="name" maxlength="80" required value="{e(v.get("name", ""))}">{err("name")}</div></div>
<div class="row2"><div class="field"><label for="town">Town</label><input id="town" name="town" maxlength="60" required list="towns" value="{e(v.get("town", ""))}">{self.town_datalist()}{err("town")}</div>
<div class="field"><label for="area">Area</label>{self.area_select(v.get("area", ""))}{err("area")}</div></div>
<div class="field"><label for="contact">Website or phone</label><input id="contact" name="contact" maxlength="200" value="{e(v.get("contact", ""))}" placeholder="e.g. example.com or (516) 555-0134">{err("contact")}</div>
<div class="field"><label for="note">Why you like them <span class="opt">(optional)</span></label><textarea id="note" name="note" rows="2" maxlength="300">{e(v.get("note", ""))}</textarea></div>
<label class="switch small" style="margin-bottom:12px"><input type="checkbox" name="real" value="1" required><span>I'm a customer of this business (no ads, and not a business I own)</span></label>{err("real")}
<div class="formfoot"><button class="btn" type="submit">Add recommendation</button></div></form>"""
        else:
            form = (f'<div class="panel" id="add"><h2>Recommend a local business</h2><p>Sign in to share a vet, groomer or walker you trust.</p>'
                    f'<a class="btn btn-sm" href="{e(self.signin_href("/recommendations#add"))}">Sign in</a></div>')
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">trusted by members</span><h1>Local favorites</h1>
<p class="lead">Vets, groomers, walkers, sitters, trainers, daycares and pet stores that BarksBuds members actually use.</p>
<div class="racts"><a class="btn btn-sm" href="#add">Recommend one</a></div></div></section>
<section class="section"><div class="wrap"><nav aria-label="Filter by area"><ul class="filters">{area_chips({"cat": cat}, area)}</ul></nav>
<nav aria-label="Filter by type"><ul class="filters">{"".join(cchips)}</ul></nav>
<div class="recgrid">{"".join(cards) or empty}</div>{form}
<p class="small muted" style="margin-top:20px">Recommendations come from members, not businesses. BarksBuds isn't paid for listings. See something wrong? Use Report.</p></div></section>"""
        title = "Local favorites" + (f" in {W.area_label(area)}" if area else "")
        qs = urlencode({k: x for k, x in (("area", area), ("cat", cat)) if x})
        self.page(title, body, code=code, index=True, active="community", flash=self.flash_from(q), canonical="/recommendations" + ("?" + qs if qs else ""),
                  desc="Dog vets, groomers, walkers, sitters, trainers, daycares and pet stores recommended by BarksBuds members.")

    def post_rec(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        v = {k: f.get(k).strip() for k in ("category", "name", "town", "area", "contact", "note")}
        errs = {}
        cat = v["category"] if v["category"] in C.REC_ONE else ""
        name, town = clean(v["name"], 80), clean(v["town"], 60)
        if not cat:
            errs["_"] = "Pick a type."
        if len(name) < 2:
            errs["name"] = "Add the business name."
        if len(town) < 2:
            errs["town"] = "Add the town."
        if v["area"] not in A.AREA_NAMES:
            errs["area"] = "Pick the area."
        contact = clean_contact(v["contact"])
        if contact is None:
            errs["contact"] = "That doesn't look like a website or a US phone number."
        elif not contact and not (cat and C.find_rec(cat, name, town)):
            errs["contact"] = "Add a website or phone number so others can reach them."
        if f.get("real") != "1":
            errs["real"] = "Please confirm you're a customer."
        if errs:
            return self.recs_page({"area": [v["area"]], "cat": [cat]}, v, errs, 422)
        if not A.LIMITER.allow(f"rec:{u['id']}", 10, 86400):
            return self.recs_page({}, v, {"_": "That's a lot of recommendations for one day. Please try again tomorrow."}, 429)
        rid, created, voted = C.add_rec(u["id"], cat, name, town, v["area"], contact, clean(v["note"], 300, multiline=True))
        print(f"recs: {'new' if created else 'vote'} rec {rid}", flush=True)
        return self.redirect(f"/recommendations?{urlencode({'area': v['area'], 'cat': cat, 'm': 'rec_added' if created else 'rec_voted'})}#r{rid}")

    def post_rec_action(self, rid, what, q):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        r = C.rec(rid)
        if not r or r["hidden"]:
            return self.msg_page("Not found", "", code=404)
        back = f"/recommendations?{urlencode({'area': r['area'], 'cat': r['category']})}"
        if what == "vote":
            if A.LIMITER.allow(f"recvote:{u['id']}", 40, 86400):
                C.vote(rid, u["id"])
            return self.redirect(back + "&m=rec_voted#r" + str(rid))
        if what == "unvote":
            C.unvote(rid, u["id"])
            return self.redirect(back + "&m=rec_unvoted")
        reason = f.get("reason") if f.get("reason") in C.REC_REPORT_REASONS else "Something else"
        if A.LIMITER.allow(f"recreport:{u['id']}", 10, 86400):
            C.report_rec(rid, u["id"], reason, clean(f.get("details"), 500, multiline=True))
            print(f"recs: rec {rid} reported", flush=True)
        return self.redirect(back + "&m=rec_reported#r" + str(rid))

    def admin_recs(self, q, flash=""):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        hid = f'<input type="hidden" name="key" value="{e(key)}">'
        btn = lambda act, i, lbl: (f'<form method="post" action="/admin/recs" style="display:inline">{hid}<input type="hidden" name="action" value="{act}">'
                                   f'<input type="hidden" name="id" value="{i}"><button type="submit">{lbl}</button></form>')
        reps = "".join(f'<tr><td>{p["id"]}</td><td>{e(p["name"] or "(deleted)")} <small>{e(p["category"] or "")} · {e(p["town"] or "")}</small></td><td>{e(p["reason"])}</td>'
                       f'<td>{e(p["details"] or "")}</td><td>{e(p["status"])}</td><td>'
                       + (btn("hide", p["rec_id"], "Hide") + btn("delete", p["rec_id"], "Delete") if p["name"] else "") + btn("resolve", p["id"], "Resolve") + "</td></tr>"
                       for p in C.rec_reports())
        recs = "".join(f'<tr><td>{r["id"]}</td><td>{e(r["name"])}</td><td>{e(r["category"])}</td><td>{e(r["town"])}, {e(r["area"])}</td><td>{e(r["contact"])}</td>'
                       f'<td>{r["votes"]}</td><td>{"hidden" if r["hidden"] else "live"}</td><td>'
                       + (btn("unhide", r["id"], "Unhide") if r["hidden"] else btn("hide", r["id"], "Hide")) + btn("delete", r["id"], "Delete") + "</td></tr>"
                       for r in C.browse_recs(include_hidden=True, limit=500))
        t = lambda hdr, rows: (f'<table border="1" cellpadding="6" style="border-collapse:collapse"><tr>{"".join(f"<th>{h}</th>" for h in hdr)}</tr>{rows}</table>' if rows else "<p>None.</p>")
        self._admin_doc("Recommendations", f'<h2>Reports</h2>{t(["#", "Business", "Reason", "Details", "Status", ""], reps)}'
                        f'<h2>All listings</h2>{t(["#", "Name", "Type", "Where", "Contact", "Members", "State", ""], recs)}', flash)

    def post_admin_recs(self, q):
        f, key = self._admin_from_form()
        if f is None:
            return
        act, i = f.get("action"), f.get("id")
        if i.isdigit():
            i = int(i)
            if act == "hide":
                C.set_rec_hidden(i, True)
            elif act == "unhide":
                C.set_rec_hidden(i, False)
            elif act == "delete":
                C.delete_rec(i)
            elif act == "resolve":
                C.set_report_status(i, "resolved")
            print(f"recs: admin {act} {i}", flush=True)
        return self.admin_recs({"key": [key]}, "Done.")

    # ------------------------------------------------------------ care reminders (private)
    def care_page(self, dog_id, q, errs=None, code=200):
        d = self.own_dog(dog_id)
        if not d:
            return
        items = C.care_items(d["id"])
        today = C.today_et()
        kinds = {i["kind"] for i in items}
        rows = []
        for it in items:
            try:
                left = (date.fromisoformat(it["due"]) - today).days
            except ValueError:
                left = None
            if left is None:
                st = ""
            elif left < 0:
                st = f'<span class="badge red">Overdue by {-left} day{"s" if left != -1 else ""}</span>'
            elif left == 0:
                st = '<span class="badge red">Due today</span>'
            elif left <= 30:
                st = f'<span class="badge gold">Due in {left} day{"s" if left != 1 else ""}</span>'
            else:
                st = f'<span class="small muted">in {left} days</span>'
            rows.append(f"""<li class="careitem"><form method="post" action="/me/dogs/{d["id"]}/care" class="carerow">{self.csrf_field()}<input type="hidden" name="id" value="{it["id"]}">
<div><b>{e(C.care_label(it))}</b> {st}</div>
<div class="carectl"><label class="sr-only" for="due{it["id"]}">Due date</label><input id="due{it["id"]}" type="date" name="due" value="{e(it["due"])}" required>
<button class="btn btn-ghost btn-sm" name="action" value="update" type="submit">Update</button>
<button class="linkbtn small" name="action" value="delete" type="submit">Remove</button></div></form></li>""")
        opts = "".join(f'<option value="{k}">{e(lbl)}</option>' for k, lbl in C.CARE_KINDS if k == "vaccine" or k not in kinds)
        errs = errs or {}
        top = ('<p class="formerr" role="alert">' + e(next(iter(errs.values()))) + '</p>') if errs else ""
        listing = (f'<ul class="carelist">{"".join(rows)}</ul>' if rows else
                   '<p class="muted">No dates yet. Add the next rabies shot and license renewal below.</p>')
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">private</span><h1>{e(d["name"])}'s care reminders</h1>
<p class="lead">Rabies, town license and other vaccine due dates. We email you 30 days and 7 days before each one. Only you and co-owners can see this, never on {e(d["name"])}'s public page.</p></div></section>
<section class="section"><div class="wrap narrow">
<div class="panel"><h2><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg>Due dates</h2>{listing}</div>
<form class="panel" method="post" action="/me/dogs/{d["id"]}/care" novalidate>{self.csrf_field()}<input type="hidden" name="action" value="add"><h2>Add a reminder</h2>{top}
<div class="row2"><div class="field"><label for="kind">What</label><select id="kind" name="kind">{opts}</select></div>
<div class="field"><label for="due">Due date</label><input id="due" name="due" type="date" required></div></div>
<div class="field"><label for="label">Vaccine name <span class="opt">(for "Other vaccine", e.g. DHPP, Bordetella, Lyme)</span></label><input id="label" name="label" maxlength="40"></div>
<div class="formfoot"><button class="btn" type="submit">Add reminder</button><a href="/me/dogs/{d["id"]}/edit">Back to {e(d["name"])}'s profile</a></div></form>
<p class="small muted">Reminder emails can be turned off on <a href="/me#community-emails">your account page</a>. Co-owners see and get the same reminders.</p>
</div></section>"""
        self.page(f"{d['name']}'s care reminders", body, code=code, flash=self.flash_from(q))

    def post_care(self, dog_id, q):
        d = self.own_dog(dog_id)
        if not d:
            return
        f = self._form_or_fail()
        if f is None:
            return
        act = f.get("action")
        if act == "delete" and f.get("id").isdigit():
            C.delete_care(d["id"], int(f.get("id")))
            return self.redirect(f"/me/dogs/{d['id']}/care?m=care_deleted")
        due = f.get("due").strip()
        try:
            dd = date.fromisoformat(due) if due else None
        except ValueError:
            dd = None
        if not dd or not (date(2000, 1, 1) <= dd <= C.today_et() + timedelta(days=366 * 5)):
            return self.care_page(d["id"], q, {"due": "Pick a due date (within the next 5 years)."}, 422)
        if act == "update" and f.get("id").isdigit():
            C.update_care(d["id"], int(f.get("id")), dd.isoformat())
        elif act == "add":
            kind = f.get("kind") if f.get("kind") in dict(C.CARE_KINDS) else "vaccine"
            items = C.care_items(d["id"])
            label = clean(f.get("label"), 40)
            if len(items) >= C.MAX_CARE:
                return self.care_page(d["id"], q, {"_": f"You can track up to {C.MAX_CARE} dates per dog."}, 422)
            if kind == "vaccine" and not label:
                return self.care_page(d["id"], q, {"label": "Add the vaccine name."}, 422)
            ex = next((i for i in items if i["kind"] == kind and kind != "vaccine"), None)
            if ex:
                C.update_care(d["id"], ex["id"], dd.isoformat())
            else:
                C.add_care(d["id"], kind, label if kind == "vaccine" else "", dd.isoformat())
        print(f"care: dog {d['id']} reminder {act}", flush=True)
        return self.redirect(f"/me/dogs/{d['id']}/care?m=care_saved")

    # ------------------------------------------------------------ celebrations
    def _celebrant(self, slug, q):
        d = A.dog_by_slug(slug)
        if not d or d["hidden"]:
            return None, None
        want = "gotcha" if q.get("k", [""])[0] == "gotcha" else "birthday"
        dates = {"birthday": d.get("birthday") or "", "gotcha": d.get("gotcha_day") or ""}
        kind = want if C._md(dates[want]) else next((k for k in ("birthday", "gotcha") if C._md(dates[k])), None)
        if not kind:
            return d, None
        m, dd, y = C._md(dates[kind])
        today = C.today_et()
        is_today = C.is_today(dates[kind], today)
        if is_today:
            years = today.year - y
        else:
            nxt = date(today.year, m, dd if (m, dd) != (2, 29) else 28)
            if nxt < today:
                nxt = nxt.replace(year=today.year + 1)
            years = nxt.year - y
        x = dict(id=d["id"], slug=d["slug"], name=d["name"], kind=kind, today=is_today, years=years,
                 date=date(2000, m, dd).strftime("%B %-d"), photo=d.get("avatar_photo_id") or A.first_photos([d["id"]]).get(d["id"]))
        return d, x

    def celebrate_page(self, slug, q):
        d, x = self._celebrant(slug, q)
        if not x:
            back = f'<p><a class="btn" href="/dogs/{e(d["slug"])}">See {e(d["name"])}\'s page</a></p>' if d else ""
            return self.msg_page("Nothing to celebrate yet", '<p class="sub">This dog doesn\'t have a birthday or gotcha day on BarksBuds.</p>' + back, code=404, icon="i-cake")
        base = self._base()
        what = celeb_label(x)
        head = f"Happy {what.lower()}, {x['name']}!" if x["today"] else f"{x['name']}'s {what.lower()} is {x['date']}"
        img = (f'<img src="/p/{x["photo"]}.jpg" alt="{e(x["name"])}">' if x["photo"] else '<div class="noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></div>')
        share = base + celeb_path(x)
        lead = (f"Gotcha day is the day {x['name']} came home." if x["kind"] == "gotcha"
                else f"Wishing {x['name']} belly rubs, zoomies and an extra treat.")
        body = f"""<section class="section"><div class="wrap narrow"><div class="celebcard{" on" if x["today"] else ""}">
<div class="cc-ph">{img}</div><span class="eyebrow">{"celebrating today" if x["today"] else "mark the calendar"}</span>
<h1>{e(head)}</h1><p class="lead">{e(lead)}</p>
<div class="racts" style="justify-content:center"><a class="btn" href="/dogs/{e(x["slug"])}">Say hi to {e(x["name"])}</a>
<a class="btn btn-ghost" href="sms:?&amp;body={quote(head + " " + share)}">Text the card</a></div>
<div class="field" style="margin-top:16px;text-align:left"><label for="sharelink">Share link</label><input id="sharelink" type="text" readonly onfocus="this.select()" value="{e(share)}"></div>
</div></div></section>"""
        self.page(head, body, canonical=celeb_path(x), desc=f"{head} Celebrate with {x['name']} on BarksBuds.",
                  og={"title": head, "image": f"{base}/celebrate/{x['slug']}.png?k={x['kind']}&v={C.today_et().isoformat()}", "w": 1200, "h": 630, "alt": head})

    def celebrate_og(self, slug, q):
        d, x = self._celebrant(slug, q)
        if not x:
            return self._emit(404, b"Not found", "text/plain")
        photo = A.photo_blob(x["photo"], "full") if x["photo"] else None
        what = celeb_label(x)
        title = f"Happy {what.lower()}, {x['name']}!" if x["today"] else f"{x['name']}'s {what.lower()}"
        png = og_card(photo, title, "Celebrating with the BarksBuds pack" if x["today"] else x["date"],
                      "GOTCHA DAY" if x["kind"] == "gotcha" else "BIRTHDAY", (196, 132, 0))
        self._emit(200, png, "image/png", headers={"Cache-Control": "public, max-age=3600"})

    def care_panel(self, d):
        """Small panel on the dog edit page linking to the private care reminders."""
        items = C.care_items(d["id"])
        nxt = ""
        if items:
            it = items[0]
            nxt = f' Next up: <b>{e(C.care_label(it))}</b> on {e(nice_date(it["due"]))}.'
        return (f'<div class="panel" id="care"><h2><svg class="ico" aria-hidden="true"><use href="#i-shield"/></svg> Care reminders '
                f'<span class="badge"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg>Private</span></h2>'
                f'<p class="sub">Rabies, town license and other vaccine due dates. Only you and co-owners see these, and we email you '
                f'30 and 7 days before each one.{nxt}</p>'
                f'<a class="btn btn-ghost btn-sm" href="/me/dogs/{d["id"]}/care">{"Manage" if items else "Add"} care reminders</a></div>')

    # ------------------------------------------------------------ email preferences + unsubscribe
    def community_prefs_html(self, u):
        ticks = "".join(f'<label class="switch small"><input type="checkbox" name="{k}" value="1"{" checked" if C.emails_on(u["id"], k) else ""}>'
                        f'<span><b>{e(lbl)}</b>: {e(desc)}</span></label>' for k, (_, lbl, desc) in C.EMAIL_KINDS.items())
        hid = C.checkins_hidden(u["id"])
        return (f'<form id="community-emails" method="post" action="/me/community-emails" class="emailpref">{self.csrf_field()}'
                f'<p class="small" style="margin:0 0 8px"><b>Community emails</b></p><div class="prefgrid">{ticks}</div>'
                f'<p class="small" style="margin:12px 0 8px" id="privacy"><b>Check-in privacy</b></p>'
                f'<label class="switch small"><input type="checkbox" name="checkins_hidden" value="1"{" checked" if hid else ""}>'
                f'<span>When I check in at a run, count my dogs but don\'t show their names or photos</span></label>'
                f'<button class="btn btn-ghost btn-sm" type="submit" style="margin-top:10px">Save</button></form>')

    def post_community_prefs(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        for k in C.EMAIL_KINDS:
            C.set_emails(u["id"], k, f.get(k) == "1")
        C.set_checkins_hidden(u["id"], f.get("checkins_hidden") == "1")
        return self.redirect("/me?m=community_emails#community-emails")

    def community_unsub_page(self, q):
        uid, kind, tok = (q.get(k, [""])[0] for k in ("u", "k", "t"))
        if not C.check_unsub(uid, kind, tok):
            return self.msg_page("That link didn't work", '<p class="sub">It may be incomplete. You can change emails from your account page.</p>'
                                 '<p><a class="btn" href="/me#community-emails">Go to my account</a></p>', code=400, icon="i-mail")
        _, lbl, desc = C.EMAIL_KINDS[kind]
        on = C.emails_on(int(uid), kind)
        body = (f'<p class="sub">{e(lbl)} are {"on" if on else "off"}: {e(desc)}.</p>'
                f'<form method="post" action="/emails/community"><input type="hidden" name="u" value="{e(uid)}"><input type="hidden" name="k" value="{e(kind)}">'
                f'<input type="hidden" name="t" value="{e(tok)}"><input type="hidden" name="action" value="{"off" if on else "on"}">'
                f'<button class="btn" type="submit">{"Turn off " if on else "Turn back on "}{e(lbl.lower())}</button></form>')
        return self.msg_page(lbl, body, icon="i-mail")

    def post_community_unsub(self, q):
        """Token-authenticated (no session or CSRF). Handles RFC 8058 one-click POSTs too (u/k/t in the query string)."""
        f = self.read_form()
        if f is None:
            return self._emit(413, b"Too large", "text/plain")
        uid, kind, tok = (f.get(k) or q.get(k, [""])[0] for k in ("u", "k", "t"))
        if not C.check_unsub(uid, kind, tok):
            return self._emit(400, b"Invalid link", "text/plain")
        on = f.get("action") == "on"
        C.set_emails(int(uid), kind, on)
        print(f"community: {kind} emails changed via link", flush=True)
        if f.get("List-Unsubscribe") == "One-Click":
            return self._emit(200, b"Unsubscribed", "text/plain")
        lbl = C.EMAIL_KINDS[kind][1]
        return self.msg_page("Done", f'<p class="sub">{e(lbl)} are {"back on" if on else "off"}.</p><p><a class="btn" href="/me#community-emails">Email settings</a></p>', icon="i-mail")

    # ------------------------------------------------------------ daily job
    def post_daily_job(self, q):
        f = self.read_form()
        key = self.headers.get("X-Admin-Key", "") or (f.get("key") if f else "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        out = run_daily(self._base())
        self._emit(200, json.dumps(out).encode(), "application/json", headers={"Cache-Control": "no-store"})


def notify_alert(a, base):
    """Email followers of nearby runs and area residents about a new alert (capped, rate limited, opt-out aware)."""
    n = 0
    try:
        _, big = alert_photo_id(a)
        lost = a["kind"] == "lost"
        for uid in C.alert_recipients(a, W.RUNS()):
            m = C.user_row(uid)
            if not m or not C.claim_alert_mail(a["id"], uid):
                continue
            un = unsub_url(base, uid, "alert")
            subject, body, text = mailer.build_community(
                base, subject=f"{'Lost dog' if lost else 'Found dog'} near you: {alert_name(a)}", eyebrow="lost and found",
                heading=f"{'Have you seen' if lost else 'Do you know'} {alert_name(a)}?", name=m["name"], image=(base + big) if big else "",
                paras=[f"A BarksBuds member {'lost' if lost else 'found'} a dog {alert_where(a)}. Last seen {when_et(a['seen_at'])}."],
                quote=a["description"], button="See the alert and message them", url=base + alert_path(a),
                why="You're getting this because you follow a nearby dog run or live in this area.",
                unsub=un, unsub_label="Turn off lost and found emails")
            if mailer.send_async(m["email"], subject, body, text, un, "community-lost"):
                n += 1
    except Exception as ex:
        print(f"lostfound: notify failed: {type(ex).__name__}", flush=True)
    print(f"lostfound: alert {a['id']} emailed {n} member(s)", flush=True)
    return n
