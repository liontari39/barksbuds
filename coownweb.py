"""Co-owner invites: the panel on the dog edit page, invite/revoke/remove/leave, and the /invite/<token> accept page.
Data lives in coowners.py. The invite email goes through mailer.send_async (tag "coowner-invite")."""
import html
import re
import time

import accounts as A
import coowners as CO
import mailer

e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
INVITES_PER_DAY = 10   # per inviting account

CO_MSG = {"sent": "Invite sent. The link works for 7 days.", "revoked": "Invite cancelled. That link no longer works.",
          "removed": "Co-owner removed.", "left": "You're no longer a co-owner of that dog.",
          "joined": "You're now a co-owner. You can edit the profile, add photos and bring this dog to meetups and packs."}
CO_ERR = {"email": "That email doesn't look quite right.", "self": "That's your own email. You already own this dog.",
          "already": "That person is already an owner of this dog.", "pending": "There's already an open invite for that email.",
          "full": f"A dog can have up to {CO.MAX_COOWNERS} co-owners (open invites count too).",
          "limit": "That's a lot of invites today. Please try again tomorrow.", "owner": "Only the main owner can invite co-owners.",
          "mail": "We couldn't send email just now. Please try again in a little while."}


def _when(ts):
    days = max(0, round((ts - time.time()) / 86400))
    return "today" if days == 0 else "in 1 day" if days == 1 else f"in {days} days"


