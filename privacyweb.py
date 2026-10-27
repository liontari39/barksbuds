"""BarksBuds privacy settings page (/me/privacy) and the shared 'private profile' page. Data rules live in privacy.py."""
import html

import accounts as A
import coowners as CO
import privacy as PV
import webapp as W

e = html.escape

W.FLASH.update({"privacy": "Privacy settings saved."})

CSS = """<style>
.pvwrap{display:grid;gap:26px}
.pvsec h2{font-size:1.5rem;margin:0 0 .2em}
.pvsec>.hint{margin:0 0 16px;color:var(--muted)}
.pvdog{border-top:1.5px dashed var(--line);padding:16px 0 4px}
.pvdog:first-of-type{border-top:0;padding-top:4px}
.pvdog legend{font-weight:800;font-size:1.05rem;padding:0;margin:0 0 10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.pvdog legend a{font-weight:600;font-size:.9rem}
.pvopts{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;border:0;margin:0;padding:0}
.pvopt{display:flex;gap:10px;align-items:flex-start;border:2px solid var(--line);border-radius:14px;padding:12px 12px;background:#fff;cursor:pointer;min-height:100%}
.pvopt input{accent-color:var(--red);width:18px;height:18px;margin:2px 0 0;flex:none}
.pvopt b{display:block;font-size:.98rem;color:var(--black)}
.pvopt small{display:block;color:var(--muted);font-size:.84rem;line-height:1.35;margin-top:2px}
.pvopt:has(input:checked){border-color:var(--black);box-shadow:3px 3px 0 var(--gold)}
.pvopt:has(input:focus-visible){outline:3px solid var(--red);outline-offset:2px}
.pvlist{display:grid;gap:12px;margin:0}
.pvsave{position:sticky;bottom:0;background:linear-gradient(rgba(255,250,240,0),var(--cream,#FFF8EC) 30%);padding:18px 0 14px;z-index:2}
.pvnote{display:flex;gap:10px;align-items:flex-start;color:var(--muted);font-size:.92rem}
.pvnote .ico{flex:none;margin-top:3px}
.pvsel{max-width:340px}
@media (max-width:600px){.pvopts{grid-template-columns:1fr 1fr}.pvopt{padding:10px}}
</style>"""


def _opts(name, options, cur, cols=None):
    return "".join(f'<label class="pvopt"><input type="radio" name="{name}" value="{k}"{" checked" if k == cur else ""}>'
                   f'<span><b>{e(lab)}</b><small>{e(desc)}</small></span></label>' for k, lab, desc in options)


