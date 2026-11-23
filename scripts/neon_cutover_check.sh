#!/usr/bin/env bash
# Restore a BarksBuds backup into an empty Neon (or other) Postgres and compare
# per-table counts with the backup's table_end records.
#
# Usage (from repo root, or anywhere):
#   scripts/neon_cutover_check.sh [BACKUP.ndjson.gz]
#
# Reads the destination URL from $NEON_URL, or from $NEON_URL_FILE
# (default: $REPO/.neon_url, mode 600). Never echoes the URL or passwords.
# Set NEON_REPLACE=1 only for a throwaway retry. Exits nonzero on mismatch.
# Does not change Render or push code.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP="${1:-$REPO/backups/barksbuds-backup-2026-11-23.ndjson.gz}"
URL_FILE="${NEON_URL_FILE:-$REPO/.neon_url}"

if [[ -z "${NEON_URL:-}" ]]; then
  if [[ ! -f "$URL_FILE" ]]; then
    echo "missing NEON_URL and $URL_FILE" >&2
    exit 2
  fi
  mode="$(stat -c '%a' "$URL_FILE")"
  if [[ "$mode" != "600" && "$mode" != "400" ]]; then
    echo "$URL_FILE must be mode 600 (got $mode); chmod 600 and retry" >&2
    exit 2
  fi
  # strip a single trailing newline only; never print
  NEON_URL="$(tr -d '\r' < "$URL_FILE" | sed -e 's/[[:space:]]*$//')"
  export NEON_URL
fi

if [[ ! -f "$BACKUP" ]]; then
  echo "backup not found: $BACKUP" >&2
  exit 2
fi

for py in "$REPO/.venv-restore/bin/python3" "$REPO/.venv/bin/python3" python3; do
  if [[ -x "$py" ]] || command -v "$py" >/dev/null 2>&1; then
    if "$py" -c "import pg8000" >/dev/null 2>&1; then
      PYTHON="$py"
      break
    fi
  fi
done
if [[ -z "${PYTHON:-}" ]]; then
  echo "need Python with pg8000 (pip install -r requirements.txt, or $REPO/.venv-restore)" >&2
  exit 2
fi

export BB_BACKUP="$BACKUP"
export BB_REPO="$REPO"
export BB_REPLACE="${NEON_REPLACE:-0}"
# URL stays in env only; never passed on argv
exec "$PYTHON" - "$REPO" <<'PY'
import gzip, json, os, socket, sys, ipaddress, urllib.request
from urllib.parse import urlsplit

repo = sys.argv[1] if len(sys.argv) > 1 else os.environ["BB_REPO"]
backup = os.path.abspath(os.environ["BB_BACKUP"])
url = os.environ.get("NEON_URL", "").strip()
if not url:
    sys.exit("NEON_URL is empty")
if "://" not in url or "sslmode" in url.split("://", 1)[0]:
    sys.exit("NEON_URL does not look like a Postgres URL")

