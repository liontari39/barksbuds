"""BarksBuds Tips (/tips, /tips/<slug>), member tip suggestions (/tips/suggest -> /admin/tips) and the plain-language
/privacy and /terms pages.

Routes:
  GET       /tips                     index, grouped by category (indexable, in the sitemap)
  GET       /tips/<slug>              one article, with Article JSON-LD, Open Graph tags and related tips
  GET/POST  /tips/suggest             signed-in members suggest a tip (CSRF, SUGGEST_DAILY per member per day + IP limit)
  GET/POST  /admin/tips?key=KEY       review queue: mark reviewed / delete
  GET       /privacy, /terms          plain-language policies
Articles live in tipsdata.py (trusted HTML written by us). Suggestions are never published automatically.
"""
import html, json, os, re, time
from datetime import date
from urllib.parse import quote

import accounts as A
import mailer
import tipsdata as D
import webapp as W

e = html.escape
SUGGEST_DAILY = 3
MAX_TITLE, MAX_TIP = 90, 2000
CONTACT = "hello@barksbuds.app"
POLICY_UPDATED = "October 24, 2026"
CAT_ICON = {"runs": "i-pin", "health": "i-shield", "community": "i-users", "puppies": "i-paw"}


def topic_choices():
    return D.CATS + [("trail", "A dog-friendly trail"), ("other", "Something else")]


def topic_label(k):
    return dict(D.CATS + [("trail", "Trail suggestion")]).get(k, "Other")


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    store.q(f"""CREATE TABLE IF NOT EXISTS tip_suggestions(id {ID}, user_id {INT} NOT NULL, topic TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at {INT} NOT NULL)""")
    store.q("CREATE INDEX IF NOT EXISTS tip_suggestions_user_idx ON tip_suggestions(user_id, created_at)")


def nice_date(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).strftime("%B %-d, %Y")


def tip_card(t, h="h3"):
    return (f'<a class="tipcard" href="/tips/{t["slug"]}"><span class="tc-ic" aria-hidden="true"><svg class="ico"><use href="#{CAT_ICON[t["cat"]]}"/></svg></span>'
            f'<span class="tc-cat">{e(D.CAT_LABEL[t["cat"]])} &middot; {t["minutes"]} min read</span>'
            f'<{h} class="tc-t">{e(t["short"])}</{h}><span class="tc-d">{e(t["desc"])}</span><span class="tc-more" aria-hidden="true">Read &rarr;</span></a>')


