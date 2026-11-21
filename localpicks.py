"""Curated, sourced Long Island content for empty states ("Be the first in your town").

Static editorial content, not members. Every entry was checked against the official page in `src` on VERIFIED.
Only facts stated on that page are shown (name, place, size areas, hours). Hours are listed only where the
official page states them; otherwise visitors are pointed at the source. Ids match the dog run dataset
(data-seed/dog_runs_region.csv) so cards can link to our run page when the run exists.
"""
import html

e = html.escape
VERIFIED = "2026-11-21"
VERIFIED_LABEL = "Nov 21, 2026"

NASSAU_COUNTY = "https://www.nassaucountyny.gov/3501/Dog-Runs"
OYSTER_BAY = "https://oysterbaytown.com/departments/parks/dog-parks/"
MANORHAVEN = "https://manorhaven.gov/dog-park/"
GREAT_NECK = "https://www.gnparksny.gov/374/Dog-Park"
SUFFOLK_COUNTY = "https://www.suffolkcountyny.gov/Departments/Parks/Activities-and-Attractions/Dog-Parks"

SOURCE_NAMES = {NASSAU_COUNTY: "Nassau County Parks", OYSTER_BAY: "Town of Oyster Bay", MANORHAVEN: "Village of Manorhaven",
                GREAT_NECK: "Great Neck Park District", SUFFOLK_COUNTY: "Suffolk County Parks"}

RUNS = [
    # Nassau County Parks, "Dog Runs" page
    dict(id="n-006", area="Nassau", name="Christopher Morley Park", where="Searingtown Road, off L.I.E. Exit 34",
         note="One shared area for large and small dogs, north side of the parking lot.", hours="", src=NASSAU_COUNTY),
    dict(id="n-004", area="Nassau", name="Eisenhower Park", where="East Meadow",
         note="About 1.5 acres, with separate large and small dog (25 lb and under) areas, shade, water and benches.", hours="", src=NASSAU_COUNTY),
    dict(id="n-005", area="Nassau", name="Old Bethpage Village Restoration", where="Old Bethpage",
         note="Separate areas for large and small dogs, near the entrance.",
         hours="Mon–Fri 8am–4:30pm, Sat 8am–5:30pm, Sun 9:30am–5:30pm", src=NASSAU_COUNTY),
    dict(id="n-001", area="Nassau", name="South Shore Bay Park", where="East Rockaway",
         note="Separate large and small dog runs on the east side of the park.", hours="", src=NASSAU_COUNTY),
    dict(id="n-002", area="Nassau", name="Cedar Creek Park", where="Merrick Road, Seaford",
         note="Separate large and small dog runs, near Parking Field 7.", hours="", src=NASSAU_COUNTY),
    dict(id="n-003", area="Nassau", name="Wantagh Park", where="Wantagh",
         note="Separate large and small dog areas, north of the launch ramp lot.", hours="", src=NASSAU_COUNTY),
    # Town / village pages
    dict(id="n-012", area="Nassau", name="Dog Park at Massapequa", where="Massapequa (Town of Oyster Bay)",
         note="Over an acre of wooded parkland.", hours="7 days, 8am to dusk", src=OYSTER_BAY),
    dict(id="n-013", area="Nassau", name="Dog Park at Centre Island Beach", where="Bayville (Town of Oyster Bay)",
         note="", hours="7 days, 8am to dusk", src=OYSTER_BAY),
    dict(id="n-019", area="Nassau", name="Manorhaven Dog Park", where="Port Washington (Manorhaven)",
         note="", hours="7am to dusk", src=MANORHAVEN),
    dict(id="n-018", area="Nassau", name="Great Neck Park District Dog Park", where="Colonial Road, Great Neck",
         note="", hours="", src=GREAT_NECK),
    # Suffolk County Parks, "Dog Parks" page
    dict(id="s-003", area="Suffolk", name="Blydenburgh County Park", where="Smithtown", note="", hours="", src=SUFFOLK_COUNTY),
    dict(id="s-004", area="Suffolk", name="Cherry Avenue Dog Park", where="West Sayville", note="", hours="", src=SUFFOLK_COUNTY),
    dict(id="s-005", area="Suffolk", name="Gardiner County Park", where="West Bay Shore", note="", hours="", src=SUFFOLK_COUNTY),
    dict(id="s-006", area="Suffolk", name="West Hills County Park", where="Huntington", note="", hours="", src=SUFFOLK_COUNTY),
    dict(id="s-008", area="Suffolk", name="Robinson Duck Farm County Park", where="Brookhaven", note="", hours="", src=SUFFOLK_COUNTY),
    dict(id="s-009", area="Suffolk", name="Mud Creek County Park", where="East Patchogue",
         note="A \"Natural Borders\" dog park: not fully enclosed by chain-link fence.", hours="", src=SUFFOLK_COUNTY),
]

TIPS = [
    dict(text="In Nassau County parks, keep your dog leashed on the way to the dog run; dogs can't be walked through the parks.",
         src=NASSAU_COUNTY),
    dict(text="Suffolk County allows leashed dogs at most county parks, except where signs say otherwise. Off leash only inside the dog park.",
         src=SUFFOLK_COUNTY),
    dict(text="Suffolk County Parks asks owners to keep vaccinations and parasite control up to date, and to pick up after their dog.",
         src=SUFFOLK_COUNTY),
]

# Our own vet-reviewed articles that are about Long Island or local dog runs (slugs in tipsdata.py).
GUIDES = [("ticks-and-lyme-on-long-island", "Ticks and Lyme on Long Island"),
          ("vaccines-and-licenses-for-dog-runs", "Vaccines and licenses for dog runs"),
          ("first-visit-to-a-dog-run", "Your first visit to a dog run"),
          ("dog-run-etiquette", "Dog run etiquette")]


def picks(areas=None, limit=6):
    """Runs for the given areas (Nassau/Suffolk). Unfiltered or Long Island: a mix of both counties.
    Areas outside Long Island get nothing (we only curated Long Island so far)."""
    areas = [a for a in (areas or []) if a]
    if areas and not any(a in ("Nassau", "Suffolk") for a in areas):
        return []
    want = [a for a in areas if a in ("Nassau", "Suffolk")] or ["Nassau", "Suffolk"]
    by = {a: [r for r in RUNS if r["area"] == a] for a in want}
    out = []
    while len(out) < limit and any(by.values()):
        for a in want:
            if by[a] and len(out) < limit:
                out.append(by[a].pop(0))
    return out


def source_link(url):
    return f'<a href="{e(url)}" target="_blank" rel="noopener nofollow">{e(SOURCE_NAMES.get(url, "Source"))}</a>'
