"""Terms updates and short visible notes on meetup, check-in, lost-dog and puppy pack pages."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client  # noqa: E402
import test_meetups as TM  # noqa: E402
from test_community import member, lily, follow_redirect, RUN_ID  # noqa: E402
from test_puppy_pods import pup  # noqa: E402


def setUpModule():
    TM.setUpModule()


def tearDownModule():
    TM.tearDownModule()


TERMS_LINK = 'href="/terms"'


class TermsPage(unittest.TestCase):
    def test_updated_date_and_new_sections(self):
        r = Client().get("/terms")
        self.assertEqual(r.status, 200)
        self.assertIn("Last updated November 23, 2026", r.text)
        self.assertIn("Check-ins, dog counts at runs", r.text)
        self.assertIn("favorite-dog and run alerts", r.text)
        self.assertIn("run health heads-ups", r.text)
        self.assertIn("aren't a guarantee of safety or conditions", r.text)
        self.assertIn("Use your own judgment", r.text)
        self.assertIn("Lost-dog alerts are a community helper", r.text)
        self.assertIn("animal control, police, shelters or your microchip registry", r.text)
        self.assertIn("can't guarantee anyone will see an alert", r.text)
        self.assertIn("Be careful meeting people you don't know", r.text)
        self.assertIn("don't share your home address", r.text)


class ActionNotes(unittest.TestCase):
    def test_meetup_create_and_rsvp_notes(self):
        host, _, _, ids = TM.member("disc")
        form = host.get("/meetups/new").text
        self.assertIn("Meetups are organized by members. You're responsible for your dog.", form)
        self.assertIn(TERMS_LINK, form)
        mid, loc = TM.create(host)
        page = TM.mpage(host, mid).text
        self.assertIn("Meetups are organized by members. You're responsible for your dog.", page)
        self.assertIn(TERMS_LINK, page)
        self.assertIn('id="rsvp"', page)

    def test_checkin_note(self):
        c, _, _, _ = member("CheckDisc", dogs=[lily()])
        page = follow_redirect(c, f"/runs/{RUN_ID}").text
        self.assertIn("Check-ins and dog counts come from members and can be out of date.", page)
        self.assertIn("You're responsible for your dog.", page)
        self.assertIn(TERMS_LINK, page)
        self.assertIn("We're here", page)

    def test_lost_dog_create_note(self):
        c, _, _, _ = member("LostDisc", dogs=[lily()])
        page = c.get("/lost-found/new").text
        self.assertEqual(c.get("/lost-found/new").status, 200)
        self.assertIn("Lost-dog alerts are a community helper", page)
        self.assertIn("animal control, police, shelters or your microchip registry", page)
        self.assertIn(TERMS_LINK, page)

    def test_puppy_pack_create_note_and_name(self):
        c, _, _, _ = member("PackDisc", dogs=[pup()])
        listing = c.get("/packs?kind=puppy").text
        self.assertIn("Puppy packs", listing)
        self.assertNotIn("Puppy Pods", listing)
        form = c.get("/packs/new?kind=puppy").text
        self.assertIn("Start a Puppy pack", form)
        self.assertIn("Puppy packs are organized by members. You're responsible for your puppy.", form)
        self.assertIn(TERMS_LINK, form)
        self.assertNotIn("Puppy Pod", form)


class FooterNav(unittest.TestCase):
    def test_footer_and_more_menu_say_puppy_packs(self):
        home = Client().get("/").text
        self.assertIn('href="/packs?kind=puppy">Puppy packs</a>', home)
        self.assertNotIn("Puppy Pods", home)
        js = Client().get("/app-shell.js?v=7").text
        self.assertIn('["/packs?kind=puppy", "Puppy packs"]', js)
        self.assertNotIn("Puppy Pods", js)
        # old /puppy-pods URLs still redirect
        r = Client().get("/puppy-pods")
        self.assertEqual(r.status, 301)
        self.assertTrue(r.headers["Location"].startswith("/packs"))
        self.assertIn("kind=puppy", r.headers["Location"])


if __name__ == "__main__":
    unittest.main()
