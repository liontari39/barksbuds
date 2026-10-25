"""Seed the first BarksBuds dog profiles (Lily and Maggie on Mike's account), one sample meetup and one sample pack. Safe to run more than once.

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
import packs as P

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
# are only overwritten when a new revision is deliberately added here. "profile_rev" (default: rev) is the last revision
# that changed "profile", so a revision that only changes the main picture doesn't re-apply the profile.
# "main_photo" is the image used as the dog's main picture (avatar): a gallery photo or the stored avatar image.
# Revision 3 (Lily) / 4 (Maggie) put the real photos back (Oct 24, 2026); revision 4 (Lily) / 5 (Maggie), also on Mike's
# request the same night, makes the AI-made detailed pixel-art portraits (sprites/*-sprite.jpg, the stored avatar images)
# the main pictures again. The maker's pixel pals stay the dogs' pixel pals and are not made the main picture by the seed;
# the real photos stay in the galleries. Nothing is deleted. An owner who later picks another main picture is never flipped back.
DOGS = [
    dict(seed_key="mike-lily", name="Lily", breed="Standard Poodle mix", age=6, size="large",
         bio="Say hi to Lily! She's a standard poodle mix with a curly black-and-grey coat. "
             "Look for the red heart tag on her collar.",
         photos=["lily-1.jpg", "lily-2.jpg", "lily-3.jpg"], sprite="lily-sprite.jpg", main_photo="sprites/lily-sprite.jpg",
         pixel="sprites/lily-cartoon-48.png", pixel_replaces=["sprites/lily-game-32.png", "sprites/lily-pixel-64.png"],
         rev=4, profile_rev=2, profile=dict(sex="female", size="large", temperament=["Smart", "Loyal", "Great with kids", "Speedy"],
                             play_style=["Zoomies"], bio=LILY_BIO)),
    dict(seed_key="mike-maggie", name="Maggie", breed="French Bulldog", age=3, size="small",
         bio="Meet Maggie, a merle French Bulldog. Come say hello!",
         photos=["maggie-1.jpg", "maggie-2.jpg"], sprite="maggie-sprite.jpg", main_photo="sprites/maggie-sprite.jpg",
         pixel="sprites/maggie-new-A-48.png",   # Game Sprite from dogs/maggie-3.jpg (grey bed, Mike's photo)
         pixel_replaces=["sprites/maggie-game-32.png", "sprites/maggie-cartoon-48.png", "sprites/maggie-pixel-64.png", "sprites/maggie-sprite-48.png"],
         rev=5, profile_rev=3, profile=dict(sex="female", size="medium", birth_year=2023,
                             temperament=["Snuggler", "Chill", "Food motivated"], play_style=["Toy lover"],
                             bio=MAGGIE_BIO, website="https://maggiethemerle.com/"),
         extra_photos=["maggie-site/maggie-beanbag-nap-960.webp", "maggie-site/maggie-g-cream-rug-960.webp", "dogs/maggie-3.jpg"]),
]

# One clearly marked sample meetup (is_sample=1: no emails, no reminders, hideable/deletable from /admin/meetups).
SAMPLE_MEETUP = dict(
    seed_key="founding-pack-2026", title="Founding Pack Meetup at Christopher Morley Park", date="2026-10-31", time="10:00",
    rev=1,  # rev 1: renamed from "Founding Pack Meetup at Manhasset" (the old URL 301-redirects to the new slug)
    duration_min=60, run_id="n-006", fit="", capacity=None, rsvp_dogs=["mike-lily", "mike-maggie"],
    description=("Come meet the founding pack! BarksBuds started with a few friends and their dogs around Manhasset, "
                 "and this is our first get-together. Lily and Maggie will be there.\n\n"
                 "We'll meet at the Christopher Morley Park dog run, a short drive from Manhasset. It's fenced, "
                 "with water on site. All friendly dogs are welcome. Bring water, treats and poop bags, and "
                 "please keep dogs leashed outside the run.\n\n"
                 "This is a sample meetup to show how BarksBuds meetups work."),
)

# One clearly marked sample pack (is_sample=1: no emails; hideable/deletable from /admin/packs with the other samples).
SAMPLE_PACK = dict(
    seed_key="north-shore-pack-2026", name="Manhasset & North Shore Pack", area="Nassau", town="Manhasset", run_id="n-006",
    fit="all", visibility="open", cover="packs/north-shore-pack-cover.jpg", dogs=["mike-lily", "mike-maggie"],
    description=("A friendly crew of North Shore dogs and their people. We meet at the Christopher Morley Park dog run, "
                 "a short drive from Manhasset: it's fenced, with water on site, and there's plenty of room to run.\n\n"
                 "All friendly dogs are welcome, big and small. Join with your dogs to see pack meetups, chat on the pack "
                 "board and get to know the regulars. Lily and Maggie say hi!\n\n"
                 "This is a sample pack to show how BarksBuds packs work."),
)

PROFILE_COLS = {"sex", "size", "birth_year", "birthday", "breed", "bio", "website", "temperament", "play_style"}


def asset_names():
    out = []
    for spec in DOGS:
        out += [f"dogs/{fn}" for fn in spec["photos"]] + spec.get("extra_photos", [])
        out += [f"sprites/{spec['sprite']}"] if spec.get("sprite") else []
        out += [spec["pixel"]] if spec.get("pixel") else []
        out += [spec["main_photo"]] if spec.get("main_photo") and spec["main_photo"] not in out else []
        out += spec.get("pixel_replaces", [])
    return out + [SAMPLE_PACK["cover"]]


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
        if spec.get("main_photo") and not A.dog_by_id(dog_id).get("avatar_photo_id") and (A.dog_by_id(dog_id).get("seed_rev") or 0) < spec.get("rev", 0):
            _set_main_photo(dog_id, spec, load, log)   # new database: the main picture is set from the start
        if not A.dog_by_id(dog_id).get("avatar_photo_id") and spec.get("sprite"):
            raw = load(f"sprites/{spec['sprite']}")
            if raw:
                pid = A.add_photo(dog_id, raw, kind="avatar")
                A.set_avatar(dog_id, pid)
                log(f"  + avatar {spec['sprite']} -> {pid}")
        # pixel pal made with the site's own maker (/me/dogs/N/pixel); added when the dog has none, and swapped for a
        # newer seeded one only while the dog still has an older seeded sprite (pixel_replaces), so a sprite the owner
        # made themselves is never overwritten. "pixel_primary" (no longer set for Lily or Maggie) would make the sprite the
        # avatar only at the moment the seed adds or swaps it; a swap keeps whatever the owner chose.
        if spec.get("pixel"):
            assert spec["pixel"] not in spec.get("pixel_replaces", []), "a seeded sprite must never replace itself"
            raw, cur = load(spec["pixel"]), A.dog_by_id(dog_id)
            want_primary = bool(spec.get("pixel_primary"))
            if raw and not cur.get("pixel_photo_id"):
                log(f"  + pixel pal {spec['pixel']} -> {A.set_pixel(dog_id, raw, primary=want_primary)}")
            elif raw:
                row = A.one("SELECT sha FROM photos WHERE id=:i", i=cur["pixel_photo_id"])
                olds = {A.sha(b) for b in (load(r) for r in spec.get("pixel_replaces", [])) if b}
                if row and row[0] in olds and row[0] != A.sha(raw):
                    pid = A.set_pixel(dog_id, raw, primary=want_primary or bool(cur.get("pixel_primary")))
                    log(f"  ~ pixel pal replaced with {spec['pixel']} -> {pid}")
        d = A.dog_by_id(dog_id)
        missing = [rel for rel in spec.get("extra_photos", []) + ([spec["main_photo"]] if spec.get("main_photo") else []) if not load(rel)]
        if spec.get("rev") and (d.get("seed_rev") or 0) < spec["rev"] and missing:
            log(f"  ! revision {spec['rev']} not applied, missing {', '.join(missing)}")
        elif spec.get("rev") and (d.get("seed_rev") or 0) < spec["rev"]:
            sets, vals = [], {}
            redo_profile = (d.get("seed_rev") or 0) < spec.get("profile_rev", spec["rev"])
            for k, v in (spec.get("profile", {}) if redo_profile else {}).items():
                assert k in PROFILE_COLS, k
                sets.append(f"{k}=:{k}")
                vals[k] = json.dumps(v) if isinstance(v, list) else v
            A.q(f"UPDATE dogs SET {''.join(x + ', ' for x in sets)}seed_rev=:rev, updated_at=:t WHERE id=:i",
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
            if spec.get("main_photo"):
                _set_main_photo(dog_id, spec, load, log)
            log(f"  {'profile' if redo_profile else 'dog'} updated to revision {spec['rev']}")
        else:
            log(f"  profile at revision {d.get('seed_rev') or 0}, nothing to update")
        log(f"  page: /dogs/{d['slug']}")
    mid = seed_meetup(uid, log)
    seed_pack(uid, mid, load, log)
    import portraits
    portraits.mark_seeded_done()   # Lily and Maggie's AI portraits count as their done pixel portraits
    return uid


def _set_main_photo(dog_id, spec, load, log=print):
    """Make spec["main_photo"] (a gallery photo or a stored avatar image) the dog's main picture and show it instead of
    the pixel pal. Deletes nothing (unlike A.set_avatar, which drops a replaced avatar-only image); an avatar image that
    isn't stored yet is added as kind='avatar'."""
    raw = load(spec["main_photo"])
    row = A.one("SELECT id FROM photos WHERE dog_id=:d AND kind IN ('gallery','avatar','portrait') AND sha=:s ORDER BY id",
                d=dog_id, s=A.sha(raw)) if raw else None
    if not row and raw and spec["main_photo"].startswith("sprites/"):
        row = (A.add_photo(dog_id, raw, kind="avatar"),)
    if not row:
        log(f"  ! main photo {spec['main_photo']} not found in the gallery, main picture left as is")
        return None
    A.q("UPDATE dogs SET avatar_photo_id=:p, pixel_primary=0, updated_at=:t WHERE id=:d", p=row[0], t=A.now(), d=dog_id)
    log(f"  main picture: photo {row[0]} ({spec['main_photo']}), pixel pal kept as the pixel pal")
    return row[0]


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
    if spec.get("rev") and (m.get("seed_rev") or 0) < spec["rev"]:
        A.q("UPDATE meetups SET title=:t, slug=:s, seed_rev=:r, updated_at=:u WHERE id=:i",
            t=spec["title"], s=A.slugify(spec["title"], 60), r=spec["rev"], u=A.now(), i=mid)
        m = M.get(mid)
        log(f"  renamed to \"{spec['title']}\" (revision {spec['rev']})")
    if not M.rsvp_of(mid, uid):
        ids = [x[0] for x in (A.one("SELECT id FROM dogs WHERE seed_key=:k AND user_id=:u", k=k, u=uid) for k in spec["rsvp_dogs"]) if x]
        status, _prev, _p = M.set_rsvp(m, uid, "going", ids)
        log(f"  RSVP {status} with {len(ids)} dog(s), no emails sent")
    log(f"  page: /meetups/{mid}-{m['slug']}")
    return mid


