"""Co-owners: migration, invite email + accept (signed out creates the account and signs in; signed in adds the
account), expiry/revoke/single use, co-owner permissions (edit, photos, RSVP, packs, portrait panel, no delete),
remove/leave, the cap, /me listing and account deletion handing the dog to a co-owner.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, re, sys, unittest
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, jpeg_with_exif  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_meetups import member, mark, wait_mail, rsvp  # noqa: E402
import test_packs as TP  # noqa: E402
import accounts as A  # noqa: E402
import coowners as CO  # noqa: E402
import meetups as M  # noqa: E402
import packs as P  # noqa: E402

_n = [0]


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


def invite(c, dog, email):
    since = mark()
    r = c.post(f"/me/dogs/{dog}/coowners/invite", {"email": email})
    assert r.status == 303 and "co=sent" in r.headers["Location"], (r.status, r.headers.get("Location"))
    mail = wait_mail("coowner-invite", email, since)[0]
    link = re.search(r"https?://\S+/invite/[A-Za-z0-9_-]+", mail["text"]).group(0)
    return urlsplit(link).path, mail


def fresh_email(tag):
    _n[0] += 1
    return f"{tag}{_n[0]}-{TM.RUN}@example.com"


class CoownerTests(unittest.TestCase):
    def test_backfill_creates_owner_rows(self):
        c, _, uid, (dog,) = member("bf")
        self.assertEqual(A.one("SELECT role FROM dog_owners WHERE dog_id=:d AND user_id=:u", d=dog, u=uid)[0], "owner")
        A.q("DELETE FROM dog_owners WHERE dog_id=:d", d=dog)
        CO.backfill()
        CO.backfill()  # idempotent
        self.assertEqual(A.one("SELECT COUNT(*) FROM dog_owners WHERE dog_id=:d", d=dog)[0], 1)

    def test_invite_accept_signed_out_and_permissions(self):
        own, _, oid, (dog,) = member("own")
        email = fresh_email("partner")
        path, mail = invite(own, dog, email)
        self.assertIn("co-own", mail["subject"])
        # edit page shows the pending invite to the owner
        self.assertIn(email, own.get(f"/me/dogs/{dog}/edit").text)
        # GET only shows a confirmation (link scanners can't accept); invalid tokens 404
        b = Client("10.33.0.1")
        g = b.get(path)
        self.assertEqual(g.status, 200)
        self.assertIn("Accept and co-own", g.text)
        self.assertIsNone(A.one("SELECT id FROM users WHERE email=:e", e=email))
        self.assertEqual(b.get("/invite/notarealtoken123").status, 404)
        r = b.post(path, {})
        self.assertEqual(r.status, 303)
        self.assertIn(f"/me/dogs/{dog}/edit", r.headers["Location"])
        uid = A.one("SELECT id FROM users WHERE email=:e", e=email)[0]
        self.assertEqual(CO.role(dog, uid), "co-owner")
        # signed in now: /me lists the dog with a badge, edit page works, no delete link
        me = b.get("/me").text
        self.assertIn(A.dog_by_id(dog)["name"], me)
        self.assertIn("Co-owner", me)
        ed = b.get(f"/me/dogs/{dog}/edit")
        self.assertEqual(ed.status, 200)
        self.assertNotIn("Delete this profile", ed.text)
        self.assertIn("portrait-panel", ed.text)
        self.assertNotIn("Send invite", ed.text)
        # used link can't be reused
        self.assertEqual(Client("10.33.0.2").post(path, {}).status, 410)
        # edit the profile
        r = b.post(f"/me/dogs/{dog}/edit", {"name": "Sharedpup", "breed": "Mutt", "bio": "Two humans."})
        self.assertEqual(r.status, 303)
        self.assertEqual(A.dog_by_id(dog)["name"], "Sharedpup")
        self.assertEqual(A.dog_by_id(dog)["user_id"], oid)  # still the main owner
        # photos
        r = TP.multipart(b, f"/me/dogs/{dog}/photos", {}, [("photos", "a.jpg", jpeg_with_exif())])
        self.assertEqual(r.status, 303)
        self.assertEqual(A.photo_count(dog), 1)
        # profile page: co-owner sees the edit button
        self.assertIn("Edit Sharedpup", b.get(f"/dogs/{A.dog_by_id(dog)['slug']}").text)
        # can't delete, can't invite, can't remove others
        self.assertEqual(b.post(f"/me/dogs/{dog}/delete", {}).status, 404)
        self.assertIsNotNone(A.dog_by_id(dog))
        self.assertEqual(b.post(f"/me/dogs/{dog}/coowners/invite", {"email": fresh_email("x")}).status, 404)
        # meetup RSVP with the shared dog shows it next to the co-owner
        host, _, _, _ = member("host")
        mid, _ = TM.create(host)
        self.assertEqual(rsvp(b, mid, [dog]).status, 303)
        going = M.attendees(mid)["going"]
        mine = [x for x in going if x["user_id"] == uid][0]
        self.assertEqual([d["id"] for d in mine["dogs"]], [dog])
        # pack join with the shared dog
        org, _, _, odogs = member("org")
        pid, _ = TP.make_pack(org, odogs)
        self.assertEqual(TP.join(b, pid, [dog]).status, 303)
        self.assertEqual(P.membership(pid, uid)["dogs"], [dog])
        self.assertIn(dog, [d["id"] for x in P.members(pid) if x["user_id"] == uid for d in x["dogs"]])
        # co-owner leaves
        self.assertEqual(b.get(f"/me/dogs/{dog}/leave").status, 200)
        r = b.post(f"/me/dogs/{dog}/leave", {})
        self.assertEqual(r.headers["Location"], "/me?m=left")
        self.assertIsNone(CO.role(dog, uid))
        self.assertEqual(b.get(f"/me/dogs/{dog}/edit").status, 404)

    def test_signed_in_accept_revoke_remove_expire_and_cap(self):
        own, _, oid, (dog,) = member("own2")
        other, oemail, other_id, _ = member("other")
        path, _ = invite(own, dog, oemail)
        r = other.post(path, {})
        self.assertEqual(r.status, 303)
        self.assertEqual(CO.role(dog, other_id), "co-owner")
        self.assertIn(dog, [d["id"] for d in A.dogs_for_user(other_id)])
        # MAX_DOGS ignores co-owned dogs
        self.assertEqual(A.owned_dog_count(other_id), 1)
        # duplicate / self invites are refused
        r = own.post(f"/me/dogs/{dog}/coowners/invite", {"email": oemail})
        self.assertIn("coe=already", r.headers["Location"])
        own_email = A.one("SELECT email FROM users WHERE id=:u", u=oid)[0]
        self.assertIn("coe=self", own.post(f"/me/dogs/{dog}/coowners/invite", {"email": own_email}).headers["Location"])
        self.assertIn("coe=email", own.post(f"/me/dogs/{dog}/coowners/invite", {"email": "nope"}).headers["Location"])
        # owner removes the co-owner
        r = own.post(f"/me/dogs/{dog}/coowners/{other_id}/remove", {})
        self.assertIn("co=removed", r.headers["Location"])
        self.assertIsNone(CO.role(dog, other_id))
        # revoke
        e2 = fresh_email("rev")
        path2, _ = invite(own, dog, e2)
        self.assertIn("coe=pending", own.post(f"/me/dogs/{dog}/coowners/invite", {"email": e2}).headers["Location"])
        iid = CO.pending_invites(dog)[0]["id"]
        self.assertIn("co=revoked", own.post(f"/me/dogs/{dog}/coowners/invites/{iid}/revoke", {}).headers["Location"])
        self.assertEqual(Client("10.33.1.1").get(path2).status, 410)
        self.assertEqual(Client("10.33.1.2").post(path2, {}).status, 410)
        self.assertIsNone(A.one("SELECT id FROM users WHERE email=:e", e=e2))
        # expiry
        e3 = fresh_email("exp")
        path3, _ = invite(own, dog, e3)
        A.q("UPDATE dog_invites SET expires_at=:t WHERE email=:e", t=A.now() - 1, e=e3)
        g = Client("10.33.1.3").get(path3)
        self.assertEqual(g.status, 410)
        self.assertIn("expired", g.text)
        # rate limit: the inviter has used up today's invites (failed attempts count too)
        locs = [own.post(f"/me/dogs/{dog}/coowners/invite", {"email": fresh_email("lim")}).headers["Location"] for _ in range(12)]
        self.assertTrue(any("coe=limit" in x for x in locs), locs)
        A.LIMITER.hits.clear()
        # cap: co-owners + open invites <= MAX_COOWNERS
        A.q("UPDATE dog_invites SET revoked_at=:t WHERE dog_id=:d AND accepted_at IS NULL", t=A.now(), d=dog)
        for i in range(CO.MAX_COOWNERS):
            invite(own, dog, fresh_email(f"cap{i}"))
        r = own.post(f"/me/dogs/{dog}/coowners/invite", {"email": fresh_email("over")})
        self.assertIn("coe=full", r.headers["Location"])
        self.assertIn("the most co-owners", own.get(f"/me/dogs/{dog}/edit").text)

    def test_delete_dog_and_account_handover(self):
        own, _, oid, (dog, dog2) = member("own3", dogs=2)
        co, cemail, cid, _ = member("co3")
        path, _ = invite(own, dog, cemail)
        co.post(path, {})
        # account deletion: the shared dog passes to the co-owner, the unshared one is deleted
        own.post("/me/delete", {"confirm": "yes"})
        self.assertIsNone(A.one("SELECT id FROM users WHERE id=:u", u=oid))
        self.assertEqual(A.dog_by_id(dog)["user_id"], cid)
        self.assertEqual(CO.role(dog, cid), "owner")
        self.assertIsNone(A.dog_by_id(dog2))
        # new main owner deletes: owner rows and invites are cleaned up
        invite(co, dog, fresh_email("late"))
        self.assertEqual(co.post(f"/me/dogs/{dog}/delete", {}).status, 303)
        self.assertIsNone(A.dog_by_id(dog))
        self.assertEqual(A.one("SELECT COUNT(*) FROM dog_owners WHERE dog_id=:d", d=dog)[0], 0)
        self.assertEqual(A.one("SELECT COUNT(*) FROM dog_invites WHERE dog_id=:d", d=dog)[0], 0)


if __name__ == "__main__":
    unittest.main()
