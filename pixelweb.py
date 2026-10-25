"""Pixel Pals: hand-made pixel-art portraits of members' dogs (Oct 2026). The in-browser maker is retired; an owner sends
in 1 to 3 reference photos and the BarksBuds team makes the portrait (data in portraits.py).

  GET  /pixel-pals                       showcase of finished portraits (Lily and Maggie first) + how it works
  GET  /pixel-pals/start                 CTA: sign in, then the dog's portrait panel (/me/dogs/<id>/edit#portrait-panel)
  POST /me/dogs/<id>/portrait            owner: request a portrait (multipart: up to 3 in total of photo_id and "photo" uploads, note)
  GET  /admin/portraits                  admin page: all requests, with complete / reject / reset forms
  GET  /admin/portraits/pending          admin JSON: pending requests
  GET  /admin/portraits/<id>             admin JSON: one request
  GET  /admin/portraits/<id>/photo/<n>.jpg  admin: reference photo n (1..3) the owner sent in
  GET  /admin/portraits/<id>/photo.jpg   admin: alias for photo/1.jpg
  POST /admin/portraits/<id>/complete    admin: multipart "image" -> the dog's portrait (+ main picture), gated "ready" email
  POST /admin/portraits/<id>/reject      admin: "note" shown to the owner, frees the slot
  POST /admin/portraits/<id>/reset       admin: delete the request so the owner can ask again (images are kept)
  Admin routes take the admin key as the X-Admin-Key header, a "key" query parameter or a "key" form field; 404 otherwise.

  GET  /px/<id>.png, -1x.png, -og.png    old maker sprites (kind='pixel'): still served, no longer shown on the site
  GET  /me/dogs/<id>/pixel[-ai]          old maker URLs: 301 to the dog's edit page portrait panel
  POST /me/dogs/<id>/pixel[/...]         old maker endpoints: 404
"""
import html
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import accounts as A
import mailer
import portraits as P

e = html.escape
OG_CACHE = {}  # photo id -> png (sprites never change in place)
NOTICE_TO = os.environ.get("PORTRAIT_NOTICE_TO", "hello@barksbuds.app")
OLD_MAKER = re.compile(r"/me/dogs/(\d+)/pixel(-ai)?(/.*)?")
TIP = ("Add up to 3 photos. Best results: one full-body shot (standing, facing the camera) plus a clear close-up of the face, "
       "in good light. More angles help us get markings and ears just right.")
ERRS = {"photo": "Pick at least one photo or upload a new one.", "many": "Please send up to 3 photos in total.", "taken": "There's already a portrait request for this dog.",
        "big": "That photo is too big. Photos can be up to 12 MB.", "type": "That file isn't a JPEG, PNG, WebP or GIF photo.",
        "small": "That photo is too small. Please use a bigger one.", "read": "We couldn't read that photo. Please try another.",
        "limit": "Too many requests. Please try again later."}
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone.utc


