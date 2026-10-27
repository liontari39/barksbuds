"""Direct messages: Message buttons (dog pages, pack member lists, meetup attendees), sending and replying, the inbox and
unread badge, plain-text escaping and length limits, blocks, reports (emailed to the site owner), rate limits, the
notification email (preview only, 30-minute throttle, per-user off switch + unsubscribe link) and account deletion.
Run with the rest:  python3 -m unittest discover -s tests -v   (TEST_DATABASE_URL=... for Postgres)
"""
import os, re, sys, time, unittest
from urllib.parse import quote, urlsplit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, mark, outbox, wait_mail  # noqa: E402
from test_packs import make_pack, join, ppage  # noqa: E402
import accounts as A  # noqa: E402
import messages as MS  # noqa: E402
import msgweb  # noqa: E402
import runsweb  # noqa: E402


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def send_to(c, uid, body):
    return c.post(f"/messages/to/{uid}", {"body": body})


def conv_id(r):
    return int(re.match(r"/messages/(\d+)", r.headers["Location"]).group(1))


def dog_slug(did):
    return A.one("SELECT slug FROM dogs WHERE id=:d", d=did)[0]


def wait_html(tag, to, since, n=1):
    """Like wait_mail, but each email also carries its HTML body (the file outbox writes it next to the JSON)."""
    import glob, json
    wait_mail(tag, to, since, n)
    out = []
    for fn in sorted(glob.glob(os.path.join(T.TMP, "outbox", f"*-{tag}-*.json"))):
        if fn not in since:
            d = json.load(open(fn))
            if to is None or d["to"] == to:
                d["html"] = open(fn[:-5] + ".html", encoding="utf-8").read()
                out.append(d)
    return out


def no_mail(tag, to, since, wait=0.6):
    time.sleep(wait)
    return not outbox(tag, to, since)


