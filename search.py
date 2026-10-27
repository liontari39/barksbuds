"""BarksBuds site-wide search (Oct 2026): GET /search?q=...&type=... (mixed into server.H).

Searches only public content and reuses each section's own visibility rules:
  dogs (hidden=0), dog runs (static + approved member runs), packs (not hidden), meetups (active, not hidden, not ended),
  recommendations (not hidden), lost & found (live alerts plus recently reunited, as on /lost-found),
  park announcements (current, not removed), tips and trails (static guides).
Signed-in members never see dogs, packs, meetups, recommendations, alerts or announcements from someone they've
blocked (or who blocked them). Owner emails and other private fields are never read into the haystack.
Matching is case-insensitive, accent-insensitive partial matching in Python on rows from one query per type, so it behaves
the same on SQLite and Postgres. Queries are capped at MAX_Q characters and MAX_TERMS words; results per type are capped.
?frag=1 returns only the results block (used by the page's live search, which shows running Jack while it loads).
"""
import html, re, unicodedata
from urllib.parse import quote, urlencode

import accounts as A
import community as C
import meetups as M
import packs as P
import webapp as W

e = html.escape
MAX_Q, MAX_TERMS, PER_TYPE_ALL, PER_TYPE_ONE = 60, 6, 6, 40
EXAMPLES = ["poodle", "Morley", "sitter", "Westbury", "Manhasset", "vet"]

# key, tab label, singular badge, icon
TYPES = [("dogs", "Dogs", "Dog", "i-paw"), ("runs", "Dog runs", "Dog run", "i-pin"), ("packs", "Packs", "Pack", "i-users"),
         ("meetups", "Meetups", "Meetup", "i-cal"), ("recs", "Recommendations", "Recommendation", "i-heart"),
         ("lost", "Lost & found", "Lost & found", "i-alert"), ("news", "Park news", "Park news", "i-shield"),
         ("guides", "Tips & trails", "Guide", "i-tree")]
TYPE_KEYS = [t[0] for t in TYPES]
TYPE_INFO = {t[0]: t for t in TYPES}


def fold(s):
    """Lowercase, strip accents, collapse punctuation to spaces."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s).strip() + " "


def parse_query(raw):
    q = W.clean(raw or "", 200)[:MAX_Q].strip()
    terms = [t for t in fold(q).split() if t][:MAX_TERMS]
    return q, terms


def score(terms, name, hay):
    """0 = no match. Every term must appear somewhere (partial); name matches rank higher."""
    n = fold(name)
    h = n + fold(hay)
    if not all(t in h for t in terms):
        return 0
    s = 1
    phrase = " ".join(terms)
    if n.strip() == phrase:
        s += 6
    elif n.startswith(" " + phrase):
        s += 4
    s += sum(2 if (" " + t) in n else (1 if t in n else 0) for t in terms)
    return s


def blocked_ids(uid):
    if not uid:
        return set()
    try:
        rows = A.q("SELECT blocker_id, blocked_id FROM user_blocks WHERE blocker_id=:u OR blocked_id=:u", u=uid)
    except Exception:
        return set()
    return {b if a == uid else a for a, b in rows}


def _area(a):
    return W.area_label(a) if a else ""


def _top(items, limit):
    items.sort(key=lambda x: (-x["score"], x["title"].lower()))
    return items[:limit]


# ---------------------------------------------------------------- per-type searches
class Blocked(set):
    """Blocked member ids, plus the searching member's id (for privacy checks)."""
    uid = None


