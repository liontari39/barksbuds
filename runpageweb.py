"""BarksBuds run pages (Oct 2026): one page per dog run with "At the run now" check-ins, official park announcements,
follow / unfollow, nearby lost and found alerts and the run's details.

Routes:
  GET  /runs/<run id>[-slug]                 the run page (e.g. /runs/n-006-manhasset-dog-park)
  POST /runs/<run id>/checkin                "We're here": dogs (ids, owner or co-owner), anon=1 hides the dogs; 2-hour expiry
  POST /runs/<run id>/leave                  "Leaving"
  POST /runs/<run id>/follow                 on=1 follow / on=0 unfollow (followers get announcement emails)
  POST /runs/<run id>/announce               verified park account only: kind, title, body, until (YYYY-MM-DD, optional)
  POST /runs/<run id>/announce/<id>/remove   verified park account (or admin) removes an announcement
  GET  /runs/<run id>/news                   plain public page with the run's announcements (current and past)
  GET  /runs/<run id>/feed.xml               public RSS feed of the run's announcements
  GET  /api/runs/live                        {"here": {run id: dogs here now}, "news": {run id: current announcements}}
  GET  /admin/parks?key=KEY                  admin: verified park accounts (grant by member email + run ids) and announcements
  POST /admin/parks                          admin: action=grant|revoke|remove_announcement
Check-ins are rate limited (CHECKINS_PER_HOUR per member) and a member is at one run at a time.
"""
import html, re
from datetime import datetime, time as dtime
from email.utils import formatdate
from urllib.parse import quote

import accounts as A
import community as C
import coowners as CO
import mailer
import webapp as W

e = html.escape
RUN_RE = r"([a-z]-\d{1,5})"
KIND_ICON = {"closure": "i-alert", "maintenance": "i-clock", "rule": "i-shield", "event": "i-cal", "other": "i-chat"}


def run_slug(r):
    return A.slugify(r.get("name") or "dog-run", 50) or "dog-run"


def run_path(r):
    return f"/runs/{r['id']}-{run_slug(r)}"


def run_where(r):
    county = r.get("county") or ""
    return " · ".join(x for x in (r.get("park") if r.get("park") and r.get("park") != r.get("name") else "",
                                   r.get("town_or_neighborhood"), W.area_label(county)) if x)


def fmt_time(ts):
    return datetime.fromtimestamp(ts, C.ET).strftime("%-I:%M %p") if ts else ""


def fmt_day(ts):
    return datetime.fromtimestamp(ts, C.ET).strftime("%a, %b %-d") if ts else ""