def fmt_day(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%b %-d, %Y") if ts else ""


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def landing_html():
    """'Pixel Pals' section for the landing page (index.html {{PIXEL_PALS}}): the finished portraits of Lily and Maggie."""
    try:
        done = P.done_portraits(limit=2)
    except Exception as ex:  # never break the homepage
        print(f"pixel pals: landing section skipped ({ex.__class__.__name__})", flush=True)
        return ""
    if not done:
        return ""
    cards = "".join(f'<a class="pp-card" href="/dogs/{e(d["slug"])}"><img src="/p/{pid}.webp" alt="{e(d["name"])} as pixel art" '
                    f'width="240" height="240" loading="lazy"><b>{e(d["name"])}</b></a>' for d, pid in done)
    return f"""<style>
.pps{{padding:80px 0;background:var(--gold-l);background-image:linear-gradient(rgba(20,20,20,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(20,20,20,.05) 1px,transparent 1px);background-size:24px 24px}}
.pps .wrap{{display:grid;grid-template-columns:1fr 1.1fr;gap:48px;align-items:center}}
.pps h2{{font-size:clamp(2rem,4.2vw,2.85rem);line-height:1.08}}.pps p{{font-size:1.08rem;color:var(--ink)}}
.pps .cta-row{{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:center;margin-top:22px}}
.pps .textlink{{color:var(--black);font-weight:800}}
.pp-cards{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.pp-card{{display:grid;gap:8px;justify-items:center;background:#fff;border:3px solid var(--black);border-radius:22px;padding:14px;box-shadow:8px 8px 0 var(--black);text-decoration:none;color:var(--black);transition:transform .12s}}
.pp-card:hover{{transform:translateY(-2px)}}
.pp-card img{{width:100%;max-width:240px;aspect-ratio:1;height:auto;object-fit:cover;border-radius:14px}}
.pp-card b{{font:800 1.2rem/1 "Baloo 2",sans-serif}}
@media (max-width:860px){{.pps .wrap{{grid-template-columns:1fr;gap:28px}}.pps{{padding:56px 0}}}}
</style>
<section class="pps" id="pixel-pals" aria-labelledby="pp-title"><div class="wrap"><div>
<span class="eyebrow">pixel pals</span><h2 id="pp-title">Get your dog drawn as a pixel-art pal</h2>
<p>Send us a few photos of your pup and our team hand-makes a pixel-art portrait for their profile, usually within a day. One per dog, free for members.</p>
<div class="cta-row"><a class="btn" href="/pixel-pals/start">Sign up and request one for your dog</a><a class="textlink" href="/pixel-pals">See the pixel pals &rarr;</a></div></div>
<div class="pp-cards">{cards}</div></div></section>"""


class PixelRoutes:
    # ------------------------------------------------------------ dispatch
    def pixel_get(self, path, q):
        m = re.fullmatch(r"/px/(\d+)(|-1x|-og)\.png", path)
        if m:
            self._app_reset(); self.pixel_image(int(m.group(1)), m.group(2)); return True
        if path in ("/pixel-pals", "/pixel-pals/"):
            self._app_reset(); self.pixel_pals_page(); return True
        if path in ("/pixel-pals/start", "/pixel-pals/start/"):
            self._app_reset(); self.pixel_pals_start(); return True
        m = OLD_MAKER.fullmatch(path)
        if m:
            self._app_reset(); self.redirect(f"/me/dogs/{m.group(1)}/edit#portrait-panel", 301); return True
        if path == "/admin/portraits":
            self._app_reset(); self.admin_portraits_page(q); return True
        if path == "/admin/portraits/pending":
            self._app_reset(); self.admin_portraits_pending(q); return True
        m = re.fullmatch(r"/admin/portraits/(\d+)(/photo\.jpg|/photo/(\d{1,2})\.jpg)?", path)
        if m:   # n: None for the JSON, 1.. for a reference photo (photo.jpg = photo/1.jpg)
            n = int(m.group(3)) if m.group(3) else (1 if m.group(2) else None)
            self._app_reset(); self.admin_portrait_get(int(m.group(1)), n, q); return True
        return False

    def pixel_post(self, path, q):
        if OLD_MAKER.fullmatch(path):
            self._app_reset(); self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"}); return True
        m = re.fullmatch(r"/me/dogs/(\d+)/portrait", path)
        if m:
            self._app_reset(); self.post_portrait(int(m.group(1))); return True
        m = re.fullmatch(r"/admin/portraits/(\d+)/(complete|reject|reset)", path)
        if m:
            self._app_reset(); self.post_admin_portrait(int(m.group(1)), m.group(2), q); return True
        return False

    # ------------------------------------------------------------ public pages
    def pixel_pals_page(self):
        u = self.user()
        cta_href = "/pixel-pals/start"
        cta = "Request one for your dog" if u else "Sign up and request one for your dog"
        done = P.done_portraits()
        cards = "".join(f'<a class="pp-card" href="/dogs/{e(d["slug"])}"><img src="/p/{pid}.webp" alt="{e(d["name"])} as pixel art" '
                        f'width="300" height="300" loading="lazy"><b>{e(d["name"])}</b><small>{e(d["breed"] or "")}</small></a>' for d, pid in done)
        body = f"""<section class="phead pps-head"><div class="wrap"><span class="eyebrow">pixel pals</span>
<h1>Your dog, as a pixel-art pal</h1>
<p class="lead">Our team hand-makes a pixel-art portrait of your pup, usually within a day. It becomes their profile picture on BarksBuds, and you can switch back to a photo any time. One per dog, free for members.</p>
<p style="margin-top:18px"><a class="btn" href="{cta_href}">{cta}</a></p></div></section>
<section class="section" style="padding-top:28px"><div class="wrap">
{f'<div class="pp-cards pp-gallery">{cards}</div>' if cards else ''}
<div class="panel pp-how"><h2>How it works</h2><ol>
<li><b>Add your dog.</b> Sign up and give your pup a profile.</li>
<li><b>Send us up to 3 photos.</b> Pick from their photos or upload new ones. {e(TIP)}</li>
<li><b>We make the portrait.</b> Usually within a day, and it shows up as their profile picture.</li></ol>
<p><a class="btn btn-gold" href="{cta_href}">{cta}</a></p></div></div></section>"""
        return self.page("Pixel Pals: your dog as pixel art", body, index=True, active="pixel-pals", canonical=self._base() + "/pixel-pals",
                         desc="Get a hand-made pixel-art portrait of your dog for their BarksBuds profile. One per dog, free for members.",
                         og={"title": "Pixel Pals on BarksBuds", "image": self._base() + "/img/og-image.jpg", "w": 1200, "h": 630})

    def pixel_pals_start(self):
        u = self.user()
        if not u:
            return self.need_login("/pixel-pals/start")
        dogs = A.dogs_for_user(u["id"])
        if not dogs:
            return self.redirect("/me/dogs/new")
        if len(dogs) == 1:
            return self.redirect(f"/me/dogs/{dogs[0]['id']}/edit#portrait-panel")
        return self.redirect("/me")

    # ------------------------------------------------------------ owner side
    def portrait_panel(self, d, q=None, compact=False):
        """The "Get a pixel portrait" panel (edit page; compact=True on the owner's view of the profile page)."""
        q = q or {}
        did, nm = d["id"], e(d["name"])
        req = P.latest(did)
        hint = '<p class="hint">Our team hand-makes a pixel-art portrait of your pup, usually within a day.</p>'
        if req and req["status"] == "pending":
            return (f'<div class="panel portraitp" id="portrait-panel"><h2>Pixel portrait</h2>{hint}'
                    f'<p class="pstat"><span class="badge">In progress</span> Requested on {fmt_day(req["created_at"])}, in progress.</p></div>')
        if req and req["status"] == "done" and req["result_photo_id"] and A.one("SELECT id FROM photos WHERE id=:p", p=req["result_photo_id"]):
            pid = req["result_photo_id"]
            if d.get("avatar_photo_id") == pid:
                act = f'<p class="small muted" style="margin:8px 0 0">It\'s {nm}\'s profile picture. Pick "Make profile pic" on any photo to switch to a photo.</p>'
            else:
                act = (f'<form method="post" action="/me/dogs/{did}/photos/{pid}/avatar" style="margin-top:8px">{self.csrf_field()}'
                       f'<button class="btn btn-sm" type="submit">Make it the profile pic</button></form>')
            return (f'<div class="panel portraitp" id="portrait-panel"><h2>{nm}\'s pixel portrait</h2><div class="pprow">'
                    f'<img src="/p/{pid}.webp" alt="{nm} as pixel art" width="120" height="120" loading="lazy"><div>'
                    f'<p class="pstat" style="margin:0"><span class="badge">Done</span> Ready{(" on " + fmt_day(req["completed_at"])) if req["completed_at"] else ""}.</p>'
                    f'{act}</div></div></div>')
        rejected = ""
        if req and req["status"] == "rejected":
            rejected = (f'<p class="notice small">We couldn\'t make a portrait from the last photos'
                        + (f': {e(req["note"].rstrip(". "))}.' if req["note"] else ".") + ' Please send new ones.</p>')
        if compact:
            return (f'<div class="panel portraitp" id="portrait-panel"><h2>Get a pixel portrait</h2>{hint}{rejected}'
                    f'<p class="small muted">Only you can see this box.</p>'
                    f'<a class="btn btn-gold btn-sm" href="/me/dogs/{did}/edit#portrait-panel">Request a portrait</a></div>')
        photos = A.gallery(did)
        picks = "".join(f'<label class="ppick"><input type="checkbox" name="photo_id" value="{p["id"]}">'
                        f'<img src="/p/{p["id"]}.webp" alt="Photo {i + 1} of {nm}" loading="lazy"></label>' for i, p in enumerate(photos))
        pick_html = (f'<fieldset class="ppicks"><legend>Pick photos</legend>{picks}</fieldset>' if picks else "")
        err = e(ERRS.get((q.get("pre") or [""])[0], ""))
        return f"""<div class="panel portraitp" id="portrait-panel"><h2>Get a pixel portrait</h2>{hint}{rejected}
<form method="post" action="/me/dogs/{did}/portrait" enctype="multipart/form-data">{self.csrf_field()}
<p class="small pp-tip">{e(TIP)}</p>
{pick_html}<div class="field"><label for="pphoto">{"And/or upload new photos" if picks else "Upload photos"} <span class="opt">(JPEG, PNG or WebP, up to 12 MB each)</span></label>
<input id="pphoto" name="photo" type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif"></div>
<div class="field"><label for="pnote">Anything we should know? <span class="opt">(optional)</span></label>
<textarea id="pnote" name="note" maxlength="400" rows="2" placeholder="Coat colors, a favorite collar or bandana..."></textarea></div>
<span class="err" role="alert">{err}</span>
<button class="btn btn-sm" type="submit">Request a portrait</button>
<p class="small muted" style="margin:10px 0 0">One portrait per dog. Up to 3 photos in total. Photos you upload here are only seen by our team.</p></form></div>"""

    def post_portrait(self, dog_id):
        d = self.own_dog(dog_id)
        if d is None:
            return
        f = self._form_or_fail(60 * 1024 * 1024)
        if f is None:
            return
        back = f"/me/dogs/{d['id']}/edit"
        if not A.LIMITER.allow(f"portrait:{d['user_id']}", 10, 3600):
            return self.redirect(back + "?pre=limit#portrait-panel")
        raws = [data for name, fn, data in f.files if name == "photo" and data]
        pids = [x.strip() for x in f.getlist("photo_id") if x.strip()]
        if any(not x.isdigit() for x in pids):
            return self.redirect(back + "?pre=photo#portrait-panel")
        try:
            rid = P.create(d, d["user_id"], photo_ids=[int(x) for x in pids], raws=raws, owner_note=f.get("note").strip())
        except P.PortraitError as ex:
            return self.redirect(back + f"?pre={ex}#portrait-panel")
        except A.BadImage as ex:
            s = str(ex)
            err = "big" if "MB" in s else "small" if "small" in s else "type" if "isn't" in s else "read"
            return self.redirect(back + f"?pre={err}#portrait-panel")
        print(f"portraits: request {rid} for dog {d['id']}", flush=True)
        self._portrait_notice(rid, d)
        return self.redirect(back + "?m=portrait#portrait-panel")

    def _portrait_notice(self, rid, d):
        """Heads-up to the team inbox (not gated: it goes to our own address). Never includes the admin key."""
        try:
            owner = A.one("SELECT display_name FROM users WHERE id=:u", u=d["user_id"])
            req = P.get(rid)
            n = len(P.photo_ids(rid))
            subject = f"New pixel portrait request: {d['name']}"
            lines = [f"{owner[0] if owner and owner[0] else 'A member'} asked for a pixel portrait of {d['name']}"
                     + (f" ({d['breed']})" if d.get("breed") else "") + ".",
                     f"Request #{rid}, {n} reference photo{'' if n == 1 else 's'}" + (f". Note: {req['owner_note']}" if req and req["owner_note"] else ""),
                     f"Profile: {self._base()}/dogs/{d['slug']}",
                     f"Review it at {self._base()}/admin/portraits (add ?key= with your admin key), or run scripts/portraits.py list."]
            text = "\n".join(lines)
            body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622"><h2 style="margin:0 0 8px">' + e(subject) + "</h2>"
                    + "".join(f'<p style="margin:0 0 6px">{e(x)}</p>' for x in lines) + "</div>")
            mailer.send_async(NOTICE_TO, subject, body, text, None, "portrait-request")
        except Exception as ex:  # the request is saved either way
            print(f"portraits: notice email failed ({ex.__class__.__name__})", flush=True)

    def _portrait_member_email(self, req, kind):
        """'Your portrait is ready' / 'please send another photo' to the owner, through the allowlist gate in mailer."""
        try:
            d = A.dog_by_id(req["dog_id"])
            r = A.one("SELECT email, display_name FROM users WHERE id=:u", u=req["user_id"])
            if not d or not r or not r[0]:
                return False
            first = (r[1] or "").split(" ")[0] or "there"
            link = f"{self._base()}/dogs/{d['slug']}" if kind == "ready" else f"{self._base()}/me/dogs/{d['id']}/edit#portrait-panel"
            if kind == "ready":
                subject = f"{d['name']}'s pixel portrait is ready"
                paras = [f"Hi {first},", f"{d['name']}'s pixel-art portrait is done and on their BarksBuds profile.",
                         "You can switch the profile picture between the portrait and photos any time from the edit page."]
                btn = f"See {d['name']}'s profile"
            else:
                subject = f"About {d['name']}'s pixel portrait"
                paras = [f"Hi {first},", f"We couldn't make a pixel portrait from the photos you sent of {d['name']}"
                         + (f": {req['note'].rstrip('. ')}." if req.get("note") else "."), "Please send us new photos (up to 3: a full-body shot plus a close-up of the face works best) and we'll get started."]
                btn = "Send new photos"
            text = "\n\n".join(paras + [f"{btn}: {link}", "BarksBuds"])
            body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622">'
                    + "".join(f'<p style="margin:0 0 12px">{e(x)}</p>' for x in paras)
                    + f'<p><a href="{e(link)}" style="display:inline-block;background:#141414;color:#fff;padding:10px 18px;border-radius:999px;'
                      f'text-decoration:none;font-weight:700">{e(btn)}</a></p><p style="margin:16px 0 0">BarksBuds</p></div>')
            return mailer.send_async(r[0], subject, body, text, None, f"portrait-{'ready' if kind == 'ready' else 'rejected'}")
        except Exception as ex:
            print(f"portraits: member email failed ({ex.__class__.__name__})", flush=True)
            return False

    # ------------------------------------------------------------ admin
    def _admin_portrait_key(self, q, form=None):
        key = self.headers.get("X-Admin-Key", "") or q.get("key", [""])[0] or (form.get("key") if form is not None else "")
        return key if self._admin_key_ok(key) else None

    def _jsonr(self, code, obj):
        return self._emit(code, json.dumps(obj, indent=1).encode(), "application/json", {"Cache-Control": "no-store"})

    def _req_json(self, r):
        d = A.dog_by_id(r["dog_id"]) or {}
        o = A.one("SELECT email, display_name FROM users WHERE id=:u", u=r["user_id"])
        base = self._base()
        ids = P.photo_ids(r["id"])
        return dict(id=r["id"], status=r["status"], created_at=iso(r["created_at"]), completed_at=iso(r["completed_at"]),
                    note=r["note"], coat_notes=r["owner_note"],
                    dog=dict(id=d.get("id"), name=d.get("name"), slug=d.get("slug"), breed=d.get("breed"), age=A.age_text(d) if d else "",
                             sex=d.get("sex"), size=d.get("size"), bio=d.get("bio"), hidden=bool(d.get("hidden")),
                             profile_url=f"{base}/dogs/{d.get('slug')}" if d else None),
                    owner=dict(id=r["user_id"], name=o[1] if o else None, email=o[0] if o else None),
                    photo_id=r["photo_id"], photo_url=f"{base}/admin/portraits/{r['id']}/photo.jpg",
                    photo_ids=ids, photo_count=len(ids),
                    photo_urls=[f"{base}/admin/portraits/{r['id']}/photo/{n}.jpg" for n in range(1, len(ids) + 1)],
                    portrait_photo_id=r["result_photo_id"],
                    portrait_url=f"{base}/p/{r['result_photo_id']}.jpg" if r["result_photo_id"] else None)

    def admin_portraits_pending(self, q):
        if not self._admin_portrait_key(q):
            return self._emit(404, b"Not found", "text/plain")
        return self._jsonr(200, [self._req_json(r) for r in P.pending()])

    def admin_portrait_get(self, rid, n, q):
        if not self._admin_portrait_key(q):
            return self._emit(404, b"Not found", "text/plain")
        if n is not None:
            blob, req = P.request_photo(rid, n)
            if not blob:
                return self._emit(404, b"Not found", "text/plain")
            return self._emit(200, blob, "image/jpeg", {"Cache-Control": "no-store",
                                                         "Content-Disposition": f'inline; filename="portrait-request-{rid}-{n}.jpg"'})
        r = P.get(rid)
        return self._jsonr(200, self._req_json(r)) if r else self._jsonr(404, {"error": "not found"})

    def post_admin_portrait(self, rid, action, q):
        f = self.read_form(40 * 1024 * 1024)
        if f is None:
            return self._jsonr(413, {"error": "too big"})
        key = self._admin_portrait_key(q, f)
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        from_page = f.get("from") == "page"
        try:
            if action == "complete":
                raw = next((data for name, fn, data in f.files if name == "image" and data), None)
                if not raw:
                    return self._jsonr(400, {"error": "send the portrait as a multipart file field named 'image'"})
                req, made_main = P.complete(rid, raw)
                emailed = self._portrait_member_email(req, "ready")
                out = {"ok": True, "made_main": made_main, "emailed": bool(emailed), "request": self._req_json(req)}
            elif action == "reject":
                req = P.reject(rid, f.get("note"))
                emailed = self._portrait_member_email(req, "rejected")
                out = {"ok": True, "emailed": bool(emailed), "request": self._req_json(req)}
            else:
                req = P.reset(rid)
                out = {"ok": True, "reset": rid}
        except P.PortraitError as ex:
            return self._jsonr(404 if str(ex) == "state" and not P.get(rid) else 409, {"error": f"request {rid} isn't pending" if P.get(rid) else "not found"})
        except A.BadImage as ex:
            return self._jsonr(400, {"error": str(ex)})
        print(f"portraits: request {rid} {action}", flush=True)
        if from_page:
            return self.redirect("/admin/portraits?key=" + quote(key))
        return self._jsonr(200, out)

    def admin_portraits_page(self, q):
        key = self._admin_portrait_key(q)
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        k = e(key)
        rows = []
        for r in P.recent():
            j = self._req_json(r)
            d = j["dog"]
            when = datetime.fromtimestamp(r["created_at"], ET).strftime("%b %-d, %Y %-I:%M %p ET")
            hidden = f'<input type="hidden" name="key" value="{k}"><input type="hidden" name="from" value="page">'
            acts = ""
            if r["status"] == "pending":
                acts = (f'<form method="post" action="/admin/portraits/{r["id"]}/complete" enctype="multipart/form-data">{hidden}'
                        f'<input type="file" name="image" accept="image/*" required> <button class="btn btn-sm" type="submit">Complete</button></form>'
                        f'<form method="post" action="/admin/portraits/{r["id"]}/reject" style="margin-top:6px">{hidden}'
                        f'<input name="note" placeholder="Note for the owner, e.g. photo too dark" maxlength="400" required style="width:16em"> '
                        f'<button class="btn btn-ghost btn-sm" type="submit">Reject</button></form>')
            acts += (f'<form method="post" action="/admin/portraits/{r["id"]}/reset" style="margin-top:6px" '
                     f'onsubmit="return confirm(\'Reset this request? The owner can then ask again.\')">{hidden}'
                     f'<button class="linkbtn small" type="submit">Reset</button></form>')
            sent = " ".join(f'<a href="/admin/portraits/{r["id"]}/photo/{n}.jpg?key={quote(key)}"><img src="/admin/portraits/{r["id"]}/photo/{n}.jpg?key={quote(key)}" '
                            f'alt="Photo {n}" width="90" height="90" style="object-fit:cover;border-radius:8px"></a>'
                            for n in range(1, j["photo_count"] + 1))
            made = (f'<img src="/p/{r["result_photo_id"]}.webp" alt="" width="90" height="90" style="border-radius:8px">'
                    if r["result_photo_id"] else "")
            rows.append(f'<tr><td>#{r["id"]}<br><span class="small muted">{e(when)}</span></td>'
                        f'<td><a href="/dogs/{e(d["slug"] or "")}"><b>{e(d["name"] or "?")}</b></a><br><span class="small">{e(" · ".join(x for x in (d["breed"], d["age"], d["sex"]) if x))}</span>'
                        f'<br><span class="small muted">{e(j["owner"]["name"] or "")} &lt;{e(j["owner"]["email"] or "")}&gt;</span>'
                        f'{"<br><span class=small>Note: " + e(r["owner_note"]) + "</span>" if r["owner_note"] else ""}</td>'
                        f'<td><b>{e(r["status"])}</b>{"<br><span class=small>" + e(r["note"]) + "</span>" if r["note"] else ""}</td>'
                        f'<td>{sent}</td><td>{made}</td><td>{acts}</td></tr>')
        table = ('<table class="t"><thead><tr><th>Request</th><th>Dog</th><th>Status</th><th>Photos sent</th><th>Portrait</th><th></th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table>") if rows else '<p class="muted">No portrait requests yet.</p>'
        body = (f'<section class="section"><div class="wrap"><h1>Pixel portrait requests</h1>'
                f'<p class="small muted">{len(P.pending())} pending. JSON: /admin/portraits/pending (X-Admin-Key header).</p>'
                f'<div style="overflow-x:auto">{table}</div></div></section>')
        return self.page("Pixel portrait requests", body)

    # ------------------------------------------------------------ old sprite images
    def pixel_image(self, pid, variant):
        etag = '"px%d%s"' % (pid, variant)
        hdr = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": etag}
        if etag in (self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            for k, v in hdr.items():
                self.send_header(k, v)
            self.end_headers()
            return
        got = A.pixel_blob(pid, "native" if variant in ("-1x", "-og") else "big")
        if got is None:
            return self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"})
        blob, name = got
        if variant == "-og":
            if pid not in OG_CACHE:
                if len(OG_CACHE) > 50:
                    OG_CACHE.clear()
                OG_CACHE[pid] = A.pixel_og_png(blob, name)
            blob = OG_CACHE[pid]
        return self._emit(200, blob, "image/png", hdr)
