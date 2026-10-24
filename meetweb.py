"""BarksBuds meetups: pages and routes (mixed into server.H next to webapp.AppRoutes).

Server-rendered with escaped output; every member POST checks the CSRF token. Emails go through mailer.send_async,
respect each member's meetup email preference, carry a one-click unsubscribe link and are never sent for sample meetups.
Reminders: an opportunistic, throttled check runs on incoming requests, and POST /admin/meetups/reminders (ADMIN_KEY)
can be called by a scheduler.
"""
import html, json, os, re, threading, time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import accounts as A
import mailer
import meetups as M
import webapp as W
from webapp import clean, area_label, where_text

e = html.escape
W.FLASH.update({
    "m_created": "Your meetup is live! Share the link so friends can RSVP.", "m_saved": "Meetup updated.",
    "m_cancelled": "Meetup cancelled. We let everyone who RSVP'd know.",
    "m_cancelled_sample": "Sample meetup cancelled (no emails are sent for samples).",
    "m_repeat": "Copied to next week. Check the details and save.", "going": "You're going! See you there.",
    "maybe": "You're marked as Maybe.",
    "waitlist": "This meetup is full, so you're on the waitlist. We'll email you if a spot opens up.",
    "rsvp_cancelled": "Your RSVP was cancelled.", "commented": "Comment posted.", "comment_deleted": "Comment deleted.",
    "emails_on": "Meetup emails are on.", "emails_off": "Meetup emails are off.",
})
AUTO_REMINDERS = os.environ.get("MEETUP_AUTO_REMINDERS", "1") != "0"
_tick = {"last": 0.0, "lock": threading.Lock()}
FIT_ICON = {"small": "i-dog", "big": "i-dog", "puppies": "i-heart", "seniors": "i-heart", "all": "i-paw"}


def meetup_path(m):
    return f"/meetups/{m['id']}-{m['slug']}" if m.get("slug") else f"/meetups/{m['id']}"


def path_id(m):
    return f"/meetups/{m['id']}"


def run_of(m):
    return W.run_index().get(m["run_id"]) if m.get("run_id") else None


def destination(m, r=None):
    """Same rule as runs.js: verified pins route best; otherwise the written address."""
    r = r if r is not None else run_of(m)
    if r:
        if r.get("lat") is not None and (r.get("pin_precision") in ("exact", "described") or
                                         str(r.get("coord_source") or "").startswith("Centroid of NYC Open Data")):
            return f"{r['lat']},{r['lng']}"
        if r.get("address"):
            return r["address"]
        return ", ".join(x for x in (r.get("park") or r["name"], r.get("town_or_neighborhood"), "NY") if x)
    return m["address"] or m["place_name"]


def directions_url(m, r=None):
    return "https://www.google.com/maps/dir/?api=1&destination=" + quote(destination(m, r))


def apple_maps_url(m, r=None):
    return "https://maps.apple.com/?" + urlencode({"daddr": destination(m, r), "q": m["place_name"]})


def where_line(m):
    loc = where_text(m["town"], m["area"])
    return m["place_name"] + (f", {loc}" if loc and loc.lower() not in m["place_name"].lower() else "")


def _utc(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def gcal_url(base, m):
    details = (m["description"][:600] + "\n\n" if m["description"] else "") + "RSVP on BarksBuds: " + base + meetup_path(m)
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": m["title"], "dates": f"{_utc(m['starts_at'])}/{_utc(m['ends_at'])}", "details": details,
        "location": ", ".join(x for x in (m["place_name"], m["address"]) if x), "ctz": "America/New_York"})


def ics_text(base, m):
    def esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")

    def fold(line):
        out, b = [], line.encode("utf-8")
        while len(b) > 74:
            cut = 74
            while cut > 0 and (b[cut] & 0xC0) == 0x80:
                cut -= 1
            out.append(b[:cut].decode())
            b = b" " + b[cut:]
        out.append(b.decode())
        return "\r\n".join(out)
    url = base + meetup_path(m)
    desc = (m["description"] + "\n\n" if m["description"] else "") + f"Hosted by {m.get('host_name') or 'a BarksBuds member'} on BarksBuds.\n{url}"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BarksBuds//Meetups//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:meetup-{m['id']}@barksbuds.app", f"DTSTAMP:{_utc(int(time.time()))}",
             f"DTSTART:{_utc(m['starts_at'])}", f"DTEND:{_utc(m['ends_at'])}",
             f"SEQUENCE:{max(0, (m['updated_at'] - m['created_at']) // 60)}",
             f"SUMMARY:{esc(m['title'])}", f"LOCATION:{esc(', '.join(x for x in (m['place_name'], m['address']) if x))}",
             f"DESCRIPTION:{esc(desc)}", f"URL:{url}",
             "STATUS:" + ("CANCELLED" if m["status"] == "cancelled" else "CONFIRMED")]
    if m["lat"] is not None and m["lng"] is not None:
        lines.append(f"GEO:{m['lat']:.6f};{m['lng']:.6f}")
    lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + esc(m["title"]), "TRIGGER:-PT1H", "END:VALARM",
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def mail_ctx(base, m):
    s = M.to_et(m["starts_at"])
    return {"title": m["title"], "when": M.when_text(m["starts_at"], m["duration_min"]),
            "when_short": M.when_text(m["starts_at"], short=True), "time_short": M._hour(s) + " ET",
            "where": where_line(m) + (f" ({m['address']})" if m["address"] else ""),
            "url": base + meetup_path(m), "ics": base + f"/meetups/{m['id']}.ics", "gcal": gcal_url(base, m),
            "directions": directions_url(m)}


def unsub_url(base, uid):
    return f"{base}/emails/meetups?u={uid}&t={M.unsub_token(uid)}"


def send_meetup_mail(base, uid, kind, m, force=False, subject_prefix="", **kw):
    """Email one member about a meetup. Skips members who turned meetup emails off (unless force)."""
    email, name, on = M.contact(uid)
    if not email or (not on and not force):
        return False
    subject, body, text = mailer.build_meetup(base, kind, mail_ctx(base, m), name=name, unsub=unsub_url(base, uid), **kw)
    return mailer.send_async(email, subject_prefix + subject, body, text, unsub_url(base, uid), "meetup-" + kind)


def counts_text(mid):
    a = M.attendees(mid)
    g = a["going"]
    nd = sum(x["ndogs"] for x in g)
    s = f"{nd} dog{'s' if nd != 1 else ''} going ({len(g)} member{'s' if len(g) != 1 else ''})"
    if a["maybe"]:
        s += f", {len(a['maybe'])} maybe"
    if a["waitlist"]:
        s += f", {len(a['waitlist'])} on the waitlist"
    return s


def notify_rsvp(base, m, uid, final, prev, dog_ids):
    if m["is_sample"] or final == prev:
        return
    send_meetup_mail(base, uid, "confirm", m, status=final, dogs=M.dog_names(dog_ids))
    if uid != m["host_user_id"]:
        who = M.contact(uid)[1] or "A member"
        send_meetup_mail(base, m["host_user_id"], "host", m, status=final, who=who, who_dogs=M.dog_names(dog_ids),
                         counts=counts_text(m["id"]))


def notify_promoted(base, m, uids):
    if m["is_sample"]:
        return
    for uid in uids:
        r = M.rsvp_of(m["id"], uid)
        send_meetup_mail(base, uid, "promoted", m, status="going", dogs=M.dog_names(r["dogs"] if r else []))


def notify_cancel(base, m, rows):
    if m["is_sample"]:
        return
    for uid, _st in rows:
        if uid != m["host_user_id"]:
            send_meetup_mail(base, uid, "cancel", m)


def send_reminders(base):
    """Send the day-before reminders that are due. Returns (meetups, emails queued)."""
    nm = ne = 0
    for mid in M.reminders_due():
        if not M.claim_reminder(mid):
            continue
        m = M.get(mid)
        nm += 1
        for uid, st in M.reminder_recipients(mid):
            r = M.rsvp_of(mid, uid)
            if send_meetup_mail(base, uid, "reminder", m, status=st, dogs=M.dog_names(r["dogs"] if r else [])):
                ne += 1
    if nm:
        print(f"meetups: reminders for {nm} meetup(s), {ne} email(s) queued", flush=True)
    return nm, ne


def tick(base):
    """Opportunistic reminder check on traffic, at most every 10 minutes, off the request thread."""
    if not AUTO_REMINDERS:
        return
    with _tick["lock"]:
        if time.time() - _tick["last"] < 600:
            return
        _tick["last"] = time.time()

    def run():
        try:
            send_reminders(base)
        except Exception as ex:  # never break a request
            print(f"meetups: reminder check failed: {type(ex).__name__}", flush=True)
    threading.Thread(target=run, name="meetup-reminders", daemon=True).start()