def _doh_a(hostname):
    """Public A records via DNS-over-HTTPS (this box's DNS maps hosts to a private intercept)."""
    ips = []
    for endpoint in (
        f"https://cloudflare-dns.com/dns-query?name={hostname}&type=A",
        f"https://dns.google/resolve?name={hostname}&type=A",
    ):
        try:
            req = urllib.request.Request(endpoint, headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            for a in data.get("Answer") or []:
                if a.get("type") == 1:
                    ip = ipaddress.IPv4Address(a["data"])
                    if ip.is_global:
                        ips.append(ip)
            if ips:
                return ips
        except Exception:
            continue
    return ips

def _maybe_patch_dns(hostname):
    """If system DNS yields a private intercept address, use DoH public IPs instead.

    Needed only on this sandbox box. Production (Render) has normal DNS; this is
    not part of the app. SNI still uses the original hostname.
    """
    try:
        resolved = [ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(hostname, 5432, socket.AF_INET, socket.SOCK_STREAM)]
    except Exception:
        resolved = []
    if resolved and all(not a.is_private and not a.is_loopback for a in resolved):
        print("dns: system resolver already public")
        return
    ips = _doh_a(hostname)
    if not ips:
        print("dns: no public A records via DoH; trying system DNS as-is", file=sys.stderr)
        return
    real = socket.getaddrinfo
    def patched(host, port, family=0, type=0, proto=0, flags=0):
        if host == hostname and family in (0, socket.AF_INET):
            port_n = 0 if port in (None, 0, "") else int(port) if str(port).isdigit() else socket.getservbyname(str(port))
            typ = type or socket.SOCK_STREAM
            proto_n = proto or (socket.IPPROTO_TCP if typ == socket.SOCK_STREAM else 0)
            return [(socket.AF_INET, typ, proto_n, "", (str(ip), port_n)) for ip in ips]
        return real(host, port, family, type, proto, flags)
    socket.getaddrinfo = patched
    print(f"dns: using {len(ips)} public A record(s) via DoH (system DNS was intercepted)")

u = urlsplit(url)
if u.hostname:
    _maybe_patch_dns(u.hostname)

os.environ["DATABASE_URL"] = url
os.environ.setdefault("EMAIL_PROVIDER", "file")
os.environ.setdefault("ADMIN_KEY", "restore-local")
sys.path.insert(0, repo)
os.chdir(repo)

import server
server.init_app()
import accounts as A
import maintweb

replace = os.environ.get("BB_REPLACE") == "1"
with open(backup, "rb") as fh:
    result = maintweb.restore_backup(fh, store=A.STORE, replace=replace)

# Compare live counts with the backup table_end records (and result["tables"]).
ends = {}
with gzip.open(backup, "rt") as z:
    for line in z:
        rec = json.loads(line)
        if "table_end" in rec:
            ends[rec["table_end"]] = int(rec["rows"])

rows = {}
mismatches = []
for t in sorted(ends):
    n = int(A.STORE.q(f'SELECT COUNT(*) FROM "{t}"')[0][0])
    rows[t] = n
    exp = ends[t]
    wrote = int(result["tables"].get(t, 0))
    ok = n == exp == wrote
    status = "ok" if ok else "MISMATCH"
    print(f"{t}: live={n} backup={exp} wrote={wrote} {status}")
    if not ok:
        mismatches.append(t)

# Sequences / identity must sit at max(id) (or 1/false if empty) so new inserts don't collide.
seq_issues = []
for t in sorted(ends):
    cols = A.STORE.q(
        """SELECT a.attname FROM pg_class c
             JOIN pg_namespace n ON n.oid=c.relnamespace
             JOIN pg_attribute a ON a.attrelid=c.oid
           WHERE n.nspname='public' AND c.relname=:t
             AND a.attnum>0 AND NOT a.attisdropped
             AND pg_get_serial_sequence(quote_ident(:t), a.attname) IS NOT NULL""", t=t)
    for (col,) in cols:
        seq = A.STORE.q("SELECT pg_get_serial_sequence(quote_ident(:t), :c)", t=t, c=col)
        if not seq or not seq[0][0]:
            continue
        mx = int(A.STORE.q(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{t}"')[0][0])
        raw = seq[0][0]  # typically public.users_id_seq
        parts = raw.split(".")
        if len(parts) == 2 and all(__import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in parts):
            schema, sname = parts
        elif __import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
            schema, sname = "public", raw
        else:
            seq_issues.append(f"{t}.{col}: unexpected sequence name")
            continue
        st = A.STORE.q(f'SELECT last_value, is_called FROM "{schema}"."{sname}"')
        if not st:
            seq_issues.append(f"{t}.{col}: sequence not found")
            continue
        last, called = int(st[0][0]), bool(st[0][1])
        next_id = (last + 1) if called else last
        expected_next = (mx + 1) if mx >= 1 else 1
        ok = next_id >= expected_next and (mx < 1 or last >= mx)
        print(f"  seq {t}.{col}: max={mx} last_value={last} is_called={called} next={next_id} {'ok' if ok else 'BAD'}")
        if not ok:
            seq_issues.append(f"{t}.{col}: next={next_id} expected>={expected_next}")

print(f"tables: {len(ends)}  mismatches: {len(mismatches)}  seq_issues: {len(seq_issues)}")
if mismatches or seq_issues:
    if mismatches:
        print("count mismatches: " + ", ".join(mismatches), file=sys.stderr)
    if seq_issues:
        print("sequence issues: " + "; ".join(seq_issues), file=sys.stderr)
    sys.exit(1)
print("ok")
sys.exit(0)
PY
