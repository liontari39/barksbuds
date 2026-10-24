"""BarksBuds "Suggest a run": member form (new run, edit, wrong-pin report), status pages and the admin queue.

Routes:
  GET/POST /runs/suggest                    form (sign-in required); ?lat=&lng= prefill a pin, ?edit=<run id>[&pin=1] edits
  GET      /runs/suggest/s/<id>             the suggester's own status page
  GET      /runs/photo/<id>.jpg             photo of an approved member-added run
  GET/POST /admin/runs?key=KEY              moderation queue: approve (pin precision, credit) / reject (reason required)
  GET      /admin/runs/photo/<id>.jpg?key=  any suggestion photo, for review
Safety: CSRF on the member form, DAILY_LIMIT suggestions per member per day (+ an IP limit), everything escaped on output,
photos re-encoded (resized, EXIF/GPS stripped), a ~150 m duplicate check, out-of-area flagging, US-only pins.
New suggestions email RUN_SUGGEST_EMAIL (default: the single address on the meetup/pack email allowlist), and only if
that address passes the allowlist gate in mailer.send_async.
"""
import html, json, os, re
from datetime import datetime
from urllib.parse import quote

import accounts as A
import mailer
import runsugg as R
import webapp as W
from webapp import clean

e = html.escape
NOTIFY_TO = (os.environ.get("RUN_SUGGEST_EMAIL", "").strip()
             or (next(iter(mailer.RUNS_ALLOW)) if len(mailer.RUNS_ALLOW) == 1 else ""))
URL_RE = re.compile(r"^https?://[^\s<>\"']{3,300}$", re.I)
SUGG_TO_RUN = {"town": "town_or_neighborhood"}
EDIT_FIELDS = ("name", "park", "address", "town", "lat", "lng", "fenced", "small_dog_area", "water", "surface", "hours", "notes", "source_url")
LABELS = {"name": "Name", "park": "Park", "address": "Address", "town": "Town / neighborhood", "county": "Area", "state": "State",
          "lat": "Latitude", "lng": "Longitude", "fenced": "Fenced", "small_dog_area": "Small-dog area", "water": "Water",
          "surface": "Surface", "hours": "Hours", "notes": "Notes", "source_url": "Source link"}


def when_et(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%b %-d, %-I:%M %p ET")
    except Exception:
        return ""


def fnum(s, lo, hi):
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    return round(v, 6) if lo <= v <= hi and v == v else None


def run_val(r, k):
    """A run's value for a suggestion field name (blank when unknown)."""
    v = r.get(SUGG_TO_RUN.get(k, k))
    return "" if v is None else v


def notify(base, s, who):
    """Optional heads-up to Mike for each new suggestion (through the allowlist gate). Never includes the admin key."""
    if not NOTIFY_TO:
        return False
    d = s["data"]
    if s["kind"] == "new":
        subject = f"New dog run suggestion: {d.get('name') or 'unnamed'}"
        what = f"{who} suggested a new run: {d.get('name')}" + (f" ({d.get('park')})" if d.get("park") else "")
    else:
        subject = f"Dog run edit suggestion: {d.get('_run_name') or s['run_id']}"
        what = f"{who} suggested an edit to {d.get('_run_name') or s['run_id']}: {R.EDIT_LABEL.get(s['reason'], s['reason'])}"
    where = ", ".join(x for x in (d.get("address"), d.get("town"), R.AREA_LABEL.get(d.get("county"), ""), d.get("state")) if x)
    flags = []
    if not s["in_coverage"]:
        flags.append("Outside NYC / Long Island / Westchester")
    if s["dup_of"]:
        flags.append("Possible duplicate: " + s["dup_of"])
    lines = [what, where, ("Pin: %s, %s" % (d["lat"], d["lng"])) if isinstance(d.get("lat"), float) else "No pin dropped",
             *flags, "", f"Review it at {base}/admin/runs (add ?key= with your admin key)."]
    text = "\n".join(x for x in lines if x is not None)
    body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622"><h2 style="margin:0 0 8px">' + e(subject) + "</h2>"
            + "".join(f"<p style=\"margin:0 0 6px\">{e(x)}</p>" for x in lines if x) + "</div>")
    return mailer.send_async(NOTIFY_TO, subject, body, text, None, "runs-suggestion")


