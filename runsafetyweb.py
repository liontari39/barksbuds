"""Web routes and HTML for live run safety: presence mix, quiet windows, planned arrivals,
gate stickers, favorites, and run-alert preferences."""
import html, re
from datetime import datetime, timedelta

import accounts as A
import community as C
import privacy as PV
import runsafety as RS
import webapp as W

e = html.escape
RUN_RE = r"(?:n|q|s|b)-\d{3}"


def _et_ts(date_s, time_s):
    import meetups as M
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_s or "") or not re.fullmatch(r"\d{2}:\d{2}", time_s or ""):
        return None
    return M.from_et(date_s, time_s)


def _window_label(starts, ends):
    a, b = datetime.fromtimestamp(starts, RS.ET), datetime.fromtimestamp(ends, RS.ET)
    same = a.date() == b.date()
    day = a.strftime("%a, %b %-d")
    def hm(d):
        return d.strftime("%-I:%M %p").lstrip()
    if same:
        return f"{day}, {hm(a)}–{hm(b)} ET"
    return f"{day} {hm(a)} – {b.strftime('%a, %b %-d')} {hm(b)} ET"


def mix_html(mix):
    if not mix or (not mix.get("n") and not mix.get("planned")):
        return ""
    sizes = ", ".join(f"{n} {k.lower() if k != 'XL' else 'XL'}" for k, n in mix["sizes"].items() if n)
    styles = ", ".join(f"{n} {k.lower()}" for k, n in mix["styles"].items() if n)
    bits = []
    if sizes:
        bits.append(f"Size mix: {e(sizes)}.")
    if styles:
        bits.append(f"Play style: {e(styles)}.")
    planned = mix.get("planned") or []
    if planned:
        parts = [f"{p['n']} around {p['label']}" for p in planned[:4]]
        bits.append("Planning to arrive: " + ", ".join(e(x) for x in parts) + ".")
    return "<p class=\"mixline\">" + " ".join(bits) + "</p>" if bits else ""


def presence_html(h, r, u):
    """Who's at the run (delayed, dogs only) plus quiet windows, pack suggestions, and plan form."""
    rid = r["id"]
    V = h.pv()
    dogs, planned, mix = RS.here_list(rid, V)
    n = mix["n"]
    firsts = A.first_photos([d["id"] for d in dogs]) if dogs else {}
    tiles = []
    for d in dogs:
        d = dict(d, photo=d.get("photo") or firsts.get(d["id"]))
        tiles.append(f'<li><a href="/dogs/{e(d["slug"])}">{A.tile_img(d, 72)}<span>{e(d["name"])}</span></a></li>')
    if n:
        now_line = (f'<p class="herenow"><span class="livedot" aria-hidden="true"></span>'
                    f'<b>{n} dog{"s" if n != 1 else ""} here now</b></p>')
    else:
        now_line = ('<p class="muted" style="margin:0 0 12px">Nobody has checked in yet — or they just arrived, '
                    'and names show after a short wait. Heading over? Let the regulars know.</p>')
    mix_block = mix_html(mix)
    disclaimer = ('<p class="small muted" style="margin:8px 0 0">This is a snapshot of dogs who have checked in. '
                  'It isn\'t a promise the run is a good fit for every dog. Please say hello and watch how they play.</p>')
    here = f'{now_line}{f"<ul class=mdogs>{chr(10).join(tiles)}</ul>" if tiles else ""}{mix_block}{disclaimer if n else ""}'

    windows = RS.quiet_windows(rid)
    q_items = "".join(f"<li>{e(_window_label(w['starts_at'], w['ends_at']))}</li>" for w in windows)
    q_list = f'<ul class="quiet-list">{q_items}</ul>' if q_items else '<p class="small muted" style="margin:0 0 10px">No quiet hours posted yet.</p>'
    today = datetime.now(RS.ET).date().isoformat()
    if u:
        q_form = (f'<form method="post" action="/runs/{rid}/quiet" class="quiet-form">{h.csrf_field()}'
                  f'<p class="small" style="margin:0 0 8px">Owners of shy or reactive dogs can post a quiet hour.</p>'
                  f'<div class="row3"><div class="field"><label for="qdate">Date</label>'
                  f'<input type="date" id="qdate" name="date" min="{today}" required></div>'
                  f'<div class="field"><label for="qstart">From (ET)</label>'
                  f'<input type="time" id="qstart" name="start" required></div>'
                  f'<div class="field"><label for="qend">Until (ET)</label>'
                  f'<input type="time" id="qend" name="end" required></div></div>'
                  f'<button class="btn btn-ghost btn-sm" type="submit">Post a quiet hour</button></form>')
    else:
        import runpageweb
        q_form = (f'<p class="small"><a href="{e(h.signin_href(runpageweb.run_path(r)))}">Sign in</a> '
                  f'to post a quiet hour for shy or reactive dogs.</p>')
    quiet = (f'<div class="panel" id="quiet"><h2>Quiet hours</h2>'
             f'<p class="small muted" style="margin:0 0 10px">A quieter window some owners hope to keep for shy or reactive dogs. '
             f'It is a request, not a rule, and not a promise of a calm run.</p>'
             f'{q_list}{q_form}</div>')

    groups = RS.suggest_packs(dogs)
    packs = ""
    if groups:
        items = []
        for g in groups:
            names = ", ".join(e(d["name"]) for d in g["dogs"])
            items.append(f'<li><b>{names}</b> — {e(g["why"])}.</li>')
        packs = (f'<div class="panel" id="smallpack"><h2>A possible small group</h2>'
                 f'<ul class="pack-sugg">{"".join(items)}</ul>'
                 f'<p class="small muted" style="margin:8px 0 0">Just a suggestion based on size and play style — '
                 f'not a promise these dogs will get along. Always check in with each other first.</p></div>')

    plan = plan_html(h, r, u)
    return here, quiet, packs, plan