def s_dogs(terms, blocked, limit):
    import privacy as PV
    out = []
    # only dogs this searcher may open, whose owners allow search; hidden towns are blanked (and so not searchable)
    for d in PV.directory(PV.Viewer(getattr(blocked, "uid", None)), limit=10 ** 6):
        if d["user_id"] in blocked:
            continue
        sc = score(terms, d["name"], " ".join([d.get("breed") or "", d.get("town") or "", d.get("area") or "", _area(d.get("area"))]))
        if sc:
            out.append(dict(score=sc, title=d["name"], href=f'/dogs/{d["slug"]}', d=d,
                            sub=" · ".join(x for x in (d.get("breed") or "", A.age_text(d), W.where_text(d.get("town"), d.get("area"))) if x)))
    out = _top(out, limit)
    firsts = A.first_photos([r["d"]["id"] for r in out if not r["d"].get("avatar_photo_id")])
    for r in out:
        pid = r["d"].get("avatar_photo_id") or firsts.get(r["d"]["id"])
        r["img"] = f"/p/{pid}.webp" if pid else ""
    return out


def s_runs(terms, blocked, limit):
    import runpageweb
    out = []
    for r in W.RUNS():
        town = r.get("town_or_neighborhood") or ""
        hay = " ".join([r.get("park") or "", town, r.get("county") or "", r.get("address") or "", r.get("type") or "", r.get("operator") or ""])
        sc = score(terms, r.get("name") or "", hay)
        if sc:
            sub = " · ".join(x for x in (r.get("park") if r.get("park") and r.get("park") != r.get("name") else "", town, r.get("county") or "") if x)
            out.append(dict(score=sc, title=r.get("name") or "Dog run", href=runpageweb.run_path(r), sub=sub, tag=r.get("type") or ""))
    return _top(out, limit)


def s_packs(terms, blocked, limit):
    runs = W.run_index()
    out = []
    for p in P.browse():
        if p["owner_user_id"] in blocked:
            continue
        run = runs.get(p["run_id"]) if p.get("run_id") else None
        hay = " ".join([p.get("town") or "", p.get("area") or "", _area(p.get("area")), run["name"] if run else "", run.get("park", "") if run else ""])
        sc = score(terms, p["name"], hay)
        if sc:
            import packweb
            n = p.get("members", 0)
            sub = " · ".join(x for x in (W.where_text(p.get("town"), p.get("area")), f'Home run: {run["name"]}' if run else "",
                                         f'{n} member{"s" if n != 1 else ""}') if x)
            out.append(dict(score=sc, title=p["name"], href=packweb.pack_path(p), sub=sub,
                            img=f'/pp/{p["cover_photo_id"]}.webp' if p.get("cover_photo_id") else "",
                            tag="Sample" if p.get("is_sample") else ""))
    return _top(out, limit)


def s_meetups(terms, blocked, limit):
    import meetweb
    runs = W.run_index()
    n = A.now()
    rows = A.q(f"SELECT {M.M_COLS} FROM meetups WHERE status='active' AND hidden=0 AND starts_at>:a ORDER BY starts_at, id LIMIT 1000", a=n - 6 * 3600)
    out = []
    for r in rows:
        m = M._m(r)
        if m["ends_at"] <= n or m["host_user_id"] in blocked:
            continue
        run = runs.get(m["run_id"]) if m.get("run_id") else None
        hay = " ".join([m.get("place_name") or "", m.get("town") or "", m.get("area") or "", _area(m.get("area")),
                        run["name"] if run else "", run.get("park", "") if run else ""])
        sc = score(terms, m["title"], hay)
        if sc:
            place = run["name"] if run else (m.get("place_name") or "")
            out.append(dict(score=sc, title=m["title"], href=meetweb.meetup_path(m), starts=m["starts_at"],
                            sub=" · ".join(x for x in (M.when_text(m["starts_at"], short=True), place, W.where_text(m.get("town"), m.get("area"))) if x),
                            tag="Sample" if m.get("is_sample") else ""))
    return _top(out, limit)