CSS = """<style>
.tipcats{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0;padding:0;list-style:none}
.tipcats a{display:inline-flex;align-items:center;min-height:40px;background:#fff;border:2px solid var(--black);border-radius:999px;padding:6px 14px;font-weight:800;font-size:.93rem;color:var(--black);text-decoration:none}
.tipcats a:hover{background:var(--gold-l)}
.tipsec{margin:0 0 40px}.tipsec h2{font-size:1.6rem;margin:0 0 14px}
.tipgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px}
.tipcard{display:flex;flex-direction:column;gap:6px;background:#fff;border:2px solid var(--black);border-radius:var(--r);padding:20px 20px 18px;box-shadow:5px 5px 0 var(--gold);color:var(--ink);text-decoration:none;transition:transform .12s}
.tipcard:hover{transform:translateY(-2px)}.tipcard:focus-visible{outline:3px solid var(--red);outline-offset:3px}
.tc-ic{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:var(--gold-l);color:var(--red)}
.tc-ic .ico{width:22px;height:22px}
.tc-cat{font-size:.8rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.tc-t{font:800 1.28rem/1.15 "Baloo 2",system-ui,sans-serif;color:var(--black);margin:0}
.tc-d{font-size:.95rem;color:var(--muted);flex:1}.tc-more{font-weight:800;color:var(--red)}
.tipask{display:flex;flex-wrap:wrap;gap:14px 24px;align-items:center;justify-content:space-between;background:var(--black);color:#fff;border-radius:var(--r);padding:24px 26px;margin-top:10px}
.tipask h2{color:#fff;margin:0 0 4px;font-size:1.45rem}.tipask p{margin:0;color:#E9E1D3}
.tiphead .crumbs{font-size:.92rem;margin:0 0 10px}.tiphead .crumbs a{color:var(--muted)}
.tipmeta{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:.93rem;margin-top:12px}
.tipbody{font-size:1.08rem}
.tipbody .lede{font-size:1.2rem;color:var(--ink)}
.tipbody h2{font-size:1.55rem;margin:1.6em 0 .45em}
.tipbody ul,.tipbody ol{padding-left:1.3em;margin:0 0 1.1em}.tipbody li{margin:0 0 .45em}
.tipbody ul.checklist{list-style:none;padding:0}
.tipbody ul.checklist li{position:relative;padding-left:34px}
.tipbody ul.checklist li::before{content:"";position:absolute;left:0;top:.2em;width:20px;height:20px;border:2px solid var(--black);border-radius:6px;background:#fff}
.tipbody .aside-note{background:#fff;border-left:5px solid var(--gold);border-radius:0 14px 14px 0;padding:12px 16px;font-size:.98rem}
.tipvet{display:flex;gap:12px;align-items:flex-start;background:#FFF3D1;border:2px solid var(--gold-d);border-radius:16px;padding:14px 16px;margin:28px 0 0;font-size:.98rem}
.tipvet .ico{flex:none;width:24px;height:24px;color:var(--red);margin-top:2px}
.tipmore{border-top:2px dashed var(--line);margin-top:40px;padding-top:28px}
.tipmore h2{font-size:1.45rem}
.legal h2{font-size:1.4rem;margin:1.5em 0 .4em}.legal ul{padding-left:1.3em}.legal li{margin:0 0 .4em}
@media (max-width:640px){.tipbody{font-size:1.02rem}.tipbody .lede{font-size:1.1rem}.tipask{padding:20px}.tipgrid{grid-template-columns:1fr}}
</style>"""


def landing_html():
    """Small 'Tips' teaser for the landing page (index.html {{TIPS}})."""
    pick = [D.BY_SLUG[s] for s in ("dog-run-etiquette", "summer-heat-and-paw-safety", "ticks-and-lyme-on-long-island")]
    cards = "".join(
        f'<a class="tt-card" href="/tips/{t["slug"]}"><span class="tt-cat">{e(D.CAT_LABEL[t["cat"]])}</span>'
        f'<h3>{e(t["short"])}</h3><p>{e(t["desc"])}</p><span class="tt-more">Read the tip &rarr;</span></a>' for t in pick)
    return f"""<style>
.tt{{padding:72px 0}}.tt .head{{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between;margin-bottom:26px}}
.tt h2{{font-size:clamp(1.9rem,4vw,2.6rem);margin:0}}.tt .head p{{margin:6px 0 0;color:var(--muted);max-width:36em}}
.tt-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
.tt-card{{display:flex;flex-direction:column;gap:6px;background:#fff;border:2px solid var(--black);border-radius:22px;padding:22px;box-shadow:6px 6px 0 var(--gold);text-decoration:none;color:var(--ink);transition:transform .12s}}
.tt-card:hover{{transform:translateY(-2px)}}.tt-card h3{{font-size:1.35rem;margin:0}}.tt-card p{{margin:0;color:var(--muted);font-size:.97rem;flex:1}}
.tt-cat{{font-size:.8rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:var(--red)}}.tt-more{{font-weight:800;color:var(--red)}}
.tt .all{{font-weight:800;color:var(--black);white-space:nowrap}}
@media (max-width:860px){{.tt-grid{{grid-template-columns:1fr}}.tt{{padding:56px 0}}}}
</style>
<section class="tt" id="tips" aria-labelledby="tt-title"><div class="wrap">
<div class="head"><div><span class="eyebrow">tips &amp; how-tos</span><h2 id="tt-title">Good to know before the dog run</h2>
<p>Friendly, practical guides from local dog people: etiquette, seasons, ticks, meetups and more.</p></div>
<a class="all" href="/tips">All {len(D.TIPS)} tips &rarr;</a></div>
<div class="tt-grid">{cards}</div></div></section>"""