class MessageTests(unittest.TestCase):
    def test_signed_out_gets_sign_in_prompt(self):
        _, _, bid, bdogs = member("lilyowner")
        anon = Client("10.60.0.1")
        r = anon.get("/messages")
        self.assertEqual(r.status, 303)
        self.assertEqual(r.headers["Location"], "/signin?next=" + quote("/messages", safe=""))
        r = anon.get(f"/messages/to/{bid}")
        self.assertEqual(r.headers["Location"], "/signin?next=" + quote(f"/messages/to/{bid}", safe=""))
        page = anon.get(f"/dogs/{dog_slug(bdogs[0])}").text
        self.assertIn(e_attr("/signin?next=" + quote(f"/messages/to/{bid}", safe="")), page)
        self.assertEqual(anon.post(f"/messages/to/{bid}", {"body": "hi"}, csrf=False).status, 303)
        self.assertEqual(A.one("SELECT COUNT(*) FROM messages WHERE sender_id IS NULL")[0], 0)

    def test_dog_page_button_send_reply_inbox_and_badge(self):
        a, aemail, aid, _ = member("maggieowner")
        b, bemail, bid, bdogs = member("lilyowner")
        slug = dog_slug(bdogs[0])
        page = a.get(f"/dogs/{slug}").text
        self.assertIn(f'href="/messages/to/{bid}"', page)
        self.assertIn("Message Lilyowner", page)
        own = b.get(f"/dogs/{slug}").text  # owners don't see a button to themselves
        self.assertNotIn(f'href="/messages/to/{bid}"', own)
        # co-owners get their own button
        self.assertIn("Message", a.get(f"/messages/to/{bid}").text)
        r = send_to(a, bid, "Hi! Want to meet at the run Saturday?")
        self.assertEqual(r.status, 303, r.text[:400])
        cid = conv_id(r)
        self.assertEqual(MS.unread_total(bid), 1)
        self.assertEqual(MS.unread_total(aid), 0)
        # second visit to the compose page jumps to the existing conversation
        self.assertEqual(a.get(f"/messages/to/{bid}").headers["Location"], f"/messages/{cid}#reply")
        # recipient: nav badge on app pages and the home page, inbox row with unread count
        me = b.get("/me").text
        self.assertIn('class="nbadge"', me)
        self.assertIn('aria-label="Messages, 1 unread"', me)
        self.assertIn('aria-label="Messages, 1 unread"', b.get("/").text)
        inbox = b.get("/messages").text
        self.assertIn("Maggieowner", inbox)
        self.assertIn('aria-label="1 unread"', inbox)
        self.assertIn("Want to meet at the run", inbox)
        self.assertNotIn(aemail, inbox)
        conv = b.get(f"/messages/{cid}").text
        self.assertIn("Hi! Want to meet at the run Saturday?", conv)
        self.assertIn('id="reply"', conv)
        self.assertNotIn(aemail, conv)
        self.assertEqual(MS.unread_total(bid), 0)
        self.assertNotIn('class="nbadge"', b.get("/me").text)
        r = b.post(f"/messages/{cid}", {"body": "Yes! 9am?"})
        self.assertEqual(r.status, 303)
        self.assertEqual(MS.unread_total(aid), 1)
        self.assertIn("Yes! 9am?", a.get(f"/messages/{cid}").text)
        # newest first: a newer conversation goes to the top
        c3, _, cid3, _ = member("thirdowner")
        send_to(c3, aid, "Hello from a third member")
        rows = MS.inbox(aid)
        self.assertEqual([x["other_id"] for x in rows[:2]], [cid3, bid])

    def test_escaping_no_links_and_limits(self):
        a, _, aid, _ = member("maggieowner")
        _, _, bid, _ = member("lilyowner")
        evil = '<script>alert(1)</script> <b>bold</b> https://evil.example/x?a=1&b=2 "quoted"'
        cid = conv_id(send_to(a, bid, evil))
        page = a.get(f"/messages/{cid}").text
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn('href="https://evil.example', page)
        self.assertIn("https://evil.example/x?a=1&amp;b=2", page)
        # empty and too long
        r = a.post(f"/messages/{cid}", {"body": "   \n  "})
        self.assertEqual(r.status, 422)
        self.assertIn("Write a message first", r.text)
        r = a.post(f"/messages/{cid}", {"body": "x" * (MS.MAX_BODY + 500)})
        self.assertEqual(r.status, 422)
        self.assertIn("2,000 characters", r.text)
        r = a.post(f"/messages/{cid}", {"body": "y" * MS.MAX_BODY})
        self.assertEqual(r.status, 303)
        # control characters dropped, blank lines collapsed
        a.post(f"/messages/{cid}", {"body": "line1\x00\x07\n\n\n\n\nline2"})
        last = MS.messages(cid)[0][-1]["body"]
        self.assertEqual(last, "line1\n\nline2")
        # can't message yourself; unknown member
        self.assertEqual(a.get(f"/messages/to/{aid}").status, 400)
        self.assertEqual(send_to(a, aid, "me").status, 400)
        self.assertEqual(a.get("/messages/to/99999999").status, 404)

    def test_only_participants(self):
        a, _, _, _ = member("maggieowner")
        _, _, bid, _ = member("lilyowner")
        x, _, _, _ = member("outsider")
        cid = conv_id(send_to(a, bid, "private"))
        self.assertEqual(x.get(f"/messages/{cid}").status, 404)
        self.assertEqual(x.post(f"/messages/{cid}", {"body": "sneak"}).status, 404)
        self.assertEqual(x.post(f"/messages/{cid}/block", {}).status, 404)
        self.assertEqual(len(MS.messages(cid)[0]), 1)
        self.assertEqual(x.post(f"/messages/{cid}", {"body": "no csrf"}, csrf=False).status, 404)
        b2 = Client("10.60.0.9")
        self.assertEqual(b2.post(f"/messages/{cid}", {"body": "anon"}, csrf=False).status, 303)  # sign in

    def test_block_hides_and_prevents(self):
        a, _, aid, _ = member("maggieowner")
        b, _, bid, _ = member("lilyowner")
        cid = conv_id(send_to(a, bid, "hello"))
        r = b.post(f"/messages/{cid}/block", {})
        self.assertEqual(r.headers["Location"], "/messages?m=msg_blocked")
        self.assertTrue(MS.blocked(bid, aid))
        self.assertNotIn(f'href="/messages/{cid}"', b.get("/messages").text)
        self.assertIn("Blocked members (1)", b.get("/messages").text)
        self.assertEqual(MS.unread_total(bid), 0)
        t0 = mark()
        r = a.post(f"/messages/{cid}", {"body": "are you there?"})
        self.assertEqual(r.status, 403)
        self.assertIn(e_attr(msgweb.GENERIC_BLOCK), r.text)
        self.assertNotIn("blocked", r.text.split("<main")[1].lower().replace("unblock", ""))  # not told they were blocked
        self.assertEqual(send_to(a, bid, "new try").status, 403)
        self.assertEqual(len(MS.messages(cid)[0]), 1)
        self.assertTrue(no_mail("message-new", None, t0, 0.3))
        # the blocker can't send either until they unblock
        self.assertIn("Unblock them to send messages", b.get(f"/messages/{cid}").text)
        self.assertEqual(b.post(f"/messages/{cid}", {"body": "hm"}).status, 403)
        b.post(f"/messages/blocked/{aid}/unblock", {})
        self.assertFalse(MS.blocked(bid, aid))
        self.assertIn(f'href="/messages/{cid}"', b.get("/messages").text)
        self.assertEqual(a.post(f"/messages/{cid}", {"body": "ok now"}).status, 303)

    def test_report_emails_site_owner(self):
        a, aemail, aid, _ = member("maggieowner")
        b, bemail, bid, _ = member("lilyowner")
        cid = conv_id(send_to(a, bid, "rude words here"))
        mid = MS.messages(cid)[0][0]["id"]
        old, runsweb.NOTIFY_TO = runsweb.NOTIFY_TO, "owner-test@example.com"
        try:
            t0 = mark()
            self.assertEqual(a.post(f"/messages/{cid}/report", {"message_id": mid, "reason": A.REPORT_REASONS[0]}).headers["Location"],
                             f"/messages/{cid}")  # can't report your own message
            r = b.post(f"/messages/{cid}/report", {"message_id": mid, "reason": A.REPORT_REASONS[0], "details": "Not nice"})
            self.assertEqual(r.headers["Location"], f"/messages/{cid}?m=msg_reported")
            got = wait_html("runs-message-report", "owner-test@example.com", t0)[0]
            self.assertIn("rude words here", got["text"])
            self.assertIn("/admin/messages", got["text"])
            for addr in (aemail, bemail):
                self.assertNotIn(addr, got["text"] + got["html"])
            self.assertNotIn("test-admin-key", got["text"])
        finally:
            runsweb.NOTIFY_TO = old
        rows = [x for x in MS.list_reports() if x["message_id"] == mid]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["reporter"], rows[0]["reported"], rows[0]["body"]), (bid, aid, "rude words here"))
        # admin view (key only) and moderation
        self.assertEqual(Client().get("/admin/messages").status, 404)
        adm = Client().get("/admin/messages?key=test-admin-key")
        self.assertEqual(adm.status, 200)
        self.assertIn("rude words here", adm.text)
        self.assertNotIn(aemail, adm.text)
        Client().post("/admin/messages", {"key": "test-admin-key", "id": rows[0]["id"], "action": "delete_message"}, csrf=False)
        self.assertIsNone(MS.message(mid))
        self.assertEqual([x for x in MS.list_reports() if x["message_id"] == mid][0]["status"], "resolved")

    def test_notification_email_throttle_and_off_switch(self):
        a, aemail, aid, _ = member("maggieowner")
        b, bemail, bid, _ = member("lilyowner")
        long_body = "Secret plan: " + "woof " * 60 + "THE-END-MARKER"
        t0 = mark()
        cid = conv_id(send_to(a, bid, long_body))
        got = wait_html("message-new", bemail, t0)
        self.assertEqual(len(got), 1)
        m = got[0]
        self.assertEqual(m["subject"], "You have a new message from Maggieowner on BarksBuds")
        self.assertIn(f"/messages/{cid}", m["text"])
        self.assertIn(f"/messages/{cid}", m["html"])
        self.assertNotIn("THE-END-MARKER", m["text"] + m["html"])  # preview only, never the full text
        snippet = re.search(r'"(Secret plan:[^"]*)"', m["text"]).group(1)
        self.assertLessEqual(len(snippet), MS.PREVIEW)
        self.assertNotIn(aemail, m["text"] + m["html"])
        self.assertIn("/emails/messages?u=", m["text"])
        # throttle: more messages within 30 minutes don't email again
        t1 = mark()
        a.post(f"/messages/{cid}", {"body": "second"})
        a.post(f"/messages/{cid}", {"body": "third"})
        self.assertTrue(no_mail("message-new", bemail, t1))
        # after the window, another email
        A.q("UPDATE conversation_state SET last_email_at=:t WHERE conversation_id=:c AND user_id=:u", t=A.now() - MS.EMAIL_EVERY - 5, c=cid, u=bid)
        t2 = mark()
        a.post(f"/messages/{cid}", {"body": "fourth"})
        wait_mail("message-new", bemail, t2)
        # off switch on /me
        self.assertIn("Message emails:", b.get("/me").text)
        r = b.post("/me/message-emails", {"on": "0"})
        self.assertEqual(r.headers["Location"], "/me?m=message_emails_off#message-emails")
        self.assertFalse(MS.emails_on(bid))
        A.q("UPDATE conversation_state SET last_email_at=0 WHERE conversation_id=:c", c=cid)
        t3 = mark()
        a.post(f"/messages/{cid}", {"body": "fifth"})
        self.assertTrue(no_mail("message-new", bemail, t3))
        b.post("/me/message-emails", {"on": "1"})
        self.assertTrue(MS.emails_on(bid))
        # token unsubscribe link (no session needed), bad token rejected
        link = re.search(r"(/emails/messages\?u=\d+&t=\w+)", m["text"]).group(1)
        anon = Client("10.60.0.20")
        self.assertEqual(anon.get(link).status, 200)
        u, t = re.search(r"u=(\d+)&t=(\w+)", link).groups()
        self.assertEqual(anon.post("/emails/messages", {"u": u, "t": t, "action": "off"}, csrf=False).status, 200)
        self.assertFalse(MS.emails_on(bid))
        self.assertEqual(anon.post("/emails/messages", {"u": u, "t": "bad", "action": "on"}, csrf=False).status, 400)
        self.assertEqual(anon.get(f"/emails/messages?u={u}&t=bad").status, 400)

    def test_rate_limits(self):
        old = (MS.NEW_PER_DAY, MS.SEND_PER_HOUR)
        MS.NEW_PER_DAY, MS.SEND_PER_HOUR = 2, 4
        try:
            a, _, aid, _ = member("maggieowner", dogs=0)
            others = [member(f"pal{i}", dogs=0)[2] for i in range(3)]
            self.assertEqual(send_to(a, others[0], "hi 1").status, 303)
            self.assertEqual(send_to(a, others[1], "hi 2").status, 303)
            r = send_to(a, others[2], "hi 3")
            self.assertEqual(r.status, 429)
            self.assertIn("new conversations today", r.text)
            self.assertIn("hi 3", r.text)  # their text is kept
            cid = MS.find(aid, others[0])["id"]
            self.assertEqual(a.post(f"/messages/{cid}", {"body": "r1"}).status, 303)
            self.assertEqual(a.post(f"/messages/{cid}", {"body": "r2"}).status, 303)
            r = a.post(f"/messages/{cid}", {"body": "r3"})
            self.assertEqual(r.status, 429)
            self.assertIn("sending messages quickly", r.text)
        finally:
            MS.NEW_PER_DAY, MS.SEND_PER_HOUR = old

    def test_pack_members_and_meetup_attendees_have_message_links(self):
        org, _, oid, odogs = member("packorg")
        mem, _, mid_user, mdogs = member("lilyowner")
        pid, _ = make_pack(org, odogs)
        join(mem, pid, mdogs)
        page = ppage(mem, pid).text
        self.assertIn(f'href="/messages/to/{oid}"', page)
        self.assertNotIn(f'href="/messages/to/{mid_user}"', page)  # not to yourself
        self.assertIn(f'href="/messages/to/{mid_user}"', org.get(f"/packs/{pid}/members").text)
        anon_page = ppage(Client("10.60.0.30"), pid).text
        self.assertIn(e_attr("/signin?next=" + quote(f"/messages/to/{oid}", safe="")), anon_page)
        # meetup attendees
        meet_id, _ = TM.create(org)
        TM.rsvp(mem, meet_id, mdogs)
        mp = TM.mpage(org, meet_id).text
        self.assertIn(f'href="/messages/to/{mid_user}"', mp)
        self.assertNotIn(f'href="/messages/to/{oid}"', mp)

    def test_delete_account_removes_messages(self):
        a, _, aid, _ = member("leaver")
        b, _, bid, _ = member("lilyowner")
        cid = conv_id(send_to(a, bid, "bye soon"))
        b.post(f"/messages/{cid}", {"body": "ok"})
        mid = MS.messages(cid)[0][0]["id"]
        MS.add_report(MS.message(mid), bid, "Spam", "x", "1.2.3.4")
        MS.block(bid, aid)
        A.delete_user(aid)
        self.assertIsNone(MS.get(cid))
        for sql in ("SELECT COUNT(*) FROM messages WHERE conversation_id=:c", "SELECT COUNT(*) FROM conversation_state WHERE conversation_id=:c"):
            self.assertEqual(A.one(sql, c=cid)[0], 0)
        self.assertEqual(A.one("SELECT COUNT(*) FROM messages WHERE sender_id=:u", u=aid)[0], 0)
        self.assertEqual(A.one("SELECT COUNT(*) FROM user_blocks WHERE blocker_id=:u OR blocked_id=:u", u=aid)[0], 0)
        rep = A.one("SELECT reported_user_id, body FROM message_reports WHERE message_id=:m", m=mid)
        self.assertEqual(rep, (None, "") if isinstance(rep, tuple) else [None, ""])
        self.assertEqual(MS.inbox(bid), [])
        self.assertEqual(b.get(f"/messages/{cid}").status, 404)


def e_attr(s):
    import html
    return html.escape(s)


if __name__ == "__main__":
    unittest.main()