def plan_html(h, r, u):
    rid = r["id"]
    dogs, planned, mix = RS.here_list(rid, h.pv())
    # planned arrivals already in mix_html; show upcoming line + form
    lines = []
    for p in planned:
        lines.append(f'<li>{p["n"]} dog{"s" if p["n"] != 1 else ""} around {e(RS.time_label(p["arrives_at"]))}</li>')
    upcoming = f'<ul class="plan-list">{"".join(lines)}</ul>' if lines else ""
    if not u:
        import runpageweb
        return (f'<div class="panel" id="plan"><h2>Planning to come?</h2>{upcoming}'
                f'<p class="small"><a href="{e(h.signin_href(runpageweb.run_path(r)))}">Sign in</a> to share a planned arrival time.</p></div>')
    own = A.dogs_for_user(u["id"])
    ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}" checked>'
                    f'<span>{e(d["name"])}</span></label>' for d in own)
    mine_rows = RS.my_planned(u["id"], rid)
    mine_html = ""
    if mine_rows:
        items = []
        for p in mine_rows:
            items.append(f'<li>{e(RS.time_label(p["arrives_at"]))} '
                         f'<form method="post" action="/runs/{rid}/plan/{p["id"]}/cancel" class="inline">{h.csrf_field()}'
                         f'<button class="linkbtn" type="submit">Cancel</button></form></li>')
        mine_html = f'<p class="small" style="margin:0 0 8px">Your plans</p><ul class="plan-list mine">{"".join(items)}</ul>'
    today = datetime.now(RS.ET).date().isoformat()
    if not own:
        form = '<p class="small">Add your dog to share a planned arrival. <a href="/me/dogs/new">Add a dog</a></p>'
    else:
        form = (f'<form method="post" action="/runs/{rid}/plan" class="plan-form">{h.csrf_field()}'
                f'<fieldset class="checks-grid" style="margin-bottom:10px"><legend>Who\'s coming?</legend>{ticks}</fieldset>'
                f'<div class="row2"><div class="field"><label for="pdate">Date</label>'
                f'<input type="date" id="pdate" name="date" min="{today}" required></div>'
                f'<div class="field"><label for="ptime">About this time (ET)</label>'
                f'<input type="time" id="ptime" name="time" required></div></div>'
                f'<button class="btn btn-ghost btn-sm" type="submit">I\'ll be there</button></form>')
    return (f'<div class="panel" id="plan"><h2>Planning to come?</h2>'
            f'<p class="small muted" style="margin:0 0 10px">Share a time you hope to arrive. Other members see a count and a time, not your name.</p>'
            f'{upcoming}{mine_html}{form}</div>')