class TipRoutes:
    def tips_get(self, path, q):
        if path in ("/tips", "/tips/"):
            self._app_reset(); self.tips_index(q); return True
        if path in ("/tips/suggest", "/tips/suggest/"):
            self._app_reset()
            t = q.get("topic", [""])[0]
            self.tip_suggest_page({"topic": t} if t in dict(topic_choices()) else None); return True
        m = re.fullmatch(r"/tips/([a-z0-9-]{1,80})/?", path)
        if m:
            self._app_reset(); self.tip_page(m.group(1)); return True
        if path in ("/privacy", "/privacy/"):
            self._app_reset(); self.privacy_page(); return True
        if path in ("/terms", "/terms/"):
            self._app_reset(); self.terms_page(); return True
        if path == "/admin/tips":
            self._app_reset(); self.admin_tips(q); return True
        return False

    def tips_post(self, path, q):
        if path == "/tips/suggest":
            self._app_reset(); self.post_tip_suggest(); return True
        if path == "/admin/tips":
            self._app_reset(); self.post_admin_tips(); return True
        return False

    # ------------------------------------------------------------ articles
    def _og(self, title, desc):
        return {"title": title, "desc": desc, "image": self._base() + "/img/og-image.jpg?v=jack2", "w": 1200, "h": 630,
                "alt": "BarksBuds: a group of friends that love their dogs"}

    def tips_index(self, q):
        flash = "Thanks! Your tip is in our review queue." if q.get("m", [""])[0] == "sent" else ""
        chips = "".join(f'<li><a href="#cat-{k}">{e(v)}</a></li>' for k, v in D.CATS)
        secs = []
        for k, v in D.CATS:
            ts = [t for t in D.TIPS if t["cat"] == k]
            if ts:
                secs.append(f'<section class="tipsec" id="cat-{k}" aria-labelledby="h-{k}"><h2 id="h-{k}">{e(v)}</h2>'
                            f'<div class="tipgrid">{"".join(tip_card(t) for t in ts)}</div></section>')
        ask = ('<div class="tipask"><div><h2>Got a tip worth sharing?</h2><p>Favorite trail, clever trick, or something every new dog owner should know? '
               'Send it in and we may feature it.</p></div><a class="btn btn-gold" href="/tips/suggest">Suggest a tip</a></div>')
        body = f"""{CSS}<section class="phead"><div class="wrap"><span class="eyebrow">tips &amp; how-tos</span>
<h1>Tips for dog people</h1><p class="lead">Practical, friendly guides for dog owners in NYC, Long Island and Westchester: dog run etiquette,
reading play, seasonal safety, meetups and packs.</p><ul class="tipcats" aria-label="Jump to a topic">{chips}</ul></div></section>
<section class="section"><div class="wrap">{"".join(secs)}{ask}
<p class="small muted" style="margin-top:22px">These tips are general information, not veterinary advice. For anything about your own dog's health, ask your vet.</p>
</div></section>"""
        ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "BarksBuds tips for dog owners", "url": self._base() + "/tips",
              "hasPart": [{"@type": "Article", "headline": t["title"], "url": f'{self._base()}/tips/{t["slug"]}'} for t in D.TIPS]}
        body += '<script type="application/ld+json">' + json.dumps(ld).replace("<", "\\u003c") + "</script>"
        desc = "Practical tips for dog owners in NYC, Long Island and Westchester: dog run etiquette, body language, summer heat, winter salt, ticks, meetups and more."
        return self.page("Tips for dog owners", body, index=True, active="tips", canonical="/tips", desc=desc,
                         og=self._og("Tips for dog people | BarksBuds", desc), flash=flash)

    def tip_page(self, slug):
        t = D.BY_SLUG.get(slug)
        if not t:
            return self.msg_page("We couldn't find that tip", '<p class="sub">It may have moved.</p><p><a class="btn" href="/tips">See all tips</a></p>', code=404, icon="i-chat")
        related = [x for x in D.TIPS if x["cat"] == t["cat"] and x is not t] + [x for x in D.TIPS if x["cat"] != t["cat"]]
        vet = ('<aside class="tipvet" aria-label="A note about health"><svg class="ico" aria-hidden="true"><use href="#i-heart"/></svg><div>'
               "<strong>Ask your vet.</strong> This is general information, not veterinary advice. Every dog is different, so check with your vet "
               "about your dog's health, vaccines and prevention, and call right away if something seems wrong.</div></aside>") if t["vet"] else ""
        base = self._base()
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": t["title"], "description": t["desc"],
              "datePublished": t["updated"], "dateModified": t["updated"], "image": base + "/img/og-image.jpg?v=jack2",
              "mainEntityOfPage": f"{base}/tips/{slug}", "author": {"@type": "Organization", "name": "BarksBuds"},
              "publisher": {"@type": "Organization", "name": "BarksBuds", "logo": {"@type": "ImageObject", "url": base + "/img/icon-512.png?v=jack2"}}}
        bc = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Tips", "item": base + "/tips"},
            {"@type": "ListItem", "position": 2, "name": t["short"], "item": f"{base}/tips/{slug}"}]}
        lds = "".join('<script type="application/ld+json">' + json.dumps(x).replace("<", "\\u003c") + "</script>" for x in (ld, bc))
        body = f"""{CSS}<section class="phead tiphead"><div class="wrap narrow">
<nav class="crumbs" aria-label="Breadcrumb"><a href="/tips">Tips</a> &rsaquo; <a href="/tips#cat-{t["cat"]}">{e(D.CAT_LABEL[t["cat"]])}</a></nav>
<h1>{e(t["title"])}</h1>
<div class="tipmeta"><span>{t["minutes"]} min read</span><span>Updated <time datetime="{t["updated"]}">{nice_date(t["updated"])}</time></span><span>By the BarksBuds team</span></div></div></section>
<section class="section"><div class="wrap narrow"><article class="tipbody">{t["body"]}{vet}</article>
<div class="tipmore"><h2>More tips</h2><div class="tipgrid">{"".join(tip_card(x) for x in related[:3])}</div>
<p style="margin-top:22px"><a href="/tips">&larr; All tips</a> &middot; <a href="/tips/suggest">Suggest a tip</a></p></div></div></section>{lds}"""
        return self.page(t["title"], body, index=True, active="tips", canonical=f"/tips/{slug}", desc=t["desc"],
                         og=dict(self._og(t["title"], t["desc"]), type="article"))

    # ------------------------------------------------------------ member tip suggestions
    def tip_suggest_page(self, vals=None, errs=None, code=200):
        vals, errs = vals or {}, errs or {}
        tr = vals.get("topic") == "trail"
        u = self.user()
        if not u:
            return self.need_login("/tips/suggest?topic=trail" if tr else "/tips/suggest")
        v = lambda k: e(str(vals.get(k) or ""))
        err = lambda k: f'<span class="err" id="{k}-err">{e(errs[k])}</span>' if k in errs else ""
        inv = lambda k: f' aria-invalid="true" aria-describedby="{k}-err"' if k in errs else ""
        opts = "".join(f'<option value="{k}"{" selected" if vals.get("topic") == k else ""}>{e(t)}</option>' for k, t in topic_choices())
        top = '<div class="formerr" role="alert">Please fix the highlighted fields.</div>' if errs else ""
        if tr:
            h1, lead = "Suggest a trail", ("Know a trail where dogs are welcome in NYC, Long Island or Westchester? Tell us the trail and park, and where the dog rules "
                                           "are posted. We check every suggestion against the official park page before adding it to the trails map.")
            t_lbl, t_ph, b_lbl, b_ph, btn, back = ("Trail and park", "Blue Trail, Clove Lakes Park", "Where is it, and what are the dog rules?",
                                                   "Town or borough, trailhead or parking, and a link to the official page or what the sign says.", "Send trail", "/trails")
        else:
            h1, lead = "Suggest a tip", "A favorite trail, a training trick, a rainy-day idea? Send it in. We read every one and may turn it into a tip, with credit if you'd like."
            t_lbl, t_ph, b_lbl, b_ph, btn, back = ("Your tip in a few words", "Bring a towel to the beach run", "The details",
                                                   "What works for you and your dog?", "Send tip", "/tips")
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">share what you know</span><h1>{h1}</h1>
<p class="lead">{e(lead)}</p></div></section>
<section class="section"><div class="wrap narrow"><form class="panel mform" method="post" action="/tips/suggest" novalidate>{self.csrf_field()}{top}
<div class="field"><label for="topic">Topic</label><select id="topic" name="topic">{opts}</select></div>
<div class="field"><label for="title">{t_lbl}</label><input type="text" id="title" name="title" maxlength="{MAX_TITLE}" required value="{v("title")}" placeholder="{e(t_ph)}"{inv("title")}>{err("title")}</div>
<div class="field"><label for="body">{b_lbl}</label><textarea id="body" name="body" rows="7" maxlength="{MAX_TIP}" required placeholder="{e(b_ph)}"{inv("body")}>{v("body")}</textarea>{err("body")}</div>
<div class="formfoot"><button class="btn" type="submit">{btn}</button><a class="small" href="{back}">Cancel</a></div>
<p class="small muted" style="margin:14px 0 0">Up to {SUGGEST_DAILY} suggestions a day. Please keep it about dogs, kind and practical. We don't publish anything automatically.</p></form></div></section>"""
        return self.page(h1, body, code=code, active="trails" if tr else "tips")

    def post_tip_suggest(self):
        u = self.user()
        if not u:
            return self.need_login("/tips/suggest")
        f = self._form_or_fail()
        if f is None:
            return
        since = int(time.time()) - 86400
        n = A.one("SELECT COUNT(*) FROM tip_suggestions WHERE user_id=:u AND created_at>:s", u=u["id"], s=since)[0]
        if n >= SUGGEST_DAILY or not A.LIMITER.allow("tipsugg-ip:" + self._client_ip(), 10, 86400):
            return self.msg_page("That's plenty for today", f'<p class="sub">You can send up to {SUGGEST_DAILY} tips a day. Thank you! '
                                 'Please come back tomorrow.</p><p><a class="btn" href="/tips">Back to tips</a></p>', code=429, icon="i-chat")
        vals = {"topic": f.get("topic") if f.get("topic") in dict(topic_choices()) else "other",
                "title": W.clean(f.get("title"), MAX_TITLE), "body": W.clean(f.get("body"), MAX_TIP, multiline=True)}
        errs = {}
        if len(vals["title"]) < 4:
            errs["title"] = "Give your tip a short title."
        if len(vals["body"]) < 20:
            errs["body"] = "Tell us a little more (at least a sentence or two)."
        if errs:
            return self.tip_suggest_page(vals, errs, code=422)
        A.q("INSERT INTO tip_suggestions(user_id,topic,title,body,status,created_at) VALUES(:u,:t,:ti,:b,'pending',:c)",
            u=u["id"], t=vals["topic"], ti=vals["title"], b=vals["body"], c=int(time.time()))
        print("tips: new suggestion", flush=True)
        self._notify_tip(vals, u)
        return self.redirect("/trails?m=sent" if vals["topic"] == "trail" else "/tips?m=sent")

    def _notify_tip(self, vals, u):
        import runsweb
        to = runsweb.NOTIFY_TO
        if not to:
            return False
        who = u.get("display_name") or "A member"
        subject = f"New tip suggestion: {vals['title']}"
        text = f"{who} suggested a tip ({topic_label(vals['topic'])}):\n\n{vals['title']}\n\n{vals['body']}\n\nReview it at {self._base()}/admin/tips (add ?key= with your admin key)."
        body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622"><h2 style="margin:0 0 8px">' + e(subject) + "</h2>"
                f"<p>{e(who)} suggested a tip.</p><p style=\"white-space:pre-line\">{e(vals['body'])}</p>"
                f"<p>Review it at {e(self._base())}/admin/tips (add ?key= with your admin key).</p></div>")
        return mailer.send_async(to, subject, body, text, None, "runs-tip-suggestion")

    def admin_tips(self, q):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        rows = A.q("SELECT s.id,s.topic,s.title,s.body,s.status,s.created_at,u.display_name,u.email FROM tip_suggestions s "
                   "LEFT JOIN users u ON u.id=s.user_id ORDER BY CASE WHEN s.status='pending' THEN 0 ELSE 1 END, s.id DESC")
        hid = f'<input type="hidden" name="key" value="{e(key)}">'
        cards = []
        for i, topic, title, b, st, ts, name, email in rows[:200]:
            acts = "".join(f'<form method="post" action="/admin/tips" style="display:inline">{hid}<input type="hidden" name="id" value="{i}">'
                           f'<button class="btn btn-sm{" btn-ghost" if a != "delete" else " btn-danger"}" name="action" value="{a}">{lbl}</button></form> '
                           for a, lbl in (("reviewed", "Mark reviewed"), ("pending", "Back to pending"), ("delete", "Delete")) if a != st)
            cards.append(f'<div class="panel"><p class="small muted" style="margin:0">#{i} &middot; {e(topic_label(topic))} &middot; '
                         f'<b>{e(st)}</b> &middot; {e(name or "")} &lt;{e(email or "")}&gt;</p><h2 style="font-size:1.25rem;margin:6px 0">{e(title)}</h2>'
                         f'<p style="white-space:pre-line">{e(b)}</p>{acts}</div>')
        body = (f'<section class="phead"><div class="wrap narrow"><h1>Tip suggestions</h1><p class="lead">{sum(1 for r in rows if r[4] == "pending")} waiting for review. '
                'Nothing here is published automatically; good ones can be written up in tipsdata.py.</p></div></section>'
                f'<section class="section"><div class="wrap narrow">{"".join(cards) or "<p>No suggestions yet.</p>"}</div></section>')
        return self.page("Tip suggestions (admin)", body)

    def post_admin_tips(self):
        f = self.read_form()
        key = ((f.get("key") if f else "") or self.headers.get("X-Admin-Key", ""))
        if not f or not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        act, sid = f.get("action"), f.get("id")
        if sid.isdigit():
            if act == "delete":
                A.q("DELETE FROM tip_suggestions WHERE id=:i", i=int(sid))
            elif act in ("reviewed", "pending"):
                A.q("UPDATE tip_suggestions SET status=:s WHERE id=:i", s=act, i=int(sid))
        print(f"admin: tip action {act}", flush=True)
        return self.redirect("/admin/tips?key=" + quote(key))

    # ------------------------------------------------------------ policies
    def _legal(self, title, slug, desc, inner):
        body = f"""{CSS}<section class="phead"><div class="wrap narrow"><span class="eyebrow">the plain-language version</span><h1>{e(title)}</h1>
<p class="lead">Last updated {POLICY_UPDATED}. Questions? Email <a href="mailto:{CONTACT}">{CONTACT}</a>.</p></div></section>
<section class="section"><div class="wrap narrow"><div class="panel legal tipbody">{inner}</div></div></section>"""
        return self.page(title, body, index=True, canonical=slug, desc=desc, og=self._og(f"{title} | BarksBuds", desc))

    def privacy_page(self):
        inner = f"""<p class="lede">BarksBuds is a small, local community for dog owners. We collect only what we need to run it, we never sell your information, and you can delete your account at any time.</p>
<h2>What we collect</h2>
<ul>
<li><strong>Waitlist:</strong> your first name, email, your dog's name and, if you share it, your zip code.</li>
<li><strong>Your account:</strong> your email (used to send sign-in links), and the display name, area, town and bio you choose to add.</li>
<li><strong>Your dogs:</strong> the profile details and photos you add. We remove location data (EXIF/GPS) from photos when you upload them.</li>
<li><strong>What you do on BarksBuds:</strong> meetups you host or RSVP to, packs you join, posts and comments, dog run and tip suggestions, and reports you send.</li>
<li><strong>Basic technical logs</strong> kept by our hosting provider to keep the site running and secure, such as IP addresses and the pages requested.</li>
</ul>
<h2>What's public</h2>
<p>Dog profiles, your display name, your town or neighborhood, and what you post in meetups and packs can be seen by other people. <strong>Your email address is never shown</strong> on BarksBuds.</p>
<h2>How we use it</h2>
<ul>
<li>To run BarksBuds: sign-in links, profiles, meetups, packs and the dog run map.</li>
<li>To send the emails you'd expect, like RSVP confirmations, meetup reminders and pack updates. You can turn these off from your account or from the link in any email.</li>
<li>To keep the community safe, such as reviewing reports and preventing spam.</li>
</ul>
<p>We don't sell or rent your information, and we don't use advertising trackers.</p>
<h2>Cookies</h2>
<p>We use a small number of cookies that are needed for the site to work: one that keeps you signed in and one that protects forms from forgery. That's it.</p>
<h2>Services we rely on</h2>
<p>We use a few trusted providers to run BarksBuds: Render (hosting and database), Cloudflare (our domain and network), Brevo (sending email), OpenStreetMap (map tiles) and Google Fonts (typefaces). They only get what they need to do their job, such as your email address for sending an email, or your browser's IP address when it loads a map tile or font.</p>
<h2>Your choices</h2>
<ul>
<li>Edit or delete your dogs, photos and profile at any time from <a href="/me">My dogs</a>.</li>
<li>Delete your whole account with &ldquo;Delete my account&rdquo; on <a href="/me">My dogs</a>. This removes your profile, dogs and photos.</li>
<li>Leave the waitlist with the remove-me link in any waitlist email.</li>
<li>Email <a href="mailto:{CONTACT}">{CONTACT}</a> and we'll help with anything else, including a copy of your data or deleting it.</li>
</ul>
<h2>Kids</h2>
<p>BarksBuds accounts are for adults. Kids are always welcome at meetups with their grown-ups.</p>
<h2>Changes</h2>
<p>If we change this policy in a meaningful way, we'll update the date above and let members know.</p>"""
        return self._legal("Privacy policy", "/privacy", "How BarksBuds collects, uses and protects your information, in plain language.", inner)

    def terms_page(self):
        inner = f"""<p class="lede">BarksBuds helps dog owners find dog runs, meet up and make friends. By using it, you agree to these simple terms.</p>
<h2>Be a good neighbor</h2>
<ul>
<li>Be kind and respectful. Keep conversations about dogs and the community.</li>
<li>No harassment, hate, spam, scams or selling.</li>
<li>Only post photos and content you have the right to share, and don't post other people's private information.</li>
<li>Use your real dogs. Profiles are for actual pups.</li>
</ul>
<p>We may remove content or accounts that break these rules. You can report a profile, meetup or pack from its page.</p>
<h2>Meetups and dog runs</h2>
<ul>
<li>Meetups and packs are organized by members, not by BarksBuds. We don't supervise them.</li>
<li>You're responsible for your dog, including its behavior, health, vaccinations and license, and for following each park's posted rules.</li>
<li>Vaccination badges on profiles are self-reported. We can't verify them.</li>
<li>Dog run details come from public sources and members and can change. Check the posted rules and hours before you go.</li>
<li>Please use good judgment, meet in public places, and leave if anything feels off.</li>
</ul>
<h2>Your content</h2>
<p>You own the photos and words you post. By posting, you give BarksBuds permission to show them on the site (for example, on your dog's profile or in a pack) and in previews when someone shares a link. If you delete something, we stop showing it.</p>
<h2>Tips and information</h2>
<p>Tips on BarksBuds are general information, not veterinary, legal or professional advice. Ask your vet about your own dog.</p>
<h2>The service</h2>
<p>BarksBuds is free. We work hard to keep it running well, but it's provided "as is," and we can't promise it will always be available or error-free. To the extent the law allows, BarksBuds isn't liable for injuries, losses or disputes that come from meetups, dog runs or interactions between members.</p>
<h2>Changes and contact</h2>
<p>We may update these terms as BarksBuds grows; we'll change the date above when we do. Questions? Email <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>"""
        return self._legal("Terms of use", "/terms", "The simple, plain-language terms for using BarksBuds.", inner)
