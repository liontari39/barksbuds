"""BarksBuds packs: pages and routes (mixed into server.H next to webapp.AppRoutes and meetweb.MeetupRoutes).

A pack is a standing group of members and their dogs around a home dog run. Server-rendered with escaped output;
every member POST checks the CSRF token; posts, comments, joins and reports are rate limited. Pack emails go through
mailer.send_async (behind PACK_EMAIL_ALLOWLIST / MEETUP_EMAIL_ALLOWLIST), respect each member's pack email preference,
carry a one-click unsubscribe link and are never sent for sample packs.
"""
import html, json, re
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import accounts as A
import mailer
import meetups as M
import packs as P
import webapp as W
from webapp import clean, area_label, where_text

e = html.escape
W.FLASH.update({
    "p_created": "Your pack is live! Share the link so friends can join.", "p_saved": "Pack updated.",
    "p_joined": "Welcome to the pack!", "p_requested": "Request sent. An organizer will review it soon.",
    "p_left": "You left the pack.", "p_cancelled": "Request withdrawn.", "p_dogs": "Your dogs in this pack were updated.",
    "p_approved": "Request approved.", "p_denied": "Request declined.", "p_removed": "Member removed.",
    "p_promoted": "They're now a co-organizer.", "p_demoted": "They're now a member.", "p_owner": "Ownership transferred.",
    "p_posted": "Posted to the pack board.", "p_post_deleted": "Post deleted.", "p_pinned": "Post pinned.", "p_unpinned": "Post unpinned.",
    "p_commented": "Comment posted.", "p_comment_deleted": "Comment deleted.", "p_cover_removed": "Cover photo removed.",
    "p_deleted": "Pack deleted.", "pack_emails_on": "Pack emails are on.", "pack_emails_off": "Pack emails are off.",
})
ERRS = {"slow": "That's a lot of activity. Please wait a few minutes and try again.", "nodogs": "Pick at least one of your dogs.",
        "adddog": "Add your dog's profile first, then join.", "empty": "Write something first.", "members": "Join the pack to do that.",
        "photo": "We couldn't use that photo. Try a JPEG, PNG, WebP or HEIC under 15 MB.", "owner": "Transfer the pack to another member before leaving.",
        "toomany": "This pack has a lot of photos already. Post without a photo, or ask an organizer to tidy up."}
FIT_ICON = {"small": "i-dog", "big": "i-dog", "puppies": "i-heart", "seniors": "i-heart", "all": "i-paw"}


def pack_path(p):
    return f"/packs/{p['id']}" + (f"-{p['slug']}" if p.get("slug") else "")


def run_of(p):
    return W.run_index().get(p["run_id"]) if p.get("run_id") else None


def where_line(p):
    return where_text(p.get("town"), p.get("area"))


def unsub_url(base, uid):
    return f"{base}/emails/packs?u={uid}&t={P.unsub_token(uid)}"


def pack_ctx(base, p):
    return {"name": p["name"], "url": base + pack_path(p), "where": where_line(p)}


def send_pack_mail(base, uid, kind, p, force=False, subject_prefix="", **kw):
    """Email one member about a pack. Skips members who turned pack emails off (unless force)."""
    email, name, on = P.contact(uid)
    if not email or (not on and not force):
        return False
    subject, body, text = mailer.build_pack(base, kind, pack_ctx(base, p), name=name, unsub=unsub_url(base, uid), **kw)
    return mailer.send_async(email, subject_prefix + subject, body, text, unsub_url(base, uid), "pack-" + kind)


def _user_name(uid):
    r = A.one("SELECT display_name FROM users WHERE id=:u", u=uid)
    return (r[0] if r else "") or "A member"


def notify_join_request(base, p, uid, dog_ids, message):
    if p["is_sample"]:
        return 0
    who, dogs = _user_name(uid), M.dog_names(dog_ids)
    return sum(1 for o in P.organizer_ids(p["id"]) if o != uid and
               send_pack_mail(base, o, "request", p, who=who, who_dogs=dogs, message=message))


def notify_approved(base, p, uid):
    if p["is_sample"]:
        return False
    return send_pack_mail(base, uid, "approved", p)


def meetup_mail(base, m):
    import meetweb
    c = meetweb.mail_ctx(base, m)
    c.update(host=_user_name(m["host_user_id"]), members_only=bool(m.get("members_only")))
    return c


def notify_pack_meetup(base, m):
    """Tell a pack's members (except the host) about a new pack meetup. Never for samples."""
    p = P.get(m["pack_id"]) if m.get("pack_id") else None
    if not p or p["is_sample"] or m["is_sample"] or p["hidden"]:
        return 0
    ctx = meetup_mail(base, m)
    return sum(1 for uid in P.member_ids(p["id"]) if uid != m["host_user_id"] and
               send_pack_mail(base, uid, "meetup", p, meetup=ctx))


def dog_tiles(dogs, size=72):
    out = []
    for d in dogs:
        img = A.tile_img(d, size)
        out.append(f'<li><a href="/dogs/{e(d["slug"])}">{img}<span>{e(d["name"])}</span></a></li>')
    return "".join(out)


def ago(ts):
    s = max(A.now() - ts, 0)
    if s < 60:
        return "just now"
    for n, lab in ((86400 * 7, None), (86400, "d"), (3600, "h"), (60, "m")):
        if s >= n:
            if lab is None:
                return M.to_et(ts).strftime("%b %-d")
            return f"{s // n}{lab} ago"
    return "just now"


