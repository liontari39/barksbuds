"""BarksBuds direct messages: web routes (inbox, conversations, Message buttons, block/report, email preferences).

Mixed into server.H. Plain text only: every message is HTML-escaped and shown with white-space:pre-wrap; links are
never turned into anchors. Members' email addresses are never shown; notifications go out from the site.
"""
import html, re
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, quote, urlsplit

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5), "ET")

import accounts as A
import mailer
import messages as MS
import webapp as W
from webapp import clean

e = html.escape

W.FLASH.update({
    "msg_sent": "Message sent.", "msg_blocked": "Blocked. They can't message you, and the conversation is hidden from your inbox.",
    "msg_unblocked": "Unblocked.", "msg_reported": "Thanks. The BarksBuds team will take a look.",
    "message_emails_on": "Message emails are on.", "message_emails_off": "Message emails are off.",
})
GENERIC_BLOCK = "You can't send messages to this member right now."


def when_short(ts):
    """'3:04 PM' today, 'Mon 3:04 PM' this week, else 'Oct 3' (America/New_York)."""
    d = datetime.fromtimestamp(ts, ET)
    nowd = datetime.now(ET)
    if d.date() == nowd.date():
        return d.strftime("%-I:%M %p")
    if (nowd.date() - d.date()).days < 6:
        return d.strftime("%a %-I:%M %p")
    return d.strftime("%b %-d") if d.year == nowd.year else d.strftime("%b %-d, %Y")


def when_long(ts):
    return datetime.fromtimestamp(ts, ET).strftime("%b %-d, %Y at %-I:%M %p ET")


def conv_path(cid):
    return f"/messages/{int(cid)}"


def initial(name):
    m = re.search(r"\w", name or "")
    return (m.group(0).upper() if m else "?")


