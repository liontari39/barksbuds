"""Web routes for Puppy Pods: home/backyard playdates for puppies under 16 weeks."""
import html, re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import accounts as A
import puppypods as P
import webapp as W

e = html.escape
ET = ZoneInfo("America/New_York")


def pod_path(p):
    slug = A.slugify(p.get("title") or "puppy-pod", 40)
    return f"/puppy-pods/{p['id']}-{slug}"


def review_rows_html(key):
    rows = []
    for r in P.list_reports():
        hid = (f'<input type="hidden" name="key" value="{e(key)}"><input type="hidden" name="kind" value="pod">'
               f'<input type="hidden" name="id" value="{r["id"]}">')
        acts = []
        if r["status"] == "open":
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="action" value="dismiss"><button class="linkbtn" type="submit">Dismiss</button></form>')
        else:
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="action" value="reopen"><button class="linkbtn" type="submit">Reopen</button></form>')
        if r.get("pod_id"):
            hide_lab = "Show pod" if r["hidden"] else "Hide pod"
            hide_act = "unhide_pod" if r["hidden"] else "hide_pod"
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="pod" value="{r["pod_id"]}">'
                        f'<input type="hidden" name="action" value="{hide_act}">'
                        f'<button class="linkbtn" type="submit">{hide_lab}</button></form>')
        if r.get("host_user_id"):
            sus = A.is_suspended(r["host_user_id"])
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="user" value="{r["host_user_id"]}">'
                        f'<input type="hidden" name="action" value="{"unsuspend" if sus else "suspend"}">'
                        f'<button class="linkbtn" type="submit">{"Unsuspend" if sus else "Suspend"} user</button></form>')
        when = datetime.fromtimestamp(r["created_at"], ET).strftime("%Y-%m-%d %H:%M ET")
        what = f'<a href="/puppy-pods/{r["pod_id"]}">{e(r["title"] or "Puppy Pod")}</a>'
        if r["hidden"]:
            what += " <b>(hidden)</b>"
        if r.get("pod_status") == "cancelled":
            what += " <b>(cancelled)</b>"
        rows.append(f'<tr><td>{r["id"]}</td><td>{when}</td><td>{what}</td>'
                    f'<td>{e(r["reporter_name"] or "deleted")}</td>'
                    f'<td>{e(r["reason"])}</td><td style="white-space:pre-line">{e((r["details"] or "")[:200])}</td>'
                    f'<td>{e(r["status"])}</td><td>{" · ".join(acts)}</td></tr>')
    return "".join(rows)


def handle_review_action(f):
    if f.get("kind") != "pod":
        return False
    act, rid = f.get("action"), f.get("id")
    if act in ("resolve", "dismiss", "reopen") and rid and rid.isdigit():
        P.set_report_status(int(rid), "open" if act == "reopen" else "resolved")
        return True
    if act in ("hide_pod", "unhide_pod") and (f.get("pod") or "").isdigit():
        P.set_hidden(int(f.get("pod")), act == "hide_pod")
        if act == "hide_pod" and rid and rid.isdigit():
            P.set_report_status(int(rid), "resolved")
        return True
    return False