class CoownerRoutes:
    # ------------------------------------------------------------ routing
    def coown_get(self, path, q):
        m = re.fullmatch(r"/invite/([A-Za-z0-9_-]{10,100})", path)
        if m:
            self.invite_page(m.group(1)); return True
        m = re.fullmatch(r"/me/dogs/(\d+)/leave", path)
        if m:
            d = self.own_dog(int(m.group(1)))
            if d is not None:
                self.leave_page(d)
            return True
        return False

    def coown_post(self, path, q):
        routes = [(r"/invite/([A-Za-z0-9_-]{10,100})", self.post_invite_accept),
                  (r"/me/dogs/(\d+)/coowners/invite", self.post_coowner_invite),
                  (r"/me/dogs/(\d+)/coowners/invites/(\d+)/revoke", self.post_coowner_revoke),
                  (r"/me/dogs/(\d+)/coowners/(\d+)/remove", self.post_coowner_remove),
                  (r"/me/dogs/(\d+)/leave", self.post_coowner_leave)]
        for pat, fn in routes:
            m = re.fullmatch(pat, path)
            if m:
                fn(*m.groups())
                return True
        return False

    # ------------------------------------------------------------ edit-page panel
    def coowner_panel(self, d, q=None):
        q = q or {}
        u = self.user()
        did, nm = d["id"], e(d["name"])
        role = CO.role(d, u["id"]) if u else None
        msg, err = q.get("co", [""])[0], q.get("coe", [""])[0]
        cos = CO.coowners(did)
        owner = A.owner_public(d["user_id"])
        rows = [f'<li><span><b>{e(owner["display_name"] or "A member")}</b>{" (you)" if role == "owner" else ""}</span><span class="badge">Main owner</span></li>']
        for c in cos:
            me = u and c["user_id"] == u["id"]
            act = ""
            if role == "owner":
                act = (f'<form method="post" action="/me/dogs/{did}/coowners/{c["user_id"]}/remove" '
                       f'onsubmit="return confirm(\'Remove {e(c["name"])} as a co-owner of {nm}?\')">{self.csrf_field()}'
                       f'<button class="linkbtn" type="submit">Remove</button></form>')
            elif me:
                act = f'<a class="small" href="/me/dogs/{did}/leave">Leave</a>'
            rows.append(f'<li><span><b>{e(c["name"])}</b>{" (you)" if me else ""}</span><span class="small muted">Co-owner</span>{act}</li>')
        pend = ""
        if role == "owner":
            for i in CO.pending_invites(did):
                rows.append(f'<li><span>{e(i["email"])}</span><span class="small muted">Invited, link expires {_when(i["expires_at"])}</span>'
                            f'<form method="post" action="/me/dogs/{did}/coowners/invites/{i["id"]}/revoke">{self.csrf_field()}'
                            f'<button class="linkbtn" type="submit">Cancel invite</button></form></li>')
            n_used = len(cos) + len(CO.pending_invites(did))
            if n_used < CO.MAX_COOWNERS:
                pend = f"""<form method="post" action="/me/dogs/{did}/coowners/invite" class="coinv" novalidate>{self.csrf_field()}
<div class="field"><label for="co-email">Invite a co-owner</label>
<div class="coinv-row"><input id="co-email" name="email" type="email" inputmode="email" autocomplete="off" maxlength="254" required placeholder="their@email.com"{' aria-invalid="true"' if err else ''}>
<button class="btn btn-sm" type="submit">Send invite</button></div>
<span class="help">We'll email them a link (valid 7 days). They can edit {nm}'s profile and photos and bring {nm} to meetups and packs. Only you can delete {nm}'s profile.</span></div></form>"""
            else:
                pend = f'<p class="small muted">{nm} has the most co-owners we allow ({CO.MAX_COOWNERS}, open invites included).</p>'
        else:
            pend = f'<p class="small muted">Only the main owner can invite or remove co-owners and delete {nm}\'s profile.</p>'
        note = (f'<p class="notice small" role="status">{e(CO_MSG[msg])}</p>' if msg in CO_MSG else "") + \
               (f'<p class="err" role="alert">{e(CO_ERR[err])}</p>' if err in CO_ERR else "")
        return f"""<div class="panel" id="coowners-panel"><h2>Co-owners</h2>
<p class="hint">Share {nm} with a partner, family member or dog walker. Everyone shares one profile and one pixel portrait.</p>
{note}<ul class="colist">{"".join(rows)}</ul>{pend}</div>"""

    def _co_back(self, did, **kw):
        qs = "&".join(f"{k}={v}" for k, v in kw.items())
        return self.redirect(f"/me/dogs/{did}/edit" + (f"?{qs}" if qs else "") + "#coowners-panel")

    # ------------------------------------------------------------ owner actions
    def post_coowner_invite(self, dog_id):
        d = self.own_dog(int(dog_id), primary=True)
        if d is None:
            return
        f = self._form_or_fail()
        if f is None:
            return
        u = self.user()
        email = (f.get("email") or "").strip().lower()[:254]
        if not EMAIL_RE.match(email):
            return self._co_back(d["id"], coe="email")
        if not A.LIMITER.allow(f"coinvite:{u['id']}", INVITES_PER_DAY, 86400):
            return self._co_back(d["id"], coe="limit")
        try:
            raw = CO.create_invite(d, u["id"], email)
        except CO.InviteError as ex:
            return self._co_back(d["id"], coe=str(ex))
        link = f"{self._base()}/invite/{raw}"
        who = u["display_name"] or u["email"]
        subject = f"{who} invited you to co-own {d['name']} on BarksBuds"
        paras = [f"Hi,", f"{who} added you as a co-owner of {d['name']} on BarksBuds, the local social network for dogs and their people.",
                 f"As a co-owner you can edit {d['name']}'s profile and photos and bring {d['name']} to meetups and packs.",
                 "The link below works for 7 days and signs you in (it creates your free account if you don't have one). No password needed."]
        text = "\n\n".join(paras + [f"Accept the invite: {link}",
                                    "If you don't know this person, just ignore this email.", "BarksBuds"])
        body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622">'
                + "".join(f'<p style="margin:0 0 12px">{e(x)}</p>' for x in paras)
                + f'<p><a href="{e(link)}" style="display:inline-block;background:#141414;color:#fff;padding:10px 18px;border-radius:999px;'
                  f'text-decoration:none;font-weight:700">Accept the invite</a></p>'
                  '<p style="margin:16px 0 0;color:#6b645c;font-size:14px">If you don\'t know this person, just ignore this email.</p>'
                  '<p style="margin:16px 0 0">BarksBuds</p></div>')
        queued = mailer.send_async(email, subject, body, text, None, "coowner-invite")
        print(f"coowners: dog {d['id']} invite to {mailer._mask(email)} by user {u['id']} (email {'queued' if queued else 'not sent'})", flush=True)
        if not queued:
            A.q("UPDATE dog_invites SET revoked_at=:t WHERE token_hash=:h", t=A.now(), h=A.sha(raw))
            return self._co_back(d["id"], coe="mail")
        return self._co_back(d["id"], co="sent")

    def post_coowner_revoke(self, dog_id, invite_id):
        d = self.own_dog(int(dog_id), primary=True)
        if d is None or self._form_or_fail() is None:
            return
        CO.revoke(d["id"], int(invite_id))
        return self._co_back(d["id"], co="revoked")

    def post_coowner_remove(self, dog_id, user_id):
        d = self.own_dog(int(dog_id), primary=True)
        if d is None or self._form_or_fail() is None:
            return
        if CO.remove(d["id"], int(user_id)):
            print(f"coowners: dog {d['id']} co-owner {user_id} removed by owner", flush=True)
        return self._co_back(d["id"], co="removed")

    # ------------------------------------------------------------ co-owner leaves
    def leave_page(self, d):
        if d.get("my_role") != "co-owner":
            return self.redirect(f"/me/dogs/{d['id']}/edit#coowners-panel")
        return self.msg_page(f"Stop co-owning {d['name']}?", f"""<p class="sub">{e(d["name"])} will disappear from your dogs. The profile, photos and portrait stay with the main owner.</p>
<form method="post" action="/me/dogs/{d["id"]}/leave">{self.csrf_field()}<button class="btn" type="submit">Leave</button></form>
<p class="small" style="margin-top:14px"><a href="/me/dogs/{d["id"]}/edit">Stay a co-owner</a></p>""", icon="i-alert")

    def post_coowner_leave(self, dog_id):
        d = self.own_dog(int(dog_id))
        if d is None or self._form_or_fail() is None:
            return
        if d.get("my_role") != "co-owner":
            return self.redirect(f"/me/dogs/{d['id']}/edit#coowners-panel")
        CO.remove(d["id"], self.user()["id"])
        print(f"coowners: user {self.user()['id']} left dog {d['id']}", flush=True)
        return self.redirect("/me?m=left")

    # ------------------------------------------------------------ accepting
    def _invite_bad(self, state):
        title, txt = {"used": ("That invite was already used", "Each invite link works once. If it was you, the dog is already on your account."),
                      "revoked": ("That invite was cancelled", "The owner cancelled this invite. Ask them to send a new one if you need it."),
                      "expired": ("That invite has expired", "Invite links work for 7 days. Ask the owner to send a new one."),
                      "full": ("That dog has all the co-owners it can have", f"A dog can have up to {CO.MAX_COOWNERS} co-owners."),
                      }.get(state, ("That invite link doesn't work", "Check that you copied the whole link from the email."))
        u = self.user()
        btn = '<a class="btn" href="/me">My dogs</a>' if u else '<a class="btn" href="/signin">Sign in</a>'
        return self.msg_page(title, f'<p class="sub">{e(txt)}</p><p>{btn}</p>', code=410 if state in ("used", "revoked", "expired") else 404,
                             icon="i-alert")

    def invite_page(self, raw):
        state, inv = CO.peek(raw)
        if state != "ok":
            return self._invite_bad(state)
        d = A.dog_by_id(inv["dog_id"])
        inviter = A.owner_public(inv["inviter_user_id"])["display_name"] or "A BarksBuds member"
        u = self.user()
        if u and CO.can_manage(d, u["id"]):
            return self.redirect(f"/me/dogs/{d['id']}/edit")
        who = (f'<p class="small muted">You\'re signed in as <b>{e(u["email"])}</b>. {e(d["name"])} will be added to this account.'
               + ('' if u["email"].lower() == inv["email"] else f' (The invite was sent to {e(inv["email"])}.)') + '</p>') if u else \
              f'<p class="small muted">This signs you in as <b>{e(inv["email"])}</b> and creates your free account if you don\'t have one. No password needed.</p>'
        photos = A.gallery(d["id"])
        _, av = A.cover_and_avatar(d, photos)
        img = f'<p><img class="av" src="/p/{av}.webp" alt="" width="92" height="92" style="display:block;margin:0 auto;border-radius:50%"></p>' if av else ""
        return self.msg_page(f"Co-own {d['name']} on BarksBuds", f"""{img}<p class="sub">{e(inviter)} invited you to be a co-owner of
<a href="/dogs/{e(d["slug"])}">{e(d["name"])}</a>. You'll be able to edit {e(d["name"])}'s profile and photos and bring {e(d["name"])} to meetups and packs.</p>
<form method="post" action="/invite/{e(raw)}">{self.csrf_field()}<button class="btn" type="submit">Accept and co-own {e(d["name"])}</button></form>
{who}<p class="small muted">The link works until it's used, for 7 days.</p>""", icon="i-heart")

    def post_invite_accept(self, raw):
        f = self._form_or_fail()
        if f is None:
            return
        if not A.LIMITER.allow("invite-ip:" + self._client_ip(), 30, 600):
            return self.msg_page("Slow down a little", "<p class=\"sub\">Too many attempts. Please wait a few minutes.</p>", code=429)
        state, inv = CO.peek(raw)
        if state != "ok":
            return self._invite_bad(state)
        u = self.user()
        new = False
        if u:
            uid = u["id"]
        else:
            uid, new = A.get_or_create_user(inv["email"])
        try:
            d = CO.accept(raw, uid)
        except CO.InviteError as ex:
            return self._invite_bad(str(ex))
        if not u:  # the link was emailed to this address, so it signs them in like a magic link
            import webapp
            self._set_cookie(webapp.SESSION_COOKIE, A.create_session(uid), max_age=A.SESSION_TTL)
            print(f"signin: {'new account' if new else 'signed in'} user {uid} via co-owner invite", flush=True)
        print(f"coowners: user {uid} joined dog {d['id']}", flush=True)
        return self.redirect(f"/me/dogs/{d['id']}/edit?co=joined#coowners-panel")