class PrivacyRoutes:
    # ------------------------------------------------------------ viewer helper (cached per request)
    def pv(self):
        u = self.user()
        uid = u["id"] if u else None
        key = (uid, id(self.headers))
        c = getattr(self, "_pvc", None)
        if c is None or c[0] != key:
            c = self._pvc = (key, PV.Viewer(uid))
        return c[1]

    def private_dog_page(self):
        signed = self.user()
        extra = ("" if signed else f'<p><a class="btn" href="{e(self.signin_href(self.path))}">Sign in</a></p>'
                 '<p class="small muted">Some profiles are only visible to signed-in members.</p>')
        body = ('<p class="sub">This dog\'s owner has chosen who can see their profile. '
                'If you know them, say hi at the run or join one of their packs.</p>' + extra +
                '<p><a class="btn btn-ghost" href="/dogs">Meet other dogs</a></p>')
        return self.msg_page("This profile is private", body, code=403, icon="i-lock")

    # ------------------------------------------------------------ /me/privacy
    def privacy_settings_page(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        st = PV.settings(u["id"])
        dogs = A.dogs_for_user(u["id"])
        rows = []
        for d in dogs:
            vis = d.get("visibility") or "public"
            co = ""
            if d["user_id"] != u["id"]:
                co = ' <span class="badge">Co-owner</span>'
            elif CO.coowners(d["id"]):
                co = ' <span class="badge">Shared</span>'
            rows.append(f'<fieldset class="pvdog"><legend>{e(d["name"])}{co} <a href="/dogs/{e(d["slug"])}">View page</a></legend>'
                        f'<div class="pvopts">{_opts("vis_%d" % d["id"], PV.VIS, vis)}</div></fieldset>')
        if not rows:
            rows.append('<p class="muted">You haven\'t added a dog yet. <a href="/me/dogs/new">Add one</a> and it will use the default below.</p>')
        dv = "".join(f'<option value="{k}"{" selected" if k == st["priv_default_vis"] else ""}>{e(l)}</option>' for k, l, _ in PV.VIS)
        flags = "".join(f'<label class="switch"><input type="checkbox" name="{k}" value="1"{" checked" if st[k] else ""}>'
                        f'<span><b>{e(lab)}</b><br><span class="small muted">{e(desc)}</span></span></label>' for k, lab, desc in PV.FLAGS)
        flags += (f'<label class="switch"><input type="checkbox" name="show_checkins" value="1"{"" if st["checkins_hidden"] else " checked"}>'
                  '<span><b>Show my dogs when I check in at a run</b><br><span class="small muted">When this is off, the run page only counts '
                  '\u201c1 dog\u201d for you, with no names or photos.</span></span></label>')
        coown = any(d["user_id"] != u["id"] for d in dogs)
        conote = ('<p class="small muted">For dogs you co-own, any owner can change who sees the profile. Details like town and '
                  'first name follow the main owner\'s settings.</p>') if coown or any(CO.coowners(d["id"]) for d in dogs if d["user_id"] == u["id"]) else ""
        body = f"""{CSS}<section class="phead"><div class="wrap narrow"><a class="mback" href="/me">&larr; My dogs</a>
<span class="eyebrow">privacy</span><h1>Privacy settings</h1>
<p class="lead">Choose who can see your dogs, how easy they are to find, and who can message you.</p></div></section>
<section class="section"><div class="wrap narrow"><form method="post" action="/me/privacy" class="pvwrap">{self.csrf_field()}
<div class="panel pvsec" id="profiles"><h2>Who can see your dogs</h2><p class="hint">People who can't see a profile get a
\u201cThis profile is private\u201d page with no name, photos or details.</p>{''.join(rows)}{conote}
<div class="field" style="margin:18px 0 0"><label for="priv_default_vis">For dogs you add later</label>
<select class="pvsel" id="priv_default_vis" name="priv_default_vis">{dv}</select>
<label class="switch small" style="margin-top:10px"><input type="checkbox" name="apply_all" value="1"><span>Also use this for all my dogs now</span></label></div></div>

<div class="panel pvsec" id="search"><h2>How findable you are</h2><p class="hint">Search never shows a dog to someone who can't open its profile.</p>
<fieldset class="pvopts" style="grid-template-columns:1fr"><legend class="sr-only">Who can find your dogs in search</legend>{_opts("priv_search", PV.SEARCH, st["priv_search"])}</fieldset>
<label class="switch" style="margin-top:16px"><input type="checkbox" name="priv_index" value="1"{" checked" if st["priv_index"] else ""}>
<span><b>Let Google and other search engines list my public dogs</b><br><span class="small muted">Only applies to Public profiles shown to Everyone in search. When off, we ask search engines not to index them.</span></span></label></div>

<div class="panel pvsec" id="details"><h2>What others see</h2><p class="hint">You and your co-owners always see everything. Your email is never shown to anyone.</p>
<div class="pvlist">{flags}</div></div>

<div class="panel pvsec" id="messages"><h2>Who can message you</h2><p class="hint">Conversations you already have stay readable, and blocked members can never message you.</p>
<fieldset class="pvopts"><legend class="sr-only">Who can message you</legend>{_opts("priv_msg", PV.MSG, st["priv_msg"])}</fieldset></div>

<div class="pvsave"><div class="formfoot" style="justify-content:flex-start"><button class="btn" type="submit">Save privacy settings</button><a href="/me">Cancel</a></div></div>
</form>
<p class="pvnote"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg><span>Pack-mates are members who are in a pack with you or RSVP'd
to the same meetup. Changes apply right away; links people already opened may stay in their browser for a little while.</span></p>
</div></section>"""
        return self.page("Privacy settings", body, flash=self.flash_from(q))

    def post_privacy_settings(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        st = PV.settings(u["id"])
        pick = lambda k, keys: f.get(k) if f.get(k) in keys else st[k]
        new = dict(priv_default_vis=pick("priv_default_vis", PV.VIS_KEYS), priv_search=pick("priv_search", PV.SEARCH_KEYS),
                   priv_msg=pick("priv_msg", PV.MSG_KEYS), priv_index=1 if f.get("priv_index") == "1" else 0,
                   checkins_hidden=0 if f.get("show_checkins") == "1" else 1)
        for k in PV.FLAG_KEYS:
            new[k] = 1 if f.get(k) == "1" else 0
        PV.save_settings(u["id"], new)
        for d in A.dogs_for_user(u["id"]):
            v = new["priv_default_vis"] if f.get("apply_all") == "1" else f.get(f"vis_{d['id']}")
            if v in PV.VIS_KEYS and v != d.get("visibility") and CO.can_manage(d, u["id"]):
                PV.set_visibility(d["id"], v)
        print(f"privacy: settings saved for user {u['id']}", flush=True)
        return self.redirect("/me/privacy?m=privacy")