class RunSafetyRoutes:
    def safety_get(self, path, q):
        if path == "/me/run-alerts":
            self._app_reset(); self.run_alerts_page(q); return True
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/sticker/?", path)
        if m:
            self._app_reset(); self.run_sticker(m.group(1)); return True
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/gate/?", path)
        if m:
            self._app_reset(); self.run_gate(m.group(1)); return True
        return False

    def safety_post(self, path, q):
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/quiet", path)
        if m:
            self._app_reset(); self.post_quiet(m.group(1)); return True
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/quiet/(\d+)/cancel", path)
        if m:
            self._app_reset(); self.post_quiet_cancel(m.group(1), int(m.group(2))); return True
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/plan", path)
        if m:
            self._app_reset(); self.post_plan(m.group(1)); return True
        m = re.fullmatch(r"/runs/(" + RUN_RE + r")/plan/(\d+)/cancel", path)
        if m:
            self._app_reset(); self.post_plan_cancel(m.group(1), int(m.group(2))); return True
        m = re.fullmatch(r"/dogs/([a-z0-9-]+)/favorite", path)
        if m:
            self._app_reset(); self.post_favorite(m.group(1)); return True
        if path == "/me/run-alerts":
            self._app_reset(); self.post_run_alerts(); return True
        return False

    def _run_or_404(self, rid):
        import runpageweb
        return runpageweb.RunPageRoutes._run_or_404(self, rid)

    def run_gate(self, rid):
        import runpageweb
        r = self._run_or_404(rid)
        if not r:
            return
        return self.redirect(runpageweb.run_path(r) + "?m=gate#here")

    def run_sticker(self, rid):
        import runpageweb, growth
        r = self._run_or_404(rid)
        if not r:
            return
        url = self._base() + f"/runs/{rid}/gate"
        qr = growth.qr_svg(url, scale=10)
        where = e(runpageweb.run_where(r))
        name = e(r["name"])
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Gate sticker · {name} | BarksBuds</title>
<style>
  :root {{ --ink:#141414; --red:#C8201E; --gold:#FBB321; --cream:#F6EFE4; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:Georgia, "Times New Roman", serif; color:var(--ink); background:var(--cream); }}
  .sheet {{ max-width:720px; margin:0 auto; padding:36px 28px 48px; text-align:center; }}
  .brand {{ display:flex; align-items:center; justify-content:center; gap:12px; margin:0 0 28px; font-family:system-ui,sans-serif; font-weight:800; letter-spacing:.04em; text-transform:uppercase; font-size:13px; }}
  .brand img {{ width:56px; height:56px; }}
  h1 {{ font-size:2.2rem; line-height:1.15; margin:0 0 8px; }}
  .where {{ margin:0 0 8px; font-size:1.15rem; }}
  .qr {{ display:inline-block; background:#fff; padding:14px; border:4px solid var(--ink); box-shadow:8px 8px 0 var(--red); }}
  .qr svg {{ width:260px; height:260px; display:block; }}
  .hint {{ margin:22px auto 0; max-width:28rem; font-size:1.05rem; line-height:1.4; }}
  .url {{ margin:10px 0 0; font-family:system-ui,sans-serif; font-size:14px; word-break:break-all; }}
  .tools {{ margin:28px 0 0; display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }}
  .tools a, .tools button {{ font-family:system-ui,sans-serif; font-weight:700; font-size:14px; background:var(--ink); color:#fff; border:0; padding:10px 16px; cursor:pointer; text-decoration:none; }}
  @media print {{
    body {{ background:#fff; }}
    .tools {{ display:none; }}
    .sheet {{ padding:0; }}
    .qr {{ box-shadow:none; }}
  }}
</style></head>
<body>
  <div class="sheet">
    <div class="brand"><img src="/img/icon-192.png?v=jack4" width="56" height="56" alt="">BarksBuds</div>
    <h1>{name}</h1>
    <p class="where">{where}</p>
    <div class="qr">{qr}</div>
    <p class="hint">Scan at the gate to check in on BarksBuds. NFC tags can use this same link. This page is just a print layout — nothing is posted for you.</p>
    <p class="url">{e(url)}</p>
    <div class="tools">
      <button type="button" onclick="window.print()">Print sticker</button>
      <a href="{e(runpageweb.run_path(r))}">Back to the run</a>
    </div>
  </div>
</body></html>"""
        self._emit(200, body, "text/html; charset=utf-8", headers={"Cache-Control": "public, max-age=300", "X-Robots-Tag": "noindex"})

    def post_quiet(self, rid):
        import runpageweb
        r = self._run_or_404(rid)
        if not r:
            return
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        if not A.LIMITER.allow(f"quiet:{u['id']}", 3, 86400):
            return self.redirect(runpageweb.run_path(r) + "?m=quiet_slow#quiet")
        start = _et_ts(f.get("date"), f.get("start"))
        end = _et_ts(f.get("date"), f.get("end"))
        if start and end and end <= start:
            # overnight window: end the next day
            end = _et_ts((datetime.fromtimestamp(start, RS.ET).date() + timedelta(days=1)).isoformat(), f.get("end"))
        if not RS.add_quiet_window(u["id"], rid, start or 0, end or 0):
            return self.redirect(runpageweb.run_path(r) + "?m=quiet_bad#quiet")
        return self.redirect(runpageweb.run_path(r) + "?m=quiet#quiet")

    def post_quiet_cancel(self, rid, wid):
        import runpageweb
        r = self._run_or_404(rid)
        if not r:
            return
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        RS.cancel_quiet_window(u["id"], wid)
        return self.redirect(runpageweb.run_path(r) + "?m=quiet_off#quiet")

    def post_plan(self, rid):
        import runpageweb, coowners as CO
        r = self._run_or_404(rid)
        if not r:
            return
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        if not A.LIMITER.allow(f"plan:{u['id']}", 8, 86400):
            return self.redirect(runpageweb.run_path(r) + "?m=plan_slow#plan")
        mine = {d["id"] for d in A.dogs_for_user(u["id"]) if CO.can_manage(d, u["id"])}
        picked = [int(x) for x in f.getlist("dogs") if str(x).isdigit() and int(x) in mine]
        at = _et_ts(f.get("date"), f.get("time"))
        anon = f.get("anon") == "1" or C.checkins_hidden(u["id"])
        if not picked or not RS.add_planned(u["id"], rid, picked, at or 0, anon=anon):
            return self.redirect(runpageweb.run_path(r) + "?m=plan_bad#plan")
        return self.redirect(runpageweb.run_path(r) + "?m=plan#plan")

    def post_plan_cancel(self, rid, pid):
        import runpageweb
        r = self._run_or_404(rid)
        if not r:
            return
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        RS.cancel_planned(u["id"], pid)
        return self.redirect(runpageweb.run_path(r) + "?m=plan_off#plan")

    def post_favorite(self, slug):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        d = A.dog_by_slug(slug)
        if not d or not PV.can_view(d, self.pv()):
            return self.msg_page("We couldn't find that dog", '<p class="sub">This profile may have been removed.</p>'
                                 '<p><a class="btn" href="/dogs">Meet the dogs</a></p>', code=404)
        import coowners as CO
        if CO.can_manage(d, u["id"]):
            return self.redirect(f"/dogs/{e(d['slug'])}")
        on = f.get("on") != "0"
        RS.favorite(u["id"], d["id"], on=on)
        return self.redirect(f"/dogs/{e(d['slug'])}?m={'faved' if on else 'unfaved'}")

    def run_alerts_page(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        flash = {"saved": "Alert settings saved.", "hours": "Please pick valid quiet hours."}.get(q.get("m", [""])[0], "")
        qs, qe = RS.quiet_hours(u["id"])
        def hhmm(m):
            return f"{int(m)//60:02d}:{int(m)%60:02d}"
        favs = RS.favorite_dogs(u["id"])
        fav_html = ""
        if favs:
            items = []
            for d in favs:
                items.append(f'<li><a href="/dogs/{e(d["slug"])}">{e(d["name"])}</a>'
                             f'<form method="post" action="/dogs/{e(d["slug"])}/favorite" class="inline">{self.csrf_field()}'
                             f'<input type="hidden" name="on" value="0"><button class="linkbtn" type="submit">Remove</button></form></li>')
            fav_html = f'<ul class="favdogs">{"".join(items)}</ul>'
        else:
            fav_html = '<p class="small muted">You haven\'t favorited any dogs yet. Open a dog\'s page and tap Favorite.</p>'
        prefs = {p["run_id"]: p for p in RS.user_alert_prefs(u["id"])}
        followed = C.followed_runs(u["id"])
        runs = W.run_index()
        ids = list(dict.fromkeys(list(followed) + list(prefs)))
        rows = []
        for rid in ids:
            r = runs.get(rid)
            if not r:
                continue
            p = prefs.get(rid) or dict(crowd_threshold=0, planned_on=0, meetup_on=0, favorite_on=0)
            rows.append(
                f'<tr><td><a href="/runs/{e(rid)}">{e(r["name"])}</a></td>'
                f'<td><input type="hidden" name="run" value="{e(rid)}">'
                f'<label class="sr-only" for="th-{e(rid)}">Dogs here now</label>'
                f'<select id="th-{e(rid)}" name="crowd_{e(rid)}">'
                + "".join(f'<option value="{n}"{" selected" if p["crowd_threshold"]==n else ""}>'
                          f'{"Off" if n==0 else str(n) + "+"}</option>' for n in range(0, 9))
                + f'</select></td>'
                f'<td><label class="switch small"><input type="checkbox" name="fav_{e(rid)}" value="1"'
                f'{" checked" if p["favorite_on"] else ""}><span class="sr-only">Favorite dogs</span></label></td>'
                f'<td><label class="switch small"><input type="checkbox" name="plan_{e(rid)}" value="1"'
                f'{" checked" if p["planned_on"] else ""}><span class="sr-only">Planned arrivals</span></label></td>'
                f'<td><label class="switch small"><input type="checkbox" name="meet_{e(rid)}" value="1"'
                f'{" checked" if p["meetup_on"] else ""}><span class="sr-only">Meetups</span></label></td></tr>'
            )
        add_opts = "".join(f'<option value="{e(rid)}">{e(r["name"])}</option>'
                           for rid, r in sorted(runs.items(), key=lambda kv: kv[1]["name"])
                           if rid not in ids)
        table = (f'<div style="overflow-x:auto"><table class="t alerts-t"><thead><tr>'
                 f'<th>Run</th><th>Dogs here now</th><th>Favorite dogs</th><th>Planned arrivals</th><th>Meetups</th>'
                 f'</tr></thead><tbody>{"".join(rows) or "<tr><td colspan=5 class=muted>Pick a run below to start.</td></tr>"}</tbody></table></div>'
                 f'<div class="field" style="margin-top:12px"><label for="add_run">Add a run</label>'
                 f'<select id="add_run" name="add_run"><option value="">Choose a run…</option>{add_opts}</select></div>')
        own = A.dogs_for_user(u["id"])
        own_ticks = "".join(
            f'<label class="switch small"><input type="checkbox" name="ok_{d["id"]}" value="1"'
            f'{" checked" if RS.checkin_alerts_ok(d["id"]) else ""}><span>Let friends get alerts when {e(d["name"])} checks in</span></label>'
            for d in own) or '<p class="small muted">Add a dog first.</p>'
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">alerts</span>
<h1>Run alerts</h1>
<p class="lead">Opt-in heads-ups when dogs are at a run you care about. Alerts never show an owner's name, and a dog only triggers a favorite alert if their human has turned that on.</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel" method="post" action="/me/run-alerts">{self.csrf_field()}
<h2>Quiet hours</h2>
<p class="small muted">We won't send run alerts during this window. Default is 9:00 PM–7:00 AM Eastern.</p>
<div class="row2"><div class="field"><label for="quiet_start">From</label>
<input type="time" id="quiet_start" name="quiet_start" value="{hhmm(qs)}"></div>
<div class="field"><label for="quiet_end">Until</label>
<input type="time" id="quiet_end" name="quiet_end" value="{hhmm(qe)}"></div></div>
<h2>Favorite dogs</h2>
{fav_html}
<h2>Your dogs</h2>
<p class="small muted">This starts off. Turn it on only if you're comfortable with members who favorite your dog getting a heads-up after they check in.</p>
<div class="prefgrid">{own_ticks}</div>
<h2>Runs you watch</h2>
<p class="small muted">Pick a threshold for “dogs here now,” and whether you want planned arrivals, meetups, or a favorite-dog check-in at that run. If you leave favorite-dog alerts off for every run, a favorite still notifies you at any run.</p>
{table}
<p class="small muted">These use your check-in notifications. You can turn those on in <a href="/me#push">account settings</a>. We cap how many of each kind you get in an hour.</p>
<button class="btn" type="submit">Save alerts</button>
</form></div></section>"""
        return self.page("Run alerts", body, active="me", flash=flash, index=False)

    def post_run_alerts(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        start, end = RS.parse_minutes(f.get("quiet_start")), RS.parse_minutes(f.get("quiet_end"))
        if start is None or end is None:
            return self.redirect("/me/run-alerts?m=hours")
        RS.set_quiet_hours(u["id"], start, end)
        for d in A.dogs_for_user(u["id"]):
            RS.set_checkin_alerts_ok(d["id"], f.get(f"ok_{d['id']}") == "1")
        runs = W.run_index()
        seen = set(f.getlist("run"))
        add = f.get("add_run") or ""
        if add in runs:
            seen.add(add)
        for rid in seen:
            if rid not in runs:
                continue
            RS.save_alert_pref(
                u["id"], rid,
                crowd_threshold=f.get(f"crowd_{rid}") or (3 if rid == add else 0),
                planned_on=f.get(f"plan_{rid}") == "1",
                meetup_on=f.get(f"meet_{rid}") == "1",
                favorite_on=f.get(f"fav_{rid}") == "1" or (rid == add and f.get(f"fav_{rid}") is None),
            )
        return self.redirect("/me/run-alerts?m=saved")
