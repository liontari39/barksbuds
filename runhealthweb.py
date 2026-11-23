"""Run-page panel and routes for owner-reported health heads-ups."""
import html, re
from datetime import datetime
from zoneinfo import ZoneInfo

import accounts as A
import community as C
import runhealth as RH
import runpageweb as RP
import webapp as W

e = html.escape
ET = ZoneInfo("America/New_York")
RUN_RE = RP.RUN_RE


def _when(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%b %-d")


def pin_html(p, u, csrf, report_flash=""):
    badge = "Unverified owner report" if p.get("source") != "vet" else "Vet-sourced alert"
    note = f'<p class="health-note">{e(p["note"])}</p>' if p.get("note") else ""
    report = ""
    if u:
        reasons = "".join(f'<option>{e(r)}</option>' for r in RH.REPORT_REASONS)
        report = (f'<details class="health-rep"><summary>Report this</summary>'
                  f'<form method="post" action="/runs/{e(p["run_id"])}/health/{p["id"]}/report" class="stack">'
                  f'{csrf}<label>Reason <select name="reason" required>{reasons}</select></label>'
                  f'<label>Details (optional) <textarea name="details" rows="2" maxlength="400"></textarea></label>'
                  f'<button class="btn btn-ghost btn-sm" type="submit">Send report</button></form></details>')
    return (f'<li class="health-pin"><p class="health-kind"><b>{e(p["label"])}</b>'
            f' <span class="badge health-unv">{e(badge)}</span></p>'
            f'{note}<p class="small muted">Posted {_when(p["created_at"])} · expires {_when(p["expires_at"])}. '
            f'{e(RH.DISCLAIMER)}</p>{report}{report_flash}</li>')


def health_html(h, r, u, q=None):
    """Panel on the run page. Never names the reporter or any dog."""
    rid = r["id"]
    pins = RH.live_pins(rid)
    q = q or {}
    items = []
    for p in pins:
        p = dict(p, run_id=rid)
        flash = ""
        if q.get("m", [""])[0] == "health_reported" and str(q.get("pin", [""])[0]) == str(p["id"]):
            flash = '<p class="flash ok">Thanks. We\'ll review this report.</p>'
        items.append(pin_html(p, u, h.csrf_field() if u else "", flash))
    listed = (f'<ul class="health-list">{"".join(items)}</ul>' if items
              else '<p class="muted">No live health heads-ups at this run.</p>')
    form = ""
    if u:
        kinds = "".join(f'<option value="{e(k)}">{e(lab)}</option>' for k, lab in RH.HEALTH_KINDS)
        form = (f'<form method="post" action="/runs/{rid}/health" class="health-form stack">'
                f'{h.csrf_field()}<p class="small muted">Members can post a short heads-up. Don\'t name dogs or people, '
                f'and don\'t try to diagnose. Reports expire after 10 days and can be reviewed if someone flags them.</p>'
                f'<div class="row2"><label>What was noticed <select name="kind" required>{kinds}</select></label></div>'
                f'<label>Optional details (don\'t name dogs or people) '
                f'<input type="text" name="note" maxlength="200" autocomplete="off"></label>'
                f'<p class="small muted">{e(RH.DISCLAIMER)}</p>'
                f'<button class="btn btn-sm" type="submit">Post a heads-up</button></form>')
    else:
        form = (f'<p class="small muted"><a href="{e(h.signin_href(RP.run_path(r) + "#health"))}">Sign in</a> '
                f'to post a health heads-up.</p>')
    return (f'<div class="panel health-panel" id="health"><h2>Health heads-up</h2>'
            f'<p class="small muted" style="margin:0 0 10px">{e(RH.DISCLAIMER)}</p>'
            f'{listed}{form}</div>')


def review_rows_html(key):
    """Table body rows for the admin review queue."""
    rows = []
    for r in RH.list_reports():
        hid = (f'<input type="hidden" name="key" value="{e(key)}"><input type="hidden" name="kind" value="health">'
               f'<input type="hidden" name="id" value="{r["id"]}">')
        acts = []
        if r["status"] == "open":
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="action" value="dismiss"><button class="linkbtn" type="submit">Dismiss</button></form>')
        else:
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="action" value="reopen"><button class="linkbtn" type="submit">Reopen</button></form>')
        if r.get("pin_id"):
            hide_lab = "Show pin" if r["hidden"] else "Hide pin"
            hide_act = "unhide_health" if r["hidden"] else "hide_health"
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="pin" value="{r["pin_id"]}">'
                        f'<input type="hidden" name="action" value="{hide_act}">'
                        f'<button class="linkbtn" type="submit">{hide_lab}</button></form>')
        if r.get("poster_user_id"):
            sus = A.is_suspended(r["poster_user_id"])
            acts.append(f'<form method="post" action="/admin/review" style="display:inline">{hid}'
                        f'<input type="hidden" name="user" value="{r["poster_user_id"]}">'
                        f'<input type="hidden" name="action" value="{"unsuspend" if sus else "suspend"}">'
                        f'<button class="linkbtn" type="submit">{"Unsuspend" if sus else "Suspend"} user</button></form>')
        when = datetime.fromtimestamp(r["created_at"], ET).strftime("%Y-%m-%d %H:%M ET")
        run = (W.run_index().get(r["run_id"]) or {}).get("name") or r["run_id"]
        what = f'<a href="/runs/{e(r["run_id"])}#health">{e(r["label"])} at {e(run)}</a>'
        if r["hidden"]:
            what += " <b>(hidden)</b>"
        rows.append(f'<tr><td>{r["id"]}</td><td>{when}</td><td>{what}</td>'
                    f'<td>{e(r["reporter_name"] or "deleted")}</td>'
                    f'<td>{e(r["reason"])}</td><td style="white-space:pre-line">{e((r["details"] or "")[:200])}</td>'
                    f'<td>{e(r["status"])}</td><td>{" · ".join(acts)}</td></tr>')
    return "".join(rows)


