"""BarksBuds photo feed: pages and actions (mixed into server.H). Data and privacy rules live in feed.py.

  GET  /photos                     the feed, newest first (?dog=<slug>, ?run=<id>, ?before=<post id> for the next page)
  GET  /photos/new                 share a photo (sign-in required)
  POST /photos/new                 up to 4 photos, 1+ of your dogs, optional caption / dog run / stricter audience
  GET  /photos/<id>                one post with comments (OG tags for link previews)
  GET  /photos/<id>/edit           edit caption + audience (poster)
  POST /photos/<id>/edit|delete|like|comments|report
  POST /photos/comments/<id>/delete|report
  GET  /fp/<photo id>.jpg|webp     feed photo files, checked against the post's audience
"""
import html, json, re
from datetime import datetime
from urllib.parse import quote, urlencode

import accounts as A
import feed as F
import privacy as PV
import webapp as W
from webapp import clean

e = html.escape

FLASH = {"posted": "Your photo is up!", "saved": "Saved.", "deleted": "Post deleted.", "commented": "Comment added.",
         "comment_deleted": "Comment deleted.", "reported": "Thanks. Our team will take a look."}
ERRS = {"photos": "Choose at least one photo.", "toomany": f"A post can have up to {F.MAX_PHOTOS} photos.",
        "dogs": "Tag at least one of your dogs.", "run": "Pick a dog run from the list, or leave it blank.",
        "slow": "That's a lot of posts. Please try again in a little while.", "toobig": "That upload was too big. Photos can be up to 12 MB each and 40 MB together.",
        "empty": "Write a comment first.", "cslow": "That's a lot of comments. Please try again in a few minutes.",
        **{"type": W.PHOTO_ERR["type"], "big": W.PHOTO_ERR["big"], "small": W.PHOTO_ERR["small"], "read": W.PHOTO_ERR["read"]}}
HEART = ('<svg class="ico hrt" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.5s-7.5-4.6-9.3-9.2C1.4 7.8 3.6 4.5 7 4.5c2 0 3.6 1.1 5 3'
         ' 1.4-1.9 3-3 5-3 3.4 0 5.6 3.3 4.3 6.8-1.8 4.6-9.3 9.2-9.3 9.2z"/></svg>')
CHAT = '<svg class="ico" aria-hidden="true"><use href="#i-chat"/></svg>'


def post_path(pid):
    return f"/photos/{int(pid)}"


def ago(ts):
    s = max(A.now() - ts, 0)
    if s < 60:
        return "just now"
    for n, lab in ((86400 * 7, None), (86400, "d"), (3600, "h"), (60, "m")):
        if s >= n:
            if lab is None:
                import meetups as M
                d = M.to_et(ts)
                return d.strftime("%b %-d" if d.year == M.to_et(A.now()).year else "%b %-d, %Y")
            return f"{s // n}{lab} ago"
    return "just now"


def when_html(ts):
    import meetups as M
    d = M.to_et(ts)
    return f'<time datetime="{d.isoformat()}" title="{e(d.strftime("%a %b %-d, %Y, %-I:%M %p ET"))}">{e(ago(ts))}</time>'