def json_attr(obj):
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def map_points(ms):
    return [{"id": m["id"], "t": m["title"], "u": meetup_path(m), "w": M.when_text(m["starts_at"], m["duration_min"]),
             "p": where_line(m), "lat": m["lat"], "lng": m["lng"]}
            for m in ms if m["lat"] is not None and m["lng"] is not None]


MAP_JS = """<script src="/vendor/leaflet/leaflet.js"></script><script>(function(){var el=document.getElementById('%s');if(!el||!window.L)return;
var pts=JSON.parse(el.getAttribute('data-pts')||'[]');var map=L.map(el,{scrollWheelZoom:false,zoomSnap:0.25});
map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,crossOrigin:true,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
map.on('focus click',function(){map.scrollWheelZoom.enable()});map.on('mouseout',function(){map.scrollWheelZoom.disable()});
var icon=L.divIcon({className:'mpin',html:'<svg viewBox="0 0 30 40" aria-hidden="true"><path d="M15 1C7.3 1 1 7.1 1 14.7 1 25 15 39 15 39s14-14 14-24.3C29 7.1 22.7 1 15 1z" fill="#C8201E" stroke="#141414" stroke-width="2"/><circle cx="15" cy="14.5" r="5.5" fill="#FBB321"/></svg>',iconSize:[30,40],iconAnchor:[15,40],popupAnchor:[0,-36]});var b=[];
pts.forEach(function(p){var mk=L.marker([p.lat,p.lng],{icon:icon,title:p.t}).addTo(map);b.push([p.lat,p.lng]);if(%s){
var d=document.createElement('div');d.className='mpop';var a=document.createElement('a');a.href=p.u;a.textContent=p.t;var w=document.createElement('div');w.textContent=p.w;
var pl=document.createElement('div');pl.className='pl';pl.textContent=p.p;d.appendChild(a);d.appendChild(w);d.appendChild(pl);mk.bindPopup(d)}});
if(b.length>1)map.fitBounds(b,{padding:[40,40],maxZoom:13});else if(b.length)map.setView(b[0],%s);else map.setView([40.8,-73.55],9);})();</script>"""