def handle_review_action(f):
    """Handle health-kind admin actions. Returns True if consumed."""
    if f.get("kind") != "health":
        return False
    act, rid = f.get("action"), f.get("id")
    if act in ("resolve", "dismiss", "reopen") and rid and rid.isdigit():
        RH.set_report_status(int(rid), "open" if act == "reopen" else "resolved")
        return True
    if act in ("hide_health", "unhide_health") and (f.get("pin") or "").isdigit():
        RH.set_hidden(int(f.get("pin")), act == "hide_health")
        if act == "hide_health" and rid and rid.isdigit():
            RH.set_report_status(int(rid), "resolved")
        return True
    return False


class RunHealthRoutes:
    def health_get(self, path, q):
        return False

    def health_post(self, path, q):
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/health", path)
        if m:
            self._app_reset()
            self.post_health(m.group(1))
            return True
        m = re.fullmatch(r"/runs/" + RUN_RE + r"/health/(\d+)/report", path)
        if m:
            self._app_reset()
            self.post_health_report(m.group(1), int(m.group(2)))
            return True
        return False

    def post_health(self, rid):
        u = self.user()
        r = self._run_or_404(rid)
        if not r:
            return True
        dest = RP.run_path(r)
        if not u:
            return self.redirect(self.signin_href(dest + "#health"))
        f = self.read_form()
        if f is None:
            return self.redirect(dest + "#health")
        if A.is_suspended(u["id"]):
            return self.redirect(dest + "?m=health_bad#health")
        result = RH.add_pin(u["id"], rid, f.get("kind"), f.get("note") or "")
        msg = {"ok": "health", "already": "health_already", "limit": "health_slow", "bad": "health_bad"}[result]
        return self.redirect(dest + "?m=" + msg + "#health")

    def post_health_report(self, rid, pid):
        u = self.user()
        r = self._run_or_404(rid)
        p = RH.pin(pid)
        if not r:
            return True
        if not p or p["run_id"] != rid:
            return self._emit(404, b"Not found", "text/plain")
        dest = RP.run_path(r)
        if not u:
            return self.redirect(self.signin_href(dest + "#health"))
        f = self.read_form()
        if f is None:
            return self.redirect(dest + "#health")
        if not A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            return self.redirect(dest + "#health")
        out = RH.add_report(pid, u["id"], f.get("reason"), f.get("details") or "")
        if not out:
            return self._emit(404, b"Not found", "text/plain")
        return self.redirect(dest + "?m=health_reported&pin=" + str(pid) + "#health")
