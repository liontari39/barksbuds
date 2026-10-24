"""Seed the first BarksBuds dog profiles (Lily and Maggie on Mike's account) and one sample meetup. Safe to run more than once.

Usage:  DATABASE_URL=... python3 seed.py [--assets /path/to/barksbuds-assets]
        (without DATABASE_URL it seeds the local SQLite database in DATA_DIR)
   or:  python3 seed.py --url https://barksbuds.app [--assets ...]
        uploads the photos to the site's admin-only /admin/seed endpoint (key from $ADMIN_KEY or ./.admin_key),
        for when the database isn't reachable directly.

Idempotent: the account is matched by email, dogs by a fixed seed key, and photos are only added to a dog that has none,
so existing edits made through the site are never overwritten.
"""
import argparse
import json
import os
import urllib.request
import uuid
from datetime import date

import accounts as A
import meetups as M

OWNER = dict(email="mike.karachalios@gmail.com", display_name="Mike", area="Nassau", town="Manhasset", bio="")

LILY_BIO = ("Lily is a 6-year-old standard poodle mix with a curly black-and-grey coat and a red heart tag. "
            "She's absurdly smart, loyal and loves kids, and when she takes off at the run she goes like a horse. "
            "Good luck keeping up!")
MAGGIE_BIO = ("Meet Maggie, a.k.a. the couch monster: a merle French Bulldog born in the summer of 2023, about 26 pounds "
              "of snuggler, snorter and self-appointed floor cleaner. Her favorite spots are the extra-large bean bag and "
              "the gap between the couch cushions. She's a jealous girl who will try to steal your cuddles, and for a dog "
              "who loves lounging, she's surprisingly agile. Favorite toys: Lamb Chop and her squeaky Gumby. "
              "Her big sister is Lily.")

# "rev" bumps re-apply "profile" (and add "extra_photos") once per revision, so later edits made on the site
# are only overwritten when a new revision is deliberately added here.
DOGS = [
    dict(seed_key="mike-lily", name="Lily", breed="Standard Poodle mix", age=6, size="large",
         bio="Say hi to Lily! She's a standard poodle mix with a curly black-and-grey coat. "
             "Look for the red heart tag on her collar.",
         photos=["lily-1.jpg", "lily-2.jpg", "lily-3.jpg"], sprite="lily-sprite.jpg",
         rev=2, profile=dict(sex="female", size="large", temperament=["Smart", "Loyal", "Great with kids", "Speedy"],
                             play_style=["Zoomies"], bio=LILY_BIO)),
    dict(seed_key="mike-maggie", name="Maggie", breed="French Bulldog", age=3, size="small",
         bio="Meet Maggie, a merle French Bulldog. Come say hello!",
         photos=["maggie-1.jpg", "maggie-2.jpg"], sprite="maggie-sprite.jpg",
         rev=2, profile=dict(sex="female", size="medium", birth_year=2023,
                             temperament=["Snuggler", "Chill", "Food motivated"], play_style=["Toy lover"],
                             bio=MAGGIE_BIO, website="https://maggiethemerle.com/"),
         extra_photos=["maggie-site/maggie-beanbag-nap-960.webp", "maggie-site/maggie-g-cream-rug-960.webp"]),
]

# One clearly marked sample meetup (is_sample=1: no emails, no reminders, hideable/deletable from /admin/meetups).
SAMPLE_MEETUP = dict(
    seed_key="founding-pack-2026", title="Founding Pack Meetup at Manhasset", date="2026-10-31", time="10:00",
    duration_min=60, run_id="n-006", fit="", capacity=None, rsvp_dogs=["mike-lily", "mike-maggie"],
    description=("Come meet the founding pack! BarksBuds started with a few friends and their dogs around Manhasset, "
                 "and this is our first get-together. Lily and Maggie will be there.\n\n"
                 "We'll meet at the Christopher Morley Park dog run, a short drive from Manhasset. It's fenced, "
                 "with water on site. All friendly dogs are welcome. Bring water, treats and poop bags, and "
                 "please keep dogs leashed outside the run.\n\n"
                 "This is a sample meetup to show how BarksBuds meetups work."),
)

PROFILE_COLS = {"sex", "size", "birth_year", "birthday", "breed", "bio", "website", "temperament", "play_style"}


def asset_names():
    out = []
    for spec in DOGS:
        out += [f"dogs/{fn}" for fn in spec["photos"]] + [f"sprites/{spec['sprite']}"] + spec.get("extra_photos", [])
    return out


