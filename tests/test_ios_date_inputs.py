"""iOS Safari date/time inputs must be full-width fields, not native overflow controls."""
import os, re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "public" / "app.css").read_text()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_app as T  # noqa: E402
from test_app import Client, sign_in, RUN  # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


def css_version():
    text = (ROOT / "webapp.py").read_text()
    m = re.search(r'app\.css\?v=(\d+)', text)
    if not m:
        raise AssertionError("no app.css?v= tag in webapp.py")
    return m.group(1)


class IosDateInputTests(unittest.TestCase):
    def test_css_rules_cover_date_time_and_datetime_local(self):
        # Pull the dedicated date/time rule, not the general input list or .carectl override.
        block = re.search(
            r"input\[type=date\],input\[type=time\],input\[type=datetime-local\]\{([^}]+)\}",
            CSS,
        )
        self.assertIsNotNone(block, "missing combined date/time/datetime-local rule")
        body = block.group(1)
        for token in ("-webkit-appearance:none", "appearance:none", "display:block",
                      "width:100%", "max-width:100%", "min-width:0", "box-sizing:border-box",
                      "padding:12px 14px", "border:2px solid #D9CBAA"):
            self.assertIn(token, body, token)
        self.assertRegex(body, r"font-size:(max\(16px,.+\)|1\.02rem|[1-9][0-9]*px)")
        self.assertRegex(
            CSS,
            r"input\[type=date\]::-webkit-date-and-time-value,\s*"
            r"input\[type=time\]::-webkit-date-and-time-value,\s*"
            r"input\[type=datetime-local\]::-webkit-date-and-time-value\{[^}]*text-align:left;min-height:1\.2em",
        )
        self.assertIn(".field,.row2,.row3,.carectl,.carerow{min-width:0}", CSS)

    def test_meetup_form_serves_the_bumped_stylesheet(self):
        v = css_version()
        c = Client("10.90.0.1")
        sign_in(c, f"iosdate-{RUN}@example.com")
        r = c.get("/meetups/new")
        self.assertEqual(r.status, 200)
        self.assertIn(f"/app.css?v={v}", r.text)
        self.assertIn('type="date"', r.text)
        self.assertIn('type="time"', r.text)