class PuppyPodRoutes:
    def pod_get(self, path, q):
        if path in ("/puppy-pods", "/puppy-pods/"):
            self._app_reset(); self.pods_page(q); return True
        if path == "/puppy-pods/new":
            self._app_reset(); self.pod_form(q); return True
        m = re.fullmatch(r"/puppy-pods/(\d+)(?:-[a-z0-9-]*)?/?", path)
        if m:
            self._app_reset(); self.pod_page(int(m.group(1)), q); return True
        return False

    def pod_post(self, path, q):
        if path == "/puppy-pods/new":
            self._app_reset(); self.post_pod_new(); return True
        m = re.fullmatch(r"/puppy-pods/(\d+)(?:-[a-z0-9-]*)?/(join|leave|report|check|cancel)", path)
        if m:
            self._app_reset()
            getattr(self, "post_pod_" + m.group(2))(int(m.group(1)))
            return True
        return False

    def _need(self, nxt):
        u = self.user()
        if not u:
            self.redirect(self.signin_href(nxt))
        return u

    def _pup_options(self, pups, name="dog"):
        opts = []
        for d in pups:
            w = P.age_weeks(d)
            lab = f'{d["name"]} · {w} week{"s" if w != 1 else ""} · {A.SIZE_SHORT.get(d.get("size") or "", d.get("size") or "size?")}'
            opts.append(f'<option value="{d["id"]}">{e(lab)}</option>')
        if not opts:
            return ('<p class="notice">To start or join a Puppy Pod, add a puppy under 16 weeks with a birthday '
                    f'on <a href="/me/dogs/new">your dogs</a> page.</p>')
        return f'<label>Which puppy <select name="{name}" required>{"".join(opts)}</select></label>'

    def _attest_fields(self):
        return (f'<p class="small muted">{e(P.VET_NOTE)}</p>'
                '<label class="switch"><input type="checkbox" name="dhpp_first" value="1" required>'
                "<span><b>This puppy has had at least the first DHPP vaccine</b><br>"
                '<span class="small muted">Owner-reported. We don\'t verify veterinary records.</span></span></label>'
                '<label class="switch"><input type="checkbox" name="vaccines_age_ok" value="1" required>'
                "<span><b>This puppy's vaccines are age-appropriate, as advised by our vet</b><br>"
                '<span class="small muted">You are attesting to this. Talk to your vet if you\'re unsure.</span></span></label>')

    def pods_page(self, q):
        u = self._need("/puppy-pods")
        if not u:
            return
        area = q.get("area", [""])[0]
        if area not in A.AREA_NAMES:
            area = ""
        pods = P.list_pods(u["id"], area=area or None)
        sugg = P.suggestions(u["id"])
        flash = {"created": "Your Puppy Pod is set up.", "joined": "You're in. The exact place is now visible.",
                 "left": "You've left this pod.", "cancelled": "This Puppy Pod has been cancelled.",
                 "reported": "Thanks. We'll review this report.",
                 "limit": "That's a lot of Puppy Pods today. Please try again tomorrow.",
                 }.get(q.get("m", [""])[0], "")
        cards = "".join(self._card(p, u) for p in pods) or '<p class="muted">No Puppy Pods yet in this area. Start one for a backyard playdate.</p>'
        sug_html = ""
        if sugg:
            sug_html = (f'<div class="panel" id="matches"><h2>Good fits for your puppy</h2>'
                        f'<ul class="pod-list">{"".join(self._card(p, u, li=True) for p in sugg)}</ul></div>')
        chips = [(f'/puppy-pods', "All", not area)] + [(f'/puppy-pods?area={quote(a)}', W.area_label(a), area == a) for a in A.AREA_NAMES]
        filt = "".join(f'<a class="chip{" on" if on else ""}" href="{e(h)}">{e(t)}</a>' for h, t, on in chips)
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">under 16 weeks</span><h1>Puppy Pods</h1>
<p class="lead">{e(P.BANNER)} Small groups of 3–5 puppies, matched by size, age and vaccine status, for home or backyard playdates.</p>
<div class="formfoot"><a class="btn" href="/puppy-pods/new">Start a Puppy Pod</a></div></div></section>
<section class="section"><div class="wrap">{sug_html}
<nav class="filters" aria-label="Filter by area">{filt}</nav>
<div class="panel"><h2>Open pods</h2><div class="pod-grid">{cards}</div></div></div></section>"""
        return self.page("Puppy Pods", body, active="community", flash=flash, index=False, canonical="/puppy-pods",
                         desc="Small, matched backyard playdates for puppies under 16 weeks. Never at a dog run.")

    def _card(self, p, u, li=False):
        spots = p["capacity"] - p.get("n", 0)
        loc = P.public_loc(p)
        ages = [m["weeks"] for m in p.get("members") or [] if m.get("weeks") is not None]
        age_s = ""
        if ages:
            lo, hi = min(ages), max(ages)
            age_s = f'{lo}–{hi} weeks' if lo != hi else f'{lo} week{"s" if lo != 1 else ""}'
        size = A.SIZE_SHORT.get(p.get("size_band") or "", "")
        meta = " · ".join(x for x in (loc, size, age_s, f'{spots} spot{"s" if spots != 1 else ""} left' if spots else "Full") if x)
        tag = 'li' if li else 'div'
        match = ""
        if p.get("match_dog"):
            match = f'<p class="small muted">A possible match for {e(p["match_dog"]["name"])}.</p>'
        return (f'<{tag} class="pod-card"><a href="{e(pod_path(p))}"><strong>{e(p["title"])}</strong>'
                f'<span class="pwhere">{e(meta)}</span>{match}</a></{tag}>')

    def pod_form(self, q):
        u = self._need("/puppy-pods/new")
        if not u:
            return
        pups = P.eligible_puppies(u["id"])
        err = {"area": "Please pick an area.", "town": "Please add a town or neighborhood.",
               "title": "Please give this pod a name.", "capacity": "Pods have 3 to 5 puppies.",
               "vaccine": "Please confirm the first DHPP and that vaccines are age-appropriate.",
               "puppy": "Pick a puppy under 16 weeks with a birthday on file.",
               "limit": "That's a lot of Puppy Pods today. Please try again tomorrow."}.get(q.get("err", [""])[0], "")
        caps = "".join(f'<option value="{n}"{" selected" if n==4 else ""}>{n} puppies</option>' for n in range(P.MIN_CAP, P.MAX_CAP + 1))
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">puppy pods</span><h1>Start a Puppy Pod</h1>
<p class="lead">{e(P.BANNER)}</p></div></section>
<section class="section"><div class="wrap"><form method="post" action="/puppy-pods/new" class="panel stack pod-form">
{self.csrf_field()}
<p class="notice">{e(P.BANNER)} We'll show the town or neighborhood to members browsing pods. The exact place stays hidden until someone joins.</p>
{"<p class='err'>"+e(err)+"</p>" if err else ""}
<label>Name <input type="text" name="title" required maxlength="80" placeholder="Saturday backyard play"></label>
{self._pup_options(pups)}
<div class="row2"><label>Area {self.area_select("", "area")}</label>
<label>Town or neighborhood <input type="text" name="town" required maxlength="80" placeholder="Manhasset"></label></div>
<label>Exact place (shown only after someone joins) <input type="text" name="place" maxlength="200" placeholder="Our backyard on a quiet street"></label>
<label>About this pod <textarea name="description" rows="3" maxlength="600" placeholder="A shady backyard, water out, and a short, calm play window."></textarea></label>
<label>How many puppies, including yours <select name="capacity">{caps}</select></label>
{self._attest_fields()}
<p class="formfoot"><button class="btn" type="submit">Start this pod</button>
<a class="btn btn-ghost" href="/puppy-pods">Cancel</a></p>
</form></div></section>"""
        return self.page("Start a Puppy Pod", body, index=False)

    def pod_page(self, pid, q):
        u = self._need(f"/puppy-pods/{pid}")
        if not u:
            return
        p = P.get(pid)
        if not p or p["hidden"] or (p["status"] != "active" and not (u and (P.member_of(pid, u["id"]) or p["host_user_id"] == u["id"]))):
            return self.msg_page("We couldn't find that Puppy Pod", '<p class="sub">It may have been cancelled or removed.</p>'
                                 '<p><a class="btn" href="/puppy-pods">See Puppy Pods</a></p>', code=404, icon="i-paw")
        if p and u and __import__("messages").either_blocked(u["id"], p["host_user_id"]):
            return self.msg_page("We couldn't find that Puppy Pod", '<p class="sub">It may have been cancelled or removed.</p>'
                                 '<p><a class="btn" href="/puppy-pods">See Puppy Pods</a></p>', code=404, icon="i-paw")
        members = P.member_rows(pid)
        mine = next((m for m in members if m["user_id"] == u["id"]), None)
        loc = P.public_loc(p)
        exact = (f'<p><b>Exact place:</b> {e(p["place"])}</p>' if mine and p.get("place") else
                 '<p class="muted">The exact place is shared after you join.</p>' if p.get("place") else "")
        puppies = []
        for m in members:
            w = f'{m["weeks"]} weeks' if m["weeks"] is not None else ""
            size = A.SIZE_SHORT.get((m["dog"] or {}).get("size") or "", "")
            vax = "First DHPP noted" if m["dhpp_first"] else ""
            bits = " · ".join(x for x in (w, size, vax, "Host" if m["role"] == "host" else "") if x)
            name = (m["dog"] or {}).get("name") or "A puppy"
            # Don't show owner last names; display_name may be a first name or nickname
            puppies.append(f'<li><b>{e(name)}</b>' + (f' <span class="muted">({e(m["display_name"].split()[0] if m["display_name"] else "")})</span>' if mine else "")
                           + (f'<br><span class="small muted">{e(bits)}</span>' if bits else "") + '</li>')
        flash = {"created": "Your Puppy Pod is set up.",
                 "joined": "You're in. The exact place is now visible.",
                 "left": "You've left this pod.", "cancelled": "This Puppy Pod has been cancelled.",
                 "reported": "Thanks. We'll review this report.",
                 "check": "Checklist saved.",
                 "vaccine": "Please confirm the first DHPP and that vaccines are age-appropriate.",
                 "puppy": "Pick a puppy under 16 weeks with a birthday on file.",
                 "full": "This pod is full.",
                 "size": "This pod is for a different size of puppy.",
                 "blocked": "You can't join this pod.",
                 "limit": "That's a lot of joins today. Please try again tomorrow.",
                 "already": "You're already in this pod."}.get(q.get("m", [""])[0], "")
        acts = []
        if p["status"] != "active":
            acts.append('<p class="notice">This Puppy Pod has been cancelled.</p>')
        elif mine and mine["role"] == "host":
            acts.append(f'<form method="post" action="{pod_path(p)}/cancel" class="inline">{self.csrf_field()}'
                        f'<button class="btn btn-ghost btn-sm" type="submit">Cancel this pod</button></form>')
        elif mine:
            acts.append(f'<form method="post" action="{pod_path(p)}/leave" class="inline">{self.csrf_field()}'
                        f'<button class="btn btn-ghost btn-sm" type="submit">Leave this pod</button></form>')
        else:
            pups = P.eligible_puppies(u["id"])
            acts.append(f'<form method="post" action="{pod_path(p)}/join" class="stack pod-join">{self.csrf_field()}'
                        f'<p class="small muted">{e(P.BANNER)}</p>{self._pup_options(pups)}{self._attest_fields()}'
                        f'<button class="btn" type="submit">Join this pod</button></form>')
        reasons = "".join(f'<option>{e(r)}</option>' for r in P.REPORT_REASONS)
        report = (f'<details class="health-rep"><summary>Report this pod</summary>'
                  f'<form method="post" action="{pod_path(p)}/report" class="stack">{self.csrf_field()}'
                  f'<label>Reason <select name="reason" required>{reasons}</select></label>'
                  f'<label>Details (optional) <textarea name="details" rows="2" maxlength="400"></textarea></label>'
                  f'<button class="btn btn-ghost btn-sm" type="submit">Send report</button></form></details>')
        checks = P.checks_of(pid, u["id"]) if mine else set()
        weeks_html = []
        for week, label, items in P.CHECKLIST:
            lis = []
            for it in items:
                if mine:
                    on = (week, it) in checks
                    lis.append(f'<li><form method="post" action="{pod_path(p)}/check" class="inline check-item">{self.csrf_field()}'
                               f'<input type="hidden" name="week" value="{week}"><input type="hidden" name="item" value="{e(it)}">'
                               f'<input type="hidden" name="on" value="{0 if on else 1}">'
                               f'<button class="check-btn{" on" if on else ""}" type="submit">{"✓" if on else "○"} {e(it)}</button></form></li>')
                else:
                    lis.append(f'<li>{e(it)}</li>')
            weeks_html.append(f'<div class="pod-week"><h3>{e(label)}</h3><ul>{"".join(lis)}</ul></div>')
        size = A.SIZE_SHORT.get(p.get("size_band") or "", "mixed sizes")
        cancelled = ' <span class="badge">Cancelled</span>' if p["status"] != "active" else ""
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">puppy pod</span>
<h1>{e(p["title"])}{cancelled}</h1>
<p class="lead">{e(loc)} · {e(size)} · {len(members)} of {p["capacity"]} puppies</p></div></section>
<section class="section"><div class="wrap"><div class="panel">
<p class="notice">{e(P.BANNER)}</p>
{f'<p>{e(p["description"])}</p>' if p.get("description") else ""}
{exact}
<h2>Puppies</h2>
<ul class="pod-pups">{"".join(puppies) or "<li>No puppies yet.</li>"}</ul>
{''.join(acts)}{report}
</div>
<div class="panel" id="checklist"><h2>Weekly socialization checklist</h2>
<p class="small muted">{e(P.VET_NOTE)}</p>
{"".join(weeks_html)}</div>
<p class="small"><a href="/puppy-pods">All Puppy Pods</a></p>
</div></section>"""
        return self.page(p["title"] + " · Puppy Pod", body, flash=flash, index=False)

    def post_pod_new(self):
        u = self._need("/puppy-pods/new")
        if not u:
            return
        f = self.read_form()
        if f is None:
            return self.redirect("/puppy-pods/new")
        pid, err = P.create_pod(u["id"], f.get("dog"), W.clean(f.get("title"), 80), f.get("area"),
                                W.clean(f.get("town"), 80), W.clean(f.get("place"), 200),
                                W.clean(f.get("description"), 600, multiline=True), f.get("capacity") or 4,
                                f.get("dhpp_first") == "1", f.get("vaccines_age_ok") == "1")
        if err:
            return self.redirect("/puppy-pods/new?err=" + err)
        return self.redirect(pod_path(P.get(pid)) + "?m=created")

    def post_pod_join(self, pid):
        u = self._need(f"/puppy-pods/{pid}")
        if not u:
            return
        p = P.get(pid)
        dest = pod_path(p) if p else "/puppy-pods"
        f = self.read_form()
        if f is None or not p:
            return self.redirect(dest)
        result = P.join(u["id"], pid, f.get("dog"), f.get("dhpp_first") == "1", f.get("vaccines_age_ok") == "1")
        msg = {"ok": "joined", "already": "already", "full": "full", "vaccine": "vaccine", "puppy": "puppy",
               "size": "size", "blocked": "blocked", "limit": "limit", "missing": "left"}.get(result, "puppy")
        return self.redirect(dest + "?m=" + msg)

    def post_pod_leave(self, pid):
        u = self._need(f"/puppy-pods/{pid}")
        if not u:
            return
        f = self.read_form()
        p = P.get(pid)
        dest = pod_path(p) if p else "/puppy-pods"
        if f is None:
            return self.redirect(dest)
        result = P.leave(u["id"], pid)
        if result == "cancelled":
            return self.redirect("/puppy-pods?m=cancelled")
        return self.redirect((pod_path(P.get(pid)) if P.get(pid) else "/puppy-pods") + "?m=left")

    def post_pod_cancel(self, pid):
        return self.post_pod_leave(pid)

    def post_pod_report(self, pid):
        u = self._need(f"/puppy-pods/{pid}")
        if not u:
            return
        p = P.get(pid)
        dest = pod_path(p) if p else "/puppy-pods"
        f = self.read_form()
        if f is None or not p:
            return self.redirect(dest)
        if not A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            return self.redirect(dest)
        out = P.add_report(pid, u["id"], f.get("reason"), f.get("details") or "")
        if not out:
            return self._emit(404, b"Not found", "text/plain")
        return self.redirect(dest + "?m=reported")

    def post_pod_check(self, pid):
        u = self._need(f"/puppy-pods/{pid}")
        if not u:
            return
        p = P.get(pid)
        dest = pod_path(p) if p else "/puppy-pods"
        f = self.read_form()
        if f is None or not p:
            return self.redirect(dest + "#checklist")
        week = f.get("week") or ""
        if week.isdigit():
            P.set_check(pid, u["id"], int(week), f.get("item") or "", f.get("on") != "0")
        return self.redirect(dest + "?m=check#checklist")