def run(load, log=print):
    """Seed using load(relative_path) -> bytes or None. Returns the user id."""
    uid, created = A.get_or_create_user(OWNER["email"])
    u = A.one("SELECT display_name, area, town, bio FROM users WHERE id=:i", i=uid)
    A.update_profile(uid, u[0] or OWNER["display_name"], u[1] or OWNER["area"], u[2] or OWNER["town"], u[3] or OWNER["bio"])
    log(f"owner: user {uid} ({'created' if created else 'existing'})")
    for spec in DOGS:
        row = A.one("SELECT id FROM dogs WHERE seed_key=:k", k=spec["seed_key"])
        if row:
            dog_id = row[0]
            log(f"{spec['name']}: exists (dog {dog_id}), leaving profile as is")
        else:
            f = dict(name=spec["name"], breed=spec["breed"], birthday="", birth_year=date.today().year - spec["age"],
                     sex="", size=spec["size"], temperament=[], play_style=[], vaccinated=False, fav_runs=[], bio=spec["bio"])
            dog_id = A.save_dog(uid, f, seed_key=spec["seed_key"])
            log(f"{spec['name']}: created dog {dog_id}")
        if A.photo_count(dog_id) == 0:
            for fn in spec["photos"]:
                raw = load(f"dogs/{fn}")
                if raw:
                    log(f"  + photo {fn} -> {A.add_photo(dog_id, raw)}")
                else:
                    log(f"  ! missing {fn}")
        if not A.dog_by_id(dog_id).get("avatar_photo_id") and spec.get("sprite"):
            raw = load(f"sprites/{spec['sprite']}")
            if raw:
                pid = A.add_photo(dog_id, raw, kind="avatar")
                A.set_avatar(dog_id, pid)
                log(f"  + avatar {spec['sprite']} -> {pid}")
        d = A.dog_by_id(dog_id)
        missing = [rel for rel in spec.get("extra_photos", []) if not load(rel)]
        if spec.get("rev") and (d.get("seed_rev") or 0) < spec["rev"] and missing:
            log(f"  ! revision {spec['rev']} not applied, missing {', '.join(missing)}")
        elif spec.get("rev") and (d.get("seed_rev") or 0) < spec["rev"]:
            sets, vals = [], {}
            for k, v in spec.get("profile", {}).items():
                assert k in PROFILE_COLS, k
                sets.append(f"{k}=:{k}")
                vals[k] = json.dumps(v) if isinstance(v, list) else v
            A.q(f"UPDATE dogs SET {', '.join(sets)}, seed_rev=:rev, updated_at=:t WHERE id=:i",
                rev=spec["rev"], t=A.now(), i=dog_id, **vals)
            have = {r[0] for r in A.q("SELECT sha FROM photos WHERE dog_id=:d", d=dog_id)}
            for rel in spec.get("extra_photos", []):
                raw = load(rel)
                if not raw:
                    log(f"  ! missing {rel}")
                elif A.sha(raw) in have:
                    log(f"  = photo {rel} already there")
                elif A.photo_count(dog_id) < A.MAX_PHOTOS:
                    log(f"  + photo {rel} -> {A.add_photo(dog_id, raw)}")
            log(f"  profile updated to revision {spec['rev']}")
        else:
            log(f"  profile at revision {d.get('seed_rev') or 0}, nothing to update")
        log(f"  page: /dogs/{d['slug']}")
    seed_meetup(uid, log)
    return uid


def _run(run_id):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data-seed", "dog_runs_region.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data["runs"] if isinstance(data, dict) and "runs" in data else data
    return next(r for r in rows if r["id"] == run_id)


def seed_meetup(uid, log=print):
    """Create the sample meetup once (matched by seed key) with the owner's dogs RSVP'd Going. Sends no email."""
    spec = SAMPLE_MEETUP
    row = A.one("SELECT id FROM meetups WHERE seed_key=:k", k=spec["seed_key"])
    if row:
        mid = row[0]
        log(f"sample meetup: exists (meetup {mid}), leaving it as is")
    else:
        r = _run(spec["run_id"])
        f = dict(title=spec["title"], starts_at=M.from_et(spec["date"], spec["time"]), duration_min=spec["duration_min"],
                 run_id=r["id"], place_name=r["name"], address=r.get("address") or "", lat=r.get("lat"), lng=r.get("lng"),
                 area=r.get("county") or "", town=r.get("town_or_neighborhood") or "", description=spec["description"],
                 fit=spec["fit"], capacity=spec["capacity"])
        mid, _ = M.save(uid, f, seed_key=spec["seed_key"], is_sample=1)
        log(f"sample meetup: created meetup {mid} at {r['name']} ({r['id']})")
    m = M.get(mid)
    if not M.rsvp_of(mid, uid):
        ids = [x[0] for x in (A.one("SELECT id FROM dogs WHERE seed_key=:k AND user_id=:u", k=k, u=uid) for k in spec["rsvp_dogs"]) if x]
        status, _prev, _p = M.set_rsvp(m, uid, "going", ids)
        log(f"  RSVP {status} with {len(ids)} dog(s), no emails sent")
    log(f"  page: /meetups/{mid}-{m['slug']}")
    return mid


def upload(url, assets):
    key = os.environ.get("ADMIN_KEY") or open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".admin_key")).read().strip()
    bnd = "----bbseed" + uuid.uuid4().hex
    parts = [f'--{bnd}\r\nContent-Disposition: form-data; name="key"\r\n\r\n{key}\r\n'.encode()]
    for rel in asset_names():
        with open(os.path.join(assets, rel), "rb") as fh:
            data = fh.read()
        parts.append(f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="{rel}"\r\n'
                     f'Content-Type: image/jpeg\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    req = urllib.request.Request(url.rstrip("/") + "/admin/seed", data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}", "User-Agent": "barksbuds-seed"})
    with urllib.request.urlopen(req, timeout=180) as r:
        print(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "barksbuds-assets"))
    ap.add_argument("--url", help="seed a running site through its admin-only /admin/seed endpoint")
    args = ap.parse_args()
    if args.url:
        return upload(args.url, args.assets)
    import server
    server.init_app()

    def load(rel):
        p = os.path.join(args.assets, rel)
        return open(p, "rb").read() if os.path.exists(p) else None
    run(load)


if __name__ == "__main__":
    main()