CSS = """<style>
.sgmap{height:340px;border:3px solid var(--black);border-radius:18px;overflow:hidden;box-shadow:5px 5px 0 var(--gold);background:#EEF3E4;margin:6px 0 8px}
.sgtools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:.9rem}
.sgtools .ll{color:var(--muted);font-variant-numeric:tabular-nums}
.sgwarn{background:#FFF3D1;border:2px solid var(--gold-d);border-radius:14px;padding:10px 14px;margin:8px 0;font-size:.93rem}
.sgwarn ul{margin:6px 0 0;padding-left:18px}
.sgcur{background:#fff;border:2px dashed var(--line);border-radius:14px;padding:12px 14px;margin-bottom:18px;font-size:.93rem}
.sgcur b{color:var(--black)}
.sglist{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.sglist li{background:#fff;border:2px solid var(--line);border-radius:14px;padding:10px 14px;font-size:.93rem}
.st{display:inline-block;border-radius:999px;padding:2px 10px;font-weight:800;font-size:.8rem}
.st-pending{background:var(--gold-l)}.st-approved{background:#E3F3E6;color:#1F7A3A}.st-rejected{background:#FBEDEC;color:#9E1714}
.pinx svg{width:100%;height:100%;filter:drop-shadow(0 3px 3px rgba(0,0,0,.35))}
.aq{background:#fff;border:2px solid var(--black);border-radius:18px;padding:16px;margin-bottom:18px;box-shadow:4px 4px 0 var(--line)}
.aq h3{margin:0 0 4px}.aq .flags{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.aq .flag{background:#FBEDEC;color:#9E1714;border-radius:999px;padding:3px 10px;font-weight:800;font-size:.8rem}
.aq .flag.ok{background:#E3F3E6;color:#1F7A3A}
.aq img{border-radius:12px;border:2px solid var(--black);max-width:220px;height:auto}
.aq .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px 14px;margin:10px 0}
.aq label{display:block;font-weight:800;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
.aq input[type=text],.aq select{width:100%;font:inherit;font-size:.93rem;padding:7px 9px;border:2px solid #D9CBAA;border-radius:10px;background:#FFFDF8}
.aq .acts{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;border-top:1px solid var(--line);padding-top:12px;margin-top:8px}
.aq .diff td{font-size:.9rem}
@media (max-width:640px){.sgmap{height:280px}}
</style>"""