def s_recs(terms, blocked, limit):
    plural = dict(C.REC_CATS)
    out = []
    for r in C.browse_recs(limit=2000):
        if r["created_by"] in blocked:
            continue
        cat = r["category"]
        hay = " ".join([C.REC_ONE.get(cat, ""), plural.get(cat, ""), cat, r.get("town") or "", r.get("area") or "", _area(r.get("area"))])
        sc = score(terms, r["name"], hay)
        if sc:
            v = r.get("votes", 0)
            out.append(dict(score=sc, title=r["name"], href=f'/recommendations?{urlencode({"cat": cat})}#r{r["id"]}', tag=C.REC_ONE.get(cat, ""),
                            sub=" · ".join(x for x in (C.REC_ONE.get(cat, ""), W.where_text(r.get("town"), r.get("area")),
                                                       f'{v} member{"s" if v != 1 else ""} use{"s" if v == 1 else ""} them') if x)))
    return _top(out, limit)


def s_lost(terms, blocked, limit):
    import communityweb as CW
    runs = W.run_index()
    out = []
    for a in C.recent_alerts(300):
        if a["user_id"] in blocked:
            continue
        run = runs.get(a["run_id"]) if a.get("run_id") else None
        kind = "Lost" if a["kind"] == "lost" else "Found"
        hay = " ".join([kind, a.get("town") or "", a.get("area") or "", _area(a.get("area")), run["name"] if run else "", run.get("park", "") if run else ""])
        sc = score(terms, CW.alert_name(a), hay)
        if sc:
            small, _ = CW.alert_photo_id(a)
            st = {"reunited": "Reunited", "expired": "Expired"}.get(a["state"], kind)
            out.append(dict(score=sc + (2 if a["state"] == "active" else 0), title=CW.alert_headline(a), href=CW.alert_path(a), img=small or "",
                            sub=CW.alert_where(a) + " · " + CW.ago(a["created_at"]), tag=st, kind=a["kind"]))
    return _top(out, limit)


def s_news(terms, blocked, limit):
    import runpageweb
    runs = W.run_index()
    rows = A.q(f"SELECT {C.ANN_COLS} FROM announcements WHERE removed=0 AND (ends_at IS NULL OR ends_at>:t) ORDER BY created_at DESC, id DESC LIMIT 500",
               t=C.now())
    out = []
    for r in rows:
        a = C._ann(r)
        run = runs.get(a["run_id"])
        if not run or a["user_id"] in blocked:
            continue
        hay = " ".join([a.get("org_name") or "", run["name"], run.get("park") or "", run.get("town_or_neighborhood") or "", run.get("county") or ""])
        sc = score(terms, a["title"], hay)
        if sc:
            out.append(dict(score=sc, title=a["title"], href=f"/runs/{run['id']}/news", sub=" · ".join(x for x in (a.get("org_name") or "", run["name"]) if x),
                            tag=dict(C.ANN_KINDS).get(a.get("kind"), "Notice")))
    return _top(out, limit)


def s_guides(terms, blocked, limit):
    import tipsdata, trailsdata
    out = []
    for t in tipsdata.TIPS:
        sc = score(terms, t["title"], t.get("short", "") + " " + t.get("desc", ""))
        if sc:
            out.append(dict(score=sc, title=t["title"], href=f'/tips/{t["slug"]}', sub=f'Tip · {t.get("minutes", 3)} min read', tag="Tip"))
    for t in trailsdata.TRAILS:
        sc = score(terms, t["name"], " ".join([t.get("park") or "", t.get("area") or "", t.get("where") or "", "trail hike walk"]))
        if sc:
            out.append(dict(score=sc + 1, title=t["name"], href=f'/trails#{t["slug"]}', sub=" · ".join(x for x in ("Trail", t.get("park"), t.get("area")) if x), tag="Trail"))
    return _top(out, limit)


SEARCHERS = {"dogs": s_dogs, "runs": s_runs, "packs": s_packs, "meetups": s_meetups, "recs": s_recs, "lost": s_lost,
             "news": s_news, "guides": s_guides}


