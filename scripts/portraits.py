#!/usr/bin/env python3
"""Work the BarksBuds pixel portrait queue from the command line (admin API, see pixelweb.py).

Usage:
  python3 scripts/portraits.py list                      pending requests
  python3 scripts/portraits.py fetch <id>                photos + metadata -> /workspace/barksbuds-assets/portrait-requests/<id>/
                                                         (photo-1.jpg .. photo-3.jpg, photo.jpg = photo 1, request.json)
  python3 scripts/portraits.py complete <id> <image>     upload the finished portrait (becomes the main picture)
  python3 scripts/portraits.py reject <id> <note...>     reject with a note shown to the owner (frees the slot)
  python3 scripts/portraits.py reset <id>                forget a request so the owner can ask again

Options (before the command): --url https://barksbuds.app (or $BARKSBUDS_URL), --key-file path (default: .admin_key in the
repo, or $BARKSBUDS_KEY_FILE), --out dir (default /workspace/barksbuds-assets/portrait-requests).
The admin key is read from the file and sent as the X-Admin-Key header; it is never printed.
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = "/workspace/barksbuds-assets/portrait-requests"


def key_from(path):
    with open(path, encoding="utf-8") as fh:
        k = fh.read().strip()
    if not k:
        sys.exit(f"{path} is empty")
    return k


def call(args, method, path, body=None, ctype=None, raw=False):
    req = urllib.request.Request(args.url.rstrip("/") + path, data=body, method=method,
                                 headers={"X-Admin-Key": key_from(args.key_file), "User-Agent": "barksbuds-portraits/1"})
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
    except urllib.error.HTTPError as ex:
        detail = ex.read()[:300].decode("utf-8", "replace")
        sys.exit(f"{method} {path}: HTTP {ex.code} {detail if ex.code != 404 else '(not found, or wrong admin key)'}")
    return data if raw else json.loads(data)


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode(), str(v).encode(), b"\r\n"]
    for k, (fn, data) in files.items():
        ct = mimetypes.guess_type(fn)[0] or "application/octet-stream"
        out += [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{os.path.basename(fn)}\"\r\nContent-Type: {ct}\r\n\r\n".encode(),
                data, b"\r\n"]
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def show(r):
    d = r["dog"]
    bits = " · ".join(x for x in (d.get("breed"), d.get("age"), d.get("sex"), d.get("size")) if x)
    print(f"#{r['id']}  {r['status']:<8} {r['created_at']}  {d.get('name')} ({bits})  owner: {r['owner'].get('name') or ''}")
    if r.get("photo_count"):
        print(f"      {r['photo_count']} reference photo{'' if r['photo_count'] == 1 else 's'}")
    if r.get("coat_notes"):
        print(f"      note: {r['coat_notes']}")
    if r.get("note"):
        print(f"      admin note: {r['note']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("BARKSBUDS_URL", "https://barksbuds.app"))
    ap.add_argument("--key-file", default=os.environ.get("BARKSBUDS_KEY_FILE", os.path.join(REPO, ".admin_key")))
    ap.add_argument("--out", default=os.environ.get("BARKSBUDS_PORTRAIT_DIR", DEFAULT_OUT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("fetch"); p.add_argument("id", type=int)
    p = sub.add_parser("complete"); p.add_argument("id", type=int); p.add_argument("image")
    p = sub.add_parser("reject"); p.add_argument("id", type=int); p.add_argument("note", nargs="+")
    p = sub.add_parser("reset"); p.add_argument("id", type=int)
    args = ap.parse_args(argv)

    if args.cmd == "list":
        rows = call(args, "GET", "/admin/portraits/pending")
        if not rows:
            print("No pending portrait requests.")
        for r in rows:
            show(r)
        return 0
    if args.cmd == "fetch":
        meta = call(args, "GET", f"/admin/portraits/{args.id}")
        n = meta.get("photo_count") or 1   # (an older server only had photo.jpg)
        photos = [call(args, "GET", f"/admin/portraits/{args.id}/photo/{i}.jpg" if meta.get("photo_count") else
                       f"/admin/portraits/{args.id}/photo.jpg", raw=True) for i in range(1, n + 1)]
        d = os.path.join(args.out, str(args.id))
        os.makedirs(d, exist_ok=True)
        for old in os.listdir(d):   # a re-fetch never leaves stale photos from before
            if old.startswith("photo-") and old.endswith(".jpg"):
                os.remove(os.path.join(d, old))
        saved = []
        for i, data in enumerate(photos, 1):
            with open(os.path.join(d, f"photo-{i}.jpg"), "wb") as fh:
                fh.write(data)
            saved.append(f"photo-{i}.jpg ({len(data) // 1024} KB)")
        with open(os.path.join(d, "photo.jpg"), "wb") as fh:   # compatibility: photo.jpg = photo 1
            fh.write(photos[0])
        with open(os.path.join(d, "request.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1)
        show(meta)
        print(f"saved to {d}/: " + ", ".join(saved) + ", photo.jpg (= photo-1.jpg), request.json")
        return 0
    if args.cmd == "complete":
        with open(args.image, "rb") as fh:
            data = fh.read()
        body, ct = multipart({}, {"image": (args.image, data)})
        r = call(args, "POST", f"/admin/portraits/{args.id}/complete", body, ct)
        show(r["request"])
        print(f"done: portrait photo {r['request']['portrait_photo_id']}, "
              f"{'set as the main picture' if r['made_main'] else 'main picture left as the owner chose'}, "
              f"ready email {'queued' if r['emailed'] else 'not sent (allowlist or email off)'}")
        return 0
    if args.cmd == "reject":
        body, ct = multipart({"note": " ".join(args.note)}, {})
        r = call(args, "POST", f"/admin/portraits/{args.id}/reject", body, ct)
        show(r["request"])
        print(f"rejected; owner email {'queued' if r['emailed'] else 'not sent (allowlist or email off)'}")
        return 0
    if args.cmd == "reset":
        body, ct = multipart({}, {})
        call(args, "POST", f"/admin/portraits/{args.id}/reset", body, ct)
        print(f"request {args.id} reset; the owner can send a new one")
        return 0


if __name__ == "__main__":
    sys.exit(main())