def ago(ts):
    m = max(0, (C.now() - ts) // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} hr ago"


def end_of_day(s):
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return int(datetime.combine(d, dtime(23, 59, 59), C.ET).timestamp())


def follow_unsub_url(base, uid, kind="follow"):
    return f"{base}/emails/community?u={uid}&k={kind}&t={C.unsub_token(uid, kind)}"


class RunPageRoutes:
    # ------------------------------------------------------------ routing
    def runpage_get(self, path, q):
        if path == "/api/runs/live":
            self._app_reset()
            return self._json_nc({"here": C.here_counts(), "news": C.announcement_counts()}) or True
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/feed\.xml", path)
        if m:
            self._app_reset(); self.run_feed(m.group(1)); return True
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/news/?", path)
        if m:
            self._app_reset(); self.run_news(m.group(1)); return True
        m = re.fullmatch(r"/runs/" + RUN_RE + r"(-[a-z0-9-]*)?/?", path)
        if m:
            self._app_reset(); self.run_page(m.group(1), m.group(2) or "", q); return True
        if path == "/admin/parks":
            self._app_reset(); self.admin_parks(q); return True
        return False

    def runpage_post(self, path, q):
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/(checkin|leave|follow|announce)", path)
        if m:
            self._app_reset()
            getattr(self, "post_run_" + m.group(2))(m.group(1)); return True
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/announce/(\d+)/remove", path)
        if m:
            self._app_reset(); self.post_run_ann_remove(m.group(1), int(m.group(2))); return True
        if path == "/admin/parks":
            self._app_reset(); self.post_admin_parks(); return True
        return False

    def _json_nc(self, obj):
        import json
        self._emit(200, json.dumps(obj).encode(), "application/json; charset=utf-8", headers={"Cache-Control": "no-cache"})

    def _run_or_404(self, rid):
        r = W.run_index().get(rid)
        if not r:
            self.msg_page("We couldn't find that dog run", '<p class="sub">It may have closed or moved.</p>'
                          '<p><a class="btn" href="/runs">See the dog run map</a></p>', code=404, icon="i-pin")
        return r

    # ------------------------------------------------------------ the run page
    def run_page(self, rid, slug, q):
        r = self._run_or_404(rid)
        if not r:
            return
        if slug != "-" + run_slug(r):
            return self.redirect(run_path(r) + ("?" + "&".join(f"{k}={quote(v[0])}" for k, v in q.items()) if q else ""), 301)
        u = self.user()
        base = self._base()
        anns = C.announcements(rid)
        here = C.here_now(rid)
        ndogs = sum(x["ndogs"] for x in here)
        flash = {"here": "You're checked in. Have fun!", "left": "Checked out. See you next time!",
                 "followed": "You're following this run.", "unfollowed": "You're no longer following this run.",
                 "posted": "Announcement posted.", "removed": "Announcement removed.",
                 "slow": "That's a lot of check-ins. Please try again in a bit.", "nodogs": "Pick at least one dog."}.get(q.get("m", [""])[0], "")
        # announcements: prominent, above everything else
        ann_html = ""
        if anns:
            items = []
            for a in anns:
                until = f' · until {e(fmt_day(a["ends_at"]))}' if a["ends_at"] else ""
                items.append(f"""<article class="annc k-{e(a["kind"])}"><div class="annc-h"><span class="offbadge"><svg class="ico" aria-hidden="true"><use href="#i-shield"/></svg>Official</span>
<span class="annc-k"><svg class="ico" aria-hidden="true"><use href="#{KIND_ICON.get(a["kind"], "i-chat")}"/></svg>{e(dict(C.ANN_KINDS).get(a["kind"], "Notice"))}</span></div>
<h3>{e(a["title"])}</h3>{f'<p class="annc-b">{e(a["body"])}</p>' if a["body"] else ""}
<p class="annc-by">From {e(a["org_name"] or "the park")} · {e(fmt_day(a["created_at"]))}{until}</p></article>""")
            ann_html = f'<section class="anncs" aria-label="Official announcements">{"".join(items)}</section>'
        # lost and found near this run
        lost = C.alerts_near(r.get("lat"), r.get("lng"), r.get("county"), limit=3)
        lost_html = ""
        if lost:
            import communityweb
            lost_html = ('<div class="panel lfpanel"><h2><svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg>Lost and found nearby</h2>'
                         f'<div class="lfmini">{"".join(communityweb.alert_mini(a) for a in lost)}</div>'
                         '<p class="small" style="margin:12px 0 0"><a href="/lost-found">All lost and found alerts</a></p></div>')
        # at the run now
        tiles, anon_dogs = [], 0
        for x in here:
            if x["anon"]:
                anon_dogs += x["ndogs"]
                continue
            for d in x["dogs"]:
                tiles.append(f'<li><a href="/dogs/{e(d["slug"])}">{A.tile_img(d, 72)}<span>{e(d["name"])}</span></a></li>')
            anon_dogs += x["ndogs"] - len(x["dogs"])
        more = f'<p class="small muted" style="margin:6px 0 0">+ {anon_dogs} more dog{"s" if anon_dogs != 1 else ""} checked in privately.</p>' if anon_dogs and tiles else (
            f'<p class="small muted" style="margin:6px 0 0">Checked in privately, so their names aren\'t shown.</p>' if anon_dogs else "")
        now_line = (f'<p class="herenow"><span class="livedot" aria-hidden="true"></span><b>{ndogs} dog{"s" if ndogs != 1 else ""} here now</b></p>'
                    if ndogs else '<p class="muted" style="margin:0 0 12px">Nobody has checked in yet. Heading over? Let the regulars know.</p>')
        here_html = f'{now_line}{f"<ul class=mdogs>{chr(10).join(tiles)}</ul>" if tiles else ""}{more}'
        here_form = self._checkin_form(r, u)
        # follow
        nf = C.follower_count(rid)
        if u:
            on = C.follows(u["id"], rid)
            follow = (f'<form method="post" action="/runs/{rid}/follow">{self.csrf_field()}<input type="hidden" name="on" value="{0 if on else 1}">'
                      f'<button class="btn {"btn-ghost " if on else ""}btn-sm" type="submit" aria-pressed="{"true" if on else "false"}">'
                      f'<svg class="ico" aria-hidden="true"><use href="#{"i-check" if on else "i-heart"}"/></svg>{"Following" if on else "Follow this run"}</button></form>')
        else:
            follow = f'<a class="btn btn-sm" href="{e(self.signin_href(run_path(r)))}"><svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg>Follow this run</a>'
        # park account tools
        org = C.park_role(u["id"], rid) if u else None
        park_html = self._park_tools(r, org) if org else ""
        # details
        LBL = {"yes": "Yes", "no": "No", "partial": "Partial", "seasonal": "Seasonal", "nearby": "Nearby, outside the run", "minimal": "Minimal"}
        val = lambda v: e(LBL.get(str(v or "").strip().lower(), str(v or "").strip())) or '<span class="unk">Not yet confirmed</span>'
        amen = [("Fenced", r.get("fenced")), ("Small-dog area", r.get("small_dog_area")), ("Water", r.get("water")), ("Shade", r.get("shade")),
                ("Surface", r.get("surface")), ("Seating", r.get("seating"))]
        facts = [("Hours", r.get("hours")), ("Who can use it", r.get("residency_permit_rules")), ("Fees", r.get("fees")),
                 ("Run by", r.get("operator")), ("Address", r.get("address")), ("Good to know", r.get("notes"))]
        dl = "".join(f"<div><dt>{k}</dt><dd>{val(v)}</dd></div>" for k, v in amen)
        dl2 = "".join(f"<div><dt>{k}</dt><dd>{e(str(v))}</dd></div>" for k, v in facts if str(v or "").strip())
        dest = quote(f'{r["lat"]},{r["lng"]}' if isinstance(r.get("lat"), (int, float)) else (r.get("address") or r.get("name")))
        news_link = f'<a href="/runs/{rid}/news">All announcements</a> · <a href="/runs/{rid}/feed.xml">RSS feed</a>'
        body = f"""<section class="phead rhead"><div class="wrap"><span class="eyebrow">dog run</span><h1>{e(r["name"])}</h1>
<p class="lead">{e(run_where(r))}</p>
<div class="racts">{follow}<a class="btn btn-ghost btn-sm" href="/runs?q={quote(r["name"])}"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>See it on the map</a>
<a class="btn btn-ghost btn-sm" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&amp;destination={dest}"><svg class="ico" aria-hidden="true"><use href="#i-nav"/></svg>Directions</a></div>
<p class="small muted" style="margin:10px 0 0">{nf} member{"s" if nf != 1 else ""} follow{"s" if nf == 1 else ""} this run · {news_link}</p></div></section>
<section class="section"><div class="wrap">{ann_html}
<div class="dgrid2"><div>
<div class="panel herepanel" id="here"><h2>At the run now</h2>{here_html}{here_form}</div>
{lost_html}
<div class="panel"><h2>About this run</h2><dl class="amen">{dl}</dl><dl class="facts">{dl2}</dl>
<p class="small muted" style="margin:14px 0 0">Know this run? <a href="/runs/suggest?edit={quote(rid)}">Suggest an edit</a></p></div>
</div><div>{park_html}
<div class="panel"><h2>Meet up here</h2><p>Plan a park hang or a group walk at {e(r["name"])}.</p>
<a class="btn btn-sm" href="/meetups/new?run={quote(rid)}"><svg class="ico" aria-hidden="true"><use href="#i-cal"/></svg>Host a meetup here</a></div>
<div class="panel"><h2>Lost a dog nearby?</h2><p class="small">Post a lost or found alert and we'll email members who follow nearby runs.</p>
<a class="btn btn-ghost btn-sm" href="/lost-found/new?run={quote(rid)}"><svg class="ico" aria-hidden="true"><use href="#i-alert"/></svg>Post an alert</a></div>
</div></div></div></section>"""
        desc = f"{r['name']} in {run_where(r)}: who's at the run now, official park news and details on BarksBuds."
        extra = f'<link rel="alternate" type="application/rss+xml" title="{e(r["name"])} announcements" href="/runs/{rid}/feed.xml">'
        self.page(r["name"], body.replace("<section", extra + "<section", 1), index=True, canonical=run_path(r), desc=desc, active="runs",
                  og={"title": r["name"] + " · BarksBuds", "image": base + "/img/og-image.jpg?v=jack3", "w": 1200, "h": 630}, flash=flash)

    def _checkin_form(self, r, u):
        rid = r["id"]
        if not u:
            return (f'<p style="margin:14px 0 0"><a class="btn btn-sm" href="{e(self.signin_href(run_path(r) + "#here"))}">'
                    f'<svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>Sign in to check in</a></p>')
        mine = C.active_checkin(u["id"])
        if mine and mine["run_id"] == rid:
            names = W_and(d["name"] for d in C.dog_tiles(mine["dogs"])) or "your dogs"
            priv = " (privately)" if mine["anon"] else ""
            return (f'<div class="mine-in"><p style="margin:0 0 10px"><b>You\'re here with {e(names)}{priv}.</b> '
                    f'<span class="muted">Checked in at {e(fmt_time(mine["created_at"]))}, ends at {e(fmt_time(mine["expires_at"]))}.</span></p>'
                    f'<form method="post" action="/runs/{rid}/leave">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit">Leaving</button></form></div>')
        dogs = A.dogs_for_user(u["id"])
        if not dogs:
            return '<p style="margin:14px 0 0" class="small">Add your dog to check in. <a href="/me/dogs/new">Add a dog</a></p>'
        elsewhere = ""
        if mine:
            other = W.run_index().get(mine["run_id"])
            elsewhere = f'<p class="small muted" style="margin:0 0 8px">You\'re checked in at {e(other["name"] if other else "another run")}. Checking in here ends that one.</p>'
        ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}" checked><span>{e(d["name"])}</span></label>' for d in dogs)
        hidden = C.checkins_hidden(u["id"])
        return (f'<form class="checkin" method="post" action="/runs/{rid}/checkin">{self.csrf_field()}{elsewhere}'
                f'<fieldset class="checks-grid" style="margin-bottom:10px"><legend>Who\'s with you?</legend>{ticks}</fieldset>'
                f'<label class="switch small" style="margin-bottom:12px"><input type="checkbox" name="anon" value="1"{" checked" if hidden else ""}>'
                f'<span>Count us, but don\'t show our dogs</span></label>'
                f'<button class="btn btn-sm" type="submit"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg>We\'re here</button>'
                f'<p class="small muted" style="margin:8px 0 0">Check-ins end on their own after 2 hours. <a href="/me#privacy">Privacy settings</a></p></form>')

    def _park_tools(self, r, org):
        rid = r["id"]
        kinds = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in C.ANN_KINDS)
        rows = []
        for a in C.announcements(rid, current=False, limit=10):
            state = "ended" if a["ends_at"] and a["ends_at"] < C.now() else "live"
            rows.append(f'<li><b>{e(a["title"])}</b> <span class="small muted">{e(fmt_day(a["created_at"]))} · {state}</span>'
                        f'<form method="post" action="/runs/{rid}/announce/{a["id"]}/remove" style="display:inline">{self.csrf_field()}'
                        f'<button class="linkbtn small" type="submit">Remove</button></form></li>')
        return f"""<div class="panel parkpanel"><h2>Post an official update</h2><p class="small muted">You're the verified park account for this run ({e(org)}). Followers get an email.</p>
<form method="post" action="/runs/{rid}/announce">{self.csrf_field()}
<div class="field"><label for="a-kind">Type</label><select id="a-kind" name="kind">{kinds}</select></div>
<div class="field"><label for="a-title">Title</label><input id="a-title" name="title" maxlength="90" required placeholder="e.g. Run closed Tuesday for resurfacing"></div>
<div class="field"><label for="a-body">Details <span class="opt">(optional)</span></label><textarea id="a-body" name="body" rows="3" maxlength="1500"></textarea></div>
<div class="field"><label for="a-until">Show until <span class="opt">(optional)</span></label><input id="a-until" name="until" type="date"></div>
<button class="btn btn-sm" type="submit">Post announcement</button></form>
{f'<ul class="annlist">{"".join(rows)}</ul>' if rows else ""}</div>"""

    # ------------------------------------------------------------ check-ins
    def _run_member(self, rid):
        u = self.user()
        if not u:
            self.need_login(); return None, None, None
        r = W.run_index().get(rid)
        if not r:
            self.msg_page("We couldn't find that dog run", "", code=404); return None, None, None
        f = self._form_or_fail()
        if f is None:
            return None, None, None
        return u, r, f

    def post_run_checkin(self, rid):
        u, r, f = self._run_member(rid)
        if not u:
            return
        mine = {d["id"] for d in A.dogs_for_user(u["id"])}
        picked = []
        for x in f.getlist("dogs"):
            if x.isdigit() and int(x) in mine and int(x) not in picked:
                picked.append(int(x))
        if not picked:
            return self.redirect(run_path(r) + "?m=nodogs#here")
        if not A.LIMITER.allow(f"checkin:{u['id']}", C.CHECKINS_PER_HOUR, 3600):
            return self.redirect(run_path(r) + "?m=slow#here")
        C.check_in(u["id"], rid, picked, anon=f.get("anon") == "1")
        print(f"checkins: user {u['id']} at {rid} with {len(picked)} dog(s)", flush=True)
        return self.redirect(run_path(r) + "?m=here#here")

    def post_run_leave(self, rid):
        u, r, f = self._run_member(rid)
        if not u:
            return
        C.leave(u["id"])
        return self.redirect(run_path(r) + "?m=left#here")

    def post_run_follow(self, rid):
        u, r, f = self._run_member(rid)
        if not u:
            return
        on = f.get("on") == "1"
        C.follow(u["id"], rid, on)
        return self.redirect(run_path(r) + "?m=" + ("followed" if on else "unfollowed"))

    # ------------------------------------------------------------ announcements
    def post_run_announce(self, rid):
        u, r, f = self._run_member(rid)
        if not u:
            return
        org = C.park_role(u["id"], rid)
        if not org:
            return self.msg_page("Only the park's verified account can post here", "", code=403, icon="i-shield")
        kind = f.get("kind") if f.get("kind") in dict(C.ANN_KINDS) else "other"
        title, body = W.clean(f.get("title"), 90), W.clean(f.get("body"), 1500, multiline=True)
        until = end_of_day(f.get("until").strip()) if f.get("until").strip() else None
        if not title:
            return self.msg_page("Add a title", '<p class="sub">Announcements need a short title.</p>'
                                 f'<p><a class="btn" href="{e(run_path(r))}">Back to the run</a></p>', code=422)
        if not A.LIMITER.allow(f"announce:{u['id']}", 10, 86400):
            return self.msg_page("That's a lot of announcements for one day", '<p class="sub">Please try again tomorrow.</p>', code=429)
        aid = C.add_announcement(u["id"], rid, org, kind, title, body, until)
        print(f"announcements: {aid} posted at {rid}", flush=True)
        self.notify_followers(r, C.announcement(aid))
        return self.redirect(run_path(r) + "?m=posted")

    def notify_followers(self, r, a):
        base, n = self._base(), 0
        for uid in C.followers([r["id"]]):
            if not C.emails_on(uid, "follow"):
                continue
            m = C.user_row(uid)
            if not m:
                continue
            unsub = follow_unsub_url(base, uid)
            kind = dict(C.ANN_KINDS).get(a["kind"], "Notice")
            until = f"Until {fmt_day(a['ends_at'])}." if a["ends_at"] else ""
            subject, body, text = mailer.build_community(
                base, subject=f"{kind} at {r['name']}: {a['title']}", eyebrow="official park news", heading=a["title"], name=m["name"],
                paras=[f"{a['org_name'] or 'The park'} posted an official {kind.lower()} for {r['name']}." + (" " + until if until else "")],
                quote=a["body"], quote_by=a["org_name"], button="See the run page", url=base + run_path(r),
                why=f"You're getting this because you follow {r['name']} on BarksBuds.", unsub=unsub, unsub_label="Turn off park news emails")
            if mailer.send_async(m["email"], subject, body, text, unsub, "community-announce"):
                n += 1
        return n

    def post_run_ann_remove(self, rid, aid):
        u, r, f = self._run_member(rid)
        if not u:
            return
        a = C.announcement(aid)
        if not a or a["run_id"] != rid or not C.park_role(u["id"], rid):
            return self.msg_page("Not found", "", code=404)
        C.remove_announcement(aid)
        return self.redirect(run_path(r) + "?m=removed")

    def run_news(self, rid):
        r = self._run_or_404(rid)
        if not r:
            return
        anns = C.announcements(rid, current=False, limit=50)
        items = "".join(f'<article class="panel"><p class="small muted" style="margin:0 0 4px"><span class="offbadge">Official</span> '
                        f'{e(dict(C.ANN_KINDS).get(a["kind"], "Notice"))} · {e(fmt_day(a["created_at"]))}'
                        + (f' · until {e(fmt_day(a["ends_at"]))}' if a["ends_at"] else "") + f'</p><h2>{e(a["title"])}</h2>'
                        + (f'<p class="bio">{e(a["body"])}</p>' if a["body"] else "") + f'<p class="small muted" style="margin:0">From {e(a["org_name"])}</p></article>'
                        for a in anns) or '<div class="empty"><h2>No announcements yet</h2><p class="muted">Official park updates for this run will show up here.</p></div>'
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">official park news</span><h1>{e(r["name"])}</h1>
<p class="lead">Announcements from the park's verified account. <a href="/runs/{rid}/feed.xml">RSS feed</a> · <a href="{e(run_path(r))}">Back to the run</a></p></div></section>
<section class="section"><div class="wrap narrow">{items}</div></section>"""
        self.page(f"{r['name']} announcements", body, index=True, canonical=f"/runs/{rid}/news", active="runs",
                  desc=f"Official announcements for {r['name']}: closures, maintenance, rules and events.")

    def run_feed(self, rid):
        r = W.run_index().get(rid)
        if not r:
            return self._emit(404, b"Not found", "text/plain")
        base = self._base()
        x = lambda s: html.escape(s or "", quote=False)
        items = "".join(f"""<item><title>{x(dict(C.ANN_KINDS).get(a["kind"], "Notice") + ": " + a["title"])}</title><link>{x(base + f"/runs/{rid}/news")}</link>