class MessageRoutes:
    # ------------------------------------------------------------ routing
    def msg_get(self, path, q):
        self._app_reset()
        if path in ("/messages", "/messages/"):
            self.inbox_page(q); return True
        mt = re.fullmatch(r"/messages/(\d+)/?", path)
        if mt:
            self.conversation_page(int(mt.group(1)), q); return True
        mt = re.fullmatch(r"/messages/to/(\d+)/?", path)
        if mt:
            self.compose_page(int(mt.group(1)), q); return True
        if path == "/emails/messages":
            self.message_unsub_page(q); return True
        if path == "/admin/messages":
            self.admin_messages(q); return True
        return False

    def msg_post(self, path, q):
        self._app_reset()
        routes = [(r"/messages/to/(\d+)", self.post_compose), (r"/messages/(\d+)", self.post_reply),
                  (r"/messages/(\d+)/(block|unblock)", self.post_conv_block),
                  (r"/messages/(\d+)/report", self.post_msg_report),
                  (r"/messages/blocked/(\d+)/unblock", self.post_unblock_member),
                  (r"/me/message-emails", self.post_message_email_prefs), (r"/emails/messages", self.post_message_unsub),
                  (r"/admin/messages", self.post_admin_messages)]
        for pat, fn in routes:
            mt = re.fullmatch(pat, path)
            if mt:
                fn(*[int(x) if x.isdigit() else x for x in mt.groups()])
                return True
        return False

    # ------------------------------------------------------------ Message buttons (used by dog, pack and meetup pages)
    def message_button(self, uid, label="Message", cls="btn btn-ghost btn-sm msgbtn"):
        """A Message link to member `uid`; '' for yourself. Signed-out visitors go to sign in first, then the compose page."""
        u = self.user()
        if not uid or (u and u["id"] == uid):
            return ""
        href = f"/messages/to/{int(uid)}"
        if not u:
            href = self.signin_href(href)
        return (f'<a class="{cls}" href="{e(href)}"><svg class="ico" aria-hidden="true"><use href="#i-chat"/></svg>'
                f'<span>{e(label)}</span></a>')

    def message_link(self, uid, name=""):
        """A small inline 'Message' link for member lists."""
        lab = f"Message {name}" if name else "Message"
        b = self.message_button(uid, "Message", cls="msglink")
        return b.replace('<a class="msglink"', f'<a class="msglink" aria-label="{e(lab)}"', 1) if b else ""

    # ------------------------------------------------------------ inbox
    def inbox_page(self, q):
        u = self.user()
        if not u:
            return self.need_login()
        convs = MS.inbox(u["id"])
        items = []
        for c in convs:
            mine = c["last_sender"] == u["id"]
            unread = c["unread"]
            pv = ("You: " if mine else "") + MS.preview(c["last_body"], 90)
            badge = (f'<span class="ubadge" aria-label="{unread} unread">{unread if unread < 100 else "99+"}</span>' if unread else "")
            items.append(f'<li class="{"unread" if unread else ""}"><a href="{conv_path(c["id"])}">'
                         f'<span class="mav" aria-hidden="true">{e(initial(c["other_name"]))}</span>'
                         f'<span class="mrow"><span class="mtop"><strong>{e(c["other_name"])}</strong>'
                         f'<time datetime="{datetime.fromtimestamp(c["last_at"], timezone.utc).isoformat()}">{e(when_short(c["last_at"]))}</time></span>'
                         f'<span class="mpv">{e(pv)}</span></span>{badge}</a></li>')
        if items:
            lst = f'<ul class="inbox">{"".join(items)}</ul>'
        else:
            lst = ('<div class="panel mempty"><span class="mailicon"><svg class="ico" aria-hidden="true"><use href="#i-chat"/></svg></span>'
                   '<h2>No messages yet</h2><p class="muted">Say hi to another dog owner: look for the <b>Message</b> button on a dog\'s page, '
                   'in a pack\'s member list or on a meetup\'s RSVP list.</p>'
                   '<p class="formfoot" style="justify-content:center"><a class="btn btn-sm" href="/dogs">Meet the dogs</a>'
                   '<a class="btn btn-ghost btn-sm" href="/packs">Browse packs</a></p></div>')
        bl = MS.blocked_list(u["id"])
        blocked = ""
        if bl:
            rows = "".join(f'<li><span>{e(b["name"])}</span><form method="post" action="/messages/blocked/{b["user_id"]}/unblock">'
                           f'{self.csrf_field()}<button class="linkbtn" type="submit">Unblock</button></form></li>' for b in bl)
            blocked = (f'<details class="mblocked"><summary>Blocked members ({len(bl)})</summary>'
                       f'<p class="small muted">They can\'t message you. Your conversations with them are hidden.</p><ul>{rows}</ul></details>')
        total = sum(c["unread"] for c in convs)
        sub = f"{total} unread" if total else "Private conversations with other members"
        body = f"""<section class="phead"><div class="wrap narrow"><span class="eyebrow">messages</span><h1>Messages</h1>
<p class="lead">{e(sub)}</p></div></section>
<section class="section msec"><div class="wrap narrow">{lst}
<p class="small muted mnote"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg><span>Only you and the other member can read a conversation.
Your email address is never shared. Turn message emails on or off on <a href="/me#message-emails">your account page</a>.</span></p>
{blocked}</div></section>"""
        return self.page("Messages", body, active="messages", flash=self.flash_from(q))

    # ------------------------------------------------------------ compose (first message to a member)
    def _recipient_or_fail(self, uid):
        """(user, other_id) or renders an error / redirect and returns (None, None)."""
        u = self.user()
        if not u:
            self.need_login()
            return None, None
        if uid == u["id"]:
            self.msg_page("That's you!", '<p class="sub">You can\'t send a message to yourself.</p>'
                          '<p><a class="btn" href="/messages">Go to messages</a></p>', code=400, icon="i-chat")
            return None, None
        if not MS.user_exists(uid):
            self.msg_page("We couldn't find that member", '<p class="sub">Their account may have been closed.</p>'
                          '<p><a class="btn" href="/messages">Go to messages</a></p>', code=404, icon="i-chat")
            return None, None
        return u, uid

    def compose_page(self, uid, q, text="", err="", code=200):
        u, oid = self._recipient_or_fail(uid)
        if not u:
            return
        c = MS.find(u["id"], oid)
        if c and c["last_message_id"] and not err:
            return self.redirect(conv_path(c["id"]) + "#reply")
        name = MS.name_of(oid)
        form = self.reply_form(f"/messages/to/{oid}", name, text, err, MS.blocked(u["id"], oid), oid)
        body = f"""<section class="phead"><div class="wrap narrow"><a class="mback" href="/messages">&larr; Messages</a>
<span class="eyebrow">new message</span><h1>Message {e(name)}</h1>{self.dogs_line(oid, name)}</div></section>
<section class="section msec"><div class="wrap narrow"><div class="panel">{form}</div>
<p class="small muted mnote"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg><span>{e(name)} gets a short email that you sent a message;
your email address stays private. Be kind, and keep plans for meeting up in public places like the dog run.</span></p></div></section>"""
        return self.page(f"Message {name}", body, code=code, active="messages")

    def dogs_line(self, oid, name):
        dogs = MS.other_dogs(oid)
        if not dogs:
            return ""
        links = W_and([f'<a href="/dogs/{e(s)}">{e(n)}</a>' for s, n in dogs])
        return f'<p class="mdogsline">{links}\'s human</p>'

    def reply_form(self, action, name, text="", err="", i_blocked=False, oid=None, can_send=True):
        if i_blocked:
            return (f'<p class="mstop">You blocked {e(name)}. Unblock them to send messages.</p>'
                    f'<form method="post" action="/messages/blocked/{int(oid)}/unblock">{self.csrf_field()}'
                    f'<button class="btn btn-ghost btn-sm" type="submit">Unblock {e(name)}</button></form>')
        if not can_send:
            return f'<p class="mstop">{e(GENERIC_BLOCK)}</p>'
        inv = ' aria-invalid="true" aria-describedby="err-body"' if err else ""
        errh = f'<p class="formerr" id="err-body" role="alert">{e(err)}</p>' if err else ""
        return (f'<form class="mreply" id="reply" method="post" action="{e(action)}">{self.csrf_field()}{errh}'
                f'<label class="sr-only" for="body">Message to {e(name)}</label>'
                f'<textarea id="body" name="body" rows="3" maxlength="{MS.MAX_BODY}" required placeholder="Write a message to {e(name)}"{inv}>{e(text)}</textarea>'
                f'<div class="mreplyfoot"><span class="small muted" data-count>Plain text, up to {MS.MAX_BODY:,} characters</span>'
                f'<button class="btn btn-sm" type="submit"><svg class="ico" aria-hidden="true"><use href="#i-nav"/></svg>Send</button></div></form>')

    # ------------------------------------------------------------ conversation
    def own_conv(self, cid):
        u = self.user()
        if not u:
            self.need_login()
            return None, None
        c = MS.get(cid)
        if not MS.is_participant(c, u["id"]):
            self.msg_page("We couldn't find that conversation", '<p class="sub">It may have been removed.</p>'
                          '<p><a class="btn" href="/messages">Go to messages</a></p>', code=404, icon="i-chat")
            return None, None
        return c, u

    def conversation_page(self, cid, q, text="", err="", code=200):
        c, u = self.own_conv(cid)
        if not c:
            return
        oid = MS.other(c, u["id"])
        name = MS.name_of(oid)
        i_blocked = MS.blocked(u["id"], oid)
        can_send = not MS.either_blocked(u["id"], oid)
        msgs, more = MS.messages(cid)
        st = MS.state(cid, u["id"])
        if not i_blocked:
            MS.mark_read(cid, u["id"])
        reasons = "".join(f"<option>{e(r)}</option>" for r in A.REPORT_REASONS)
        items, last_day = [], None
        for m in msgs:
            mine = m["sender_id"] == u["id"]
            day = datetime.fromtimestamp(m["created_at"], ET).strftime("%A, %B %-d")
            if day != last_day:
                items.append(f'<li class="mday"><span>{e(day)}</span></li>')
                last_day = day
            new = (not mine and m["id"] > st["last_read_id"])
            rep = "" if mine else (
                f'<details class="mrep"><summary>Report</summary><form method="post" action="{conv_path(cid)}/report">{self.csrf_field()}'
                f'<input type="hidden" name="message_id" value="{m["id"]}"><label class="sr-only" for="r{m["id"]}">Reason</label>'
                f'<select id="r{m["id"]}" name="reason">{reasons}</select>'
                f'<label class="sr-only" for="d{m["id"]}">Details</label><textarea id="d{m["id"]}" name="details" maxlength="1000" rows="2" placeholder="Anything else? (optional)"></textarea>'
                f'<button class="btn btn-sm" type="submit">Send report</button>'
                f'<p class="small muted" style="margin:6px 0 0">Reports go to the BarksBuds team, not to {e(name)}.</p></form></details>')
            items.append(f'<li class="msg {"mine" if mine else "theirs"}{" new" if new else ""}" id="m{m["id"]}"'
                         f'><div class="bubble"><span class="sr-only">{"You" if mine else e(name)}:</span>'
                         f'<p>{e(m["body"])}</p></div><div class="mmeta"><time title="{e(when_long(m["created_at"]))}">'
                         f'{e(datetime.fromtimestamp(m["created_at"], ET).strftime("%-I:%M %p"))}</time>{rep}</div></li>')
        older = '<li class="mday"><span>Older messages aren\'t shown</span></li>' if more else ""
        thread = (f'<ol class="thread" aria-label="Messages with {e(name)}">{older}{"".join(items)}</ol>' if items else
                  '<p class="muted">No messages yet.</p>')
        form = self.reply_form(conv_path(cid), name, text, err, i_blocked, oid, can_send)
        safety = (f'<details class="msafety"><summary>Block {e(name)}</summary><p class="small">{e(name)} won\'t be able to message you, '
                  f'and this conversation is hidden from your inbox. They aren\'t told.</p><form method="post" action="{conv_path(cid)}/block">'
                  f'{self.csrf_field()}<button class="btn btn-danger btn-sm" type="submit">Block {e(name)}</button></form></details>'
                  if not i_blocked else "")
        js = """<script>(function(){var t=document.getElementById('body'),c=document.querySelector('[data-count]');
if(t&&c){var max=+t.getAttribute('maxlength');t.addEventListener('input',function(){var n=t.value.length;c.textContent=n>max-300?(max-n)+' characters left':'Plain text, up to '+max.toLocaleString()+' characters'})}
if(!location.hash){var l=document.querySelector('.thread li:last-child');if(l)l.scrollIntoView({block:'end'})}
var f=document.getElementById('reply');if(f)f.addEventListener('submit',function(){var b=f.querySelector('button');setTimeout(function(){b.disabled=true},0)});
if(t)t.addEventListener('keydown',function(ev){if(ev.key==='Enter'&&(ev.metaKey||ev.ctrlKey)&&t.value.trim()){f.requestSubmit?f.requestSubmit():f.submit()}})})();</script>"""
        body = f"""<section class="phead mhead"><div class="wrap narrow"><a class="mback" href="/messages">&larr; Messages</a>
<div class="mwho"><span class="mav lg" aria-hidden="true">{e(initial(name))}</span><div><h1>{e(name)}</h1>{self.dogs_line(oid, name)}</div></div></div></section>
<section class="section msec"><div class="wrap narrow"><div class="panel mconv">{thread}{form}</div>
<p class="small muted mnote"><svg class="ico" aria-hidden="true"><use href="#i-lock"/></svg><span>Only you and {e(name)} can read this.
Never share passwords or payment details. Something wrong? Report a message or block {e(name)}.</span></p>{safety}</div></section>"""
        return self.page(f"Messages with {name}", body, code=code, active="messages", scripts=js, flash=self.flash_from(q))

    # ------------------------------------------------------------ sending
    def _validate_send(self, u, oid, new_conv):
        """'' if this member may send now, else the error to show (and the HTTP status)."""
        if MS.either_blocked(u["id"], oid):
            return GENERIC_BLOCK, 403
        if new_conv and (MS.started_today(u["id"]) >= MS.NEW_PER_DAY or not A.LIMITER.allow(f"msg-new:{u['id']}", MS.NEW_PER_DAY, 86400)):
            return f"You've started {MS.NEW_PER_DAY} new conversations today. Try again tomorrow, or reply in an existing one.", 429
        if not A.LIMITER.allow(f"msg-send:{u['id']}", MS.SEND_PER_HOUR, 3600):
            return "You're sending messages quickly. Please wait a bit and try again.", 429
        return "", 200

    def _read_body(self, f):
        raw = f.get("body") or ""
        body = MS.clean_body(raw)
        if not body:
            return body, "Write a message first."
        if len(raw.strip()) > MS.MAX_BODY + 200:
            return body[:MS.MAX_BODY], f"Messages can be up to {MS.MAX_BODY:,} characters."
        return body, ""

    def post_compose(self, uid):
        u, oid = self._recipient_or_fail(uid)
        if not u:
            return
        f = self._form_or_fail()
        if f is None:
            return
        body, err = self._read_body(f)
        if err:
            return self.compose_page(oid, {}, body, err, code=422)
        existing = MS.find(u["id"], oid)
        new_conv = not (existing and existing["last_message_id"])
        err, code = self._validate_send(u, oid, new_conv)
        if err:
            return self.compose_page(oid, {}, body, err, code=code)
        c, _ = MS.get_or_create(u["id"], oid)
        MS.add_message(c, u["id"], body)
        print(f"messages: new conversation {c['id']}" if new_conv else f"messages: message in conversation {c['id']}", flush=True)
        self.notify_message(c, u, oid, body)
        return self.redirect(conv_path(c["id"]) + "?m=msg_sent#reply")

    def post_reply(self, cid):
        c, u = self.own_conv(cid)
        if not c:
            return
        f = self._form_or_fail()
        if f is None:
            return
        oid = MS.other(c, u["id"])
        body, err = self._read_body(f)
        if err:
            return self.conversation_page(cid, {}, body, err, code=422)
        err, code = self._validate_send(u, oid, False)
        if err:
            return self.conversation_page(cid, {}, body, err, code=code)
        MS.add_message(c, u["id"], body)
        print(f"messages: message in conversation {cid}", flush=True)
        self.notify_message(c, u, oid, body)
        return self.redirect(conv_path(cid) + "#reply")

    def notify_message(self, c, sender, rid, body):
        """At most one email per conversation per recipient every 30 minutes, if they have message emails on."""
        to, rname, on = MS.contact(rid)
        if not to or not on or MS.blocked(rid, sender["id"]):
            return False
        if not MS.claim_email_slot(c["id"], rid):
            return False
        base = self._base()
        sname = sender.get("display_name") or "A BarksBuds member"
        subject, html_body, text = mailer.build_message(base, rname, sname, MS.preview(body), base + conv_path(c["id"]),
                                                        unsub=message_unsub_url(base, rid))
        return mailer.send_async(to, subject, html_body, text, message_unsub_url(base, rid), "message-new")

    # ------------------------------------------------------------ block / unblock / report
    def post_conv_block(self, cid, what):
        c, u = self.own_conv(cid)
        if not c:
            return
        if self._form_or_fail() is None:
            return
        oid = MS.other(c, u["id"])
        if what == "block":
            MS.block(u["id"], oid)
            print(f"messages: block in conversation {cid}", flush=True)
            return self.redirect("/messages?m=msg_blocked")
        MS.unblock(u["id"], oid)
        return self.redirect(conv_path(cid) + "?m=msg_unblocked")

    def post_unblock_member(self, oid):
        u = self.user()
        if not u:
            return self.need_login()
        if self._form_or_fail() is None:
            return
        MS.unblock(u["id"], oid)
        c = MS.find(u["id"], oid)
        return self.redirect((conv_path(c["id"]) if c and c["last_message_id"] else f"/messages/to/{oid}") + "?m=msg_unblocked")

    def post_msg_report(self, cid):
        c, u = self.own_conv(cid)
        if not c:
            return
        f = self._form_or_fail()
        if f is None:
            return
        try:
            mid = int(f.get("message_id") or 0)
        except ValueError:
            mid = 0
        m = MS.message(mid)
        if not m or m["conversation_id"] != cid or m["sender_id"] == u["id"]:
            return self.redirect(conv_path(cid))
        reason = f.get("reason") if f.get("reason") in A.REPORT_REASONS else "Something else"
        details = clean(f.get("details"), 1000, multiline=True)
        if A.LIMITER.allow("report:" + self._client_ip(), 10, 3600) and A.LIMITER.allow(f"msg-report:{u['id']}", 10, 3600):
            MS.add_report(m, u["id"], reason, details, self._client_ip())
            print(f"reports: new report on message {mid} in conversation {cid}", flush=True)
            self.notify_report(m, u, reason, details)
        return self.redirect(conv_path(cid) + "?m=msg_reported")

    def notify_report(self, m, reporter, reason, details):
        """Email the report to Mike (RUN_SUGGEST_EMAIL / the runs allowlist address), like tip and run suggestions.
        Includes the reported message so it can be reviewed, but never anyone's email address or the admin key."""
        import runsweb
        to = runsweb.NOTIFY_TO
        if not to:
            return False
        rname = reporter.get("display_name") or "A member"
        sname = MS.name_of(m["sender_id"])
        subject = f"Message reported: {reason}"
        lines = [f"{rname} (member #{reporter['id']}) reported a message from {sname} (member #{m['sender_id']}).",
                 f"Reason: {reason}", f"Details: {details}" if details else "", f"Sent: {when_long(m['created_at'])}",
                 "", "Reported message:", m["body"][:1500], "",
                 f"Review it at {self._base()}/admin/messages (add ?key= with your admin key)."]
        text = "\n".join(lines)
        body = ('<div style="font:16px/1.5 system-ui,sans-serif;color:#2a2622"><h2 style="margin:0 0 8px">' + e(subject) + "</h2>"
                + "".join(f'<p style="margin:0 0 6px">{e(x)}</p>' for x in lines[:4] if x)
                + f'<blockquote style="margin:10px 0;padding:10px 14px;border-left:4px solid #FBB321;background:#FFF8EA;white-space:pre-wrap">{e(m["body"][:1500])}</blockquote>'
                + f'<p>Review it at {e(self._base())}/admin/messages (add ?key= with your admin key).</p></div>')
        return mailer.send_async(to, subject, body, text, None, "runs-message-report")

    # ------------------------------------------------------------ email preferences
    def message_email_prefs_html(self, u):
        on = MS.emails_on(u["id"])
        return (f'<form id="message-emails" method="post" action="/me/message-emails" class="emailpref">{self.csrf_field()}'
                f'<input type="hidden" name="on" value="{0 if on else 1}"><p class="small" style="margin:0 0 8px"><b>Message emails:</b> '
                f'{"On" if on else "Off"}. A heads-up when a member messages you (at most one per conversation every 30 minutes).</p>'
                f'<button class="btn btn-ghost btn-sm" type="submit">{"Turn off message emails" if on else "Turn on message emails"}</button></form>')

    def post_message_email_prefs(self):
        u = self.user()
        if not u:
            return self.need_login()
        f = self._form_or_fail()
        if f is None:
            return
        on = f.get("on") == "1"
        MS.set_emails(u["id"], on)
        return self.redirect("/me?m=" + ("message_emails_on" if on else "message_emails_off") + "#message-emails")

    def message_unsub_page(self, q):
        uid, tok = q.get("u", [""])[0], q.get("t", [""])[0]
        if not MS.check_unsub(uid, tok):
            return self.msg_page("That link didn't work", '<p class="sub">It may be incomplete. You can change message emails from your account page.</p>'
                                 '<p><a class="btn" href="/me">Go to my account</a></p>', code=400, icon="i-mail")
        on = MS.emails_on(int(uid))
        body = (f'<p class="sub">{"Message emails are on" if on else "Message emails are off"}: a short heads-up when a member sends you a message.</p>'
                f'<form method="post" action="/emails/messages"><input type="hidden" name="u" value="{e(uid)}"><input type="hidden" name="t" value="{e(tok)}">'
                f'<input type="hidden" name="action" value="{"off" if on else "on"}"><button class="btn" type="submit">'
                f'{"Turn off message emails" if on else "Turn message emails back on"}</button></form>'
                '<p class="small muted" style="margin-top:14px">Your messages stay in your BarksBuds inbox either way.</p>')
        return self.msg_page("Message emails" if on else "Message emails are off", body, icon="i-mail")

    def post_message_unsub(self):
        """Token-authenticated (no session or CSRF needed). Also handles RFC 8058 one-click POSTs from mail apps."""
        f = self.read_form()
        if f is None:
            return self._emit(413, b"Too large", "text/plain")
        uid, tok = f.get("u"), f.get("t")
        if not uid:
            qs = parse_qs(urlsplit(self.path).query)
            uid, tok = qs.get("u", [""])[0], qs.get("t", [""])[0]
        if not MS.check_unsub(uid, tok):
            return self._emit(400, b"Invalid link", "text/plain")
        on = f.get("action") == "on"
        MS.set_emails(int(uid), on)
        print("messages: email preference changed via link", flush=True)
        if f.get("List-Unsubscribe") == "One-Click":
            return self._emit(200, b"Unsubscribed", "text/plain")
        msg = "You'll get message emails again." if on else "You won't get message emails anymore. Your inbox is still at barksbuds.app/messages."
        return self.msg_page("Done", f'<p class="sub">{e(msg)}</p><p><a class="btn" href="/messages">Go to messages</a></p>', icon="i-mail")

    # ------------------------------------------------------------ admin: reported messages
    def admin_messages(self, q):
        key = q.get("key", [""])[0] or self.headers.get("X-Admin-Key", "")
        if not self._admin_key_ok(key):
            return self._emit(404, b"Not found", "text/plain")
        rows = MS.list_reports()
        hid = f'<input type="hidden" name="key" value="{e(key)}">'
        n_conv = A.one("SELECT COUNT(*) FROM conversations")[0]
        n_msg = A.one("SELECT COUNT(*) FROM messages")[0]
        tr = []
        for r in rows:
            act = "resolved" if r["status"] == "open" else "open"
            tr.append(f'<tr><td>{r["id"]}</td><td>{e(when_long(r["created_at"]))}</td><td>{e(r["status"])}</td>'
                      f'<td>{e(r["reporter_name"] or "deleted")} (#{r["reporter"] or "-"})</td><td>{e(r["reported_name"] or "deleted")} (#{r["reported"] or "-"})</td>'
                      f'<td>{e(r["reason"])}<br><small>{e(r["details"])}</small></td><td style="white-space:pre-wrap;max-width:420px">{e(r["body"])}</td>'
                      f'<td><form method="post" action="/admin/messages">{hid}<input type="hidden" name="id" value="{r["id"]}">'
                      f'<input type="hidden" name="status" value="{act}"><button type="submit">Mark {act}</button></form>'
                      + (f'<form method="post" action="/admin/messages" style="margin-top:6px">{hid}<input type="hidden" name="id" value="{r["id"]}">'
                         f'<input type="hidden" name="action" value="delete_message"><button type="submit">Remove message from conversation</button></form>'
                         if r["message_id"] and r["live"] else "<br><small>message removed</small>") + '</td></tr>')
        table = ('<table border="1" cellpadding="6" style="border-collapse:collapse;font:14px system-ui"><tr><th>#</th><th>When</th><th>Status</th>'
                 '<th>Reporter</th><th>Reported</th><th>Reason</th><th>Message</th><th></th></tr>' + "".join(tr) + "</table>") if tr else "<p>No reported messages.</p>"
        doc = (f'<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>Reported messages</title>'
               f'<body style="font:15px system-ui;padding:20px"><h1>Reported messages</h1><p>{n_conv} conversations, {n_msg} messages. '
               f'Only reported messages are shown here.</p>{table}</body>')
        return self._emit(200, doc, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    def post_admin_messages(self):
        f = self.read_form()
        if f is None or not self._admin_key_ok(f.get("key") or self.headers.get("X-Admin-Key", "")):
            return self._emit(404, b"Not found", "text/plain")
        try:
            rid = int(f.get("id") or 0)
        except ValueError:
            rid = 0
        if rid and f.get("status") in ("open", "resolved"):
            MS.set_report_status(rid, f.get("status"))
        elif rid and f.get("action") == "delete_message":
            MS.delete_reported_message(rid)
            print(f"messages: admin removed the message in report {rid}", flush=True)
        return self.redirect("/admin/messages?key=" + quote(f.get("key") or ""))


def message_unsub_url(base, uid):
    return f"{base}/emails/messages?u={uid}&t={MS.unsub_token(uid)}"


def W_and(xs):
    xs = list(xs)
    return " and ".join(xs) if len(xs) < 3 else ", ".join(xs[:-1]) + " and " + xs[-1]