def dog_info(ids):
    """{dog_id: {id, slug, name, user_id, photo}} (photo: avatar or first gallery photo id)."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    rows = A.q(f"""SELECT d.id, d.slug, d.name, d.user_id, d.avatar_photo_id,
                          (SELECT p.id FROM photos p WHERE p.dog_id=d.id AND p.kind='gallery' ORDER BY p.position, p.id LIMIT 1)
                   FROM dogs d WHERE d.id IN ({','.join(map(str, ids))})""")
    return {r[0]: dict(id=r[0], slug=r[1], name=r[2], user_id=r[3], photo=r[4] or r[5]) for r in rows}


def names_html(dogs, link=True):
    parts = [f'<a href="/dogs/{e(d["slug"])}">{e(d["name"])}</a>' if link else e(d["name"]) for d in dogs]
    if len(parts) <= 2:
        return " &amp; ".join(parts)
    return ", ".join(parts[:-1]) + " &amp; " + parts[-1]


def names_text(dogs):
    n = [d["name"] for d in dogs]
    return n[0] if len(n) == 1 else (", ".join(n[:-1]) + " & " + n[-1]) if n else "A dog"


def run_map():
    return W.run_index()


def run_link(rid, runs=None):
    import runpageweb
    r = (runs or run_map()).get(rid)
    if not r:
        return ""
    return (f'<a class="fp-run" href="{e(runpageweb.run_path(r))}"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>'
            f'{e(r["name"])}</a>')


def grid_html(pid, photos, alt, link=True):
    """1 photo: natural shape (clamped 4:5 .. 1.91:1). 2: side by side. 3: one big + two. 4: 2x2."""
    n = min(len(photos), F.MAX_PHOTOS)
    if not n:
        return ""
    imgs = []
    for i, ph in enumerate(photos[:n]):
        big = n == 1 or (n == 3 and i == 0)
        sizes = "(max-width: 720px) 100vw, 680px" if big else "(max-width: 720px) 50vw, 340px"
        a = f"{alt}, photo {i + 1} of {n}" if n > 1 else alt
        img = (f'<img src="/fp/{ph["id"]}.webp" srcset="/fp/{ph["id"]}.webp 640w, /fp/{ph["id"]}.jpg 1600w" sizes="{sizes}" '
               f'width="{ph["width"]}" height="{ph["height"]}" alt="{e(a)}" loading="{"eager" if i == 0 else "lazy"}" decoding="async">')
        imgs.append(img if link else f'<a href="/fp/{ph["id"]}.jpg" data-full="/fp/{ph["id"]}.jpg">{img}</a>')
    style = ""
    if n == 1:
        w, h = photos[0]["width"] or 1, photos[0]["height"] or 1
        r = max(0.8, min(1.91, w / h))
        style = f' style="aspect-ratio:{r:.3f}"'
    inner = "".join(imgs)
    if link:
        return f'<a class="fp-grid n{n}" href="{post_path(pid)}"{style} aria-label="Open this post">{inner}</a>'
    return f'<div class="fp-grid n{n}"{style}>{inner}</div>'


def strip_html(items, more_href="", more_label="See all"):
    """A row of square thumbnails linking to posts. items: [(post, first_photo, alt)]."""
    li = "".join(f'<li><a href="{post_path(p["id"])}"><img src="/fp/{ph["id"]}.webp" width="160" height="160" alt="{e(alt)}" loading="lazy" decoding="async">'
                 + (f'<span class="fs-n" aria-hidden="true">+{cnt - 1}</span>' if cnt > 1 else "") + '</a></li>'
                 for p, ph, alt, cnt in items)
    more = f'<p class="small" style="margin:12px 0 0"><a href="{e(more_href)}">{e(more_label)}</a></p>' if more_href else ""
    return f'<ul class="fstrip">{li}</ul>{more}'


def strip_items(posts):
    """[(post, first photo, alt, photo count)] for strip_html."""
    if not posts:
        return []
    pids = [p["id"] for p in posts]
    phs, dmap = F.photos_of(pids), F.dogs_of(pids)
    info = dog_info({d for ds in dmap.values() for d in ds})
    out = []
    for p in posts:
        if phs.get(p["id"]):
            dogs = [info[d] for d in dmap[p["id"]] if d in info]
            alt = f"Photo of {names_text(dogs)}" + (f": {p['caption'][:80]}" if p["caption"] else "")
            out.append((p, phs[p["id"]][0], alt, len(phs[p["id"]])))
    return out


def dog_strip(dog, V, is_owner=False, limit=6):
    """'Photos' strip for a dog's profile: the newest posts tagging this dog that the viewer may see."""
    try:
        posts = F.visible(F.recent(dog_id=dog["id"], limit=60), V, "view")[:limit]
    except Exception as ex:  # never break a profile over the strip
        print(f"photos: dog strip failed: {type(ex).__name__}", flush=True)
        return ""
    if not posts and not is_owner:
        return ""
    if not posts:
        return (f'<div class="panel fstrip-panel" id="feed-photos"><h2>In the photo feed</h2><p class="muted" style="margin:0 0 14px">Share a photo of {e(dog["name"])} '
                f'with the community.</p><a class="btn btn-sm" href="/photos/new?dog={dog["id"]}"><svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg>Share a photo</a></div>')
    share = (f' <a class="fs-add" href="/photos/new?dog={dog["id"]}">+ Share a photo</a>' if is_owner else "")
    return (f'<div class="panel fstrip-panel" id="feed-photos"><h2>In the photo feed{share}</h2>'
            + strip_html(strip_items(posts), f"/photos?dog={quote(dog['slug'])}", f"See all of {dog['name']}'s photo posts") + "</div>")


def run_strip(rid, V, limit=6):
    try:
        posts, _ = F.page(V, run_id=rid, limit=limit)
    except Exception as ex:
        print(f"photos: run strip failed: {type(ex).__name__}", flush=True)
        return ""
    if not posts:
        return ""
    return ('<div class="panel fstrip-panel"><h2>Photos from this run</h2>'
            + strip_html(strip_items(posts), f"/photos?run={quote(rid)}", "See all photos from this run") + "</div>")


def home_html(limit=6):
    """Homepage strip: a few recent Public photo posts. Only shown once there are at least 3, so it never looks empty."""
    try:
        posts, _ = F.page(PV.SIGNED_OUT, limit=limit)
        if len(posts) < 3:
            return ""
        items = strip_items(posts)
    except Exception as ex:
        print(f"photos: homepage strip skipped ({type(ex).__name__})", flush=True)
        return ""
    li = "".join(f'<li><a href="{post_path(p["id"])}"><img src="/fp/{ph["id"]}.webp" width="200" height="200" alt="{e(alt)}" loading="lazy" decoding="async"></a></li>'
                 for p, ph, alt, _n in items)
    return (f'<section class="section homephotos" aria-labelledby="hp-title"><div class="wrap"><div class="hp-head"><div><span class="eyebrow">fresh from the run</span>'
            f'<h2 id="hp-title">Photos from the pack</h2></div><a class="btn btn-ghost btn-sm" href="/photos">See the photo feed</a></div>'
            f'<ul class="hp-strip">{li}</ul></div></section>')