def run_search(raw, uid=None, only=None, limit=None):
    """{type: (results, total)} for a query; empty dict when the query has no searchable words."""
    q, terms = parse_query(raw)
    if not terms:
        return q, {}
    blocked = Blocked(blocked_ids(uid))
    blocked.uid = uid
    out = {}
    for k in TYPE_KEYS:
        try:
            res = SEARCHERS[k](terms, blocked, 10 ** 6)
        except Exception as ex:  # one broken section never breaks search
            print(f"search: {k} failed: {type(ex).__name__}: {ex}", flush=True)
            res = []
        cap = limit or (PER_TYPE_ONE if only else PER_TYPE_ALL)
        out[k] = (res[:cap] if (not only or k == only) else [], len(res))
    return q, out


# ---------------------------------------------------------------- HTML
SEARCH_SVG = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">'
              '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></svg>')
JACK_IMG = ('<img class="jk-img" src="/img/jack-run-72.webp?v=1" srcset="/img/jack-run-72.webp?v=1 1x, /img/jack-run-144.webp?v=1 2x" '
            'width="78" height="72" alt="" decoding="async">')


def jack_runner(label="Fetching…", cls=""):
    """Jack (Mike's original art, unchanged) trotting across a little track. Pure CSS; static with reduced motion."""
    return (f'<div class="jk {cls}" role="status" aria-live="polite"><div class="jk-track" aria-hidden="true">'
            f'<span class="jk-dog">{JACK_IMG}<i class="jk-puff p1"></i><i class="jk-puff p2"></i><i class="jk-puff p3"></i></span>'
            f'<span class="jk-ground"></span></div><p class="jk-label">{e(label)}</p></div>')


def nav_search_html(active=""):
    """Search button + popover box for the top nav (all pages). Works without JS (a GET form)."""
    return ('<details class="nsrch"><summary aria-label="Search BarksBuds" title="Search (press /)">' + SEARCH_SVG + '</summary>'
            '<form class="nsrch-pop" role="search" action="/search" method="get">'
            '<label class="sr-only" for="nsrch-q">Search BarksBuds</label>'
            f'<input id="nsrch-q" type="search" name="q" maxlength="{MAX_Q}" placeholder="Dogs, breeds, parks, towns, vets…" autocomplete="off" enterkeyhint="search">'
            '<button type="submit" class="nsrch-go">Search</button></form></details>'
            '<div id="jk-overlay" class="jk-over" hidden>' + jack_runner("Fetching…") + '</div>'
            "<script>(function(){var d=document.querySelector('details.nsrch');if(!d)return;var i=d.querySelector('input');"
            "d.addEventListener('toggle',function(){if(d.open){setTimeout(function(){i.focus()},0)}});"
            "document.addEventListener('click',function(ev){if(d.open&&!d.contains(ev.target))d.open=false});"
            "document.addEventListener('keydown',function(ev){var t=ev.target,tag=(t&&t.tagName)||'';"
            "if(ev.key==='Escape'&&d.open){d.open=false;d.querySelector('summary').focus()}"
            "else if(ev.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(tag)&&!(t&&t.isContentEditable)){var p=document.getElementById('sq');ev.preventDefault();if(p){p.focus();p.select()}else{d.open=true}}});"
            "var o=document.getElementById('jk-overlay');window.addEventListener('pageshow',function(){if(o)o.hidden=true});"
            "document.addEventListener('submit',function(ev){var fm=ev.target;if(!fm.matches||!fm.matches('form[action=\"/search\"]')||fm.id==='sform')return;"
            "var x=fm.querySelector('input[name=q]');if(!x.value.trim()){ev.preventDefault();x.focus();return}if(o)o.hidden=false})})();</script>")


def mobile_search_html():
    return ('<li class="mm-search"><form role="search" action="/search" method="get"><label class="sr-only" for="mm-q">Search BarksBuds</label>'
            f'<input id="mm-q" type="search" name="q" maxlength="{MAX_Q}" placeholder="Search BarksBuds" autocomplete="off" enterkeyhint="search">'
            f'<button type="submit" aria-label="Search">{SEARCH_SVG}</button></form></li>')


