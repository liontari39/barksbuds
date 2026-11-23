"""Month calendar view of upcoming meetups (/meetups/calendar) and the list/calendar/map toggle.

Run with the rest:  python3 -m unittest discover -s tests -v
"""
import os, sys, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, RUN  # noqa: E402
import accounts as A  # noqa: E402
import meetups as M  # noqa: E402
import meetweb  # noqa: E402
from test_meetups import member, create  # noqa: E402


def setUpModule():
    meetweb.AUTO_REMINDERS = False
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def ymd(days, hhmm="10:00"):
    d = datetime.now(M.ET) + timedelta(days=days)
    return d.strftime("%Y-%m-%d"), hhmm, d.year, d.month


class MeetupCalendarTests(unittest.TestCase):
    def test_list_calendar_toggle_and_month_view(self):
        host, _, uid, _ = member("cal")
        day, hhmm, year, month = ymd(5)
        title = f"Lily park hang {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm)
        lst = Client().get("/meetups").text
        self.assertIn('href="/meetups/calendar"', lst)
        self.assertIn(">Calendar</a>", lst)
        r = Client().get(f"/meetups/calendar?y={year}&m={month}")
        self.assertEqual(r.status, 200)
        page = r.text
        self.assertIn('aria-current="page">Calendar</a>', page)
        self.assertIn('href="/meetups"', page)
        self.assertIn(">List</a>", page)
        self.assertIn("view=map", page)
        self.assertIn(title, page)
        self.assertIn(f"/meetups/{mid}-", page)
        self.assertIn('class="cal"', page)
        # other month should not include this meetup
        other_y, other_m = (year, month - 1) if month > 1 else (year - 1, 12)
        other = Client().get(f"/meetups/calendar?y={other_y}&m={other_m}").text
        self.assertNotIn(title, other)
        self.assertIn("Previous", page)
        self.assertIn("Next", page)
        # invalid month falls back to the current month
        now = M.to_et(A.now())
        fallback = Client().get("/meetups/calendar?y=nope&m=99").text
        self.assertIn(now.strftime("%B %Y"), fallback)

    def test_calendar_area_filter(self):
        host, _, uid, _ = member("calarea")
        day, hhmm, year, month = ymd(6)
        title = f"Queens romp {RUN}"
        mid, _ = create(host, title=title, date=day, time=hhmm, loc="custom",
                        place_name="Forest Park", address="Forest Park, Queens, NY", area="Queens", town="Woodhaven",
                        run_id="")
        nassau = Client().get(f"/meetups/calendar?area=Nassau&y={year}&m={month}").text
        self.assertNotIn(title, nassau)
        queens = Client().get(f"/meetups/calendar?area=Queens&y={year}&m={month}").text
        self.assertIn(title, queens)
        self.assertIn('aria-current="page"', queens)