class PhotoRoutes:
    # ------------------------------------------------------------ routing
    def photo_get(self, path, q):
        if not (path.startswith("/photos") or path.startswith("/fp/")):
            return False
        self._app_reset()
        routes = [(r"/photos/?", lambda: self.feed_page(q)), (r"/photos/new", lambda: self.new_photo_page(q=q)),
                  (r"/photos/(\d+)", lambda i: self.photo_post_page(int(i), q)), (r"/photos/(\d+)/edit", lambda i: self.edit_photo_page(int(i))),
                  (r"/fp/(\d+)\.(jpg|webp)", lambda i, x: self.feed_photo(int(i), x))]
        for pat, fn in routes:
            m = re.fullmatch(pat, path)
            if m:
                fn(*m.groups())
                return True
        return False

    def photo_post(self, path, q):
        if not path.startswith("/photos/"):
            return False
        self._app_reset()
        routes = [(r"/photos/new", self.post_new_photo), (r"/photos/(\d+)/(edit|delete|like|comments|report)", self.post_photo_act),
                  (r"/photos/comments/(\d+)/(delete|report)", self.post_photo_comment_act)]
        for pat, fn in routes:
            m = re.fullmatch(pat, path)
            if m:
                fn(*m.groups())
                return True
        return False

    # ------------------------------------------------------------ helpers
    def _fp_ctx(self, posts):
        """Everything the cards need, in a few queries."""
        u = self.user()
        pids = [p["id"] for p in posts]
        dmap, phs = F.dogs_of(pids), F.photos_of(pids)
        info = dog_info({d for ds in dmap.values() for d in ds})
        meta = PV._meta({d for ds in dmap.values() for d in ds})
        likes, coms, mine = F.counts(pids, u["id"] if u else None)
        st = PV.settings_map(list({p["user_id"] for p in posts}))
        names = {r[0]: r[1] or "" for r in A.q(f"SELECT id, display_name FROM users WHERE id IN ({','.join(str(p['user_id']) for p in posts) or '0'})")}
        return dict(u=u, dmap=dmap, phs=phs, info=info, meta=meta, likes=likes, coms=coms, mine=mine, st=st, names=names, runs=run_map())

    def _poster_name(self, p, ctx):
        s = ctx["st"].get(p["user_id"]) or PV.LEGACY
        return ctx["names"].get(p["user_id"], "") if s["priv_owner_name"] else ""

    def like_btn(self, p, ctx):
        n = ctx["likes"].get(p["id"], 0)
        lab = f'<span class="fp-n">{n}</span><span class="sr-only"> like{"s" if n != 1 else ""}</span>'
        if not ctx["u"]:
            return f'<a class="fp-like" href="{e(self.signin_href(post_path(p["id"])))}" aria-label="Sign in to like this post">{HEART}{lab}</a>'
        on = p["id"] in ctx["mine"]
        return (f'<form method="post" action="/photos/{p["id"]}/like" class="fp-likef">{self.csrf_field()}'
                f'<button class="fp-like" type="submit" aria-pressed="{"true" if on else "false"}" title="{"Unlike" if on else "Like"}">'
                f'{HEART}<span class="sr-only">{"Unlike" if on else "Like"}, </span>{lab}</button></form>')

    def card_html(self, p, ctx, full=False):
        dogs = [ctx["info"][d] for d in ctx["dmap"].get(p["id"], []) if d in ctx["info"]]
        avs = "".join((f'<img src="/p/{d["photo"]}.webp" width="44" height="44" alt="">' if d["photo"] else
                       '<span class="noph"><svg class="ico" aria-hidden="true"><use href="#i-paw"/></svg></span>') for d in dogs[:3])
        who = self._poster_name(p, ctx)
        metas = [ctx["meta"][d] for d in ctx["dmap"].get(p["id"], []) if d in ctx["meta"]]
        aud = F.strictest(p, metas)
        aud_html = ("" if aud == "public" else
                    f' · <span class="fp-aud" title="Who can see this post"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg>{e(PV.VIS_LABEL.get(aud, ""))}</span>')
        hidden = ' <span class="badge">Hidden by our team</span>' if p["hidden"] else ""
        meta_line = " · ".join(x for x in (e(who) if who else "", f'<a href="{post_path(p["id"])}">{when_html(p["created_at"])}</a>') if x)
        alt = f"Photo of {names_text(dogs)}" + (f": {p['caption'][:100]}" if p["caption"] else "")
        nc = ctx["coms"].get(p["id"], 0)
        comments_link = (f'<a class="fp-com" href="{post_path(p["id"])}#comments">{CHAT}<span class="fp-n">{nc}</span>'
                         f'<span class="sr-only"> comment{"s" if nc != 1 else ""}</span></a>')
        cap = f'<p class="fp-cap">{e(p["caption"])}</p>' if p["caption"] else ""
        run = run_link(p["run_id"], ctx["runs"]) if p["run_id"] else ""
        mine = ctx["u"] and ctx["u"]["id"] == p["user_id"]
        tools = ""
        if mine and not full:
            tools = (f'<span class="fp-tools"><a href="/photos/{p["id"]}/edit">Edit</a></span>')
        return f"""<article class="fpost" id="post-{p["id"]}">
<header class="fp-head"><span class="fp-avs">{avs}</span><div class="fp-who"><b>{names_html(dogs)}</b><span class="fp-meta">{meta_line}{aud_html}{hidden}</span></div>{tools}</header>
{grid_html(p["id"], ctx["phs"].get(p["id"], []), alt, link=not full)}
<div class="fp-body"><div class="fp-acts">{self.like_btn(p, ctx)}{comments_link}{run}</div>{cap}</div></article>"""

    def _post_or_404(self, pid):
        p = F.get(pid)
        if not p:
            self.msg_page("We couldn't find that post", '<p class="sub">It may have been deleted.</p><p><a class="btn" href="/photos">See the photo feed</a></p>', code=404)
            return None, None
        ds = F.dogs_of([pid])[pid]
        if not F.can_see(p, ds, self.pv()):
            u = self.user()
            body = ('<p class="sub">Whoever shared this chose who can see it.</p>' +
                    ("" if u else f'<p><a class="btn" href="{e(self.signin_href(post_path(pid)))}">Sign in</a></p>'
                                  '<p class="small muted">Some photos are only visible to signed-in members.</p>') +
                    '<p><a class="btn btn-ghost" href="/photos">See the photo feed</a></p>')
            self.msg_page("This post is private", body, code=403 if p and not p["hidden"] else 404, icon="i-lock")
            return None, None
        return p, ds

    # ------------------------------------------------------------ feed
    def feed_page(self, q):
        u = self.user()
        V = self.pv()
        before = q.get("before", [""])[0]
        before = int(before) if before.isdigit() else None
        dslug, rid = q.get("dog", [""])[0], q.get("run", [""])[0]
        dog, run, filt = None, None, ""
        if dslug:
            dog = A.dog_by_slug(dslug)
            if not dog or not (PV.can_view(dog, V)):
                return self.msg_page("We couldn't find that dog", '<p class="sub">This profile may be private or removed.</p>'
                                     '<p><a class="btn" href="/photos">See the photo feed</a></p>', code=404)
            filt = f'Photos of <a href="/dogs/{e(dog["slug"])}">{e(dog["name"])}</a>'
        elif rid:
            run = run_map().get(rid)
            if not run:
                return self.redirect("/photos")
            filt = f'Photos from {run_link(rid)}'
        purpose = "view" if dog else "list"
        posts, nxt = F.page(V, before=before, dog_id=dog["id"] if dog else None, run_id=rid or None, purpose=purpose)
        ctx = self._fp_ctx(posts) if posts else None
        cards = "".join(self.card_html(p, ctx) for p in posts)
        params = {k: v for k, v in (("dog", dslug), ("run", rid)) if v}
        more = ""
        if nxt:
            href = "/photos?" + urlencode({**params, "before": nxt})
            more = (f'<div class="fp-more"><a class="btn btn-ghost" href="{e(href)}" data-more>Load more photos</a>'
                    f'<div class="fp-loading" hidden>{self._jack("Fetching more photos…")}</div></div>')
        if self.headers.get("X-Partial") == "1":  # "Load more" fetches just the cards + the next link
            return self._emit(200, cards + more, headers={"Cache-Control": "no-store", "Vary": "Cookie"})
        share = (f'<a class="btn" href="/photos/new{("?dog=" + str(dog["id"])) if dog and u and PV.is_owner(dog, V) else ("?run=" + quote(rid)) if rid else ""}">'
                 '<svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg>Share a photo</a>' if u else
                 f'<a class="btn" href="{e(self.signin_href("/photos/new"))}"><svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg>Sign in to share a photo</a>')
        if posts:
            listing = f'<div class="fp-list" id="fp-list">{cards}{more}</div>'
        elif before:
            listing = '<div class="empty"><p style="margin:0">That\'s everything. <a href="/photos">Back to the newest photos</a></p></div>'
        else:
            listing = (f'<div class="empty fp-empty">{self._jack("No photos yet, be the first!")}'
                       f'<p class="muted" style="margin:6px 0 18px">Share a photo of your dog at the run, on a walk or napping on the couch.</p>{share}</div>')
        filt_html = (f'<p class="fp-filter">{filt} <a class="fp-clear" href="/photos" aria-label="Show all photos">&times; Show all</a></p>' if filt else "")
        signed_out_note = ("" if u else '<p class="small muted" style="margin:14px 0 0">You\'re seeing public posts. '
                           f'<a href="{e(self.signin_href("/photos"))}">Sign in</a> to see photos shared with members.</p>')
        body = f"""<section class="phead fp-phead"><div class="wrap"><div class="fp-hrow"><div><span class="eyebrow">photo feed</span><h1>Photos from the pack</h1>
<p class="lead">Dogs at the run, on the trail and on the couch, shared by BarksBuds members.</p></div><div class="fp-hcta">{share}</div></div>{signed_out_note}</div></section>
<section class="section fp-section"><div class="wrap fp-wrap">{filt_html}{listing}</div></section>"""
        js = """<script>(function(){var list=document.getElementById('fp-list');if(!list||!window.fetch)return;
list.addEventListener('click',function(ev){var a=ev.target.closest('a[data-more]');if(!a)return;ev.preventDefault();var box=a.parentNode,ld=box.querySelector('.fp-loading');
a.hidden=true;if(ld)ld.hidden=false;fetch(a.href,{headers:{'X-Partial':'1'},credentials:'same-origin'}).then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(h){
var t=document.createElement('div');t.innerHTML=h;box.remove();while(t.firstChild)list.appendChild(t.firstChild)}).catch(function(){location.href=a.href})});})();</script>""" + LIKE_JS
        title = (f"Photos of {dog['name']}" if dog else f"Photos from {run['name']}" if run else "Photo feed")
        return self.page(title, body, desc="Dog photos shared by BarksBuds members: dogs at the run, on the trail and at home.",
                         canonical="/photos", index=False, active="photos", scripts=js, flash=FLASH.get(q.get("m", [""])[0], ""),
                         og={"title": "Photos from the pack · BarksBuds", "image": self._base() + "/img/og-image.jpg?v=jack3", "w": 1200, "h": 630})

    def _jack(self, label, static=False):
        import search
        return search.jack_runner(label, "fp-jack" + (" jk-static" if static else ""))

    # ------------------------------------------------------------ one post
    def photo_post_page(self, pid, q):
        p, ds = self._post_or_404(pid)
        if not p:
            return
        u = self.user()
        V = self.pv()
        ctx = self._fp_ctx([p])
        card = self.card_html(p, ctx, full=True)
        mine = bool(u and u["id"] == p["user_id"])
        metas = [ctx["meta"][d] for d in ds if d in ctx["meta"]]
        owners = F._owners(metas)
        blocks = V.blocks() if u else set()
        cl = [c for c in F.comments(pid) if not (c["hidden"] and not (u and u["id"] == c["user_id"])) and c["user_id"] not in blocks]
        cst = PV.settings_map(list({c["user_id"] for c in cl}))
        reasons = "".join(f'<option>{e(r)}</option>' for r in A.REPORT_REASONS)
        items = []
        for c in cl:
            s = cst.get(c["user_id"]) or PV.LEGACY
            nm = (c["name"] if s["priv_owner_name"] else "") or "A BarksBuds member"
            if c["user_id"] in owners or c["user_id"] == p["user_id"]:
                nm += " (poster)" if c["user_id"] == p["user_id"] else ""
            acts = []
            if u and (u["id"] == c["user_id"] or mine):
                acts.append(f'<form method="post" action="/photos/comments/{c["id"]}/delete" onsubmit="return confirm(\'Delete this comment?\')">{self.csrf_field()}'
                            '<button class="linkbtn" type="submit">Delete</button></form>')
            if u and u["id"] != c["user_id"]:
                acts.append(f'<details class="creport"><summary>Report</summary><form method="post" action="/photos/comments/{c["id"]}/report">{self.csrf_field()}'
                            f'<label class="sr-only" for="cr{c["id"]}">Reason</label><select id="cr{c["id"]}" name="reason">{reasons}</select>'
                            '<button class="btn btn-sm btn-ghost" type="submit">Send report</button></form></details>')
            hid = ' <span class="badge">Hidden by our team</span>' if c["hidden"] else ""
            items.append(f'<li id="c-{c["id"]}"><div class="chead"><b>{e(nm)}</b><span>{when_html(c["created_at"])}</span>{hid}</div>'
                         f'<p class="cbody">{e(c["body"])}</p>{f"""<div class="cacts">{"".join(acts)}</div>""" if acts else ""}</li>')
        err = ERRS.get(q.get("e", [""])[0], "")
        if u:
            cform = (f'<form method="post" action="/photos/{pid}/comments" class="pcform fp-cform">{self.csrf_field()}'
                     f'<label class="sr-only" for="cbody">Add a comment</label><input type="text" id="cbody" name="body" maxlength="{F.MAX_COMMENT}" '
                     f'placeholder="Say something nice…" required autocomplete="off"><button class="btn btn-sm" type="submit">Post</button></form>'
                     + (f'<p class="err" role="alert">{e(err)}</p>' if err else ""))
        else:
            cform = f'<p class="small" style="margin:12px 0 0"><a href="{e(self.signin_href(post_path(pid)))}">Sign in</a> to like and comment.</p>'
        clist = f'<ul class="clist pcomments">{"".join(items)}</ul>' if items else '<p class="muted small" style="margin:0">No comments yet.</p>'
        owner_tools, report = "", ""
        if mine:
            owner_tools = (f'<div class="fp-owner"><a class="btn btn-ghost btn-sm" href="/photos/{pid}/edit">Edit caption</a>'
                           f'<form method="post" action="/photos/{pid}/delete" onsubmit="return confirm(\'Delete this post and its photos? This can\\\'t be undone.\')">'
                           f'{self.csrf_field()}<button class="btn btn-danger btn-sm" type="submit">Delete post</button></form></div>')
        else:
            report = f"""<details class="report fp-report"><summary>Report this post</summary>
<form method="post" action="/photos/{pid}/report">{self.csrf_field()}
<div class="field"><label for="reason">What's wrong?</label><select id="reason" name="reason">{reasons}</select></div>
<div class="field"><label for="details">Details <span class="opt">(optional)</span></label><textarea id="details" name="details" maxlength="1000" rows="3"></textarea></div>
<button class="btn btn-sm" type="submit">Send report</button><p class="small muted" style="margin:10px 0 0">Reports go to the BarksBuds team, not to the poster.</p></form></details>"""
        dogs = [ctx["info"][d] for d in ds if d in ctx["info"]]
        title = f"{names_text(dogs)} on BarksBuds"
        desc = p["caption"] or f"A photo of {names_text(dogs)}, shared on BarksBuds."
        if len(desc) > 158:
            desc = desc[:155].rsplit(" ", 1)[0] + "…"
        phs = ctx["phs"].get(pid, [])
        og = {"title": title, "desc": desc, "type": "article", "alt": f"Photo of {names_text(dogs)}",
              "image": self._base() + (f"/fp/{phs[0]['id']}.jpg" if phs else "/img/og-image.jpg?v=jack3")}
        og.update(w=phs[0]["width"], h=phs[0]["height"]) if phs else og.update(w=1200, h=630)
        body = f"""<section class="section fp-section fp-single"><div class="wrap fp-wrap">
<p class="fp-back"><a href="/photos">&larr; Photo feed</a></p>{card}{owner_tools}
<div class="panel fp-comments" id="comments"><h2>Comments</h2>{clist}{cform}</div>{report}</div></section>
<dialog class="lb" aria-label="Photo"><button class="x" type="button" aria-label="Close">&times;</button><img alt=""></dialog>"""
        js = """<script>(function(){var dl=document.querySelector('dialog.lb');if(!dl||!dl.showModal)return;var im=dl.querySelector('img');
document.querySelectorAll('.fp-grid a').forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();im.src=a.dataset.full;im.alt=a.querySelector('img').alt;dl.showModal()})});
dl.addEventListener('click',function(ev){if(ev.target===dl||ev.target.classList.contains('x'))dl.close()})})();</script>""" + LIKE_JS
        return self.page(title, body, desc=desc, canonical=post_path(pid), og=og, index=F.indexable(p, ds, ctx["meta"]) and not p["hidden"],
                         active="photos", scripts=js, flash=FLASH.get(q.get("m", [""])[0], ""))

    # ------------------------------------------------------------ files
    def feed_photo(self, photo_id, ext):
        nf = lambda: self._emit(404, b"Not found", "text/plain", {"Cache-Control": "no-store"})
        pid = F.photo_post(photo_id)
        p = F.get(pid) if pid else None
        if not p:
            return nf()
        ds = F.dogs_of([pid])[pid]
        meta = PV._meta(ds)
        if not F.can_see(p, ds, self.pv(), meta):
            return nf()
        public = F.is_public(p, ds, meta)
        etag = '"fp%d%s"' % (photo_id, ext)
        hdr = ({"Cache-Control": "public, max-age=86400", "ETag": etag} if public else
               {"Cache-Control": "private, max-age=600", "ETag": etag, "Vary": "Cookie"})
        if not (public and F.indexable(p, ds, meta)):
            hdr["X-Robots-Tag"] = "noindex"
        if etag in (self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            for k, v in hdr.items():
                self.send_header(k, v)
            self.end_headers()
            return
        blob = F.photo_blob(photo_id, "full" if ext == "jpg" else "thumb")
        if blob is None:
            return nf()
        return self._emit(200, blob, "image/jpeg" if ext == "jpg" else "image/webp", hdr)

    # ------------------------------------------------------------ new post
    def new_photo_page(self, vals=None, err="", code=200, q=None):
        u = self.user()
        if not u:
            return self.need_login("/photos/new")
        q = q or {}
        dogs = A.dogs_for_user(u["id"])
        if not dogs:
            return self.msg_page("Add your dog first", '<p class="sub">Photo posts are tagged with your dogs, so add a profile for your dog first.</p>'
                                 '<p><a class="btn" href="/me/dogs/new">Add your dog</a></p>', icon="i-camera")
        vals = vals or {}
        pre_dog = q.get("dog", [""])[0]
        chosen = set(vals.get("dogs") or ([int(pre_dog)] if pre_dog.isdigit() else ([dogs[0]["id"]] if len(dogs) == 1 else [])))
        ticks = "".join(f'<label class="tick"><input type="checkbox" name="dogs" value="{d["id"]}" data-vis="{e(d.get("visibility") or "public")}" '
                        f'data-name="{e(d["name"])}"{" checked" if d["id"] in chosen else ""}><span>{e(d["name"])}</span></label>' for d in dogs)
        run_sel = vals.get("run", q.get("run", [""])[0])
        groups = {}
        for r in W.RUNS():
            groups.setdefault(r.get("county") or "Other", []).append(r)
        opts = ['<option value="">No dog run</option>']
        for county in [a for a in A.AREA_NAMES if a in groups] + [c for c in groups if c not in A.AREA_NAMES]:
            opts.append(f'<optgroup label="{e(W.area_label(county))}">' + "".join(
                f'<option value="{e(r["id"])}"{" selected" if r["id"] == run_sel else ""}>{e(r["name"])}'
                + (f' ({e(r.get("town_or_neighborhood"))})' if r.get("town_or_neighborhood") else "") + '</option>'
                for r in sorted(groups[county], key=lambda r: r["name"])) + '</optgroup>')
        vis = vals.get("vis", "")
        vopts = "".join(f'<option value="{k}"{" selected" if vis == k else ""}>{e(lab)}</option>' for k, lab in F.OVERRIDES)
        st = PV.settings(u["id"])
        list_note = ("" if st["priv_search"] == "everyone" else
                     '<p class="notice small">Your <a href="/me/privacy">privacy settings</a> keep your dogs out of lists, so this post won\'t appear in the '
                     'main photo feed. It still shows on your dog\'s profile and at its own link for people allowed to see it.</p>')
        errh = f'<p class="formerr" role="alert">{e(err)}</p>' if err else ""
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">share</span><h1>Share a photo</h1>
<p class="lead">Post up to {F.MAX_PHOTOS} photos of your dog. We remove location data and other hidden info from every photo.</p></div></section>
<section class="section fp-section"><div class="wrap fp-wrap">
<form class="panel fp-form" method="post" action="/photos/new" enctype="multipart/form-data" id="fpf">{self.csrf_field()}{errh}{list_note}
<div class="field"><span class="lab">Photos</span>
<div class="drop fp-drop"><svg class="ico" aria-hidden="true" style="width:34px;height:34px;color:var(--red)"><use href="#i-camera"/></svg>
<label for="fp-photos"><b>Choose photos</b> <span class="muted small">(JPEG, PNG, WebP or GIF, up to 12 MB each, {F.MAX_PHOTOS} max)</span></label>
<input id="fp-photos" name="photos" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple required>
<span class="err" role="alert" id="fp-perr"></span></div>
<ul class="fp-prev" id="fp-prev" aria-live="polite"></ul></div>
<div class="field"><fieldset class="checks-grid"><legend>Who's in it?</legend>{ticks}</fieldset></div>
<div class="field"><label for="fp-cap">Caption <span class="opt">(optional)</span></label>
<textarea id="fp-cap" name="caption" maxlength="{F.MAX_CAPTION}" rows="3" placeholder="Zoomies at the run this morning!">{e(vals.get("caption", ""))}</textarea>
<span class="help"><span id="fp-left">{F.MAX_CAPTION - len(vals.get("caption", ""))}</span> characters left</span></div>
<div class="field"><label for="fp-run">Dog run or park <span class="opt">(optional)</span></label><select id="fp-run" name="run">{"".join(opts)}</select></div>
<div class="field"><label for="fp-vis">Who can see this post</label><select id="fp-vis" name="vis">{vopts}</select>
<span class="help" id="fp-vhelp">A post is never more open than the profiles of the dogs in it.</span></div>
<div class="formfoot"><button class="btn" type="submit"><svg class="ico" aria-hidden="true"><use href="#i-camera"/></svg>Share photo</button><a href="/photos">Cancel</a></div>
<div class="fp-loading" hidden id="fp-busy">{self._jack("Uploading…")}</div>
</form></div></section>"""
        js = f"""<script>(function(){{var MAX={F.MAX_PHOTOS},inp=document.getElementById('fp-photos'),pv=document.getElementById('fp-prev'),er=document.getElementById('fp-perr');
inp.addEventListener('change',function(){{pv.innerHTML='';er.textContent='';var fs=[].slice.call(inp.files||[]);if(fs.length>MAX){{er.textContent='Pick up to '+MAX+' photos.';}}
fs.slice(0,MAX).forEach(function(f){{var li=document.createElement('li'),im=document.createElement('img');im.alt='';im.src=URL.createObjectURL(f);li.appendChild(im);pv.appendChild(li)}})}});
var cap=document.getElementById('fp-cap'),left=document.getElementById('fp-left');cap.addEventListener('input',function(){{left.textContent={F.MAX_CAPTION}-cap.value.length}});
var LBL={json.dumps(PV.VIS_LABEL)},R={json.dumps(F.RANK)},vh=document.getElementById('fp-vhelp'),sel=document.getElementById('fp-vis');
function vis(){{var c=[].slice.call(document.querySelectorAll('input[name=dogs]:checked'));if(!c.length){{vh.textContent='A post is never more open than the profiles of the dogs in it.';return}}
var k='public';c.forEach(function(x){{if(R[x.dataset.vis]>R[k])k=x.dataset.vis}});if(sel.value&&R[sel.value]>R[k])k=sel.value;
vh.textContent='Who can see it: '+LBL[k]+(k==='public'?' (anyone, even people who aren\\u2019t signed in).':'.')}}
document.querySelectorAll('input[name=dogs]').forEach(function(x){{x.addEventListener('change',vis)}});sel.addEventListener('change',vis);vis();
document.getElementById('fpf').addEventListener('submit',function(ev){{if((inp.files||[]).length>MAX){{ev.preventDefault();er.textContent='Pick up to '+MAX+' photos.';return}}
document.getElementById('fp-busy').hidden=false}});}})();</script>"""
        return self.page("Share a photo", body, code=code, active="photos", scripts=js)

    def post_new_photo(self):
        u = self.user()
        if not u:
            return self.need_login("/photos/new")
        f = self.read_form(W.MAX_UPLOAD_REQUEST)
        if f is None:
            return self.new_photo_page(err=ERRS["toobig"], code=413)
        if not self.csrf_ok(f):
            return self.csrf_fail()
        mine = {d["id"]: d for d in A.dogs_for_user(u["id"])}
        dog_ids = [int(x) for x in f.getlist("dogs") if x.isdigit() and int(x) in mine]
        caption = clean(f.get("caption"), F.MAX_CAPTION, multiline=True)
        rid = f.get("run").strip()
        vis = f.get("vis") if f.get("vis") in F.OVR_KEYS else ""
        vals = dict(dogs=dog_ids, caption=caption, run=rid, vis=vis)
        files = [x for x in f.files if x[0] == "photos" and x[2]]
        if not files:
            return self.new_photo_page(vals, ERRS["photos"], 400)
        if len(files) > F.MAX_PHOTOS:
            return self.new_photo_page(vals, ERRS["toomany"], 400)
        if not dog_ids:
            return self.new_photo_page(vals, ERRS["dogs"], 400)
        if rid and rid not in run_map():
            return self.new_photo_page(vals, ERRS["run"], 400)
        if not (A.LIMITER.allow(f"fpost:{u['id']}", 5, 600) and A.LIMITER.allow(f"fpost-day:{u['id']}", 30, 86400)):
            return self.new_photo_page(vals, ERRS["slow"], 429)
        processed = []
        for _n, _fn, data in files:
            try:
                processed.append(A.process_image(data))
            except A.BadImage as ex:
                s = str(ex)
                k = "big" if "MB" in s else "small" if "small" in s else "type" if "isn't" in s else "read"
                return self.new_photo_page(vals, ERRS[k], 400)
        pid = F.create(u["id"], dog_ids, rid, caption, vis, processed)
        print(f"photos: new post {pid} ({len(processed)} photo{'s' if len(processed) != 1 else ''})", flush=True)
        return self.redirect(post_path(pid) + "?m=posted")

    # ------------------------------------------------------------ edit / delete / like / comment / report
    def edit_photo_page(self, pid, err=""):
        u = self.user()
        if not u:
            return self.need_login(f"/photos/{pid}/edit")
        p = F.get(pid)
        if not p or p["user_id"] != u["id"]:
            return self.msg_page("You can't edit that post", '<p class="sub">Only the person who shared a post can edit it.</p>', code=404, icon="i-lock")
        vopts = "".join(f'<option value="{k}"{" selected" if p["vis"] == k else ""}>{e(lab)}</option>' for k, lab in F.OVERRIDES)
        ds = F.dogs_of([pid])[pid]
        metas = list(PV._meta(ds).values())
        dogv = F.strictest(dict(p, vis=""), metas)
        phs = F.photos_of([pid])[pid]
        thumbs = "".join(f'<li><img src="/fp/{ph["id"]}.webp" alt=""></li>' for ph in phs)
        body = f"""<section class="phead"><div class="wrap"><span class="eyebrow">edit</span><h1>Edit your post</h1></div></section>
<section class="section fp-section"><div class="wrap fp-wrap"><form class="panel fp-form" method="post" action="/photos/{pid}/edit">{self.csrf_field()}
{f'<p class="formerr" role="alert">{e(err)}</p>' if err else ''}<ul class="fp-prev" style="margin-bottom:18px">{thumbs}</ul>
<div class="field"><label for="fp-cap">Caption <span class="opt">(optional)</span></label>
<textarea id="fp-cap" name="caption" maxlength="{F.MAX_CAPTION}" rows="3">{e(p["caption"])}</textarea></div>
<div class="field"><label for="fp-vis">Who can see this post</label><select id="fp-vis" name="vis">{vopts}</select>
<span class="help">Your dog's profile is <b>{e(PV.VIS_LABEL.get(dogv, ""))}</b>, so this post is never more open than that.</span></div>
<div class="formfoot"><button class="btn" type="submit">Save</button><a href="{post_path(pid)}">Cancel</a><span class="spacer"></span></div></form>
<form method="post" action="/photos/{pid}/delete" class="fp-delform" onsubmit="return confirm('Delete this post and its photos? This can\\'t be undone.')">{self.csrf_field()}
<button class="btn btn-danger btn-sm" type="submit">Delete this post</button></form></div></section>"""
        return self.page("Edit your post", body, active="photos")

    def post_photo_act(self, pid, act):
        pid = int(pid)
        u = self.user()
        if not u:
            return self.need_login(post_path(pid))
        p, ds = self._post_or_404(pid)
        if not p:
            return
        if act == "report":
            return self._fp_report(pid, None, post_path(pid))
        if act == "edit":
            f = self._form_or_fail()
            if f is None:
                return
            if p["user_id"] != u["id"]:
                return self.msg_page("You can't edit that post", "", code=403, icon="i-lock")
            vis = f.get("vis") if f.get("vis") in F.OVR_KEYS else ""
            F.update(pid, clean(f.get("caption"), F.MAX_CAPTION, multiline=True), vis)
            return self.redirect(post_path(pid) + "?m=saved")
        if act == "delete":
            f = self._form_or_fail()
            if f is None:
                return
            if p["user_id"] != u["id"]:
                return self.msg_page("You can't delete that post", '<p class="sub">Only the person who shared a post can delete it.</p>', code=403, icon="i-lock")
            F.delete(pid)
            print(f"photos: post {pid} deleted by its poster", flush=True)
            return self.redirect("/photos?m=deleted")
        if act == "like":
            f = self._form_or_fail()
            if f is None:
                return
            if not A.LIMITER.allow(f"flike:{u['id']}", 60, 600):
                return self._json_or_back({"error": "slow"}, post_path(pid), 429)
            if p["hidden"]:
                return self._json_or_back({"error": "hidden"}, post_path(pid), 403)
            on, n = F.toggle_like(pid, u["id"])
            return self._json_or_back({"liked": on, "count": n}, (self._back() or post_path(pid)) + f"#post-{pid}")
        if act == "comments":
            f = self._form_or_fail()
            if f is None:
                return
            if p["hidden"]:
                return self.redirect(post_path(pid))
            body = clean(f.get("body"), F.MAX_COMMENT, multiline=True)
            if not body:
                return self.redirect(post_path(pid) + "?e=empty#comments")
            if not (A.LIMITER.allow(f"fcomment:{u['id']}", 8, 600) and A.LIMITER.allow(f"fcomment-day:{u['id']}", 60, 86400)):
                return self.redirect(post_path(pid) + "?e=cslow#comments")
            cid = F.add_comment(pid, u["id"], body)
            return self.redirect(post_path(pid) + f"?m=commented#c-{cid}")

    def post_photo_comment_act(self, cid, act):
        cid = int(cid)
        u = self.user()
        if not u:
            return self.need_login()
        c = F.get_comment(cid)
        if not c:
            return self.msg_page("We couldn't find that comment", "", code=404)
        p, _ds = self._post_or_404(c["post_id"])
        if not p:
            return
        back = post_path(p["id"])
        if act == "report":
            return self._fp_report(p["id"], cid, back + "#comments")
        if self._form_or_fail() is None:
            return
        if u["id"] not in (c["user_id"], p["user_id"]):
            return self.msg_page("You can't delete that comment", '<p class="sub">Only the comment\'s author or the person who shared the post can delete it.</p>',
                                 code=403, icon="i-lock")
        F.delete_comment(cid)
        return self.redirect(back + "?m=comment_deleted#comments")

    def _fp_report(self, pid, cid, back):
        f = self._form_or_fail()
        if f is None:
            return
        reason = f.get("reason") if f.get("reason") in A.REPORT_REASONS else "Something else"
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600):
            u = self.user()
            F.add_report(pid, cid, u["id"] if u else None, reason, clean(f.get("details"), 1000, multiline=True), self._client_ip())
            print(f"reports: new report on photo post {pid}" + (f" comment {cid}" if cid else ""), flush=True)
        path, _, frag = back.partition("#")
        return self.redirect(path + "?m=reported" + (("#" + frag) if frag else ""))

    def _back(self):
        from urllib.parse import urlsplit
        ref = urlsplit(self.headers.get("Referer") or "")
        if ref.netloc == (self.headers.get("Host") or "") and ref.path.startswith("/photos"):
            return W.safe_next(ref.path + ("?" + ref.query if ref.query else ""))
        return ""

    def _json_or_back(self, obj, back, code=200):
        if "application/json" in (self.headers.get("Accept") or ""):
            return self._emit(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})
        return self.redirect(back)


LIKE_JS = """<script>(function(){if(!window.fetch)return;document.addEventListener('submit',function(ev){var f=ev.target;if(!f.classList||!f.classList.contains('fp-likef'))return;
ev.preventDefault();var b=f.querySelector('button'),n=b.querySelector('.fp-n');b.disabled=true;fetch(f.action,{method:'POST',body:new FormData(f),credentials:'same-origin',headers:{'Accept':'application/json'}})
.then(function(r){return r.json()}).then(function(j){if(j.count===undefined)throw 0;b.setAttribute('aria-pressed',j.liked?'true':'false');b.title=j.liked?'Unlike':'Like';n.textContent=j.count;
b.querySelector('.sr-only').textContent=(j.liked?'Unlike':'Like')+', ';b.classList.toggle('pop',j.liked)}).catch(function(){f.submit()}).then(function(){b.disabled=false})});})();</script>"""