def result_row(r, kind):
    _, _, badge, icon = TYPE_INFO[kind]
    if r.get("img"):
        th = f'<span class="sr-th"><img src="{e(r["img"])}" alt="" loading="lazy" width="56" height="56"></span>'
    else:
        th = f'<span class="sr-th sr-ic"><svg class="ico" aria-hidden="true"><use href="#{icon}"/></svg></span>'
    tag = r.get("tag") or ""
    tg = f'<span class="badge">{e(tag)}</span>' if tag and tag != badge else ""
    return (f'<li><a class="sr-row" href="{e(r["href"])}">{th}<span class="sr-tx"><b>{e(r["title"])}</b>'
            f'<small>{e(r.get("sub") or "")}</small></span>{tg}<span class="sr-go" aria-hidden="true">›</span></a></li>')


def results_html(q, res, only):
    if not q:
        ex = "".join(f'<li><a href="/search?q={quote(x)}">{e(x)}</a></li>' for x in EXAMPLES)
        return (f'<div class="sr-empty">{jack_runner("Ready when you are.", "jk-idle")}<h2>What are you sniffing for?</h2>'
                f'<p class="muted">Search dogs, breeds, dog runs and parks, packs, meetups, local vets, groomers and sitters, '
                f'lost &amp; found alerts and guides.</p><ul class="filters sr-ex">{ex}</ul></div>')
    total = sum(n for _, n in res.values())
    qs = lambda t: "/search?" + urlencode({"q": q, **({"type": t} if t else {})})
    cur = lambda on: ' aria-current="page"' if on else ""
    chips = [f'<li><a href="{e(qs(""))}" data-type=""{cur(not only)}>All <span class="n">{total}</span></a></li>']
    chips += [f'<li><a href="{e(qs(k))}" data-type="{k}"{cur(only == k)}>{e(lbl)} <span class="n">{res[k][1]}</span></a></li>'
              for k, lbl, _, _ in TYPES if res.get(k) and res[k][1]]
    head = f'<p class="sr-count" role="status">{total} result{"s" if total != 1 else ""} for <b>“{e(q)}”</b></p>'
    if not total:
        ex = "".join(f'<li><a href="/search?q={quote(x)}">{e(x)}</a></li>' for x in EXAMPLES if x.lower() != q.lower())
        return (head + f'<div class="sr-empty">{jack_runner("Sniffed every dog run…", "jk-sniff")}<h2>No matches for “{e(q)}”</h2>'
                f'<p class="muted">Try a shorter word, a town or park name, or a breed. Some ideas:</p><ul class="filters sr-ex">{ex}</ul></div>')
    groups = []
    for k, lbl, _, icon in TYPES:
        items, n = res.get(k, ([], 0))
        if not items or (only and k != only):
            continue
        more = (f'<a class="sr-more" href="{e(qs(k))}" data-type="{k}">See all {n} {e(lbl.lower())} ›</a>' if not only and n > len(items) else "")
        groups.append(f'<section class="sr-grp" aria-labelledby="g-{k}"><h2 id="g-{k}"><svg class="ico" aria-hidden="true"><use href="#{icon}"/></svg>{e(lbl)}'
                      f'<span class="n">{n}</span></h2><ul class="sr-list">{"".join(result_row(r, k) for r in items)}</ul>{more}</section>')
    if only and not groups:
        groups.append(f'<p class="muted">No {e(TYPE_INFO[only][1].lower())} match. <a href="{e(qs(""))}">See all results</a>.</p>')
    return head + f'<nav aria-label="Filter results by type"><ul class="filters sr-tabs">{"".join(chips)}</ul></nav>' + "".join(groups)