class MeetupRoutes:
    # ------------------------------------------------------------ routing
    def meetup_get(self, path, q):
        self._app_reset()
        if path in ("/meetups", "/meetups/"):
            self.meetups_page(q); return True
        if path == "/meetups/new":
            self.meetup_form_page(None, q=q); return True
        mt = re.fullmatch(r"/meetups/(\d+)\.ics", path)
        if mt:
            self.meetup_ics(int(mt.group(1))); return True
        mt = re.fullmatch(r"/meetups/(\d+)/(edit|cancel)", path)
        if mt:
            m = self.own_meetup(int(mt.group(1)))
            if m:
                if mt.group(2) == "edit":
                    self.meetup_form_page(m, q=q)
                else:
                    self.meetup_cancel_page(m)
            return True
        mt = re.fullmatch(r"/meetups/(\d+)(-[a-z0-9-]*)?/?", path)
        if mt:
            self.meetup_page(int(mt.group(1)), mt.group(2) or "", q); return True
        if path == "/api/meetups":
            self.meetups_api(); return True
        if path == "/emails/meetups":
            self.unsub_page(q); return True
        if path == "/admin/meetups":
            self.admin_meetups(q); return True
        return False

    def meetup_post(self, path, q):
        self._app_reset()
        routes = [(r"/meetups/new", self.post_meetup), (r"/meetups/(\d+)/edit", self.post_meetup),
                  (r"/meetups/(\d+)/cancel", self.post_meetup_cancel), (r"/meetups/(\d+)/repeat", self.post_meetup_repeat),
                  (r"/meetups/(\d+)/rsvp", self.post_rsvp), (r"/meetups/(\d+)/rsvp/cancel", self.post_rsvp_cancel),
                  (r"/meetups/(\d+)/comments", self.post_comment),
                  (r"/meetups/(\d+)/comments/(\d+)/delete", self.post_comment_delete),
                  (r"/meetups/(\d+)/comments/(\d+)/report", self.post_comment_report),
                  (r"/meetups/(\d+)/report", self.post_meetup_report),
                  (r"/me/emails", self.post_email_prefs), (r"/emails/meetups", self.post_unsub),
                  (r"/admin/meetups", self.post_admin_meetups), (r"/admin/meetups/reminders", self.post_admin_reminders),
                  (r"/admin/meetups/test-email", self.post_admin_test_email)]
        for pat, fn in routes:
            mt = re.fullmatch(pat, path)
            if mt:
                fn(*[int(x) for x in mt.groups()])
                return True
        return False

    def not_found_meetup(self):
        return self.msg_page("We couldn't find that meetup", '<p class="sub">It may have been removed.</p>'
                             '<p><a class="btn" href="/meetups">See upcoming meetups</a></p>', code=404, icon="i-cal")

    def visible_meetup(self, mid):
        m = M.get(mid)
        u = self.user()
        if not m or (m["hidden"] and not (u and u["id"] == m["host_user_id"])):
            self.not_found_meetup()
            return None
        return m

    def own_meetup(self, mid):
        u = self.user()
        if not u:
            self.need_login()
            return None
        m = M.get(mid)
        if not m or m["host_user_id"] != u["id"]:
            self.msg_page("Only the host can do that", '<p class="sub">This meetup belongs to another member.</p>'
                          '<p><a class="btn" href="/meetups">See upcoming meetups</a></p>', code=403, icon="i-lock")
            return None
        return m

    # ------------------------------------------------------------ dashboard hooks (called from webapp.dashboard)
    def email_prefs_html(self, u):
        on = M.emails_on(u["id"])
        return (f'<form id="emails" method="post" action="/me/emails" class="emailpref">{self.csrf_field()}'
                f'<input type="hidden" name="on" value="{0 if on else 1}"><p class="small" style="margin:0 0 8px"><b>Meetup emails:</b> '
                f'{"On" if on else "Off"}. RSVP confirmations, host notices, cancellations and day-before reminders.</p>'
                f'<button class="btn btn-ghost btn-sm" type="submit">{"Turn off meetup emails" if on else "Turn on meetup emails"}</button></form>')

    def meetups_dashboard(self, u):
        host, att = M.for_user(u["id"])
        li = []
        for m in host:
            li.append(self.meetup_row(m, "Hosting" + (" · cancelled" if m["status"] == "cancelled" else "")))
        for m in att:
            if m["host_user_id"] == u["id"]:
                continue
            tag = {"going": "Going", "maybe": "Maybe", "waitlist": "Waitlist"}.get(m["my_status"], "")
            li.append(self.meetup_row(m, tag + (" · cancelled" if m["status"] == "cancelled" else "")))
        inner = (f'<ul class="mrows">{"".join(li)}</ul>' if li else
                 '<p class="muted" style="margin:0 0 14px">No upcoming meetups yet. Join one or host your own at your favorite run.</p>')
        return (f'<div class="panel" style="margin-top:28px"><div class="mehead"><h2 style="margin:0">Your meetups</h2>'
                f'<div class="formfoot" style="margin:0"><a class="btn btn-ghost btn-sm" href="/meetups">Find meetups</a>'
                f'<a class="btn btn-sm" href="/meetups/new">Host a meetup</a></div></div><div style="margin-top:14px">{inner}</div></div>')

    def meetup_row(self, m, tag):
        s = M.to_et(m["starts_at"])
        return (f'<li><a href="{e(meetup_path(m))}"><span class="mdate"><b>{s.strftime("%b").upper()}</b>{s.day}</span>'
                f'<span class="mrt"><strong>{e(m["title"])}</strong><small>{e(M.when_text(m["starts_at"], short=True))} ET · {e(m["place_name"])}</small></span>'
                f'<span class="mtag">{e(tag)}</span></a></li>')

    # ------------------------------------------------------------ listing
    def meetup_card(self, m, going=None):
        s = M.to_et(m["starts_at"])
        going = M.going_dogs(m["id"]) if going is None else going
        tags = []
        if m["is_sample"]:
            tags.append('<span class="badge sample">Sample</span>')
        if m["fit"]:
            tags.append(f'<span class="badge">{e(M.FIT_LABEL[m["fit"]])}</span>')
        cap = ""
        if m["capacity"]:
            left = max(m["capacity"] - going, 0)
            cap = " · " + ("Full, waitlist open" if left == 0 else f"{left} spot" + ("s" if left != 1 else "") + " left")
        tagh = f'<span class="mtags">{"".join(tags)}</span>' if tags else ""
        return f"""<a class="mcard" href="{e(meetup_path(m))}"><span class="mdate big"><b>{s.strftime("%a").upper()}</b>{s.day}<small>{s.strftime("%b")}</small></span>
<span class="mbody">{tagh}<span class="mh">{e(m["title"])}</span>
<span class="mline"><svg class="ico" aria-hidden="true"><use href="#i-clock"/></svg>{e(M.when_text(m["starts_at"], m["duration_min"]))}</span>
<span class="mline"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>{e(where_line(m))}</span>
<span class="mline"><svg class="ico" aria-hidden="true"><use href="#i-dog"/></svg>{going} dog{"s" if going != 1 else ""} going{cap}</span></span></a>"""

    def north_shore_html(self, ms):
        feat = "".join(self.meetup_card(m) for m in ms[:2])
        return f"""<div class="nshore"><div class="nsl"><span class="eyebrow">where it all began</span><h2>Starting on the North Shore</h2>
<p>BarksBuds started with a group of friends and their dogs in Manhasset. Our first meetups are around Manhasset and the North Shore of Long Island. Come meet the founding pack, then host one at your own run.</p>
<div class="formfoot"><a class="btn btn-gold btn-sm" href="/meetups?ns=1">North Shore meetups</a><a class="btn btn-ghost btn-sm" href="/meetups/new">Host a meetup</a></div></div>
<div class="nsr">{feat or '<p class="nsempty">The first North Shore meetup is being planned. Check back soon!</p>'}</div></div>"""

    def meetups_page(self, q):
        g = lambda k: q.get(k, [""])[0]
        area, region, when, view, ns = g("area"), g("region"), g("when"), g("view"), g("ns") == "1"
        areas, label = None, "all areas"
        if area in A.AREA_NAMES:
            areas, label, region = [area], area_label(area), ""
        elif region in A.REGIONS:
            label, areas = A.REGIONS[region]
            area = ""
        else:
            area = region = ""
        start = end = None
        if when == "week":
            start, end = M.week_window()
        elif when == "weekend":
            start, end = M.weekend_window()
        else:
            when = ""
        view = "map" if view == "map" else ""
        ms = M.upcoming(areas, start, end, north_shore=ns)

        def link(**kw):
            p = {"region": region, "area": area, "when": when, "view": view, "ns": "1" if ns else ""}
            p.update(kw)
            qs = urlencode({k: v for k, v in p.items() if v})
            return "/meetups" + ("?" + qs if qs else "")
        cur = lambda on: ' aria-current="page"' if on else ""
        chips = [f'<li><a href="{e(link(region="", area="", ns=""))}"{cur(not areas and not ns)}>All areas</a></li>',
                 f'<li><a href="{e(link(region="", area="", ns="1"))}"{cur(ns)}>North Shore</a></li>']
        chips += [f'<li><a href="{e(link(region=k, area="", ns=""))}"{cur(region == k)}>{e(v[0])}</a></li>' for k, v in A.REGIONS.items()]
        chips.append('<li class="sep" aria-hidden="true"></li>')
        chips += [f'<li><a href="{e(link(area=a, region="", ns=""))}"{cur(area == a)}>{e(area_label(a))}</a></li>'
                  for a in A.AREA_NAMES if a != "Westchester"]
        dchips = "".join(f'<li><a href="{e(link(when=k))}"{cur(when == k)}>{t}</a></li>'
                         for k, t in (("", "Any date"), ("week", "This week"), ("weekend", "This weekend")))
        vchips = (f'<li><a href="{e(link(view=""))}"{cur(not view)}>List</a></li>'
                  f'<li><a href="{e(link(view="map"))}"{cur(view == "map")}>Map</a></li>')
        host_href = "/meetups/new" if self.user() else "/signin"
        scripts = ""
        if ms and view == "map":
            pts = map_points(ms)
            off = len(ms) - len(pts)
            content = (f'<div id="mmap" class="mmap" data-pts="{e(json_attr(pts))}" role="region" aria-label="Map of upcoming meetups"></div>'
                       + (f'<p class="small muted">{off} meetup{"s" if off != 1 else ""} at custom places aren\'t on the map. '
                          f'<a href="{e(link(view=""))}">See the list</a>.</p>' if off else ""))
            scripts = '<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">' + MAP_JS % ("mmap", "true", "12")
        elif ms:
            content = f'<div class="mgrid">{"".join(self.meetup_card(m) for m in ms)}</div>'
        else:
            content = (f'<div class="empty"><svg class="ico" aria-hidden="true"><use href="#i-cal"/></svg><h2>No meetups {"here " if areas or ns else ""}yet</h2>'
                       f'<p class="muted">Be the first! Pick a dog run, choose a time and invite the regulars.</p><a class="btn" href="{host_href}">Host a meetup</a></div>')
        nsm = M.upcoming(north_shore=True, limit=2)
        n = len(ms)
        when_lab = {"week": " this week", "weekend": " this weekend"}.get(when, "")
        body = f"""<section class="phead"><div class="wrap"><div class="mehead"><div><span class="eyebrow">meet the pack</span><h1>Dog meetups</h1>
<p class="lead">Park hangs, group romps and playdates at dog runs across NYC, Long Island and Westchester. RSVP with your dogs and see who's coming.</p></div>
<a class="btn" href="{host_href}"><svg class="ico" aria-hidden="true"><use href="#i-cal"/></svg>Host a meetup</a></div></div></section>
<section class="section"><div class="wrap">{self.north_shore_html(nsm)}
<nav aria-label="Filter by area"><ul class="filters">{''.join(chips)}</ul></nav>
<div class="mbar"><nav aria-label="Filter by date"><ul class="filters">{dchips}</ul></nav><nav aria-label="View"><ul class="filters">{vchips}</ul></nav></div>
<p class="small muted mcount">{n} upcoming meetup{"s" if n != 1 else ""} in {e("the North Shore" if ns else label)}{when_lab}. All times are Eastern (ET).</p>
{content}</div></section>"""
        canon = "/meetups" + (f"?region={region}" if region else f"?area={quote(area)}" if area else "")
        return self.page("Dog meetups" + (f" in {label}" if areas else ""), body, index=not (when or view or ns), active="meetups",
                         canonical=canon, scripts=scripts, flash=self.flash_from(q),
                         desc="Find and host dog meetups at dog runs across NYC, Long Island and Westchester. RSVP with your dogs on BarksBuds.",
                         og={"title": "Dog meetups on BarksBuds", "image": self._base() + "/img/og-image.jpg", "w": 1200, "h": 630})

    def meetups_api(self):
        """Upcoming meetups keyed by run id, for the dog run finder."""
        out = {}
        for m in M.upcoming(limit=500):
            if m["run_id"]:
                out.setdefault(m["run_id"], []).append({"id": m["id"], "title": m["title"], "url": meetup_path(m),
                                                        "when": M.when_text(m["starts_at"], short=True), "sample": bool(m["is_sample"])})
        return self._emit(200, json.dumps({"runs": out}).encode(), "application/json", {"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ create / edit
    def run_select(self, chosen):
        groups = {}
        for r in W.RUNS():
            groups.setdefault(r.get("county") or "Other", []).append(r)
        out = ['<option value="">Choose a dog run</option>']
        for county in [a for a in A.AREA_NAMES if a in groups] + [c for c in groups if c not in A.AREA_NAMES]:
            opts = "".join(f'<option value="{e(r["id"])}"{" selected" if r["id"] == chosen else ""}>{e(r["name"])}'
                           f'{" · " + e(r["town_or_neighborhood"]) if r.get("town_or_neighborhood") else ""}</option>'
                           for r in sorted(groups[county], key=lambda r: r["name"]))
            out.append(f'<optgroup label="{e(area_label(county))}">{opts}</optgroup>')
        return f'<select id="run_id" name="run_id">{"".join(out)}</select>'

    def meetup_form_page(self, m, vals=None, errs=None, code=200, q=None):
        u = self.user()
        if not u:
            return self.need_login()
        errs = errs or {}
        if vals is None:
            if m:
                s = M.to_et(m["starts_at"])
                custom = not m["run_id"]
                vals = dict(title=m["title"], date=s.strftime("%Y-%m-%d"), time=s.strftime("%H:%M"), duration=str(m["duration_min"]),
                            loc="custom" if custom else "run", run_id=m["run_id"], place_name=m["place_name"] if custom else "",
                            address=m["address"] if custom else "", area=m["area"] if custom else "", town=m["town"] if custom else "",
                            description=m["description"], fit=m["fit"], capacity=str(m["capacity"] or ""))
            else:
                rid = (q or {}).get("run", [""])[0]
                vals = dict(title="", date="", time="10:00", duration="60", loc="run", run_id=rid if rid in W.run_index() else "",
                            place_name="", address="", area=u.get("area") or "", town="", description="", fit="", capacity="")
        v = lambda k: e(vals.get(k) or "")
        err = lambda k: f'<span class="err" id="{k}-err">{e(errs.get(k, ""))}</span>'
        inv = lambda k: ' aria-invalid="true"' if k in errs else ""
        durs = "".join(f'<option value="{d}"{" selected" if str(d) == vals.get("duration") else ""}>{M.duration_text(d)}</option>' for d in M.DURATIONS)
        fits = ('<label class="tick"><input type="radio" name="fit" value=""' + (" checked" if not vals.get("fit") else "") + '><span>No preference</span></label>'
                + "".join(f'<label class="tick"><input type="radio" name="fit" value="{k}"{" checked" if vals.get("fit") == k else ""}><span>{e(t)}</span></label>'
                          for k, t in M.FITS))
        loc = "custom" if vals.get("loc") == "custom" else "run"
        today = M.to_et(A.now()).strftime("%Y-%m-%d")
        action = f"{path_id(m)}/edit" if m else "/meetups/new"
        top = '<div class="formerr" role="alert">Please fix the highlighted fields.</div>' if errs else ""
        title = "Edit meetup" if m else "Host a meetup"
        area_sel = self.area_select(vals.get("area"), "area").replace(" required", "")
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">{"edit" if m else "let's meet up"}</span><h1>{title}</h1>
<p class="lead">Pick a dog run (or any dog-friendly place), set a time and tell people what to expect. Times are Eastern (New York).</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel mform" method="post" action="{action}" novalidate>{self.csrf_field()}{top}
<div class="field"><label for="title">Title</label><input type="text" id="title" name="title" maxlength="{M.MAX_TITLE}" required value="{v("title")}" placeholder="Saturday morning romp"{inv("title")}>{err("title")}</div>
<div class="row3"><div class="field"><label for="date">Date</label><input type="date" id="date" name="date" min="{today}" required value="{v("date")}"{inv("date")}>{err("date")}</div>
<div class="field"><label for="time">Start time (ET)</label><input type="time" id="time" name="time" step="300" required value="{v("time")}"{inv("time")}>{err("time")}</div>
<div class="field"><label for="duration">How long</label><select id="duration" name="duration">{durs}</select></div></div>
<fieldset class="field locset"><legend class="lab">Where</legend>
<div class="checks-grid" style="margin-bottom:12px"><label class="tick"><input type="radio" name="loc" value="run"{" checked" if loc == "run" else ""}><span>A dog run on our map</span></label>
<label class="tick"><input type="radio" name="loc" value="custom"{" checked" if loc == "custom" else ""}><span>Somewhere else</span></label></div>
<div class="loc-run"><label class="sr-only" for="run_id">Dog run</label>{self.run_select(vals.get("run_id"))}{err("run_id")}
<span class="help">The meetup is pinned at the run on the map and gets one-tap directions. <a href="/runs" target="_blank" rel="noopener">Browse the dog run map</a></span></div>
<div class="loc-custom"><div class="row2"><div class="field"><label for="place_name">Place name</label><input type="text" id="place_name" name="place_name" maxlength="100" value="{v("place_name")}" placeholder="Park name, meeting spot"{inv("place_name")}>{err("place_name")}</div>
<div class="field"><label for="address">Address</label><input type="text" id="address" name="address" maxlength="200" value="{v("address")}" placeholder="Street address, town"{inv("address")}>{err("address")}</div></div>
<div class="row2"><div class="field"><label for="area">Area</label>{area_sel}{err("area")}</div>
<div class="field"><label for="town">Town or neighborhood <span class="opt">(optional)</span></label><input type="text" id="town" name="town" maxlength="60" value="{v("town")}"></div></div>
<span class="help">Custom places show the address and directions but aren't pinned on the map.</span></div></fieldset>
<div class="field"><label for="description">Description <span class="opt">(optional)</span></label><textarea id="description" name="description" maxlength="{M.MAX_DESC}" rows="5" placeholder="What to expect, where exactly to find you, anything to bring.">{v("description")}</textarea></div>
<fieldset class="field"><legend class="lab">Good fit for <span class="opt">(optional)</span></legend><div class="checks-grid">{fits}</div></fieldset>
<div class="field" style="max-width:280px"><label for="capacity">Capacity <span class="opt">(optional)</span></label><input type="number" id="capacity" name="capacity" min="2" max="{M.MAX_CAPACITY}" inputmode="numeric" value="{v("capacity")}" placeholder="No limit"{inv("capacity")}>
<span class="help">Max dogs going. Extra RSVPs join a waitlist.</span>{err("capacity")}</div>
<div class="formfoot"><button class="btn" type="submit">{"Save changes" if m else "Publish meetup"}</button>
<a class="small" href="{e(meetup_path(m)) if m else "/meetups"}">Cancel</a></div>
<p class="small muted" style="margin:14px 0 0">Meetups are public. Please pick dog-friendly places and follow each run's rules and permits.</p></form></div></section>"""
        js = ("<script>(function(){var f=document.querySelector('form.mform');if(!f)return;function sync(){var c=f.querySelector('input[name=loc]:checked');"
              "var v=c?c.value:'run';f.querySelector('.loc-run').hidden=v!=='run';f.querySelector('.loc-custom').hidden=v!=='custom'}"
              "f.querySelectorAll('input[name=loc]').forEach(function(r){r.addEventListener('change',sync)});sync()})();</script>")
        return self.page(title, body, code=code, active="meetups", scripts=js, flash=self.flash_from(q or {}))

    def parse_meetup(self, f, old=None):
        errs = {}
        vals = {k: f.get(k) for k in ("title", "date", "time", "duration", "loc", "run_id", "place_name", "address", "area",
                                      "town", "description", "fit", "capacity")}
        out = {"title": clean(f.get("title"), M.MAX_TITLE)}
        if len(out["title"]) < 3:
            errs["title"] = "Give your meetup a title (at least 3 characters)."
        dok = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.get("date") or ""))
        tok = bool(re.fullmatch(r"\d{2}:\d{2}", f.get("time") or ""))
        st = M.from_et(f.get("date"), f.get("time")) if dok and tok else None
        if st is None:
            errs["date" if not dok else "time"] = "Pick a date and start time."
        elif (not old or st != old["starts_at"]) and st < A.now() + 600:
            errs["date"] = "Pick a time in the future."
        elif st > A.now() + 366 * 86400:
            errs["date"] = "Meetups can be scheduled up to a year ahead."
        out["starts_at"] = st
        d = f.get("duration")
        out["duration_min"] = int(d) if d.isdigit() and int(d) in M.DURATIONS else 60
        out["lat"] = out["lng"] = None
        if f.get("loc") == "custom":
            out.update(run_id="", place_name=clean(f.get("place_name"), 100), address=clean(f.get("address"), 200),
                       area=f.get("area") if f.get("area") in A.AREA_NAMES else "", town=clean(f.get("town"), 60))
            if not out["place_name"]:
                errs["place_name"] = "Add a place name."
            if not out["address"]:
                errs["address"] = "Add an address so people can find you."
            if not out["area"]:
                errs["area"] = "Choose an area."
        else:
            r = W.run_index().get(f.get("run_id"))
            if not r:
                errs["run_id"] = "Choose a dog run, or pick \"Somewhere else\"."
                out.update(run_id="", place_name="", address="", area="", town="")
            else:
                out.update(run_id=r["id"], place_name=r["name"], address=r.get("address") or "", area=r.get("county") or "",
                           town=r.get("town_or_neighborhood") or "", lat=r.get("lat"), lng=r.get("lng"))
        out["description"] = clean(f.get("description"), M.MAX_DESC, multiline=True)
        out["fit"] = f.get("fit") if f.get("fit") in M.FIT_LABEL else ""
        c = (f.get("capacity") or "").strip()
        out["capacity"] = None
        if c:
            if not c.isdigit() or not (2 <= int(c) <= M.MAX_CAPACITY):
                errs["capacity"] = f"Use a number from 2 to {M.MAX_CAPACITY}, or leave it blank."
            else:
                out["capacity"] = int(c)
        return out, vals, errs

    def post_meetup(self, mid=None):
        u = self.user()
        if not u:
            return self.need_login()
        old = None
        if mid:
            old = self.own_meetup(mid)
            if not old:
                return
        f = self._form_or_fail()
        if f is None:
            return
        out, vals, errs = self.parse_meetup(f, old)
        if old and old["status"] == "cancelled":
            errs["title"] = "This meetup was cancelled. Use \"Repeat next week\" to schedule it again."
        if errs:
            return self.meetup_form_page(old, vals, errs, code=400)
        if not old and not A.LIMITER.allow(f"mcreate:{u['id']}", 10, 86400):
            return self.msg_page("Slow down a little", '<p class="sub">You\'ve created a lot of meetups today. Please try again tomorrow.</p>', code=429)
        new_id, promoted = M.save(u["id"], out, mid=mid)
        m = M.get(new_id)
        notify_promoted(self._base(), m, promoted)
        print(f"meetups: {'updated' if old else 'created'} meetup {new_id}", flush=True)
        return self.redirect(meetup_path(m) + ("?m=m_saved" if old else "?m=m_created"))

    def meetup_cancel_page(self, m):
        if m["status"] == "cancelled":
            return self.redirect(meetup_path(m))
        n = sum(len(v) for v in M.attendees(m["id"]).values())
        note = " Sample meetups don't send emails." if m["is_sample"] else ""
        body = (f'<p class="sub">This tells everyone who RSVP\'d ({n} member{"s" if n != 1 else ""}) that <b>{e(m["title"])}</b> on '
                f'{e(M.when_text(m["starts_at"], short=True))} ET is off.{note}</p>'
                f'<form method="post" action="{path_id(m)}/cancel">{self.csrf_field()}<div class="formfoot" style="justify-content:center">'
                f'<button class="btn" type="submit">Cancel meetup</button><a href="{e(meetup_path(m))}">Keep it</a></div></form>')
        return self.msg_page("Cancel this meetup?", body, icon="i-cal")

    def post_meetup_cancel(self, mid):
        m = self.own_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        if m["status"] != "cancelled":
            rows = M.cancel(mid)
            notify_cancel(self._base(), M.get(mid), rows)
            print(f"meetups: cancelled meetup {mid} ({len(rows)} rsvps)", flush=True)
        return self.redirect(meetup_path(m) + ("?m=m_cancelled_sample" if m["is_sample"] else "?m=m_cancelled"))

    def post_meetup_repeat(self, mid):
        m = self.own_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        if not A.LIMITER.allow(f"mcreate:{m['host_user_id']}", 10, 86400):
            return self.msg_page("Slow down a little", '<p class="sub">You\'ve created a lot of meetups today. Please try again tomorrow.</p>', code=429)
        nid = M.duplicate_next_week(m)
        return self.redirect(f"/meetups/{nid}/edit?m=m_repeat")

    # ------------------------------------------------------------ RSVP
    def post_rsvp(self, mid):
        u = self.user()
        if not u:
            return self.need_login()
        m = self.visible_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        path = meetup_path(m)
        if m["status"] != "active" or m["ends_at"] <= A.now():
            return self.redirect(path + "?e=closed#rsvp")
        if not A.LIMITER.allow(f"rsvp:{u['id']}", 30, 600):
            return self.redirect(path + "?e=slow#rsvp")
        mine = {d["id"] for d in A.dogs_for_user(u["id"]) if not d["hidden"]}
        dog_ids = []
        for x in f.getlist("dogs"):
            if x.isdigit() and int(x) in mine and int(x) not in dog_ids:
                dog_ids.append(int(x))
        if not dog_ids:
            return self.redirect(path + ("?e=nodogs" if mine else "?e=adddog") + "#rsvp")
        status = f.get("status") if f.get("status") in ("going", "maybe") else "going"
        try:
            final, prev, promoted = M.set_rsvp(m, u["id"], status, dog_ids)
        except M.Full as ex:
            return self.redirect(path + f"?e=full&left={int(ex.args[0])}#rsvp")
        notify_rsvp(self._base(), m, u["id"], final, prev, dog_ids)
        notify_promoted(self._base(), m, promoted)
        return self.redirect(path + f"?m={final}#rsvp")

    def post_rsvp_cancel(self, mid):
        u = self.user()
        if not u:
            return self.need_login()
        m = self.visible_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        prev, promoted = M.cancel_rsvp(m, u["id"])
        notify_promoted(self._base(), m, promoted)
        return self.redirect(meetup_path(m) + ("?m=rsvp_cancelled#rsvp" if prev else "#rsvp"))

    # ------------------------------------------------------------ comments + reports
    def post_comment(self, mid):
        u = self.user()
        if not u:
            return self.need_login()
        m = self.visible_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        path = meetup_path(m)
        if not (u["id"] == m["host_user_id"] or M.rsvp_of(mid, u["id"])):
            return self.redirect(path + "?e=rsvpfirst#comments")
        body = clean(f.get("body"), M.MAX_COMMENT, multiline=True)
        if not body:
            return self.redirect(path + "?e=empty#comments")
        if not (A.LIMITER.allow(f"mcomment:{u['id']}", 6, 600) and A.LIMITER.allow(f"mcomment-day:{u['id']}", 30, 86400)):
            return self.redirect(path + "?e=slow#comments")
        M.add_comment(mid, u["id"], body)
        return self.redirect(path + "?m=commented#comments")

    def post_comment_delete(self, mid, cid):
        u = self.user()
        if not u:
            return self.need_login()
        m = self.visible_meetup(mid)
        if not m:
            return
        f = self._form_or_fail()
        if f is None:
            return
        c = M.get_comment(cid)
        if not c or c["meetup_id"] != mid or u["id"] not in (c["user_id"], m["host_user_id"]):
            return self.msg_page("You can't delete that comment", '<p class="sub">Only the author or the host can delete a comment.</p>',
                                 code=403, icon="i-lock")
        M.delete_comment(cid)
        return self.redirect(meetup_path(m) + "?m=comment_deleted#comments")

    def _report(self, m, cid):
        f = self._form_or_fail()
        if f is None:
            return
        reason = f.get("reason") if f.get("reason") in A.REPORT_REASONS else "Something else"
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            u = self.user()
            M.add_report(m["id"], cid, u["id"] if u else None, reason, clean(f.get("details"), 1000, multiline=True), self._client_ip())
            print(f"reports: new report on meetup {m['id']}" + (f" comment {cid}" if cid else ""), flush=True)
        return self.redirect(meetup_path(m) + "?m=reported" + ("#comments" if cid else ""))

    def post_meetup_report(self, mid):
        m = self.visible_meetup(mid)
        if m:
            return self._report(m, None)

    def post_comment_report(self, mid, cid):
        u = self.user()
        if not u:
            return self.need_login()
        m = self.visible_meetup(mid)
        if not m:
            return
        c = M.get_comment(cid)
        if not c or c["meetup_id"] != mid:
            return self.not_found_meetup()
        return self._report(m, cid)

    # ------------------------------------------------------------ meetup page
    def meetup_ics(self, mid):
        m = M.get(mid)
        if not m or m["hidden"]:
            return self._emit(404, b"Not found", "text/plain")
        fn = (m["slug"] or "meetup") + ".ics"
        return self._emit(200, ics_text(self._base(), m), "text/calendar; charset=utf-8",
                          {"Content-Disposition": f'attachment; filename="{fn}"', "Cache-Control": "no-cache"})

    def rsvp_panel(self, m, u, mine):
        if m["status"] == "cancelled":
            return '<p class="muted" style="margin:0">This meetup was cancelled, so RSVPs are closed.</p>'
        if m["ends_at"] <= A.now():
            return '<p class="muted" style="margin:0">This meetup has ended.</p>'
        if not u:
            return '<p>Sign in to RSVP and pick which of your dogs are coming.</p><a class="btn" href="/signin">Sign in to RSVP</a>'
        dogs = [d for d in A.dogs_for_user(u["id"]) if not d["hidden"]]
        if not dogs:
            return '<p>Add your dog first, so everyone knows who\'s coming.</p><a class="btn" href="/me/dogs/new">Add your dog</a>'
        left = M.spots_left(m)
        chosen = set(mine["dogs"]) if mine else {d["id"] for d in dogs}
        st = mine["status"] if mine and mine["status"] != "waitlist" else "going"
        status_line = ""
        if mine:
            names = M.dog_names(mine["dogs"])
            lab = {"going": "You're going", "maybe": "You're a maybe", "waitlist": "You're on the waitlist"}[mine["status"]]
            status_line = (f'<p class="mstatus {mine["status"]}"><svg class="ico" aria-hidden="true"><use href="#i-check"/></svg><span>{lab}'
                           + (f' with {e(mailer.and_list(names))}' if names else "") + ".</span></p>")
        full = ""
        if left is not None and not (mine and mine["status"] == "going"):
            full = ('<p class="small notice" style="padding:10px 14px;margin:0 0 12px">This meetup is full. RSVP Going to join the waitlist.</p>' if left == 0
                    else f'<p class="small muted" style="margin:0 0 10px">{left} spot{"s" if left != 1 else ""} left (each dog takes a spot).</p>')
        ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}"{" checked" if d["id"] in chosen else ""}><span>{e(d["name"])}</span></label>'
                        for d in dogs)
        radios = "".join(f'<label class="tick"><input type="radio" name="status" value="{k}"{" checked" if st == k else ""}><span>{t}</span></label>'
                         for k, t in (("going", "Going"), ("maybe", "Maybe")))
        cancel = (f'<form method="post" action="{path_id(m)}/rsvp/cancel" style="margin-top:12px">{self.csrf_field()}'
                  f'<button class="linkbtn small" type="submit">Cancel my RSVP</button></form>') if mine else ""
        return (f'{status_line}{full}<form method="post" action="{path_id(m)}/rsvp">{self.csrf_field()}'
                f'<fieldset class="checks-grid" style="margin-bottom:12px"><legend>Are you coming?</legend>{radios}</fieldset>'
                f'<fieldset class="checks-grid" style="margin-bottom:16px"><legend>Which dogs?</legend>{ticks}</fieldset>'
                f'<button class="btn btn-sm" type="submit">{"Update RSVP" if mine else "RSVP"}</button></form>{cancel}')

    def who_html(self, att):
        def tiles(rows):
            out = []
            for x in rows:
                for d in x["dogs"]:
                    img = (f'<img src="/p/{d["photo"]}.webp" alt="" loading="lazy" width="72" height="72">' if d["photo"] else
                           '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></span>')
                    out.append(f'<li><a href="/dogs/{e(d["slug"])}">{img}<span>{e(d["name"])}</span></a></li>')
            return "".join(out)
        groups = []
        for key, lab in (("going", "Going"), ("maybe", "Maybe"), ("waitlist", "Waitlist")):
            rows = att.get(key) or []
            if not rows:
                continue
            nd = sum(x["ndogs"] for x in rows)
            people = ", ".join(x["name"] for x in rows)
            groups.append(f'<h3 class="mgh">{lab} <span>{nd} dog{"s" if nd != 1 else ""} · {len(rows)} member{"s" if len(rows) != 1 else ""}</span></h3>'
                          f'<ul class="mdogs">{tiles(rows)}</ul><p class="small muted" style="margin:-4px 0 14px">With {e(people)}</p>')
        return "".join(groups) or '<p class="muted" style="margin:0">No RSVPs yet. Be the first!</p>'

    def comments_html(self, m, u, is_host, mine):
        ccount = M.comment_count(m["id"])
        if not u:
            return (f'<p class="muted" style="margin:0">{ccount} comment{"s" if ccount != 1 else ""}. '
                    '<a href="/signin">Sign in</a> to read the conversation and join in.</p>')
        reasons = "".join(f"<option>{e(x)}</option>" for x in A.REPORT_REASONS)
        items = []
        for c in M.comments(m["id"]):
            acts = []
            if u["id"] in (c["user_id"], m["host_user_id"]):
                acts.append(f'<form method="post" action="{path_id(m)}/comments/{c["id"]}/delete">{self.csrf_field()}'
                            f'<button class="linkbtn" type="submit">Delete</button></form>')
            if u["id"] != c["user_id"]:
                acts.append(f'<details class="creport"><summary>Report</summary><form method="post" action="{path_id(m)}/comments/{c["id"]}/report">'
                            f'{self.csrf_field()}<select name="reason" aria-label="Reason">{reasons}</select>'
                            f'<button class="btn btn-sm" type="submit">Send report</button></form></details>')
            hostb = ' <span class="badge">Host</span>' if c["user_id"] == m["host_user_id"] else ""
            items.append(f'<li id="c{c["id"]}"><div class="chead"><b>{e(c["name"])}</b>{hostb}<span class="small muted">'
                         f'{e(M.when_text(c["created_at"], short=True))} ET</span></div><p class="cbody">{e(c["body"])}</p>'
                         f'<div class="cacts small">{"".join(acts)}</div></li>')
        lst = f'<ul class="clist">{"".join(items)}</ul>' if items else '<p class="muted">No comments yet.</p>'
        if is_host or mine:
            form = (f'<form method="post" action="{path_id(m)}/comments" class="cform">{self.csrf_field()}<label class="sr-only" for="cbody">Comment</label>'
                    f'<textarea id="cbody" name="body" maxlength="{M.MAX_COMMENT}" rows="3" required placeholder="Ask a question or say hi to the pack"></textarea>'
                    f'<button class="btn btn-sm" type="submit">Post comment</button></form>')
        else:
            form = '<p class="small muted" style="margin:0">RSVP to join the conversation.</p>'
        return lst + form

    def meetup_page(self, mid, slugpart, q):
        m = self.visible_meetup(mid)
        if not m:
            return
        if slugpart != (f"-{m['slug']}" if m["slug"] else ""):
            qs = ("?" + urlencode({k: v[0] for k, v in q.items()})) if q else ""
            return self.redirect(meetup_path(m) + qs, 301)
        u = self.user()
        base = self._base()
        is_host = bool(u and u["id"] == m["host_user_id"])
        r = run_of(m)
        att = M.attendees(mid)
        mine = M.rsvp_of(mid, u["id"]) if u else None
        going_dogs = [d for x in att["going"] for d in x["dogs"]]
        ngoing = sum(x["ndogs"] for x in att["going"])
        fact = lambda ico, txt: f'<li><svg class="ico" aria-hidden="true"><use href="#{ico}"/></svg>{txt}</li>'
        facts = [fact("i-cal", e(M.when_text(m["starts_at"], m["duration_min"]))), fact("i-clock", e(M.duration_text(m["duration_min"]))),
                 fact("i-pin", e(where_line(m)))]
        if m["fit"]:
            facts.append(fact(FIT_ICON.get(m["fit"], "i-paw"), e(M.FIT_LABEL[m["fit"]])))
        if m["capacity"]:
            left = max(m["capacity"] - ngoing, 0)
            facts.append(fact("i-users", f"{m['capacity']} dogs max · " + ("full, waitlist open" if left == 0 else f"{left} left")))
        banners = []
        if m["is_sample"]:
            banners.append('<p class="notice small" style="margin:0 0 16px"><b>Sample meetup.</b> An example to show how BarksBuds meetups work. '
                           'It may be removed before launch, and it doesn\'t send email notifications.</p>')
        if m["status"] == "cancelled":
            banners.append('<p class="formerr" role="status" style="margin:0 0 16px">This meetup was cancelled by the host.</p>')
        elif m["ends_at"] <= A.now():
            banners.append('<p class="notice small" style="margin:0 0 16px">This meetup has ended.</p>')
        if m["hidden"]:
            banners.append('<p class="formerr" style="margin:0 0 16px">Hidden by our team while we review a report. Only you can see it.</p>')
        left_q = q.get("left", ["0"])[0]
        err = {"closed": "RSVPs are closed for this meetup.", "slow": "That's a lot of changes. Please wait a few minutes and try again.",
               "nodogs": "Pick at least one dog.", "adddog": "Add your dog first.", "rsvpfirst": "RSVP to join the conversation.",
               "empty": "Write something first.",
               "full": f"Only {int(left_q) if left_q.isdigit() and len(left_q) < 4 else 0} spot(s) left, so you can't add more dogs right now."
               }.get(q.get("e", [""])[0], "")
        errhtml = f'<p class="formerr" role="alert">{e(err)}</p>' if err else ""
        host_tools = ""
        if is_host:
            tools = []
            if m["status"] == "active":
                tools.append(f'<a class="btn btn-ghost btn-sm" href="{path_id(m)}/edit">Edit</a>')
            tools.append(f'<form method="post" action="{path_id(m)}/repeat">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit">Repeat next week</button></form>')
            if m["status"] == "active":
                tools.append(f'<a class="btn btn-danger btn-sm" href="{path_id(m)}/cancel">Cancel meetup</a>')
            host_tools = f'<div class="formfoot mtools"><span class="small muted">You\'re the host:</span>{"".join(tools)}</div>'
        cal = ""
        if m["status"] == "active":
            cal = (f'<div class="formfoot"><a class="btn btn-gold btn-sm mjump" href="#rsvp">RSVP</a><a class="btn btn-sm" href="/meetups/{mid}.ics"><svg class="ico" aria-hidden="true"><use href="#i-cal"/></svg>Add to calendar</a>'
                   f'<a class="btn btn-ghost btn-sm" href="{e(gcal_url(base, m))}" target="_blank" rel="noopener">Google Calendar</a>'
                   f'<a class="btn btn-ghost btn-sm" href="{e(directions_url(m, r))}" target="_blank" rel="noopener"><svg class="ico" aria-hidden="true"><use href="#i-nav"/></svg>Directions</a></div>')
        scripts = ""
        if m["lat"] is not None and m["lng"] is not None:
            mapbox = f'<div id="mmap1" class="mmap one" data-pts="{e(json_attr(map_points([m])))}" role="img" aria-label="Map showing {e(m["place_name"])}"></div>'
            scripts = '<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">' + MAP_JS % ("mmap1", "false", "15")
        else:
            mapbox = (f'<div class="mplace"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg><b>{e(m["place_name"])}</b>'
                      f'<span>{e(m["address"])}</span></div>')
        reasons = "".join(f"<option>{e(x)}</option>" for x in A.REPORT_REASONS)
        report = (f'<details class="report"><summary>Report this meetup</summary><form method="post" action="{path_id(m)}/report">{self.csrf_field()}'
                  f'<div class="field"><label for="reason">What\'s wrong?</label><select id="reason" name="reason">{reasons}</select></div>'
                  f'<div class="field"><label for="details">Details <span class="opt">(optional)</span></label><textarea id="details" name="details" maxlength="1000" rows="3"></textarea></div>'
                  f'<button class="btn btn-sm" type="submit">Send report</button><p class="small muted" style="margin:10px 0 0">Reports go to the BarksBuds team, not to the host.</p></form></details>')
        wp = [f'<h2>Where</h2><p style="margin:0 0 4px"><b>{e(m["place_name"])}</b></p>']
        if m["address"]:
            wp.append(f'<p class="muted" style="margin:0 0 10px">{e(m["address"])}</p>')
        if r:
            fenced = "Fenced" if str(r.get("fenced") or "").lower().startswith(("y", "true")) else ""
            bits = [x for x in ((r.get("type") or "").capitalize(), fenced, r.get("hours")) if x]
            if bits:
                wp.append(f'<p class="small muted" style="margin:0 0 6px">{e(" · ".join(bits))}</p>')
            if r.get("residency_permit_rules"):
                wp.append(f'<p class="small" style="margin:0 0 10px"><b>Rules:</b> {e(r["residency_permit_rules"])}</p>')
            wp.append(f'<p class="small" style="margin:0 0 10px"><a href="/runs?q={quote(r["name"])}">See this run on the dog run map</a></p>')
        wp.append(f'<div class="formfoot"><a class="btn btn-ghost btn-sm" href="{e(directions_url(m, r))}" target="_blank" rel="noopener">Google Maps</a>'
                  f'<a class="btn btn-ghost btn-sm" href="{e(apple_maps_url(m, r))}" target="_blank" rel="noopener">Apple Maps</a></div>')
        desc_txt = m["description"] or f"A dog meetup at {m['place_name']}. RSVP with your dogs on BarksBuds."
        sample_b = ' · <span class="badge sample">Sample</span>' if m["is_sample"] else ""
        host_q = ("?run=" + quote(m["run_id"])) if m["run_id"] else ""
        body = f"""<section class="dhero mhero"><div class="wrap"><div>{''.join(banners)}
<span class="eyebrow" style="margin:0">dog meetup{sample_b}</span>
<h1 class="dname mtitle">{e(m["title"])}</h1><ul class="facts">{''.join(facts)}</ul>
<p class="owner"><svg class="ico" aria-hidden="true" style="width:20px;height:20px;color:var(--red)"><use href="#i-user"/></svg><span>Hosted by <b>{e(m["host_name"])}</b></span></p>
<div style="margin-top:18px">{cal}</div>{host_tools}</div><div>{mapbox}</div></div></section>
<section class="section" style="padding-top:36px"><div class="wrap">{errhtml}<div class="dgrid2"><div>
<div class="panel"><h2>About this meetup</h2><p class="bio">{e(desc_txt)}</p></div>
<div class="panel"><h2>Who's coming <span class="mcount2">{ngoing} dog{"s" if ngoing != 1 else ""} going</span></h2>{self.who_html(att)}</div>
<div class="panel" id="comments"><h2>Conversation</h2>{self.comments_html(m, u, is_host, mine)}</div></div>
<div><div class="panel" id="rsvp"><h2>RSVP</h2>{self.rsvp_panel(m, u, mine)}</div><div class="panel">{''.join(wp)}</div>
<div class="panel" style="background:var(--black);color:#E9E1D3;box-shadow:6px 6px 0 var(--red)"><h2 style="color:#fff">Host your own</h2>
<p>Pick your favorite run, set a time and invite the regulars.</p><a class="btn btn-gold btn-sm" href="/meetups/new{host_q}">Host a meetup</a></div></div></div>
{report}</div></section>"""
        when_s = M.when_text(m["starts_at"], m["duration_min"])
        extra = (m["description"][:110] + ("…" if len(m["description"]) > 110 else "")) if m["description"] else "RSVP with your dogs on BarksBuds."
        og_desc = f"{when_s} at {where_line(m)}. {extra}"
        og = {"title": m["title"], "desc": og_desc, "type": "website", "alt": f"{m['title']} on BarksBuds",
              "image": base + "/img/og-image.jpg", "w": 1200, "h": 630}
        if going_dogs and going_dogs[0]["photo"]:
            og["image"] = f"{base}/p/{going_dogs[0]['photo']}.jpg"
            og.pop("w"); og.pop("h")
        return self.page(m["title"], body, canonical=meetup_path(m), desc=og_desc, og=og,
                         index=not (m["hidden"] or m["is_sample"] or m["status"] != "active"), active="meetups", scripts=scripts,
                         flash=self.flash_from(q))

    # ------------------------------------------------------------ email preferences
    def post_email_prefs(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        on = f.get("on") == "1"
        M.set_emails(u["id"], on)
        return self.redirect("/me?m=" + ("emails_on" if on else "emails_off") + "#emails")

    def unsub_page(self, q):
        uid, tok = q.get("u", [""])[0], q.get("t", [""])[0]
        if not M.check_unsub(uid, tok):
            return self.msg_page("That link doesn't work", '<p class="sub">This unsubscribe link is incomplete. '
                                 'You can turn meetup emails off from your account page.</p><p><a class="btn" href="/me#emails">Email preferences</a></p>',
                                 code=400, icon="i-mail")
        on = M.emails_on(int(uid))
        body = (f'<p class="sub">{"Stop" if on else "You turned off"} RSVP confirmations, host notices, cancellations and reminders for meetups.</p>'
                f'<form method="post" action="/emails/meetups"><input type="hidden" name="u" value="{e(uid)}"><input type="hidden" name="t" value="{e(tok)}">'
                f'<input type="hidden" name="action" value="{"off" if on else "on"}"><button class="btn" type="submit">'
                f'{"Turn off meetup emails" if on else "Turn meetup emails back on"}</button></form>'
                '<p class="small muted" style="margin-top:14px">Sign-in links still arrive by email.</p>')
        return self.msg_page("Meetup emails" if on else "Meetup emails are off", body, icon="i-mail")

    def post_unsub(self):
        """Token-authenticated (no session or CSRF needed). Also handles RFC 8058 one-click POSTs from mail apps."""
        f = self.read_form()
        if f is None:
            return self._emit(413, b"Too large", "text/plain")
        uid, tok = f.get("u"), f.get("t")
        if not uid:
            qs = parse_qs(urlsplit(self.path).query)
            uid, tok = qs.get("u", [""])[0], qs.get("t", [""])[0]
        if not M.check_unsub(uid, tok):
            return self._emit(400, b"Invalid link", "text/plain")
        on = f.get("action") == "on"
        M.set_emails(int(uid), on)
        print("meetups: email preference changed via link", flush=True)
        if f.get("List-Unsubscribe") == "One-Click":
            return self._emit(200, b"Unsubscribed", "text/plain")
        msg = "You'll get meetup emails again." if on else "You won't get meetup emails anymore. You can turn them back on from your account page any time."
        return self.msg_page("Meetup emails are " + ("on" if on else "off"), f'<p class="sub">{msg}</p><p><a class="btn" href="/meetups">See upcoming meetups</a></p>', icon="i-mail")

    # ------------------------------------------------------------ admin (behind ADMIN_KEY)
    def _admin_key(self, f=None, q=None):
        k = (f.get("key") if f else "") or (q or {}).get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        return k if self._admin_key_ok(k) else None

    def admin_meetups(self, q):
        key = self._admin_key(q=q)
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        tr = []
        for r in A.q(f"SELECT {M.M_COLS} FROM meetups ORDER BY starts_at DESC LIMIT 300"):
            m = M._m(r)
            acts = []
            for act, lab in ((("unhide", "Unhide") if m["hidden"] else ("hide", "Hide")), ("delete", "Delete")):
                conf = ' onclick="return confirm(\'Delete this meetup with its RSVPs and comments?\')"' if act == "delete" else ""
                acts.append(f'<form method="post" action="/admin/meetups" style="display:inline"><input type="hidden" name="key" value="{e(key)}">'
                            f'<input type="hidden" name="id" value="{m["id"]}"><input type="hidden" name="action" value="{act}">'
                            f'<button class="linkbtn" type="submit"{conf}>{lab}</button></form>')
            flags = " ".join(x for x in ("<b>SAMPLE</b>" if m["is_sample"] else "", "hidden" if m["hidden"] else "",
                                         m["status"] if m["status"] != "active" else "") if x)
            n = A.one("SELECT COUNT(*) FROM rsvps WHERE meetup_id=:m", m=m["id"])[0]
            tr.append(f'<tr><td>{m["id"]}</td><td><a href="{e(meetup_path(m))}">{e(m["title"])}</a></td><td>{e(M.when_text(m["starts_at"], short=True))} ET</td>'
                      f'<td>{e(m["place_name"])}</td><td>{n}</td><td>{flags}</td><td>{" · ".join(acts)}</td></tr>')
        bulk = (f'<form method="post" action="/admin/meetups" class="formfoot" style="margin-bottom:18px"><input type="hidden" name="key" value="{e(key)}">'
                f'<button class="btn btn-ghost btn-sm" name="action" value="hide_samples">Hide all sample meetups</button>'
                f'<button class="btn btn-ghost btn-sm" name="action" value="unhide_samples">Unhide samples</button>'
                f'<button class="btn btn-danger btn-sm" name="action" value="delete_samples" onclick="return confirm(\'Delete all sample meetups?\')">Delete all sample meetups</button></form>')
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">admin</span><h1>Meetups</h1>
<p class="lead">All meetups, latest first. Reports on meetups and comments are in <a href="/admin/reports?key={e(quote(key))}">Reports</a>.</p></div></section>
<section class="section"><div class="wrap">{bulk}<div style="overflow-x:auto"><table class="t"><thead><tr><th>#</th><th>Title</th><th>When</th><th>Where</th><th>RSVPs</th><th>Flags</th><th>Actions</th></tr></thead>
<tbody>{''.join(tr) or '<tr><td colspan="7">No meetups yet.</td></tr>'}</tbody></table></div></div></section>"""
        return self.page("Admin: meetups", body)

    def post_admin_meetups(self):
        f = self.read_form()
        key = self._admin_key(f) if f else None
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        act, mid = f.get("action"), f.get("id")
        if act in ("hide", "unhide", "delete") and mid.isdigit():
            if act == "delete":
                M.delete(int(mid))
            else:
                M.set_hidden(int(mid), act == "hide")
        elif act in ("hide_samples", "unhide_samples", "delete_samples"):
            for (i,) in A.q("SELECT id FROM meetups WHERE is_sample=1"):
                if act == "delete_samples":
                    M.delete(i)
                else:
                    M.set_hidden(i, act == "hide_samples")
        print(f"admin: meetup action {act}", flush=True)
        return self.redirect("/admin/meetups?key=" + quote(key))

    def post_admin_reminders(self):
        f = self.read_form()
        if f is None or not self._admin_key(f):
            return self._emit(404, b"Not found", "text/plain")
        nm, ne = send_reminders(self._base())
        return self._emit(200, json.dumps({"ok": True, "meetups": nm, "emails_queued": ne}).encode(), "application/json",
                          {"Cache-Control": "no-store"})

    def post_admin_test_email(self):
        """Admin-only deliverability test: send one meetup email type for a meetup to that meetup's HOST only."""
        f = self.read_form()
        if f is None or not self._admin_key(f):
            return self._emit(404, b"Not found", "text/plain")
        kind, mid = f.get("kind"), f.get("id")
        m = M.get(int(mid)) if mid.isdigit() else None
        if not m or kind not in ("confirm", "promoted", "host", "cancel", "reminder"):
            return self._emit(400, b"Bad request", "text/plain")
        att = M.attendees(m["id"])
        others = [x for x in att["going"] + att["maybe"] if x["user_id"] != m["host_user_id"]] or att["going"]
        mine = M.rsvp_of(m["id"], m["host_user_id"])
        dogs = M.dog_names(mine["dogs"]) if mine else []
        who = others[0] if others else None
        kw = {"confirm": dict(status="going", dogs=dogs), "promoted": dict(status="going", dogs=dogs),
              "reminder": dict(status="going", dogs=dogs), "cancel": {},
              "host": dict(status="going", who=who["name"] if who else "A member",
                           who_dogs=[d["name"] for d in who["dogs"]] if who else [], counts=counts_text(m["id"]))}[kind]
        ok = send_meetup_mail(self._base(), m["host_user_id"], kind, m, force=True, subject_prefix="[Test] ", **kw)
        print(f"admin: meetup test email {kind} for meetup {m['id']} queued={ok}", flush=True)
        return self._emit(200, json.dumps({"ok": ok, "kind": kind, "to": "meetup host"}).encode(), "application/json",
                          {"Cache-Control": "no-store"})


def landing_html():
    """'Starting on the North Shore' highlight for the landing page (index.html {{NORTH_SHORE}})."""
    try:
        ms = M.upcoming(north_shore=True, limit=2)
    except Exception:
        ms = []
    cards = []
    for m in ms:
        s = M.to_et(m["starts_at"])
        n = M.going_dogs(m["id"])
        sample = '<span class="ns-badge">Sample</span>' if m["is_sample"] else ""
        cards.append(f'<a class="ns-card" href="{e(meetup_path(m))}"><span class="ns-date"><b>{s.strftime("%a").upper()}</b>{s.day}<small>{s.strftime("%b")}</small></span>'
                     f'<span class="ns-body">{sample}<b class="ns-t">{e(m["title"])}</b><span>{e(M.when_text(m["starts_at"], m["duration_min"]))}</span>'
                     f'<span>{e(where_line(m))}</span><span class="ns-go">{n} dog{"s" if n != 1 else ""} going &rarr;</span></span></a>')
    right = "".join(cards) or '<p class="ns-empty">The first North Shore meetup is being planned. Check back soon!</p>'
    return f"""<style>
.nsh{{padding:72px 0;background:var(--black);color:#E9E1D3}}
.nsh .wrap{{display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center}}
.nsh h2{{color:#fff;font-size:clamp(2rem,4.2vw,2.85rem)}}.nsh .eyebrow{{color:var(--gold)}}
.nsh p{{color:#D8CFC0;font-size:1.08rem}}.nsh .cta-row{{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:center}}
.nsh .textlink{{color:var(--gold);font-weight:800}}
.ns-cards{{display:grid;gap:16px}}
.ns-card{{display:flex;gap:16px;align-items:flex-start;background:#fff;color:var(--ink);text-decoration:none;border-radius:22px;padding:18px;border:3px solid var(--gold);box-shadow:8px 8px 0 var(--red);transition:transform .12s}}
.ns-card:hover{{transform:translateY(-2px)}}
.ns-date{{flex:none;width:64px;text-align:center;background:var(--gold);color:var(--black);border-radius:16px;padding:8px 0 6px;font:800 1.7rem/1 "Baloo 2",sans-serif}}
.ns-date b{{display:block;font:800 .8rem/1.2 Nunito,sans-serif;letter-spacing:.06em}}.ns-date small{{display:block;font:700 .8rem/1.3 Nunito,sans-serif}}
.ns-body{{display:flex;flex-direction:column;gap:2px;font-size:.98rem;color:var(--muted);line-height:1.4}}
.ns-t{{font:800 1.25rem/1.15 "Baloo 2",sans-serif;color:var(--black);margin-bottom:4px}}
.ns-go{{color:var(--red);font-weight:800;margin-top:4px}}
.ns-badge{{align-self:flex-start;background:var(--gold-l,#FFE7A8);color:#3A2A08;border-radius:999px;padding:2px 10px;font-weight:800;font-size:.78rem;margin-bottom:4px}}
.ns-empty{{background:#24211E;border-radius:18px;padding:22px}}
@media (max-width:860px){{.nsh .wrap{{grid-template-columns:1fr;gap:28px}}.nsh{{padding:56px 0}}}}
</style>
<section class="nsh" id="meetups" aria-labelledby="ns-title"><div class="wrap"><div>
<span class="eyebrow">new · meetups</span><h2 id="ns-title">Starting on the North Shore</h2>
<p>BarksBuds started with a group of friends and their dogs in Manhasset, so our first meetups are around Manhasset and the North Shore of Long Island. RSVP with your dogs, see who's coming, and host one at your own run.</p>
<div class="cta-row"><a class="btn btn-gold" href="/meetups">See upcoming meetups</a><a class="textlink" href="/meetups/new">or host a meetup</a></div></div>
<div class="ns-cards">{right}</div></div></section>"""