class PackRoutes:
    # ------------------------------------------------------------ routing
    def pack_get(self, path, q):
        self._app_reset()
        if path in ("/packs", "/packs/"):
            self.packs_page(q); return True
        if path == "/packs/new":
            self.pack_form_page(None, q=q); return True
        mt = re.fullmatch(r"/pp/(\d+)\.(jpg|webp)", path)
        if mt:
            self.pack_photo(int(mt.group(1)), mt.group(2)); return True
        mt = re.fullmatch(r"/packs/(\d+)(?:-[a-z0-9-]*)?/(edit|members|delete)", path)
        if mt:
            pid, what = int(mt.group(1)), mt.group(2)
            p = self.org_pack(pid, owner_only=what == "delete")
            if p:
                {"edit": lambda: self.pack_form_page(p, q=q), "members": lambda: self.members_page(p, q),
                 "delete": lambda: self.pack_delete_page(p)}[what]()
            return True
        mt = re.fullmatch(r"/packs/(\d+)(-[a-z0-9-]*)?/?", path)
        if mt:
            self.pack_page(int(mt.group(1)), mt.group(2) or "", q); return True
        if path == "/api/packs":
            self.packs_api(); return True
        if path == "/emails/packs":
            self.pack_unsub_page(q); return True
        if path == "/admin/packs":
            self.admin_packs(q); return True
        return False

    def pack_post(self, path, q):
        self._app_reset()
        routes = [(r"/packs/new", self.post_pack), (r"/packs/(\d+)/edit", self.post_pack),
                  (r"/packs/(\d+)/join", self.post_join), (r"/packs/(\d+)/leave", self.post_leave),
                  (r"/packs/(\d+)/dogs", self.post_pack_dogs),
                  (r"/packs/(\d+)/requests/(\d+)/(approve|deny)", self.post_member_action),
                  (r"/packs/(\d+)/members/(\d+)/(remove|promote|demote|owner)", self.post_member_action),
                  (r"/packs/(\d+)/posts", self.post_board),
                  (r"/packs/(\d+)/posts/(\d+)/(pin|unpin|delete|report)", self.post_board_action),
                  (r"/packs/(\d+)/posts/(\d+)/comments", self.post_pcomment),
                  (r"/packs/(\d+)/comments/(\d+)/(delete|report)", self.post_pcomment_action),
                  (r"/packs/(\d+)/report", self.post_pack_report), (r"/packs/(\d+)/delete", self.post_pack_delete),
                  (r"/packs/(\d+)/cover/remove", self.post_cover_remove),
                  (r"/me/pack-emails", self.post_pack_email_prefs), (r"/emails/packs", self.post_pack_unsub),
                  (r"/admin/packs", self.post_admin_packs), (r"/admin/packs/test-email", self.post_admin_pack_test_email)]
        for pat, fn in routes:
            mt = re.fullmatch(pat, path)
            if mt:
                fn(*[int(x) if x.isdigit() else x for x in mt.groups()])
                return True
        return False

    # ------------------------------------------------------------ guards
    def not_found_pack(self):
        return self.msg_page("We couldn't find that pack", '<p class="sub">It may have been removed.</p>'
                             '<p><a class="btn" href="/packs">Browse packs</a></p>', code=404, icon="i-users")

    def visible_pack(self, pid):
        p = P.get(pid)
        u = self.user()
        if not p or (p["hidden"] and not (u and P.is_member(pid, u["id"]))):
            self.not_found_pack()
            return None
        return p

    def org_pack(self, pid, owner_only=False):
        """The pack if the signed-in member organizes it (or owns it, when owner_only); otherwise renders an error."""
        u = self.user()
        if not u:
            self.need_login()
            return None
        p = P.get(pid)
        if not p:
            self.not_found_pack()
            return None
        ok = (u["id"] == p["owner_user_id"]) if owner_only else P.is_organizer(pid, u["id"])
        if not ok:
            self.msg_page("Only organizers can do that", '<p class="sub">' + ("Only the pack's organizer can do that." if owner_only else
                          "Pack organizers manage this.") + f'</p><p><a class="btn" href="{e(pack_path(p))}">Back to the pack</a></p>',
                          code=403, icon="i-lock")
            return None
        return p

    def member_pack(self, pid):
        """(pack, user) for POSTs that need an active member, else renders/redirects and returns (None, None)."""
        u = self.user()
        if not u:
            self.need_login()
            return None, None
        p = self.visible_pack(pid)
        if not p:
            return None, None
        if not P.is_member(pid, u["id"]):
            self.redirect(pack_path(p) + "?e=members#join")
            return None, None
        return p, u

    # ------------------------------------------------------------ dashboard hooks (called from webapp.dashboard)
    def pack_email_prefs_html(self, u):
        on = P.emails_on(u["id"])
        return (f'<form id="pack-emails" method="post" action="/me/pack-emails" class="emailpref">{self.csrf_field()}'
                f'<input type="hidden" name="on" value="{0 if on else 1}"><p class="small" style="margin:0 0 8px"><b>Pack emails:</b> '
                f'{"On" if on else "Off"}. Join requests (for organizers), approvals and new pack meetups.</p>'
                f'<button class="btn btn-ghost btn-sm" type="submit">{"Turn off pack emails" if on else "Turn on pack emails"}</button></form>')

    def pack_row(self, p, tag):
        img = (f'<img src="/pp/{p["cover_photo_id"]}.webp" alt="" width="52" height="52" loading="lazy">' if p.get("cover_photo_id") else
               '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-users"/></svg></span>')
        return (f'<li><a href="{e(pack_path(p))}"><span class="pthumb">{img}</span>'
                f'<span class="mrt"><strong>{e(p["name"])}</strong><small>{e(where_line(p))}</small></span>'
                f'<span class="mtag">{e(tag)}</span></a></li>')

    def packs_dashboard(self, u):
        mine = P.for_user(u["id"])
        li = []
        for p, role, st in mine:
            tag = "Request pending" if st == "pending" else P.ROLE_LABEL.get(role, "Member")
            if st == "active" and role in ("owner", "organizer"):
                n = P.pending_count(p["id"])
                if n:
                    tag += f" · {n} request{'s' if n != 1 else ''}"
            li.append(self.pack_row(p, tag + (" · hidden" if p["hidden"] else "")))
        inner = (f'<ul class="mrows">{"".join(li)}</ul>' if li else
                 '<p class="muted" style="margin:0 0 14px">You\'re not in a pack yet. Packs are regular crews that meet at the same run.</p>')
        mine_ids = {p["id"] for p, _r, _s in mine}
        near = []
        if u.get("area"):
            near = [p for p in P.browse(areas=[u["area"]]) if p["id"] not in mine_ids][:4]
        near_html = ""
        if near:
            near_html = (f'<h3 style="margin:22px 0 10px">Packs near you <span class="small muted" style="font-weight:600">in {e(area_label(u["area"]))}</span></h3>'
                         f'<div class="pgrid sm">{"".join(self.pack_card(p) for p in near)}</div>')
        return (f'<div class="panel" style="margin-top:28px" id="packs"><div class="mehead"><h2 style="margin:0">Your packs</h2>'
                f'<div class="formfoot" style="margin:0"><a class="btn btn-ghost btn-sm" href="/packs">Find packs</a>'
                f'<a class="btn btn-sm" href="/packs/new">Start a pack</a></div></div><div style="margin-top:14px">{inner}{near_html}</div></div>')

    # ------------------------------------------------------------ browse
    def pack_card(self, p):
        cover = (f'<img src="/pp/{p["cover_photo_id"]}.webp" alt="" loading="lazy" width="640" height="360">' if p.get("cover_photo_id") else
                 '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-users"/></svg></span>')
        tags = []
        if p["is_sample"]:
            tags.append('<span class="badge sample">Sample</span>')
        tags.append('<span class="badge">' + ("Open" if p["visibility"] == "open" else "Request to join") + '</span>')
        if p.get("fit") and p["fit"] != "all":
            tags.append(f'<span class="badge">{e(P.FIT_LABEL.get(p["fit"], ""))}</span>')
        r = run_of(p)
        members = p.get("members")
        if members is None:
            members, ndogs = P.member_counts({p["id"]}).get(p["id"], (0, 0))
        else:
            ndogs = p.get("ndogs", 0)
        stats = f'{members} member{"s" if members != 1 else ""} · {ndogs} dog{"s" if ndogs != 1 else ""}'
        home = f'<p class="phome"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>Home run: {e(r["name"])}</p>' if r else ""
        return (f'<a class="pcard" href="{e(pack_path(p))}"><span class="pcover">{cover}</span><span class="pbody">'
                f'<span class="ptags">{"".join(tags)}</span><strong>{e(p["name"])}</strong>'
                f'<span class="pwhere">{e(where_line(p))}</span>{home}<span class="pstats">{stats}</span></span></a>')

    def packs_page(self, q):
        region = q.get("region", [""])[0]
        area = q.get("area", [""])[0]
        if area not in A.AREA_NAMES:
            area = ""
        if region not in A.REGIONS and region != "northshore":
            region = ""
        areas = [area] if area else (A.REGIONS[region][1] if region in A.REGIONS else None)
        ps = P.browse(areas=areas, north_shore=region == "northshore")
        ns = [p for p in P.browse(north_shore=True)][:3] if not (area or region) else []

        def link(**kw):
            return "/packs" + (("?" + urlencode(kw)) if kw else "")
        chips = [(link(), "All", not (area or region)), (link(region="northshore"), "North Shore", region == "northshore")]
        chips += [(link(region=r), A.REGIONS[r][0], region == r) for r in A.REGIONS]
        chips += [(link(area=a), area_label(a), area == a) for a in A.AREA_NAMES]
        filt = "".join(f'<a class="chip{" on" if on else ""}" href="{e(h)}"{" aria-current=true" if on else ""}>{e(t)}</a>' for h, t, on in chips)
        u = self.user()
        start = "/packs/new" if u else self.signin_href("/packs/new")
        ns_html = ""
        if ns:
            ns_html = (f'<div class="pshore"><div class="mehead"><div><span class="eyebrow">starting on the north shore</span>'
                       f'<h2 style="margin:4px 0 6px">Our first packs are forming around Manhasset</h2>'
                       f'<p class="muted" style="margin:0">Join a crew that meets at the same run, so your dog sees familiar friends every week.</p></div>'
                       f'<a class="btn btn-gold btn-sm" href="{e(link(region="northshore"))}">See North Shore packs</a></div>'
                       f'<div class="pgrid sm" style="margin-top:16px">{"".join(self.pack_card(p) for p in ns)}</div></div>')
        if ps:
            content = f'<div class="pgrid">{"".join(self.pack_card(p) for p in ps)}</div>'
        else:
            content = (f'<div class="empty panel"><svg class="ico" aria-hidden="true"><use href="#i-users"/></svg><h2>No packs here yet</h2>'
                       f'<p class="muted">Be the first: start a pack for your run and invite your dog\'s friends.</p>'
                       f'<a class="btn" href="{e(start)}">Start a pack</a></div>')
        label = area_label(area) if area else ("the North Shore" if region == "northshore" else (A.REGIONS[region][0] if region else ""))
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">find your crew</span><h1>Dog packs</h1>
<p class="lead">Packs are friendly regular groups of dogs and their people who meet at the same runs. Join one with your dogs, see the next pack meetup and chat on the pack board.</p>
<div class="formfoot"><a class="btn" href="{e(start)}">Start a pack</a><a class="btn btn-ghost" href="/meetups">See meetups</a></div></div></section>
<section class="section"><div class="wrap">{ns_html}
<nav class="filters" aria-label="Filter packs by area">{filt}</nav>
<h2 class="sr-only">Packs{" in " + e(label) if label else ""}</h2>{content}</div></section>"""
        return self.page("Dog packs" + (f" in {label}" if label else ""), body, active="packs", index=not (area or region),
                         canonical="/packs" if not (area or region) else link(**({"area": area} if area else {"region": region})),
                         desc="Find a friendly dog pack near you in NYC, Long Island and Westchester: regular crews that meet at the same dog runs.",
                         og={"title": "Dog packs on BarksBuds", "image": self._base() + "/img/og-image.jpg"} if not (area or region) else None,
                         flash=self.flash_from(q))

    def packs_api(self):
        out = {}
        for p in P.browse():
            if p.get("run_id"):
                out.setdefault(p["run_id"], []).append({"name": p["name"], "url": pack_path(p), "members": p["members"],
                                                        "sample": bool(p["is_sample"])})
        return self._emit(200, json.dumps({"runs": out}).encode(), "application/json", {"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ create / edit
    def pack_form_page(self, p, vals=None, errs=None, code=200, q=None):
        u = self.user()
        if not u:
            return self.need_login()
        errs = errs or {}
        mydogs = [d for d in A.dogs_for_user(u["id"]) if not d["hidden"]]
        if vals is None:
            if p:
                vals = {k: p[k] or "" for k in ("name", "area", "town", "run_id", "description", "fit", "visibility")}
            else:
                rid = (q or {}).get("run", [""])[0]
                r = W.run_index().get(rid)
                vals = dict(name="", area=(r or {}).get("county") if r and (r or {}).get("county") in A.AREA_NAMES else (u.get("area") or ""),
                            town=(r or {}).get("town_or_neighborhood") or (u.get("town") or ""), run_id=rid if r else "",
                            description="", fit="", visibility="open", dogs=[d["id"] for d in mydogs])
        v = lambda k: e(str(vals.get(k) or ""))
        err = lambda k: f'<span class="err" id="{k}-err">{e(errs.get(k, ""))}</span>'
        inv = lambda k: ' aria-invalid="true"' if k in errs else ""
        import meetweb
        run_sel = meetweb.MeetupRoutes.run_select(self, vals.get("run_id") or "").replace('<option value="">Choose a dog run</option>',
                                                                                        '<option value="">No home run yet</option>')
        fits = ('<label class="tick"><input type="radio" name="fit" value=""' + (" checked" if not vals.get("fit") else "") + '><span>No preference</span></label>'
                + "".join(f'<label class="tick"><input type="radio" name="fit" value="{k}"{" checked" if vals.get("fit") == k else ""}><span>{e(t)}</span></label>'
                          for k, t in P.FITS))
        vis = "".join(f'<label class="tick"><input type="radio" name="visibility" value="{k}"{" checked" if (vals.get("visibility") or "open") == k else ""}><span>{e(t)}</span></label>'
                      for k, t in P.VISIBILITY)
        dogs_html = ""
        if not p:
            chosen = {int(x) for x in vals.get("dogs") or [] if str(x).isdigit()}
            if mydogs:
                ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}"{" checked" if d["id"] in chosen else ""}><span>{e(d["name"])}</span></label>'
                                for d in mydogs)
                dogs_html = f'<fieldset class="field"><legend class="lab">Your dogs in this pack</legend><div class="checks-grid">{ticks}</div>{err("dogs")}</fieldset>'
            else:
                dogs_html = (f'<p class="notice small">Tip: <a href="/me/dogs/new">add your dog\'s profile</a> so they show up as a pack member.</p>')
        cover = ""
        if p and p["cover_photo_id"]:
            cover = (f'<div class="pcoverprev"><img src="/pp/{p["cover_photo_id"]}.webp" alt="Current cover photo" width="320" height="180"></div>')
        action = f"/packs/{p['id']}/edit" if p else "/packs/new"
        top = '<div class="formerr" role="alert">Please fix the highlighted fields.</div>' if errs else ""
        title = "Edit pack" if p else "Start a pack"
        area_sel = self.area_select(vals.get("area"), "area")
        remove_cover = ""
        if p and p["cover_photo_id"]:
            remove_cover = (f'<form method="post" action="/packs/{p["id"]}/cover/remove" style="margin-top:12px">{self.csrf_field()}'
                            f'<button class="linkbtn small" type="submit">Remove the cover photo</button></form>')
        danger = ""
        if p and u["id"] == p["owner_user_id"]:
            danger = f'<p class="small" style="margin-top:22px"><a class="danger" href="/packs/{p["id"]}/delete">Delete this pack</a></p>'
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">{"edit" if p else "gather your crew"}</span><h1>{title}</h1>
<p class="lead">A pack is a friendly regular group that meets at the same run. Give it a name, pick a home run and say who it's for.</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel mform" method="post" action="{action}" enctype="multipart/form-data" novalidate>{self.csrf_field()}{top}
<div class="field"><label for="name">Pack name</label><input type="text" id="name" name="name" maxlength="{P.MAX_NAME}" required value="{v("name")}" placeholder="Manhasset Morning Crew"{inv("name")}>{err("name")}</div>
<div class="row2"><div class="field"><label for="area">Area</label>{area_sel}{err("area")}</div>
<div class="field"><label for="town">Town or neighborhood</label><input type="text" id="town" name="town" maxlength="60" required value="{v("town")}" placeholder="Manhasset"{inv("town")}>{err("town")}</div></div>
<div class="field"><label for="run_id">Home run <span class="opt">(optional)</span></label>{run_sel}{err("run_id")}<span class="help">Pack meetups default to the home run, and the pack shows up on that run in the map.</span></div>
<div class="field"><label for="description">About the pack</label><textarea id="description" name="description" maxlength="{P.MAX_DESC}" rows="5" required placeholder="When you usually meet, what the dogs are like, how to find you."{inv("description")}>{v("description")}</textarea>{err("description")}</div>
<fieldset class="field"><legend class="lab">Good fit for <span class="opt">(optional)</span></legend><div class="checks-grid">{fits}</div></fieldset>
<fieldset class="field"><legend class="lab">Who can join</legend><div class="checks-grid" style="grid-template-columns:1fr">{vis}</div></fieldset>
<div class="field"><label for="cover">Cover photo <span class="opt">(optional)</span></label>{cover}<input type="file" id="cover" name="cover" accept="image/jpeg,image/png,image/webp,image/gif,image/heic"{inv("cover")}>
<span class="help">A wide photo works best. We resize it and remove location data.</span>{err("cover")}</div>
{dogs_html}
<div class="formfoot"><button class="btn" type="submit">{"Save changes" if p else "Create pack"}</button><a class="small" href="{e(pack_path(p)) if p else "/packs"}">Cancel</a></div>
<p class="small muted" style="margin:14px 0 0">Packs are public so neighbors can find them. Keep it friendly and welcoming; the pack board is visible to members only.</p></form>
{remove_cover}{danger}</div></section>"""
        return self.page(title, body, code=code, active="packs", flash=self.flash_from(q or {}))

    def parse_pack(self, f, creating):
        errs = {}
        vals = {k: f.get(k) for k in ("name", "area", "town", "run_id", "description", "fit", "visibility")}
        vals["dogs"] = f.getlist("dogs")
        name = clean(f.get("name"), P.MAX_NAME)
        if len(name) < 3:
            errs["name"] = "Give your pack a name (at least 3 characters)."
        area = f.get("area")
        if area not in A.AREA_NAMES:
            errs["area"] = "Pick an area."
        town = clean(f.get("town"), 60)
        if not town:
            errs["town"] = "Add the town or neighborhood."
        rid = f.get("run_id")
        if rid and rid not in W.run_index():
            errs["run_id"] = "Pick a run from the list."
            rid = ""
        desc = clean(f.get("description"), P.MAX_DESC, multiline=True)
        if len(desc) < 10:
            errs["description"] = "Tell people a little about the pack."
        fit = f.get("fit") if f.get("fit") in P.FIT_LABEL else ""
        visv = f.get("visibility") if f.get("visibility") in dict(P.VISIBILITY) else "open"
        dogs = []
        if creating:
            mine = {d["id"] for d in A.dogs_for_user(self.user()["id"]) if not d["hidden"]}
            dogs = [int(x) for x in f.getlist("dogs") if x.isdigit() and int(x) in mine]
        out = dict(name=name, area=area, town=town, run_id=rid or "", description=desc, fit=fit, visibility=visv, dogs=dogs)
        return out, vals, errs

    def post_pack(self, pid=None):
        u = self.user()
        if not u:
            return self.need_login()
        p = None
        if pid:
            p = self.org_pack(pid)
            if not p:
                return
        f = self._form_or_fail(W.MAX_UPLOAD_REQUEST)
        if f is None:
            return
        out, vals, errs = self.parse_pack(f, creating=not p)
        if not p:
            if P.created_by(u["id"]) >= P.MAX_PACKS_PER_USER:
                errs["name"] = f"You can start up to {P.MAX_PACKS_PER_USER} packs."
            elif not errs and not A.LIMITER.allow(f"pack-create:{u['id']}", 3, 86400):
                errs["name"] = "You've started a few packs today. Please try again tomorrow."
        processed = None
        up = [x for x in f.files if x[0] == "cover" and x[2]]
        if up and not errs:
            try:
                processed = A.process_image(up[0][2])
            except A.BadImage as ex:
                errs["cover"] = str(ex)
        if errs:
            return self.pack_form_page(p, vals, errs, code=422)
        new_id = P.save(u["id"], out, pid=pid)
        if processed:
            P.set_cover(new_id, None, processed)
        print(f"packs: {'updated' if pid else 'created'} pack {new_id}", flush=True)
        return self.redirect(pack_path(P.get(new_id)) + ("?m=p_saved" if pid else "?m=p_created"))

    def post_cover_remove(self, pid):
        p = self.org_pack(pid)
        if not p or self._form_or_fail() is None:
            return
        P.remove_cover(pid)
        return self.redirect(f"/packs/{pid}/edit?m=p_cover_removed")

    def pack_delete_page(self, p):
        body = (f'<p class="sub">This deletes <b>{e(p["name"])}</b> with its members list, board posts and photos. '
                f'Pack meetups stay on the calendar as regular meetups. This can\'t be undone.</p>'
                f'<form method="post" action="/packs/{p["id"]}/delete">{self.csrf_field()}<div class="formfoot" style="justify-content:center">'
                f'<button class="btn btn-danger" type="submit">Delete the pack</button><a class="small" href="{e(pack_path(p))}">Keep it</a></div></form>')
        return self.msg_page("Delete this pack?", body, icon="i-users")

    def post_pack_delete(self, pid):
        p = self.org_pack(pid, owner_only=True)
        if not p or self._form_or_fail() is None:
            return
        P.delete(pid)
        print(f"packs: deleted pack {pid}", flush=True)
        return self.redirect("/me?m=p_deleted#packs")

    # ------------------------------------------------------------ pack page
    def join_panel(self, p, u, mem):
        path = pack_path(p)
        if not u:
            return (f'<p>Sign in to join with your dogs.</p><a class="btn" href="{e(self.signin_href(path + "#join"))}">'
                    + ("Sign in to join" if p["visibility"] == "open" else "Sign in to request to join") + '</a>')
        mydogs = [d for d in A.dogs_for_user(u["id"]) if not d["hidden"]]
        if not mydogs and not (mem and mem["status"] == "active"):
            return (f'<p>Add your dog\'s profile first, then join with them.</p>'
                    f'<a class="btn" href="/me/dogs/new">Add your dog</a>')
        chosen = set(mem["dogs"]) if mem else {d["id"] for d in mydogs}
        ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}"{" checked" if d["id"] in chosen else ""}><span>{e(d["name"])}</span></label>'
                        for d in mydogs)
        if mem and mem["status"] == "active":
            leave = ""
            if mem["role"] != "owner":
                leave = (f'<form method="post" action="/packs/{p["id"]}/leave" style="margin-top:12px">{self.csrf_field()}'
                         f'<button class="linkbtn small" type="submit" onclick="return confirm(\'Leave this pack?\')">Leave the pack</button></form>')
            dogs_form = ""
            if mydogs:
                dogs_form = (f'<form method="post" action="/packs/{p["id"]}/dogs">{self.csrf_field()}'
                             f'<fieldset class="checks-grid" style="margin-bottom:12px"><legend>Your dogs in this pack</legend>{ticks}</fieldset>'
                             f'<button class="btn btn-ghost btn-sm" type="submit">Update dogs</button></form>')
            return (f'<p class="mine"><svg class="ico" aria-hidden="true"><use href="#i-check"/></svg>You\'re '
                    + ("the organizer" if mem["role"] == "owner" else "a co-organizer" if mem["role"] == "organizer" else "a member")
                    + f' of this pack.</p>{dogs_form}{leave}')
        if mem and mem["status"] == "pending":
            return (f'<p class="mine"><svg class="ico" aria-hidden="true"><use href="#i-clock"/></svg>Your request is waiting for an organizer.</p>'
                    f'<form method="post" action="/packs/{p["id"]}/leave">{self.csrf_field()}<button class="btn btn-ghost btn-sm" type="submit">Withdraw request</button></form>')
        msg = ""
        if p["visibility"] == "request":
            msg = (f'<div class="field"><label for="jmsg">Note to the organizers <span class="opt">(optional)</span></label>'
                   f'<textarea id="jmsg" name="message" maxlength="{P.MAX_MSG}" rows="2" placeholder="Hi! We\'re at the run most mornings."></textarea></div>')
        return (f'<form method="post" action="/packs/{p["id"]}/join">{self.csrf_field()}'
                f'<fieldset class="checks-grid" style="margin-bottom:12px"><legend>Which dogs are joining?</legend>{ticks}</fieldset>{msg}'
                f'<button class="btn" type="submit">{"Join the pack" if p["visibility"] == "open" else "Request to join"}</button>'
                + ('<p class="small muted" style="margin:10px 0 0">An organizer approves each new member.</p>' if p["visibility"] == "request" else "")
                + '</form>')

    def board_html(self, p, u, mem, is_org):
        path = pack_path(p)
        n = P.post_count(p["id"])
        if not (mem and mem["status"] == "active"):
            return (f'<p class="muted" style="margin:0">The pack board is for members. '
                    + (f'{n} post{"s" if n != 1 else ""} so far. ' if n else "") + 'Join the pack to read it and say hi.</p>')
        form = (f'<form class="pboardform" method="post" action="/packs/{p["id"]}/posts" enctype="multipart/form-data">{self.csrf_field()}'
                f'<label class="sr-only" for="pbody">Write a post</label><textarea id="pbody" name="body" maxlength="{P.MAX_POST}" rows="3" required '
                f'placeholder="Share a plan, a photo from the run, or a friendly hello."></textarea>'
                f'<div class="formfoot" style="margin-top:8px"><label class="small pfile">Photo <span class="opt">(optional)</span> '
                f'<input type="file" name="photo" accept="image/jpeg,image/png,image/webp,image/gif,image/heic"></label>'
                f'<button class="btn btn-sm" type="submit">Post</button></div></form>')
        reasons = "".join(f"<option>{e(x)}</option>" for x in A.REPORT_REASONS)
        items = []
        for po in P.posts(p["id"]):
            acts = []
            if is_org:
                act = "unpin" if po["pinned"] else "pin"
                acts.append(f'<form method="post" action="/packs/{p["id"]}/posts/{po["id"]}/{act}">{self.csrf_field()}'
                            f'<button class="linkbtn" type="submit">{"Unpin" if po["pinned"] else "Pin"}</button></form>')
            if is_org or po["user_id"] == u["id"]:
                acts.append(f'<form method="post" action="/packs/{p["id"]}/posts/{po["id"]}/delete">{self.csrf_field()}'
                            f'<button class="linkbtn" type="submit" onclick="return confirm(\'Delete this post?\')">Delete</button></form>')
            if po["user_id"] != u["id"]:
                acts.append(f'<details class="creport"><summary>Report</summary><form method="post" action="/packs/{p["id"]}/posts/{po["id"]}/report">'
                            f'{self.csrf_field()}<select name="reason" aria-label="Reason">{reasons}</select><button class="linkbtn" type="submit">Send</button></form></details>')
            img = ""
            if po["photo_id"]:
                img = (f'<a href="/pp/{po["photo_id"]}.jpg" target="_blank" rel="noopener"><img class="pimg" src="/pp/{po["photo_id"]}.webp" alt="Photo shared by {e(po["name"])}" loading="lazy"></a>')
            cms = []
            for c in po["comments"]:
                cacts = []
                if is_org or c["user_id"] == u["id"]:
                    cacts.append(f'<form method="post" action="/packs/{p["id"]}/comments/{c["id"]}/delete">{self.csrf_field()}'
                                 f'<button class="linkbtn" type="submit">Delete</button></form>')
                if c["user_id"] != u["id"]:
                    cacts.append(f'<form method="post" action="/packs/{p["id"]}/comments/{c["id"]}/report">{self.csrf_field()}'
                                 f'<input type="hidden" name="reason" value="Something else"><button class="linkbtn" type="submit">Report</button></form>')
                cms.append(f'<li><div class="chead"><b>{e(c["name"])}</b><span class="small muted">{e(ago(c["created_at"]))}</span></div>'
                           f'<p class="cbody">{e(c["body"])}</p><div class="cacts">{"".join(cacts)}</div></li>')
            cform = (f'<form class="pcform" method="post" action="/packs/{p["id"]}/posts/{po["id"]}/comments">{self.csrf_field()}'
                     f'<label class="sr-only" for="pc{po["id"]}">Comment</label><input type="text" id="pc{po["id"]}" name="body" maxlength="{P.MAX_COMMENT}" required placeholder="Write a comment">'
                     f'<button class="btn btn-ghost btn-sm" type="submit">Reply</button></form>')
            pin = '<span class="badge pin">Pinned</span>' if po["pinned"] else ""
            items.append(f'<li class="post" id="post-{po["id"]}"><div class="chead"><b>{e(po["name"])}</b>{pin}<span class="small muted">{e(ago(po["created_at"]))}</span></div>'
                         f'<p class="cbody">{e(po["body"])}</p>{img}<div class="cacts">{"".join(acts)}</div>'
                         f'<ul class="clist pcomments">{"".join(cms)}</ul>{cform}</li>')
        feed = f'<ul class="posts">{"".join(items)}</ul>' if items else '<p class="muted">No posts yet. Start the conversation!</p>'
        return form + feed

    def pack_page(self, pid, slugpart, q):
        p = self.visible_pack(pid)
        if not p:
            return
        if slugpart != (f"-{p['slug']}" if p["slug"] else ""):
            qs = ("?" + urlencode({k: v[0] for k, v in q.items()})) if q else ""
            return self.redirect(pack_path(p) + qs, 301)
        import meetweb
        u = self.user()
        base = self._base()
        path = pack_path(p)
        mem = P.membership(pid, u["id"]) if u else None
        is_org = bool(mem and mem["status"] == "active" and mem["role"] in ("owner", "organizer"))
        is_mem = bool(mem and mem["status"] == "active")
        members = P.members(pid)
        dogs = [d for x in members for d in x["dogs"]]
        r = run_of(p)
        owner = next((x for x in members if x["role"] == "owner"), None)
        fact = lambda ico, txt: f'<li><svg class="ico" aria-hidden="true"><use href="#{ico}"/></svg>{txt}</li>'
        facts = [fact("i-pin", e(where_line(p))),
                 fact("i-users", f'{len(members)} member{"s" if len(members) != 1 else ""} · {len(dogs)} dog{"s" if len(dogs) != 1 else ""}'),
                 fact("i-lock" if p["visibility"] == "request" else "i-heart", "Request to join" if p["visibility"] == "request" else "Open to everyone")]
        if p["fit"]:
            facts.append(fact(FIT_ICON.get(p["fit"], "i-paw"), e(P.FIT_LABEL[p["fit"]])))
        if r:
            facts.append(fact("i-nav", f'Home run: {e(r["name"])}'))
        banners = []
        if p["is_sample"]:
            banners.append('<p class="notice small" style="margin:0 0 16px"><b>Sample pack.</b> An example to show how BarksBuds packs work. '
                           'It may be removed before launch, and it doesn\'t send email notifications.</p>')
        if p["hidden"]:
            banners.append('<p class="formerr" style="margin:0 0 16px">Hidden by our team while we review a report. Only members can see it.</p>')
        err = ERRS.get(q.get("e", [""])[0], "")
        errhtml = f'<p class="formerr" role="alert">{e(err)}</p>' if err else ""
        tools = ""
        if is_org:
            n = P.pending_count(pid)
            t = [f'<a class="btn btn-ghost btn-sm" href="/packs/{pid}/edit">Edit pack</a>',
                 f'<a class="btn btn-ghost btn-sm" href="/packs/{pid}/members">Members' + (f' <span class="count">{n}</span>' if n else "") + '</a>']
            tools = f'<div class="formfoot mtools"><span class="small muted">You organize this pack:</span>{"".join(t)}</div>'
        cta = ""
        if is_mem:
            cta = f'<a class="btn btn-gold btn-sm" href="/meetups/new?pack={pid}">Host a pack meetup</a><a class="btn btn-ghost btn-sm" href="#board">Pack board</a>'
        elif not (mem and mem["status"] == "pending"):
            cta = f'<a class="btn btn-gold btn-sm" href="#join">{"Join the pack" if p["visibility"] == "open" else "Request to join"}</a>'
        cover = (f'<img src="/pp/{p["cover_photo_id"]}.jpg" alt="{e(p["name"])} cover photo" width="1600" height="900">' if p["cover_photo_id"] else
                 '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-users"/></svg></span>')
        ms = P.meetups(pid, 6)
        mlist = "".join(self.meetup_row(m, "Members only" if m.get("members_only") else M.to_et(m["starts_at"]).strftime("%a")) for m in ms)
        host_btn = (f'<a class="btn btn-sm" href="/meetups/new?pack={pid}">Host a pack meetup</a>' if is_mem else "")
        meet_html = (f'<ul class="mrows">{mlist}</ul>' if ms else '<p class="muted" style="margin:0 0 12px">No pack meetups on the calendar yet.</p>') + \
                    (f'<div class="formfoot">{host_btn}</div>' if host_btn else "")
        run_html = ""
        if r:
            rbits = [x for x in ((r.get("type") or "").capitalize(), r.get("hours")) if x]
            dest = quote(f'{r["name"]}, {r.get("address") or r.get("town_or_neighborhood") or ""}')
            run_html = (f'<div class="panel"><h2>Home run</h2><p style="margin:0 0 4px"><b>{e(r["name"])}</b></p>'
                        + (f'<p class="muted" style="margin:0 0 6px">{e(r.get("address") or "")}</p>' if r.get("address") else "")
                        + (f'<p class="small muted" style="margin:0 0 10px">{e(" · ".join(rbits))}</p>' if rbits else "")
                        + f'<div class="formfoot"><a class="btn btn-ghost btn-sm" href="/runs?q={quote(r["name"])}">See on the map</a>'
                        f'<a class="btn btn-ghost btn-sm" href="https://www.google.com/maps/dir/?api=1&destination={dest}" target="_blank" rel="noopener">Directions</a></div></div>')
        mem_groups = []
        for x in members:
            role = P.ROLE_LABEL.get(x["role"], "Member")
            mem_groups.append(f'<li><b>{e(x["name"])}</b>' + (f' <span class="badge">{e(role)}</span>' if x["role"] != "member" else "")
                              + (f' <span class="small muted">with {e(", ".join(d["name"] for d in x["dogs"]))}</span>' if x["dogs"] else "") + '</li>')
        reasons = "".join(f"<option>{e(x)}</option>" for x in A.REPORT_REASONS)
        report = (f'<details class="report"><summary>Report this pack</summary><form method="post" action="/packs/{pid}/report">{self.csrf_field()}'
                  f'<div class="field"><label for="reason">What\'s wrong?</label><select id="reason" name="reason">{reasons}</select></div>'
                  f'<div class="field"><label for="details">Details <span class="opt">(optional)</span></label><textarea id="details" name="details" maxlength="1000" rows="3"></textarea></div>'
                  f'<button class="btn btn-sm" type="submit">Send report</button><p class="small muted" style="margin:10px 0 0">Reports go to the BarksBuds team, not to the organizers.</p></form></details>')
        sample_b = ' · <span class="badge sample">Sample</span>' if p["is_sample"] else ""
        body = f"""<section class="dhero phero"><div class="wrap"><div>{"".join(banners)}<span class="eyebrow">dog pack{sample_b}</span><h1 class="dname mtitle">{e(p["name"])}</h1>
<ul class="facts">{"".join(facts)}</ul>
{f'<p class="owner"><svg class="ico" aria-hidden="true" style="width:20px;height:20px;color:var(--red)"><use href="#i-heart"/></svg><span>Organized by <b>{e(owner["name"])}</b></span></p>' if owner else ""}
<div class="formfoot" style="margin-top:14px">{cta}</div>{tools}</div>
<div class="pcover-lg">{cover}</div></div></section>
<section class="section" style="padding-top:36px"><div class="wrap">{errhtml}<div class="dgrid2"><div>
<div class="panel"><h2>About the pack</h2><p class="bio">{e(p["description"])}</p></div>
<div class="panel"><h2>Member dogs <span class="small muted" style="font-weight:600">{len(dogs)}</span></h2>
{f'<ul class="mdogs">{dog_tiles(dogs)}</ul>' if dogs else '<p class="muted" style="margin:0">No dogs listed yet.</p>'}
<details class="pmembers"><summary>{len(members)} member{"s" if len(members) != 1 else ""}</summary><ul class="plist">{"".join(mem_groups)}</ul></details></div>
<div class="panel" id="board"><h2>Pack board</h2>{self.board_html(p, u, mem, is_org)}</div>
</div>
<div>
<div class="panel" id="join"><h2>{"Your membership" if is_mem else "Join the pack"}</h2>{self.join_panel(p, u, mem)}</div>
<div class="panel" id="meetups"><h2>Upcoming pack meetups</h2>{meet_html}</div>
{run_html}
{report}
</div></div></div></section>"""
        desc = (p["description"] or "").replace("\n", " ")
        og_desc = f"A dog pack in {where_line(p)}. " + (desc[:150] + ("…" if len(desc) > 150 else ""))
        if p["cover_photo_id"]:
            w, h = P.photo_size(p["cover_photo_id"])
            og = {"title": f"{p['name']} · BarksBuds pack", "image": f"{base}/pp/{p['cover_photo_id']}.jpg", "w": w, "h": h,
                  "alt": f"{p['name']} cover photo", "desc": og_desc}
        else:
            og = {"title": f"{p['name']} · BarksBuds pack", "image": base + "/img/og-image.jpg", "w": 1200, "h": 630, "desc": og_desc}
        return self.page(p["name"], body, canonical=path, desc=og_desc, og=og, index=not (p["hidden"] or p["is_sample"]), active="packs",
                         flash=self.flash_from(q))

    # ------------------------------------------------------------ members (organizers)
    def members_page(self, p, q):
        u = self.user()
        pid = p["id"]
        is_owner = u["id"] == p["owner_user_id"]

        def btn(uid, act, label, cls="btn btn-ghost btn-sm", conf=""):
            base = "requests" if act in ("approve", "deny") else "members"
            c = f' onclick="return confirm(\'{conf}\')"' if conf else ""
            return (f'<form method="post" action="/packs/{pid}/{base}/{uid}/{act}" style="display:inline">{self.csrf_field()}'
                    f'<button class="{cls}" type="submit"{c}>{label}</button></form>')
        pend = []
        for x in P.members(pid, "pending"):
            dogs = ", ".join(d["name"] for d in x["dogs"]) or "no dogs listed"
            note = f'<p class="small" style="margin:6px 0 0">“{e(x["message"])}”</p>' if x["message"] else ""
            pend.append(f'<li class="preq"><div><b>{e(x["name"])}</b> <span class="small muted">with {e(dogs)} · {e(ago(x["created_at"]))}</span>{note}'
                        f'{f"<ul class=mdogs style=margin-top:10px>{dog_tiles(x["dogs"], 56)}</ul>" if x["dogs"] else ""}</div>'
                        f'<div class="formfoot" style="margin:0">{btn(x["user_id"], "approve", "Approve", "btn btn-sm")}{btn(x["user_id"], "deny", "Decline")}</div></li>')
        rows = []
        for x in P.members(pid):
            acts = []
            if x["role"] != "owner" and x["user_id"] != u["id"]:
                if is_owner:
                    if x["role"] == "member":
                        acts.append(btn(x["user_id"], "promote", "Make co-organizer"))
                    else:
                        acts.append(btn(x["user_id"], "demote", "Make member"))
                    acts.append(btn(x["user_id"], "owner", "Transfer ownership", conf="Make them the pack organizer? You will become a co-organizer."))
                if is_owner or x["role"] == "member":
                    acts.append(btn(x["user_id"], "remove", "Remove", "btn btn-danger btn-sm", conf="Remove this member from the pack?"))
            dogs = ", ".join(d["name"] for d in x["dogs"])
            rows.append(f'<tr><td><b>{e(x["name"])}</b></td><td>{e(P.ROLE_LABEL.get(x["role"], "Member"))}</td><td>{e(dogs) or "—"}</td>'
                        f'<td><div class="formfoot" style="margin:0">{"".join(acts)}</div></td></tr>')
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">organizer tools</span><h1>{e(p["name"])}: members</h1>
<p class="lead"><a href="{e(pack_path(p))}">Back to the pack</a></p></div></section>
<section class="section"><div class="wrap">
<div class="panel"><h2>Join requests <span class="small muted" style="font-weight:600">{len(pend)}</span></h2>
{f'<ul class="preqs">{"".join(pend)}</ul>' if pend else '<p class="muted" style="margin:0">No requests waiting.</p>'}</div>
<div class="panel" style="margin-top:24px"><h2>Members</h2><div style="overflow-x:auto"><table class="t"><thead><tr><th>Member</th><th>Role</th><th>Dogs</th><th>Actions</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="small muted" style="margin:14px 0 0">Co-organizers can approve requests, edit the pack, remove members and pin posts. Only the organizer can change roles, transfer or delete the pack.</p></div>
</div></section>"""
        return self.page(f"{p['name']}: members", body, active="packs", flash=self.flash_from(q))

    def post_member_action(self, pid, uid, act):
        u = self.user()
        if not u:
            return self.need_login()
        owner_only = act in ("promote", "demote", "owner")
        p = self.org_pack(pid, owner_only=owner_only)
        if not p or self._form_or_fail() is None:
            return
        target = P.membership(pid, uid)
        back = f"/packs/{pid}/members"
        if not target or uid == p["owner_user_id"]:
            return self.redirect(back)
        if act in ("approve", "deny"):
            if target["status"] != "pending":
                return self.redirect(back)
            if act == "approve":
                if P.approve(pid, uid):
                    notify_approved(self._base(), p, uid)
                return self.redirect(back + "?m=p_approved")
            P.remove(pid, uid)
            return self.redirect(back + "?m=p_denied")
        if target["status"] != "active":
            return self.redirect(back)
        if act == "remove":
            if target["role"] == "organizer" and u["id"] != p["owner_user_id"]:
                return self.msg_page("Only the organizer can do that", '<p class="sub">Co-organizers can be removed by the pack organizer.</p>',
                                     code=403, icon="i-lock")
            P.remove(pid, uid)
            return self.redirect(back + "?m=p_removed")
        if act in ("promote", "demote"):
            P.set_role(pid, uid, "organizer" if act == "promote" else "member")
            return self.redirect(back + ("?m=p_promoted" if act == "promote" else "?m=p_demoted"))
        if act == "owner":
            P.transfer(pid, uid)
            return self.redirect(pack_path(p) + "?m=p_owner")
        return self.redirect(back)

    # ------------------------------------------------------------ join / leave
    def post_join(self, pid):
        u = self.user()
        if not u:
            return self.need_login()
        p = self.visible_pack(pid)
        if not p:
            return
        f = self._form_or_fail()
        if f is None:
            return
        path = pack_path(p)
        mine = {d["id"] for d in A.dogs_for_user(u["id"]) if not d["hidden"]}
        dogs = [int(x) for x in f.getlist("dogs") if x.isdigit() and int(x) in mine]
        if not dogs:
            return self.redirect(path + ("?e=nodogs" if mine else "?e=adddog") + "#join")
        cur = P.membership(pid, u["id"])
        if cur and cur["status"] == "active":
            P.set_dogs(pid, u["id"], dogs)
            return self.redirect(path + "?m=p_dogs#join")
        if not A.LIMITER.allow(f"pack-join:{u['id']}", 20, 3600):
            return self.redirect(path + "?e=slow#join")
        msg = clean(f.get("message"), P.MAX_MSG, multiline=True) if p["visibility"] == "request" else ""
        st = P.join(pid, u["id"], dogs, p["visibility"], msg)
        if st == "pending" and not (cur and cur["status"] == "pending"):
            notify_join_request(self._base(), p, u["id"], dogs, msg)
        return self.redirect(path + ("?m=p_joined#board" if st == "active" else "?m=p_requested#join"))

    def post_leave(self, pid):
        u = self.user()
        if not u:
            return self.need_login()
        p = self.visible_pack(pid)
        if not p or self._form_or_fail() is None:
            return
        cur = P.membership(pid, u["id"])
        if not cur:
            return self.redirect(pack_path(p))
        if cur["role"] == "owner":
            return self.redirect(pack_path(p) + "?e=owner#join")
        P.remove(pid, u["id"])
        return self.redirect(pack_path(p) + ("?m=p_cancelled" if cur["status"] == "pending" else "?m=p_left"))

    def post_pack_dogs(self, pid):
        p, u = self.member_pack(pid)
        if not p:
            return
        f = self._form_or_fail()
        if f is None:
            return
        mine = {d["id"] for d in A.dogs_for_user(u["id"]) if not d["hidden"]}
        dogs = [int(x) for x in f.getlist("dogs") if x.isdigit() and int(x) in mine]
        P.set_dogs(pid, u["id"], dogs)
        return self.redirect(pack_path(p) + "?m=p_dogs#join")

    # ------------------------------------------------------------ board
    def post_board(self, pid):
        p, u = self.member_pack(pid)
        if not p:
            return
        f = self._form_or_fail(W.MAX_UPLOAD_REQUEST)
        if f is None:
            return
        path = pack_path(p)
        body = clean(f.get("body"), P.MAX_POST, multiline=True)
        if not body:
            return self.redirect(path + "?e=empty#board")
        if not (A.LIMITER.allow(f"ppost:{u['id']}", 6, 600) and A.LIMITER.allow(f"ppost-day:{u['id']}", 40, 86400)):
            return self.redirect(path + "?e=slow#board")
        processed = None
        up = [x for x in f.files if x[0] == "photo" and x[2]]
        if up:
            if A.one("SELECT COUNT(*) FROM pack_photos WHERE pack_id=:p AND kind='post'", p=pid)[0] >= P.MAX_POST_PHOTOS_PER_PACK:
                return self.redirect(path + "?e=toomany#board")
            try:
                processed = A.process_image(up[0][2])
            except A.BadImage:
                return self.redirect(path + "?e=photo#board")
        post_id = P.add_post(pid, u["id"], body, processed=processed)
        return self.redirect(path + f"?m=p_posted#post-{post_id}")

    def post_board_action(self, pid, post_id, act):
        p, u = self.member_pack(pid)
        if not p:
            return
        po = P.get_post(post_id)
        if not po or po["pack_id"] != pid:
            return self.not_found_pack()
        is_org = P.is_organizer(pid, u["id"])
        path = pack_path(p)
        if act == "report":
            return self._pack_report(p, post_id, None, path + f"#post-{post_id}")
        f = self._form_or_fail()
        if f is None:
            return
        if act in ("pin", "unpin"):
            if not is_org:
                return self.msg_page("Only organizers can pin posts", "", code=403, icon="i-lock")
            P.set_pinned(post_id, act == "pin")
            return self.redirect(path + ("?m=p_pinned" if act == "pin" else "?m=p_unpinned") + "#board")
        if act == "delete":
            if not (is_org or po["user_id"] == u["id"]):
                return self.msg_page("You can't delete that post", '<p class="sub">Only the author or an organizer can delete a post.</p>',
                                     code=403, icon="i-lock")
            P.delete_post(post_id)
            return self.redirect(path + "?m=p_post_deleted#board")

    def post_pcomment(self, pid, post_id):
        p, u = self.member_pack(pid)
        if not p:
            return
        po = P.get_post(post_id)
        if not po or po["pack_id"] != pid or po["hidden"]:
            return self.not_found_pack()
        f = self._form_or_fail()
        if f is None:
            return
        path = pack_path(p)
        body = clean(f.get("body"), P.MAX_COMMENT, multiline=True)
        if not body:
            return self.redirect(path + f"?e=empty#post-{post_id}")
        if not (A.LIMITER.allow(f"pcomment:{u['id']}", 8, 600) and A.LIMITER.allow(f"pcomment-day:{u['id']}", 60, 86400)):
            return self.redirect(path + f"?e=slow#post-{post_id}")
        P.add_comment(post_id, pid, u["id"], body)
        return self.redirect(path + f"?m=p_commented#post-{post_id}")

    def post_pcomment_action(self, pid, cid, act):
        p, u = self.member_pack(pid)
        if not p:
            return
        c = P.get_comment(cid)
        if not c or c["pack_id"] != pid:
            return self.not_found_pack()
        path = pack_path(p)
        if act == "report":
            return self._pack_report(p, c["post_id"], cid, path + f"#post-{c['post_id']}")
        if self._form_or_fail() is None:
            return
        if not (P.is_organizer(pid, u["id"]) or c["user_id"] == u["id"]):
            return self.msg_page("You can't delete that comment", '<p class="sub">Only the author or an organizer can delete a comment.</p>',
                                 code=403, icon="i-lock")
        P.delete_comment(cid)
        return self.redirect(path + f"?m=p_comment_deleted#post-{c['post_id']}")

    def _pack_report(self, p, post_id, cid, back):
        f = self._form_or_fail()
        if f is None:
            return
        reason = f.get("reason") if f.get("reason") in A.REPORT_REASONS else "Something else"
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            u = self.user()
            P.add_report(p["id"], post_id, cid, u["id"] if u else None, reason, clean(f.get("details"), 1000, multiline=True), self._client_ip())
            print(f"reports: new report on pack {p['id']}" + (f" post {post_id}" if post_id else "") + (f" comment {cid}" if cid else ""), flush=True)
        path, _, frag = back.partition("#")
        return self.redirect(path + "?m=reported" + (("#" + frag) if frag else ""))

    def post_pack_report(self, pid):
        p = self.visible_pack(pid)
        if p:
            return self._pack_report(p, None, None, pack_path(p))

    # ------------------------------------------------------------ photos
    def pack_photo(self, photo_id, ext):
        info = P.photo_info(photo_id)
        nf = lambda: self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"})
        if not info:
            return nf()
        u = self.user()
        member = bool(u and P.is_member(info["pack_id"], u["id"]))
        if info["kind"] == "post":
            if not member or info["post_hidden"]:
                return nf()
            hdr = {"Cache-Control": "private, max-age=86400", "Vary": "Cookie"}
        else:
            if info["pack_hidden"] and not member:
                return nf()
            hdr = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": '"pp%d%s"' % (photo_id, ext)}
            if hdr["ETag"] in (self.headers.get("If-None-Match") or ""):
                self.send_response(304)
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.end_headers()
                return
        blob = P.photo_blob(photo_id, "full" if ext == "jpg" else "thumb")
        if blob is None:
            return nf()
        return self._emit(200, blob, "image/jpeg" if ext == "jpg" else "image/webp", hdr)

    # ------------------------------------------------------------ email preferences
    def post_pack_email_prefs(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        on = f.get("on") == "1"
        P.set_emails(u["id"], on)
        return self.redirect("/me?m=" + ("pack_emails_on" if on else "pack_emails_off") + "#pack-emails")

    def pack_unsub_page(self, q):
        uid, tok = q.get("u", [""])[0], q.get("t", [""])[0]
        if not P.check_unsub(uid, tok):
            return self.msg_page("That link didn't work", '<p class="sub">It may be incomplete. You can change pack emails from your account page.</p>'
                                 '<p><a class="btn" href="/me">Go to my account</a></p>', code=400, icon="i-mail")
        on = P.emails_on(int(uid))
        body = (f'<p class="sub">{"Pack emails are on" if on else "Pack emails are off"}: join requests for packs you organize, approvals and new pack meetups.</p>'
                f'<form method="post" action="/emails/packs"><input type="hidden" name="u" value="{e(uid)}"><input type="hidden" name="t" value="{e(tok)}">'
                f'<input type="hidden" name="action" value="{"off" if on else "on"}"><button class="btn" type="submit">'
                f'{"Turn off pack emails" if on else "Turn pack emails back on"}</button></form>'
                '<p class="small muted" style="margin-top:14px">Sign-in links and meetup emails are separate.</p>')
        return self.msg_page("Pack emails" if on else "Pack emails are off", body, icon="i-mail")

    def post_pack_unsub(self):
        """Token-authenticated (no session or CSRF needed). Also handles RFC 8058 one-click POSTs from mail apps."""
        f = self.read_form()
        if f is None:
            return self._emit(413, b"Too large", "text/plain")
        uid, tok = f.get("u"), f.get("t")
        if not uid:
            qs = parse_qs(urlsplit(self.path).query)
            uid, tok = qs.get("u", [""])[0], qs.get("t", [""])[0]
        if not P.check_unsub(uid, tok):
            return self._emit(400, b"Invalid link", "text/plain")
        on = f.get("action") == "on"
        P.set_emails(int(uid), on)
        print("packs: email preference changed via link", flush=True)
        if f.get("List-Unsubscribe") == "One-Click":
            return self._emit(200, b"Unsubscribed", "text/plain")
        msg = "You'll get pack emails again." if on else "You won't get pack emails anymore. You can turn them back on from your account page any time."
        return self.msg_page("Pack emails are " + ("on" if on else "off"), f'<p class="sub">{msg}</p><p><a class="btn" href="/packs">Browse packs</a></p>', icon="i-mail")

    # ------------------------------------------------------------ admin (behind ADMIN_KEY)
    def admin_packs(self, q):
        key = self._admin_key(q=q)
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        tr = []
        for p in P.browse(include_hidden=True):
            acts = []
            for act, lab in ((("unhide", "Unhide") if p["hidden"] else ("hide", "Hide")), ("delete", "Delete")):
                conf = ' onclick="return confirm(\'Delete this pack with its members list and board?\')"' if act == "delete" else ""
                acts.append(f'<form method="post" action="/admin/packs" style="display:inline"><input type="hidden" name="key" value="{e(key)}">'
                            f'<input type="hidden" name="id" value="{p["id"]}"><input type="hidden" name="action" value="{act}">'
                            f'<button class="linkbtn" type="submit"{conf}>{lab}</button></form>')
            flags = " ".join(x for x in ("<b>SAMPLE</b>" if p["is_sample"] else "", "hidden" if p["hidden"] else "", p["visibility"]) if x)
            tr.append(f'<tr><td>{p["id"]}</td><td><a href="{e(pack_path(p))}">{e(p["name"])}</a></td><td>{e(where_line(p))}</td>'
                      f'<td>{p["members"]}</td><td>{P.pending_count(p["id"])}</td><td>{P.post_count(p["id"])}</td><td>{flags}</td><td>{" · ".join(acts)}</td></tr>')
        bulk = (f'<form method="post" action="/admin/packs" class="formfoot" style="margin-bottom:18px"><input type="hidden" name="key" value="{e(key)}">'
                f'<button class="btn btn-ghost btn-sm" name="action" value="hide_samples">Hide all sample packs</button>'
                f'<button class="btn btn-ghost btn-sm" name="action" value="unhide_samples">Unhide samples</button>'
                f'<button class="btn btn-danger btn-sm" name="action" value="delete_samples" onclick="return confirm(\'Delete all sample packs?\')">Delete all sample packs</button>'
                f'<button class="btn btn-danger btn-sm" name="action" value="delete_all_samples" onclick="return confirm(\'Delete ALL sample packs and sample meetups?\')">Delete all samples (packs + meetups)</button></form>')
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">admin</span><h1>Packs</h1>
<p class="lead">All packs. Reports on packs, posts and comments are in <a href="/admin/reports?key={e(quote(key))}">Reports</a>. Meetups: <a href="/admin/meetups?key={e(quote(key))}">Meetups</a>.</p></div></section>
<section class="section"><div class="wrap">{bulk}<div style="overflow-x:auto"><table class="t"><thead><tr><th>#</th><th>Name</th><th>Where</th><th>Members</th><th>Pending</th><th>Posts</th><th>Flags</th><th>Actions</th></tr></thead>
<tbody>{''.join(tr) or '<tr><td colspan="8">No packs yet.</td></tr>'}</tbody></table></div></div></section>"""
        return self.page("Admin: packs", body)

    def post_admin_packs(self):
        f = self.read_form()
        key = self._admin_key(f) if f else None
        if not key:
            return self._emit(404, b"Not found", "text/plain")
        act, pid = f.get("action"), f.get("id")
        if act in ("hide", "unhide", "delete") and pid.isdigit():
            if act == "delete":
                P.delete(int(pid))
            else:
                P.set_hidden(int(pid), act == "hide")
        elif act in ("hide_samples", "unhide_samples", "delete_samples", "delete_all_samples"):
            for (i,) in A.q("SELECT id FROM packs WHERE is_sample=1"):
                if act.startswith("delete"):
                    P.delete(i)
                else:
                    P.set_hidden(i, act == "hide_samples")
            if act == "delete_all_samples":
                for (i,) in A.q("SELECT id FROM meetups WHERE is_sample=1"):
                    M.delete(i)
        print(f"admin: pack action {act}", flush=True)
        return self.redirect("/admin/packs?key=" + quote(key))

    def post_admin_pack_test_email(self):
        """Admin-only deliverability test: send one pack email type for a pack to that pack's OWNER only, marked [Test]."""
        f = self.read_form()
        if f is None or not self._admin_key(f):
            return self._emit(404, b"Not found", "text/plain")
        kind, pid = f.get("kind"), f.get("id")
        p = P.get(int(pid)) if pid.isdigit() else None
        if not p or kind not in ("request", "approved", "meetup"):
            return self._emit(400, b"Bad request", "text/plain")
        base, owner = self._base(), p["owner_user_id"]
        kw = {}
        if kind == "request":
            mem = P.membership(p["id"], owner)
            kw = dict(who="A neighbor", who_dogs=M.dog_names(mem["dogs"] if mem else [])[:1] or ["Buddy"],
                      message="Hi! We're at the run most mornings and would love to join.")
        elif kind == "meetup":
            ms = P.meetups(p["id"], 1)
            if not ms:
                return self._emit(400, b"No upcoming pack meetup to use", "text/plain")
            kw = dict(meetup=meetup_mail(base, ms[0]))
        ok = send_pack_mail(base, owner, kind, p, force=True, subject_prefix="[Test] ", **kw)
        print(f"admin: pack test email {kind} for pack {p['id']} queued={ok}", flush=True)
        return self._emit(200, json.dumps({"ok": ok, "kind": kind, "to": "pack organizer"}).encode(), "application/json",
                          {"Cache-Control": "no-store"})