<guid isPermaLink="false">barksbuds-announcement-{a["id"]}</guid><pubDate>{formatdate(a["created_at"], usegmt=True)}</pubDate>
<description>{x(a["body"] + (" (until " + fmt_day(a["ends_at"]) + ")" if a["ends_at"] else ""))}</description></item>"""
                        for a in C.announcements(rid, current=False, limit=30))
        doc = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{x(r["name"])} · BarksBuds park news</title>'
               f'<link>{x(base + run_path(r))}</link><description>Official announcements for {x(r["name"])}</description><language>en-us</language>{items}</channel></rss>\n')
        self._emit(200, doc.encode(), "application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=600"})

    # ------------------------------------------------------------ admin: verified park accounts
    def admin_parks(self, q, flash=""):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        runs = W.run_index()
        hid = f'<input type="hidden" name="key" value="{e(key)}">'
        rows = "".join(f'<tr><td>{e(x["name"] or "")}<br><small>{e(x["email"] or "deleted")}</small></td><td>{e(x["org"])}</td>'
                       f'<td>{e(runs.get(x["run_id"], {}).get("name", x["run_id"]))} <small>({e(x["run_id"])})</small></td>'
                       f'<td><form method="post" action="/admin/parks">{hid}<input type="hidden" name="action" value="revoke"><input type="hidden" name="id" value="{x["id"]}">'
                       f'<button type="submit">Revoke</button></form></td></tr>' for x in C.park_roles())
        anns = A.q("SELECT id, run_id, org_name, kind, title, created_at, removed FROM announcements ORDER BY id DESC LIMIT 100")
        arows = "".join(f'<tr><td>{a[0]}</td><td>{e(runs.get(a[1], {}).get("name", a[1]))}</td><td>{e(a[2])}</td><td>{e(a[3])}</td><td>{e(a[4])}</td>'
                        f'<td>{e(fmt_day(a[5]))}</td><td>{"removed" if a[6] else f"""<form method="post" action="/admin/parks">{hid}<input type="hidden" name="action" value="remove_announcement"><input type="hidden" name="id" value="{a[0]}"><button type="submit">Remove</button></form>"""}</td></tr>'
                        for a in anns)
        doc = (f'<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<title>Verified park accounts</title><body style="font:15px system-ui;padding:20px;max-width:1100px">'
               f'<h1>Verified park accounts</h1>{f"<p><b>{e(flash)}</b></p>" if flash else ""}'
               f'<p>A verified park account can post official announcements (closure, maintenance, rule, event, other) on the runs listed for it. '
               f'The member must have signed in to BarksBuds at least once.</p>'
               f'<form method="post" action="/admin/parks" style="display:grid;gap:8px;max-width:520px;padding:14px;border:1px solid #ccc;border-radius:10px">{hid}'
               f'<input type="hidden" name="action" value="grant"><label>Member email <input name="email" type="email" required style="width:100%"></label>'
               f'<label>Organization shown on posts <input name="org" required placeholder="e.g. Town of North Hempstead Parks" style="width:100%"></label>'
               f'<label>Run ids (comma separated, e.g. n-006, n-007) <input name="runs" required style="width:100%"></label>'
               f'<button type="submit">Grant role</button></form>'
               f'<h2>Accounts</h2>' + (f'<table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>Member</th><th>Org</th><th>Run</th><th></th></tr>{rows}</table>' if rows else "<p>None yet.</p>")
               + '<h2>Announcements</h2>' + (f'<table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>#</th><th>Run</th><th>Org</th><th>Type</th><th>Title</th><th>Posted</th><th></th></tr>{arows}</table>' if arows else "<p>None yet.</p>")
               + '</body>')
        return self._emit(200, doc, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    def post_admin_parks(self):
        f = self.read_form()
        key = (f.get("key") if f else "") or self.headers.get("X-Admin-Key", "")
        if f is None or not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        act, msg = f.get("action"), ""
        if act == "grant":
            email = f.get("email").strip().lower()
            r = A.one("SELECT id FROM users WHERE email=:e", e=email)
            runs = W.run_index()
            ids = [x.strip() for x in f.get("runs").split(",") if x.strip()]
            bad = [x for x in ids if x not in runs]
            org = W.clean(f.get("org"), 80)
            if not r:
                msg = "No member with that email. They need to sign in to BarksBuds once first."
            elif bad or not ids:
                msg = "Unknown run id(s): " + ", ".join(bad or ["(none)"])
            elif not org:
                msg = "Add the organization name."
            else:
                for rid in ids:
                    C.grant_role(r[0], rid, org)
                msg = f"Granted for {len(ids)} run(s)."
                print(f"parks: admin granted park role to user {r[0]} for {len(ids)} run(s)", flush=True)
        elif act == "revoke" and f.get("id").isdigit():
            C.revoke_role(int(f.get("id"))); msg = "Revoked."
        elif act == "remove_announcement" and f.get("id").isdigit():
            C.remove_announcement(int(f.get("id"))); msg = "Announcement removed."
        return self.admin_parks({"key": [key]}, flash=msg)


def W_and(xs):
    return mailer.and_list(xs)
