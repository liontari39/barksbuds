"""Members-only owner cards: /humans/<id>-<hmac>, report and block.

Visible only to signed-in members. Blocks in either direction, a bad token,
or a missing account all look the same (a generic 404). The page is noindex,
not in the sitemap, and never shows email, street address, last login,
check-ins, favorite runs or an owner photo.
"""
import re

import accounts as A
import humans as H
import messages as MS
import privacy as PV
import webapp as W
from webapp import e

CARD_REPORT_REASONS = ["Harassment or bullying", "Pretending to be someone else",
                       "Spam or fake account", "Safety concern", "Something else"]

W.FLASH.update({
    "card_reported": "Thanks. Our team will take a look.",
    "card_blocked": "Blocked. They can't message you, and they aren't told.",
})


class HumanRoutes:
    def human_href(self, uid):
        path = H.card_path(uid)
        return path if self.user() else self.signin_href(path)

    def human_link(self, uid, label):
        """A name (or fallback) linked to the owner card, or to sign-in."""
        if not uid or not label:
            return e(label or "")
        return f'<a class="hlink" href="{e(self.human_href(uid))}">{e(label)}</a>'

    def human_get(self, path, q):
        m = re.fullmatch(r"/humans/([^/]+)/?", path)
        if not m:
            return False
        self.human_page(m.group(1), q)
        return True

    def human_post(self, path, q):
        m = re.fullmatch(r"/humans/([^/]+)/(report|block)", path)
        if not m:
            return False
        if m.group(2) == "report":
            self.post_human_report(m.group(1))
        else:
            self.post_human_block(m.group(1))
        return True

    def _human_or_deny(self, token, signed_out_ok=False):
        """(viewer, subject id) or handled the response and returns None.

        signed_out visitors are sent to sign-in before we say whether the
        token is valid, so a guess doesn't leak that an account exists.
        """
        u = self.user()
        if not u:
            if signed_out_ok:
                return None
            self.need_login()
            return None
        uid = H.parse_token(token)
        if uid is None or not MS.user_exists(uid):
            self._human_missing()
            return None
        if uid != u["id"] and MS.either_blocked(u["id"], uid):
            self._human_missing()
            return None
        return u, uid

    def _human_missing(self):
        return self.msg_page("We couldn't find that page",
                             '<p class="sub">This card may have been removed, or the link is incomplete.</p>'
                             '<p><a class="btn" href="/dogs">Meet the dogs</a></p>',
                             code=404)

    def human_page(self, token, q):
        got = self._human_or_deny(token)
        if got is None:
            return
        u, uid = got
        row = A.one("SELECT id, display_name, area, town, bio FROM users WHERE id=:i", i=uid)
        if not row:
            return self._human_missing()
        subj = dict(id=row[0], display_name=row[1] or "", area=row[2] or "", town=row[3] or "", bio=row[4] or "")
        # Never select or render email / last_login / street / check-ins / favorite runs.
        st = PV.settings(uid)
        mine = u["id"] == uid
        show = bool(st.get("priv_card", 1)) or mine
        name = H.first_name(subj["display_name"]) if (mine or st.get("priv_owner_name", 1)) else ""
        name = name or "A BarksBuds member"
        where = ""
        if show and (mine or st.get("priv_town", 1)):
            where = W.where_text(subj["town"], subj["area"])
        bio = (subj["bio"] or "").strip() if show else ""
        dogs_html = ""
        if show:
            dogs = [d for d in A.dogs_for_user(uid) if not d.get("hidden") and (mine or PV.can_view(d, self.pv()))]
            firsts = A.first_photos([d["id"] for d in dogs])
            cards = []
            for d in dogs:
                pid = d.get("avatar_photo_id") or firsts.get(d["id"])
                # dog_card would add the owner's town; keep tiles to name/breed/photo only
                ph = self.card_ph(d, pid, d["name"])
                meta = " · ".join(x for x in (d["breed"], A.age_text(d) if mine or st.get("priv_birthday", 1) else "") if x)
                cards.append(f'<a class="dcard" href="/dogs/{e(d["slug"])}">{ph}<div class="bd"><h3>{e(d["name"])}</h3>'
                             f'<p class="meta">{e(meta) or "&nbsp;"}</p></div></a>')
            dogs_html = (f'<div class="dgrid hcard-dogs">{"".join(cards)}</div>' if cards else
                         '<p class="muted">No dogs to show yet.</p>')
        tok = H.card_token(uid)
        msg = "" if mine else self.message_button(uid, f"Message {name}" if name != "A BarksBuds member" else "Message")
        tools = ""
        if not mine:
            reasons = "".join(f'<option>{e(r)}</option>' for r in CARD_REPORT_REASONS)
            tools = f"""<div class="hcard-tools">
<details class="report"><summary>Report</summary>
<form method="post" action="/humans/{e(tok)}/report">{self.csrf_field()}
<div class="field"><label for="reason">What's wrong?</label><select id="reason" name="reason">{reasons}</select></div>
<div class="field"><label for="details">Details <span class="opt">(optional)</span></label>
<textarea id="details" name="details" maxlength="1000" rows="3"></textarea></div>
<button class="btn btn-sm" type="submit">Send report</button>
<p class="small muted" style="margin:10px 0 0">Reports go to the BarksBuds team, not to this member.</p></form></details>
<details class="report"><summary>Block</summary>
<form method="post" action="/humans/{e(tok)}/block">{self.csrf_field()}
<p class="small" style="margin:0 0 12px">They can't message you, and this conversation is hidden from your inbox. They aren't told.</p>
<button class="btn btn-ghost btn-sm" type="submit">Block this member</button></form></details>
</div>"""
        if show:
            loc = (f'<p class="hcard-where"><svg class="ico" aria-hidden="true"><use href="#i-pin"/></svg>{e(where)}</p>'
                   if where else "")
            about = f'<p class="bio">{e(bio)}</p>' if bio else ""
            inner = f"""<div class="hcard panel">
<p class="eyebrow">member card</p>
<h1>{e(name)}</h1>
{loc}{about}
<p class="ownacts msgacts">{msg}</p>
<h2 style="margin:28px 0 12px">Dogs</h2>
{dogs_html}
</div>{tools}"""
            if mine:
                inner += ('<p class="small muted" style="margin:18px 0 0">This is how signed-in members see your card. '
                          'Edit your name and bio on <a href="/me/profile">your profile</a>, or change who can open it in '
                          '<a href="/me/privacy#details">privacy settings</a>.</p>')
        else:
            inner = f"""<div class="hcard panel">
<p class="eyebrow">member card</p>
<h1>This member keeps their card private</h1>
<p class="muted">You can still send a message.</p>
<p class="ownacts msgacts">{msg}</p>
</div>{tools}"""
        body = f'<section class="section"><div class="wrap narrow">{inner}</div></section>'
        title = name if show else "Member card"
        return self.page(title, body, index=False, active="me" if mine else "dogs", flash=self.flash_from(q))

    def post_human_report(self, token):
        got = self._human_or_deny(token)
        if got is None:
            return
        u, uid = got
        if u["id"] == uid:
            return self.redirect(H.card_path(uid))
        f = self._form_or_fail()
        if f is None:
            return
        reason = f.get("reason") if f.get("reason") in CARD_REPORT_REASONS else "Something else"
        details = W.clean(f.get("details"), 1000, multiline=True)
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600) and A.LIMITER.allow(f"card-report:{u['id']}", 10, 3600):
            MS.add_member_report(u["id"], uid, reason, details, self._client_ip())
            print(f"reports: new report on member card {uid}", flush=True)
        return self.redirect(H.card_path(uid) + "?m=card_reported")

    def post_human_block(self, token):
        got = self._human_or_deny(token)
        if got is None:
            return
        u, uid = got
        if u["id"] == uid:
            return self.redirect(H.card_path(uid))
        if self._form_or_fail() is None:
            return
        MS.block(u["id"], uid)
        print(f"messages: block from owner card {uid}", flush=True)
        return self.redirect("/messages?m=card_blocked")