class RunRoutes:
    def runs_get(self, path, q):
        if path in ("/runs/suggest", "/runs/suggest/"):
            self._app_reset(); self.suggest_page(q); return True
        m = re.fullmatch(r"/runs/suggest/s/(\d+)", path)
        if m:
            self._app_reset(); self.suggest_status(int(m.group(1))); return True
        m = re.fullmatch(r"/runs/photo/(\d+)\.jpg", path)
        if m:
            self._app_reset(); self.run_photo(int(m.group(1))); return True
        if path == "/admin/runs":
            self._app_reset(); self.admin_runs(q); return True
        m = re.fullmatch(r"/admin/runs/photo/(\d+)(|-t)\.(?:jpg|webp)", path)
        if m:
            self._app_reset(); self.admin_run_photo(int(m.group(1)), bool(m.group(2)), q); return True
        return False

    def runs_post(self, path, q):
        if path == "/runs/suggest":
            self._app_reset(); self.post_suggest(); return True
        if path == "/admin/runs":
            self._app_reset(); self.post_admin_runs(); return True
        return False

    # ------------------------------------------------------------ member form
    def _target(self, rid):
        return W.run_index().get(rid) if rid else None

    def suggest_page(self, q, vals=None, errs=None, dups=None, code=200):
        u = self.user()
        if not u:
            return self.need_login()
        errs = errs or {}
        rid = (vals or {}).get("edit") if vals is not None else q.get("edit", [""])[0]
        run = self._target(rid)
        if rid and not run:
            return self.msg_page("We couldn't find that run", '<p class="sub">It may have been removed from the map.</p>'
                                 '<p><a class="btn" href="/runs">Back to the map</a></p>', code=404, icon="i-pin")
        if vals is None:
            if run:
                vals = {k: run_val(run, k) for k in EDIT_FIELDS}
                vals["fenced"] = vals["fenced"] if vals["fenced"] in ("yes", "no") else "unsure"
                for k in ("small_dog_area", "water"):
                    vals[k] = vals[k] if vals[k] in ("yes", "no") else "unsure"
                vals["county"] = run.get("county") if run.get("county") in R.COVERAGE else "other"
                vals.update(edit=rid, reason="pin" if q.get("pin", [""])[0] else "", notes="", credit="1")
            else:
                lat, lng = fnum(q.get("lat", [""])[0], -90, 90), fnum(q.get("lng", [""])[0], -180, 180)
                vals = dict(lat=lat if lat is not None and lng is not None else "", lng=lng if lat is not None and lng is not None else "",
                            county=u.get("area") or "", town="", state="NY", fenced="unsure", small_dog_area="unsure",
                            water="unsure", credit="1")
        v = lambda k: e(str(vals.get(k) if vals.get(k) is not None else ""))
        err = lambda k: f'<span class="err" id="{k}-err">{e(errs[k])}</span>' if k in errs else ""
        inv = lambda k: ' aria-invalid="true"' if k in errs else ""
        top = '<div class="formerr" role="alert">Please fix the highlighted fields.</div>' if errs else ""
        area_opts = "".join(f'<option value="{e(k)}"{" selected" if vals.get("county") == k else ""}>{e(t)}</option>' for k, t in R.AREAS)
        state_opts = "".join(f'<option{" selected" if (vals.get("state") or "NY") == s else ""}>{s}</option>' for s in R.US_STATES)

        def ynu(name, legend):
            ticks = "".join(f'<label class="tick"><input type="radio" name="{name}" value="{k}"{" checked" if (vals.get(name) or "unsure") == k else ""}><span>{t}</span></label>'
                            for k, t in R.YNU)
            return f'<fieldset class="field"><legend class="lab">{legend}</legend><div class="checks-grid">{ticks}</div></fieldset>'
        surf = "".join(f'<option value="{e(k)}"{" selected" if (vals.get("surface") or "") == k else ""}>{e(t)}</option>' for k, t in R.SURFACES)
        if vals.get("surface") and vals["surface"] not in dict(R.SURFACES):
            surf += f'<option value="{v("surface")}" selected>{v("surface")}</option>'
        dup_html = ""
        if dups:
            items = "".join(f"<li><b>{e(n)}</b> · about {m} m away</li>" for n, _i, m in dups[:5])
            dup_html = (f'<div class="sgwarn" role="alert"><b>Is it one of these?</b> We already have a run very close to your pin:<ul>{items}</ul>'
                        '<label class="tick" style="margin-top:8px;display:inline-block"><input type="checkbox" name="dup_ok" value="1"><span>'
                        "It's a different run, send my suggestion</span></label>"
                        + ('<p class="small" style="margin:6px 0 0">Please pick your photo again; browsers clear it on a resubmit.</p>' if vals.get("_had_photo") else "")
                        + "</div>")
        reason_html, cur_html = "", ""
        if run:
            reasons = "".join(f'<label class="tick"><input type="radio" name="reason" value="{k}"{" checked" if vals.get("reason") == k else ""}><span>{e(t)}</span></label>'
                              for k, t in R.EDIT_REASONS)
            reason_html = (f'<fieldset class="field"><legend class="lab">What needs fixing?</legend><div class="checks-grid" style="flex-direction:column;align-items:flex-start">{reasons}</div>{err("reason")}</fieldset>')
            where = " · ".join(x for x in (run.get("park"), run.get("town_or_neighborhood"), run.get("county")) if x)
            cur_html = f'<div class="sgcur">Suggesting a change to <b>{e(run["name"])}</b><br>{e(where)}</div>'
        title = "Suggest an edit" if run else "Suggest a run"
        name_req = "" if run else " required"
        mine = R.for_user(u["id"], 5)
        mine_html = ""
        if mine:
            lis = "".join(self._mine_li(s) for s in mine)
            mine_html = f'<h2 style="margin-top:34px;font-size:1.3rem">Your recent suggestions</h2><ul class="sglist">{lis}</ul>'
        start = [vals["lat"], vals["lng"]] if isinstance(vals.get("lat"), float) and isinstance(vals.get("lng"), float) else None
        cfg = json.dumps({"start": start, "box": R.COVER_BOX, "dup": R.DUP_METERS, "self": rid or ""}).replace("<", "\\u003c")
        body = f"""{CSS}<section class="phead"><div class="wrap narrow"><span class="eyebrow">help the map</span><h1>{title}</h1>
<p class="lead">{"Spotted something off? Tell us and we'll check it before the map changes." if run else "Know a dog run we're missing? Tell us where it is and what it's like. We check every suggestion before it goes on the map."}</p></div></section>
<section class="section"><div class="wrap narrow"><form id="sgform" class="panel mform" method="post" action="/runs/suggest" enctype="multipart/form-data" novalidate>{self.csrf_field()}{top}{dup_html}{cur_html}
<input type="hidden" name="edit" value="{e(rid or "")}">{reason_html}
<div class="field"><label for="name">Run name</label><input type="text" id="name" name="name" maxlength="{R.MAX_NAME}"{name_req} value="{v("name")}" placeholder="Shelter Rock Dog Run"{inv("name")}>{err("name")}</div>
<div class="field"><label for="park">Park <span class="opt">(optional)</span></label><input type="text" id="park" name="park" maxlength="{R.MAX_SHORT}" value="{v("park")}" placeholder="Christopher Morley Park"></div>
<div class="row2"><div class="field"><label for="county">Area</label><select id="county" name="county"{inv("county")}><option value="">Choose an area</option>{area_opts}</select>{err("county")}</div>
<div class="field"><label for="town">Town or neighborhood</label><input type="text" id="town" name="town" maxlength="60" value="{v("town")}" placeholder="Roslyn"{inv("town")}>{err("town")}</div></div>
<div class="field" id="staterow"{"" if vals.get("county") == "other" else " hidden"}><label for="state">State</label><select id="state" name="state">{state_opts}</select>
<span class="help">We're starting in NYC, Long Island and Westchester, but we'll happily keep runs from anywhere in the US on file.</span></div>
<div class="field"><label for="address">Address or directions <span class="opt">(address or a map pin)</span></label><input type="text" id="address" name="address" maxlength="200" value="{v("address")}" placeholder="Searingtown Rd, North Hills, NY 11576"{inv("where")}></div>
<div class="field"><span class="lab">Drop a pin <span class="opt">(tap the map where the run's entrance is; drag to adjust)</span></span>
<div id="sgmap" class="sgmap" role="application" aria-label="Map: tap to drop a pin on the dog run"></div>
<div class="sgtools"><button class="btn btn-ghost btn-sm" type="button" id="sgme">Use my location</button><button class="linkbtn" type="button" id="sgclear">Clear pin</button><span class="ll" id="sgll" aria-live="polite"></span></div>
<input type="hidden" name="lat" id="lat" value="{v("lat")}"><input type="hidden" name="lng" id="lng" value="{v("lng")}">
<div id="sgnear" class="sgwarn" hidden></div><div id="sgcov" class="sgwarn" hidden>That pin is outside NYC, Long Island and Westchester. That's OK: we'll flag it and keep it on file for when we grow.</div>
{err("where")}{err("lat")}</div>
{ynu("fenced", "Fenced?")}{ynu("small_dog_area", "Separate small-dog area?")}{ynu("water", "Water for dogs?")}
<div class="row2"><div class="field"><label for="surface">Surface</label><select id="surface" name="surface">{surf}</select></div>
<div class="field"><label for="hours">Hours <span class="opt">(optional)</span></label><input type="text" id="hours" name="hours" maxlength="{R.MAX_SHORT}" value="{v("hours")}" placeholder="Dawn to dusk"></div></div>
<div class="field"><label for="notes">{"What should we change?" if run else "Anything else?"} <span class="opt">{"" if run else "(optional)"}</span></label><textarea id="notes" name="notes" rows="4" maxlength="{R.MAX_NOTES}" placeholder="{"The entrance is on the north side by the tennis courts." if run else "Residents only? Parking? Shade? How busy it gets?"}"{inv("notes")}>{v("notes")}</textarea>{err("notes")}</div>
<div class="field"><label for="photo">Photo <span class="opt">(optional)</span></label><input type="file" id="photo" name="photo" accept="image/jpeg,image/png,image/webp,image/gif,image/heic"{inv("photo")}>
<span class="help">A photo of the run helps us confirm it. We resize it and remove location data.</span>{err("photo")}</div>
<div class="field"><label for="source_url">Source link <span class="opt">(optional)</span></label><input type="url" id="source_url" name="source_url" maxlength="300" value="{v("source_url")}" placeholder="https://www.townofnorthhempstead.org/..."{inv("source_url")}>
<span class="help">A town, county or parks page that mentions the run.</span>{err("source_url")}</div>
<label class="tick" style="display:inline-block;margin-bottom:18px"><input type="checkbox" name="credit" value="1"{" checked" if vals.get("credit") else ""}><span>Credit me by my display name if it's added</span></label>
<div class="formfoot"><button class="btn" type="submit">Send suggestion</button><a class="small" href="/runs">Cancel</a></div>
<p class="small muted" style="margin:14px 0 0">Up to {R.DAILY_LIMIT} suggestions a day. Please only suggest public dog runs and dog-friendly spaces.</p></form>
{mine_html}</div></section>"""
        scripts = ('<link rel="stylesheet" href="/vendor/leaflet/leaflet.css"><script src="/vendor/leaflet/leaflet.js"></script>'
                   f'<script>window.SG={cfg};</script><script src="/suggest.js?v=1"></script>')
        return self.page(title, body, code=code, active="runs", scripts=scripts)

    def _mine_li(self, s):
        d = s["data"]
        name = d.get("name") or d.get("_run_name") or "A run"
        label = ("New run: " if s["kind"] == "new" else "Edit: ") + name
        st = {"pending": "Waiting for review", "approved": "Added to the map" if s["kind"] == "new" else "Approved",
              "rejected": "Not added"}[s["status"]]
        extra = f' · {e(s["reject_reason"])}' if s["status"] == "rejected" and s["reject_reason"] else ""
        return (f'<li><a href="/runs/suggest/s/{s["id"]}"><b>{e(label)}</b></a> <span class="st st-{s["status"]}">{st}</span>'
                f'<br><span class="small muted">{e(when_et(s["created_at"]))}{extra}</span></li>')

    def parse_suggest(self, f, run):
        errs, vals = {}, {k: f.get(k) for k in EDIT_FIELDS + ("county", "state", "reason", "credit", "edit")}
        out = {}
        out["name"] = clean(f.get("name"), R.MAX_NAME)
        out["park"] = clean(f.get("park"), R.MAX_SHORT)
        out["address"] = clean(f.get("address"), 200)
        out["town"] = clean(f.get("town"), 60)
        out["county"] = f.get("county") if f.get("county") in R.AREA_LABEL else ""
        out["state"] = (f.get("state") if f.get("state") in R.US_STATES else "") if out["county"] == "other" else "NY"
        for k in ("fenced", "small_dog_area", "water"):
            out[k] = f.get(k) if f.get(k) in ("yes", "no", "unsure") else "unsure"
        out["surface"] = f.get("surface") if f.get("surface") in dict(R.SURFACES) else clean(f.get("surface"), 40)
        out["hours"] = clean(f.get("hours"), R.MAX_SHORT)
        out["notes"] = clean(f.get("notes"), R.MAX_NOTES, multiline=True)
        src = clean(f.get("source_url"), 300)
        if src and not URL_RE.match(src):
            errs["source_url"] = "Use a full web address starting with https://"
        out["source_url"] = src if URL_RE.match(src or "") else ""
        lat_s, lng_s = (f.get("lat") or "").strip(), (f.get("lng") or "").strip()
        lat, lng = fnum(lat_s, -90, 90), fnum(lng_s, -180, 180)
        if (lat_s or lng_s) and (lat is None or lng is None):
            errs["lat"] = "That pin didn't come through. Tap the map again."
        elif lat is not None and not R.in_us(lat, lng):
            errs["lat"] = "That pin isn't in the US. We can only add US dog runs."
            lat = lng = None
        out["lat"], out["lng"] = (lat, lng) if lat is not None and lng is not None else (None, None)
        vals["lat"], vals["lng"] = (out["lat"] if out["lat"] is not None else ""), (out["lng"] if out["lng"] is not None else "")
        if run:
            reason = f.get("reason")
            if reason not in R.EDIT_LABEL:
                errs["reason"] = "Pick what needs fixing."
            out["_reason"] = reason
            changed = [k for k in EDIT_FIELDS if k != "notes" and str(out.get(k) if out.get(k) is not None else "") != str(self._cur(run, k))]
            if reason == "pin" and out["lat"] is None:
                errs["lat"] = "Drop the pin where the run really is."
            elif reason == "pin" and out["lat"] is not None and isinstance(run.get("lat"), (int, float)) \
                    and R.meters(out["lat"], out["lng"], run["lat"], run["lng"]) < 5:
                errs["lat"] = "Drag the pin to where the run really is."
            if not changed and len(out["notes"]) < 5 and "lat" not in errs:
                errs["notes"] = "Tell us what's wrong, or change the details above."
            out["_changed"] = changed
            if not out["name"]:
                out["name"] = run["name"]
        else:
            if len(out["name"]) < 3:
                errs["name"] = "What's the run called? (at least 3 characters)"
            if not out["county"]:
                errs["county"] = "Pick an area."
            elif out["county"] == "other" and not out["state"]:
                errs["county"] = "Pick the state."
            if not out["town"]:
                errs["town"] = "Add the town or neighborhood."
            if len(out["address"]) < 5 and out["lat"] is None and "lat" not in errs:
                errs["where"] = "Add an address, or drop a pin on the map."
        return out, vals, errs

    def _cur(self, run, k):
        v = run_val(run, k)
        if k in ("fenced", "small_dog_area", "water"):
            return v if v in ("yes", "no") else "unsure"
        return v

    def post_suggest(self):
        u = self.user()
        if not u:
            return self.need_login("/runs/suggest")
        f = self._form_or_fail(W.MAX_UPLOAD_REQUEST)
        if f is None:
            return
        rid = f.get("edit")
        run = self._target(rid)
        if rid and not run:
            return self.msg_page("We couldn't find that run", '<p class="sub">It may have been removed from the map.</p>', code=404, icon="i-pin")
        if R.recent_count(u["id"]) >= R.DAILY_LIMIT or not A.LIMITER.allow("runsugg-ip:" + self._client_ip(), 15, 86400):
            return self.msg_page("That's plenty for today", f'<p class="sub">You can send up to {R.DAILY_LIMIT} suggestions a day. '
                                 'Thank you for helping! Please come back tomorrow.</p><p><a class="btn" href="/runs">Back to the map</a></p>',
                                 code=429, icon="i-pin")
        out, vals, errs = self.parse_suggest(f, run)
        up = [x for x in f.files if x[0] == "photo"]
        processed = None
        if up and not errs:
            try:
                processed = A.process_image(up[0][2])
            except A.BadImage as ex:
                errs["photo"] = str(ex)
        vals["_had_photo"] = bool(up)
        if errs:
            return self.suggest_page({}, vals=vals, errs=errs, code=422)
        runs = W.RUNS()
        dups = []
        if out["lat"] is not None and (not run or out["_reason"] == "pin" or "lat" in out["_changed"]):
            dups = R.near(out["lat"], out["lng"], runs, exclude=rid or "")
        if not run:
            seen = {d[1] for d in dups}
            dups += [(r["name"], r["id"], 0) for r in R.same_name(out["name"], runs) if r["id"] not in seen
                     and (out["county"] == r.get("county"))]
        if dups and not run and not f.get("dup_ok"):   # new runs: "is it one of these?" before it reaches the queue
            return self.suggest_page({}, vals=vals, dups=dups)
        coverage = R.in_coverage(out["county"] if not run else (run.get("county") if run.get("county") in R.COVERAGE else "other"),
                                 out["lat"], out["lng"])
        data = {k: v for k, v in out.items() if not k.startswith("_")}
        data["credit"] = bool(f.get("credit"))
        reason = ""
        if run:
            data["_run_name"] = run["name"]
            data["_changed"] = out["_changed"]
            reason = out["_reason"]
        dup_of = "; ".join(f"{n} ({m} m)" if m else f"{n} (same name)" for n, _i, m in dups[:3])
        sid = R.create(u["id"], "edit" if run else "new", data, run_id=rid or "", reason=reason, coverage=coverage,
                       dup_of=dup_of, photo=processed, ip_hash=A.ip_hash(self._client_ip()))
        print(f"run suggestion {sid} ({'edit' if run else 'new'}) stored", flush=True)
        try:
            notify(self._base(), R.get(sid), u.get("display_name") or "A member")
        except Exception as ex:
            print("run suggestion email failed:", type(ex).__name__, flush=True)
        return self.redirect(f"/runs/suggest/s/{sid}?m=sent")

    def suggest_status(self, sid):
        u = self.user()
        if not u:
            return self.need_login()
        s = R.get(sid)
        if not s or s["user_id"] != u["id"]:
            return self.msg_page("Not found", '<p class="sub">We couldn\'t find that suggestion.</p>', code=404, icon="i-pin")
        d = s["data"]
        name = d.get("name") or d.get("_run_name") or "your run"
        if s["status"] == "pending":
            msg = (f"<p class=\"sub\">Thanks! We'll check <b>{e(name)}</b> and add it to the map once it's confirmed."
                   if s["kind"] == "new" else f"<p class=\"sub\">Thanks! We'll check your note about <b>{e(name)}</b> and fix the map.") + "</p>"
            if not s["in_coverage"]:
                msg += ('<p class="small">It\'s outside NYC, Long Island and Westchester, where we\'re starting, '
                        "so it may take a little longer. We'll keep it on file either way.</p>")
            title = "Suggestion sent"
        elif s["status"] == "approved":
            title = "It's on the map!" if s["kind"] == "new" else "Thanks, we fixed it"
            msg = f'<p class="sub"><b>{e(name)}</b> is live on the dog run map. Thank you for helping your neighbors find it.</p>'
        else:
            title = "Not added this time"
            msg = (f'<p class="sub">We looked at <b>{e(name)}</b> but didn\'t add it.</p>'
                   + (f'<p class="small">Reason: {e(s["reject_reason"])}</p>' if s["reject_reason"] else ""))
        link = (f'/runs?q={quote(name)}' if s["status"] == "approved" else "/runs")
        return self.msg_page(title, msg + f'<p><a class="btn" href="{e(link)}">Back to the map</a> '
                             '<a class="small" href="/runs/suggest" style="margin-left:10px">Suggest another</a></p>', icon="i-pin")

    def run_photo(self, sid):
        s = R.get(sid)
        img = R.photo(sid) if s and s["status"] == "approved" and s["kind"] == "new" else None
        if not img:
            return self._emit(404, b"Not found", "text/plain")
        return self._emit(200, img, "image/jpeg", {"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------------ admin queue
    def admin_run_photo(self, sid, thumb, q):
        if not self._admin_key(q=q):
            return self._emit(404, b"Not found", "text/plain")
        img = R.photo(sid, thumb)
        if not img:
            return self._emit(404, b"Not found", "text/plain")
        return self._emit(200, img, "image/webp" if thumb else "image/jpeg", {"Cache-Control": "no-store"})

    def _who(self, uid):
        r = A.one("SELECT display_name, email FROM users WHERE id=:u", u=uid)
        return (r[0] or "A member", r[1]) if r else ("(deleted member)", "")

    def admin_runs(self, q, flash=""):
        key = self._admin_key(q=q)
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        kq = quote(key)
        idx = W.run_index()
        cards = []
        for s in R.pending():
            d = s["data"]
            name, email = self._who(s["user_id"])
            flags = []
            flags.append('<span class="flag">Outside NYC / LI / Westchester</span>' if not s["in_coverage"] else '<span class="flag ok">In our area</span>')
            if s["dup_of"]:
                flags.append(f'<span class="flag">Possible duplicate: {e(s["dup_of"])}</span>')
            if not isinstance(d.get("lat"), (int, float)):
                flags.append('<span class="flag">No pin</span>')
            pin = (f'<a href="https://www.openstreetmap.org/?mlat={d["lat"]}&amp;mlon={d["lng"]}#map=18/{d["lat"]}/{d["lng"]}" target="_blank" rel="noopener">'
                   f'pin {d["lat"]}, {d["lng"]}</a>') if isinstance(d.get("lat"), (int, float)) else ""
            ph = (f'<a href="/admin/runs/photo/{s["id"]}.jpg?key={e(kq)}" target="_blank"><img src="/admin/runs/photo/{s["id"]}-t.webp?key={e(kq)}" alt="Suggested photo" loading="lazy"></a>'
                  if s["has_photo"] else "")
            hidden = f'<input type="hidden" name="key" value="{e(key)}"><input type="hidden" name="id" value="{s["id"]}">'
            credit = (f'<label style="text-transform:none;letter-spacing:0"><input type="checkbox" name="credit" value="1"{" checked" if d.get("credit") else ""}> '
                      f'Credit &ldquo;{e(name)}&rdquo; on the map</label>')
            prec = ('<div><label for="pp{0}">Pin precision</label><select id="pp{0}" name="pin_precision"><option value="member">member (as dropped)</option>'
                    '<option value="exact">exact (I confirmed it)</option></select></div>').format(s["id"])
            reject = (f'<form method="post" action="/admin/runs" style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">{hidden}'
                      f'<input type="hidden" name="action" value="reject"><div><label for="rj{s["id"]}">Reject: reason (required)</label>'
                      f'<input type="text" id="rj{s["id"]}" name="reason" required maxlength="200" placeholder="Already on the map as ..."></div>'
                      '<button class="btn btn-ghost btn-sm" type="submit">Reject</button></form>')
            if s["kind"] == "new":
                def inp(k, val=None):
                    val = d.get(k, "") if val is None else val
                    return f'<div><label for="f{s["id"]}{k}">{LABELS[k]}</label><input type="text" id="f{s["id"]}{k}" name="f_{k}" value="{e(str(val if val is not None else ""))}"></div>'
                county_sel = "".join(f'<option value="{e(k)}"{" selected" if d.get("county") == k else ""}>{e(t)}</option>' for k, t in R.AREAS)
                yn = lambda k: (f'<div><label>{LABELS[k]}</label><select name="f_{k}">' + "".join(
                    f'<option value="{o}"{" selected" if (d.get(k) or "unsure") == o else ""}>{o}</option>' for o in ("yes", "no", "unsure")) + "</select></div>")
                grid = (inp("name") + inp("park") + inp("address") + inp("town")
                        + f'<div><label>Area</label><select name="f_county">{county_sel}</select></div>' + inp("state")
                        + inp("lat") + inp("lng") + yn("fenced") + yn("small_dog_area") + yn("water") + inp("surface") + inp("hours")
                        + inp("source_url") + f'<div style="grid-column:1/-1"><label>Notes</label><input type="text" name="f_notes" value="{e(d.get("notes") or "")}"></div>')
                head = f'<h3>New run: {e(d.get("name") or "")}</h3>'
                approve = (f'<form method="post" action="/admin/runs">{hidden}<input type="hidden" name="action" value="approve">'
                           f'<div class="grid">{grid}</div><div class="acts">{prec}<div>{credit}</div><button class="btn btn-sm" type="submit">Approve &amp; add to map</button></div></form>')
            else:
                run = idx.get(s["run_id"])
                head = (f'<h3>Edit: {e(d.get("_run_name") or s["run_id"])} <span class="small muted">({e(s["run_id"])})</span></h3>'
                        f'<p style="margin:0"><b>{e(R.EDIT_LABEL.get(s["reason"], s["reason"]))}</b></p>')
                if not run:
                    approve = '<p class="small">That run is no longer on the map. Reject this one.</p>'
                else:
                    rows = []
                    for k in d.get("_changed") or []:
                        cur = self._cur(run, k)
                        rows.append(f'<tr><td><label style="text-transform:none"><input type="checkbox" name="apply" value="{k}" checked> {LABELS.get(k, k)}</label></td>'
                                    f'<td>{e(str(cur)) or "<i>blank</i>"}</td><td><input type="text" name="f_{k}" value="{e(str(d.get(k) if d.get(k) is not None else ""))}"></td></tr>')
                    diff = (f'<table class="t diff"><thead><tr><th>Apply</th><th>Now</th><th>Suggested</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
                            if rows else '<p class="small">No field changes; see the note.</p>')
                    hide = ('<label style="text-transform:none;letter-spacing:0"><input type="checkbox" name="hide" value="1"'
                            + (" checked" if s["reason"] == "closed" else "") + "> Remove this run from the map (closed)</label>")
                    approve = (f'<form method="post" action="/admin/runs">{hidden}<input type="hidden" name="action" value="approve">{diff}'
                               f'<div class="acts">{prec if "lat" in (d.get("_changed") or []) else ""}<div>{credit}<br>{hide}</div>'
                               '<button class="btn btn-sm" type="submit">Approve edit</button></div></form>')
            note = f'<p style="margin:6px 0"><b>Note:</b> {e(d.get("notes"))}</p>' if d.get("notes") and s["kind"] == "edit" else ""
            src = (f' · <a href="{e(d["source_url"])}" target="_blank" rel="noopener nofollow">source</a>' if d.get("source_url") else "")
            cards.append(f'<div class="aq" id="s{s["id"]}">{head}<p class="small muted" style="margin:2px 0">#{s["id"]} by <b>{e(name)}</b> ({e(email)}) · '
                         f'{e(when_et(s["created_at"]))}{" · " + pin if pin else ""}{src}</p><div class="flags">{"".join(flags)}</div>{note}{ph}{approve}'
                         f'<div style="margin-top:12px">{reject}</div></div>')
        hist = "".join(
            f'<tr><td>{s["id"]}</td><td>{e(s["kind"])}</td><td>{e(s["data"].get("name") or s["data"].get("_run_name") or "")}</td>'
            f'<td>{e(s["status"])}</td><td>{e(s["reject_reason"])}</td><td>{e(when_et(s["reviewed_at"] or s["created_at"]))}</td></tr>'
            for s in R.reviewed())
        live = "".join(
            f'<tr><td>{e(m["run_id"])}</td><td>{e(m["kind"])}</td><td>{e(m["data"].get("name") or idx.get(m["run_id"], {}).get("name", ""))}</td>'
            f'<td>{e(str(m["data"].get("pin_precision", "")))}{" · hidden" if m["data"].get("_hidden") else ""}</td>'
            f'<td><form method="post" action="/admin/runs" style="display:inline"><input type="hidden" name="key" value="{e(key)}">'
            f'<input type="hidden" name="run_id" value="{e(m["run_id"])}"><input type="hidden" name="action" value="remove">'
            f'<button class="linkbtn" type="submit" onclick="return confirm(\'Undo this on the live map?\')">{"Remove from map" if m["kind"] == "new" else "Revert edits"}</button></form></td></tr>'
            for m in R.member_runs())
        fl = f'<p class="flash" role="status">{e(flash)}</p>' if flash else ""
        body = f"""{CSS}<section class="phead"><div class="wrap"><span class="eyebrow">admin</span><h1>Run suggestions</h1>
<p class="lead">{len(cards)} waiting. Approved runs go live on <a href="/runs">the map</a> right away. Other admin pages: <a href="/admin/reports?key={e(kq)}">Reports</a> · <a href="/admin/packs?key={e(kq)}">Packs</a> · <a href="/admin/meetups?key={e(kq)}">Meetups</a></p></div></section>
<section class="section"><div class="wrap">{fl}{"".join(cards) or '<p class="notice">Nothing waiting for review.</p>'}
<h2 style="margin-top:30px">Member changes on the live map</h2><div style="overflow-x:auto"><table class="t"><thead><tr><th>Run</th><th>Kind</th><th>Name</th><th>Pin</th><th></th></tr></thead>
<tbody>{live or '<tr><td colspan="5">None yet.</td></tr>'}</tbody></table></div>
<h2 style="margin-top:30px">Recently reviewed</h2><div style="overflow-x:auto"><table class="t"><thead><tr><th>#</th><th>Kind</th><th>Run</th><th>Status</th><th>Reason</th><th>When</th></tr></thead>
<tbody>{hist or '<tr><td colspan="6">None yet.</td></tr>'}</tbody></table></div></div></section>"""
        return self.page("Admin: run suggestions", body)

    def post_admin_runs(self):
        f = self.read_form()
        key = self._admin_key(f) if f else None
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        act = f.get("action")
        back = "/admin/runs?key=" + quote(key)
        if act == "remove":
            rid = f.get("run_id")
            if rid:
                R.remove(rid); print("admin: run change removed", flush=True)
            return self.redirect(back)
        sid = f.get("id")
        s = R.get(int(sid)) if sid.isdigit() else None
        if not s or s["status"] != "pending":
            return self.admin_runs({"key": [key]}, flash="That suggestion was already reviewed.")
        if act == "reject":
            why = clean(f.get("reason"), 200)
            if len(why) < 3:
                return self.admin_runs({"key": [key]}, flash=f"Add a reason to reject #{s['id']}.")
            R.reject(s["id"], why); print(f"admin: run suggestion {s['id']} rejected", flush=True)
            return self.redirect(back)
        if act != "approve":
            return self._emit(400, b"Bad request", "text/plain")
        prec = f.get("pin_precision") if f.get("pin_precision") in ("member", "exact") else "member"
        credit = self._who(s["user_id"])[0] if f.get("credit") and s["user_id"] else ""
        if credit == "(deleted member)":
            credit = ""
        if s["kind"] == "new":
            v = {k: clean(f.get("f_" + k), R.MAX_NOTES if k == "notes" else 200) for k in
                 ("name", "park", "address", "town", "county", "state", "fenced", "small_dog_area", "water", "surface", "hours", "notes", "source_url")}
            if v["source_url"] and not URL_RE.match(v["source_url"]):
                v["source_url"] = ""
            lat, lng = fnum(f.get("f_lat"), -90, 90), fnum(f.get("f_lng"), -180, 180)
            v["lat"], v["lng"] = (lat, lng) if lat is not None and lng is not None else (None, None)
            if len(v["name"]) < 3:
                return self.admin_runs({"key": [key]}, flash=f"#{s['id']} needs a name.")
            R.approve_new(s, v, prec, credit)
        else:
            if not self._target(s["run_id"]):
                return self.admin_runs({"key": [key]}, flash="That run is no longer on the map; reject the suggestion instead.")
            changes = {}
            for k in f.getlist("apply"):
                if k not in EDIT_FIELDS:
                    continue
                raw = f.get("f_" + k)
                if k in ("lat", "lng"):
                    val = fnum(raw, -90, 90) if k == "lat" else fnum(raw, -180, 180)
                    if val is None:
                        continue
                elif k in ("fenced", "small_dog_area", "water"):
                    val = raw if raw in ("yes", "no") else ""
                elif k == "source_url":
                    val = raw if URL_RE.match(raw or "") else ""
                else:
                    val = clean(raw, R.MAX_NOTES if k == "notes" else 200)
                changes[SUGG_TO_RUN.get(k, k)] = val
            if "lat" in changes or "lng" in changes:
                if not ("lat" in changes and "lng" in changes):
                    return self.admin_runs({"key": [key]}, flash="Apply both latitude and longitude to move a pin.")
                changes["pin_precision"] = prec
                changes["coord_source"] = "Location confirmed by BarksBuds" if prec == "exact" else "Pin corrected by a BarksBuds member"
            R.approve_edit(s, changes, credit, hide=bool(f.get("hide")))
        print(f"admin: run suggestion {s['id']} approved ({prec})", flush=True)
        return self.redirect(back + "&m=approved")