def seed_pack(uid, mid, load, log=print):
    """Create the sample pack once (matched by seed key), organized by the owner with Lily and Maggie, and attach the
    sample meetup to it. Sends no email."""
    spec = SAMPLE_PACK
    dog_ids = [x[0] for x in (A.one("SELECT id FROM dogs WHERE seed_key=:k AND user_id=:u", k=k, u=uid) for k in spec["dogs"]) if x]
    row = A.one("SELECT id FROM packs WHERE seed_key=:k", k=spec["seed_key"])
    if row:
        pid = row[0]
        log(f"sample pack: exists (pack {pid}), leaving it as is")
    else:
        f = {k: spec[k] for k in ("name", "area", "town", "run_id", "description", "fit", "visibility")}
        f["dogs"] = dog_ids
        pid = P.save(uid, f, seed_key=spec["seed_key"], is_sample=1)
        log(f"sample pack: created pack {pid} with {len(dog_ids)} dog(s)")
    p = P.get(pid)
    if not p["cover_photo_id"]:
        raw = load(spec["cover"])
        if raw:
            log(f"  + cover -> {P.set_cover(pid, raw)}")
        else:
            log(f"  ! missing {spec['cover']}")
    mem = P.membership(pid, uid)
    if mem and not mem["dogs"] and dog_ids:
        P.set_dogs(pid, uid, dog_ids)
        log("  owner's dogs added to the pack")
    if mid:
        m = M.get(mid)
        if m and not m.get("pack_id"):
            A.q("UPDATE meetups SET pack_id=:p WHERE id=:i", p=pid, i=mid)
            log(f"  sample meetup {mid} attached to the pack")
    p = P.get(pid)
    log(f"  page: /packs/{pid}-{p['slug']}")
    return pid


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