PAGE_JS = r"""<script>(function(){
var f=document.getElementById('sform'),i=document.getElementById('sq'),out=document.getElementById('sres'),ld=document.getElementById('sload');
if(!f||!i||!out||!window.fetch)return;var t=0,n=0,type=f.getAttribute('data-type')||'',last=i.value.trim();
function show(on){ld.hidden=!on;out.setAttribute('aria-busy',on?'true':'false');out.classList.toggle('sr-dim',on)}
function go(push){var q=i.value.trim();if(q===last&&!push)return;last=q;var my=++n,t0=Date.now();
var p=new URLSearchParams();if(q)p.set('q',q);if(type&&q)p.set('type',type);var url='/search'+(p.toString()?'?'+p:'');
show(true);fetch(url+(url.indexOf('?')>0?'&':'?')+'frag=1',{headers:{'Accept':'text/html'}}).then(function(r){return r.text()}).then(function(h){
setTimeout(function(){if(my!==n)return;out.innerHTML=h;show(false);history[push?'pushState':'replaceState'](null,'',url);
document.title=(q?q+' · ':'')+'Search | BarksBuds'},Math.max(0,450-(Date.now()-t0)))}).catch(function(){if(my===n){show(false);location.href=url}})}
i.addEventListener('input',function(){clearTimeout(t);t=setTimeout(function(){go(false)},320)});
f.addEventListener('submit',function(ev){ev.preventDefault();clearTimeout(t);last=null;go(true)});
out.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('a[data-type]');if(!a||ev.metaKey||ev.ctrlKey)return;
ev.preventDefault();type=a.getAttribute('data-type');f.setAttribute('data-type',type);var h=f.querySelector('input[name=type]');if(h)h.value=type;last=null;go(true)});
out.addEventListener('click',function(ev){var a=ev.target.closest&&ev.target.closest('.sr-ex a');if(!a)return;ev.preventDefault();
i.value=decodeURIComponent((a.getAttribute('href').split('q=')[1]||'').replace(/\+/g,' '));type='';last=null;go(true)});
window.addEventListener('popstate',function(){location.reload()});})();</script>"""


class SearchRoutes:
    def search_get(self, path, q):
        if path not in ("/search", "/search/"):
            return False
        self._app_reset()
        u = self.user()
        only = q.get("type", [""])[0]
        only = only if only in TYPE_INFO else ""
        query, res = run_search(q.get("q", [""])[0], u["id"] if u else None, only or None)
        inner = results_html(query, res, only)
        if q.get("frag", [""])[0] == "1":
            self._emit(200, inner, headers={"Cache-Control": "no-store", "Vary": "Cookie", "X-Robots-Tag": "noindex"})
            return True
        hid = f'<input type="hidden" name="type" value="{e(only)}">' if only else '<input type="hidden" name="type" value="">'
        body = f"""<section class="phead sr-head"><div class="wrap"><span class="eyebrow">search barksbuds</span><h1>Find dogs, runs and friends</h1>
<form class="sr-form" id="sform" role="search" action="/search" method="get" data-type="{e(only)}"><label class="sr-only" for="sq">Search</label>
<span class="sr-ico">{SEARCH_SVG}</span><input id="sq" type="search" name="q" value="{e(query)}" maxlength="{MAX_Q}" placeholder="Try Lily, poodle, Morley, sitter, Westbury…" autocomplete="off" enterkeyhint="search"{"" if query else " autofocus"}>{hid}
<button class="btn" type="submit">Search</button></form></div></section>
<section class="section sr-sec"><div class="wrap"><div id="sload" hidden>{jack_runner("Fetching…")}</div>
<div id="sres" aria-live="polite">{inner}</div></div></section>"""
        title = (f"{query} · Search" if query else "Search")
        self.page(title, body, active="search", canonical="/search", scripts=PAGE_JS,
                  desc="Search BarksBuds for dogs, dog runs, packs, meetups, local recommendations and lost and found alerts.")
        return True
