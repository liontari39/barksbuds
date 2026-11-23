"""Owner-reported health heads-ups per dog run.

Pins expire after HEALTH_TTL (10 days), are labeled unverified, tell people to talk
to their vet, and never diagnose or name dogs or owners. Reports go to the admin
review queue. source is 'owner' today, with room for 'vet' later.
"""
import accounts as A
import community as C

q = C.q
one = C.one
now = C.now

HEALTH_TTL = 10 * 86400
HEALTH_PER_DAY = 2
HEALTH_KINDS = (
    ("kennel_cough", "Kennel cough"),
    ("giardia", "Giardia"),
    ("ticks", "Ticks"),
    ("fleas", "Fleas"),
    ("other", "Something else"),
)
SOURCES = ("owner", "vet")
REPORT_REASONS = ("Not accurate or outdated", "Spam", "Names a person or dog", "Something else")
DISCLAIMER = "This is an unverified owner report, not a diagnosis. Talk to your vet."


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS run_health_pins(id {ID}, run_id TEXT NOT NULL, user_id {INT} NOT NULL,
            kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'owner',
            hidden {INT} NOT NULL DEFAULT 0, created_at {INT} NOT NULL, expires_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS run_health_pins_run_idx ON run_health_pins(run_id, expires_at)",
        "CREATE INDEX IF NOT EXISTS run_health_pins_user_idx ON run_health_pins(user_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS run_health_reports(id {ID}, pin_id {INT} NOT NULL, reporter_user_id {INT},
            reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
            created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS run_health_reports_pin_idx ON run_health_reports(pin_id, status)",
    ]:
        store.q(s)


def purge_user(uid):
    q("UPDATE run_health_reports SET reporter_user_id=NULL WHERE reporter_user_id=:u", u=uid)
    q("DELETE FROM run_health_reports WHERE pin_id IN (SELECT id FROM run_health_pins WHERE user_id=:u)", u=uid)
    q("DELETE FROM run_health_pins WHERE user_id=:u", u=uid)


def kind_label(kind):
    return dict(HEALTH_KINDS).get(kind, "Health report")


def add_pin(uid, run_id, kind, note="", source="owner"):
    """Returns 'ok', 'already', 'limit', or 'bad'."""
    if kind not in dict(HEALTH_KINDS) or not run_id:
        return "bad"
    source = source if source in SOURCES else "owner"
    t = now()
    if one("""SELECT id FROM run_health_pins WHERE user_id=:u AND run_id=:r AND kind=:k
              AND hidden=0 AND expires_at>:t""", u=uid, r=run_id, k=kind, t=t):
        return "already"
    if one("SELECT COUNT(*) FROM run_health_pins WHERE user_id=:u AND created_at>:s",
           u=uid, s=t - 86400)[0] >= HEALTH_PER_DAY:
        return "limit"
    note = (note or "").strip()[:200]
    q("""INSERT INTO run_health_pins(run_id, user_id, kind, note, source, created_at, expires_at)
         VALUES(:r,:u,:k,:n,:s,:t,:x)""", r=run_id, u=uid, k=kind, n=note, s=source, t=t, x=t + HEALTH_TTL)
    return "ok"


def live_pins(run_id, t=None):
    """Visible (not hidden, not expired) pins, newest first. No owner or dog identities."""
    t = t or now()
    rows = q("""SELECT id, kind, note, source, created_at, expires_at FROM run_health_pins
                WHERE run_id=:r AND hidden=0 AND expires_at>:t ORDER BY created_at DESC""", r=run_id, t=t)
    return [dict(id=r[0], kind=r[1], label=kind_label(r[1]), note=r[2] or "", source=r[3] or "owner",
                 created_at=r[4], expires_at=r[5]) for r in rows]


def pin(pid):
    r = one("""SELECT id, run_id, user_id, kind, note, source, hidden, created_at, expires_at
               FROM run_health_pins WHERE id=:i""", i=pid)
    if not r:
        return None
    return dict(id=r[0], run_id=r[1], user_id=r[2], kind=r[3], label=kind_label(r[3]), note=r[4] or "",
                source=r[5] or "owner", hidden=int(r[6] or 0), created_at=r[7], expires_at=r[8])


def set_hidden(pid, hidden=True):
    q("UPDATE run_health_pins SET hidden=:h WHERE id=:i", h=1 if hidden else 0, i=pid)


def add_report(pid, uid, reason, details=""):
    p = pin(pid)
    if not p or p["hidden"] or p["expires_at"] <= now():
        return None
    if reason not in REPORT_REASONS:
        reason = "Something else"
    if one("SELECT id FROM run_health_reports WHERE pin_id=:p AND reporter_user_id=:u AND status='open'",
           p=pid, u=uid):
        return "already"
    r = one("""INSERT INTO run_health_reports(pin_id, reporter_user_id, reason, details, created_at)
               VALUES(:p,:u,:r,:d,:t) RETURNING id""", p=pid, u=uid, r=reason, d=(details or "").strip()[:1000], t=now())
    return r[0] if r else None


def list_reports(limit=300):
    rows = q("""SELECT r.id, r.pin_id, r.reporter_user_id, r.reason, r.details, r.status, r.created_at,
                       p.run_id, p.kind, p.hidden, p.expires_at, p.user_id
                FROM run_health_reports r JOIN run_health_pins p ON p.id=r.pin_id
                ORDER BY r.created_at DESC LIMIT :n""", n=int(limit))
    out = []
    for r in rows:
        reporter = C.user_row(r[2]) if r[2] else None
        out.append(dict(id=r[0], pin_id=r[1], reporter_user_id=r[2], reason=r[3], details=r[4] or "",
                        status=r[5], created_at=r[6], run_id=r[7], kind=r[8], label=kind_label(r[8]),
                        hidden=int(r[9] or 0), expires_at=r[10], poster_user_id=r[11],
                        reporter_name=(reporter or {}).get("name") or ""))
    return out


def set_report_status(rid, status):
    if status in ("open", "resolved"):
        q("UPDATE run_health_reports SET status=:s WHERE id=:i", s=status, i=rid)
