"""BarksBuds direct messages: data layer (conversations between two members, messages, read state, blocks, reports).

Any signed-in member can message any other member (no friends list or allowlist). One conversation per pair of
members (user_lo < user_hi). Each side has its own row in conversation_state: last_read_id (unread counts),
last_email_at (notification throttle) and hidden (set when that side blocks the other).

Blocks: if either member has blocked the other, neither can send. The blocker's copy of the conversation is hidden
and messages from the blocked member never count as unread or trigger email. The blocked member only sees a generic
"you can't reply" note, never that they were blocked.

Bodies are plain text (escaped on output, never auto-linked). Account deletion removes the member's conversations,
messages, blocks and read state, and anonymizes any reports that mention them.
"""
import hashlib, hmac, re

import accounts as A

MAX_BODY = 2000                     # characters per message
SEND_PER_HOUR = 30                  # messages a member can send per hour (all conversations)
NEW_PER_DAY = 10                    # new conversations a member can start per day
EMAIL_EVERY = 30 * 60               # at most one notification email per conversation per recipient in this window
PREVIEW = 80                        # characters of the message shown in the notification email
PAGE = 200                          # messages shown on a conversation page (newest)


def q(sql, **kw):
    return A.STORE.q(sql, **kw)


def one(sql, **kw):
    r = A.STORE.q(sql, **kw)
    return r[0] if r else None


def init_schema(store):
    pg = store.kind == "postgres"
    ID = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    INT = "BIGINT" if pg else "INTEGER"
    for s in [
        f"""CREATE TABLE IF NOT EXISTS conversations(id {ID}, user_lo {INT} NOT NULL, user_hi {INT} NOT NULL,
            created_by {INT} NOT NULL, created_at {INT} NOT NULL, last_message_at {INT} NOT NULL DEFAULT 0,
            last_message_id {INT} NOT NULL DEFAULT 0, UNIQUE(user_lo, user_hi))""",
        "CREATE INDEX IF NOT EXISTS conversations_hi_idx ON conversations(user_hi)",
        "CREATE INDEX IF NOT EXISTS conversations_creator_idx ON conversations(created_by, created_at)",
        f"""CREATE TABLE IF NOT EXISTS conversation_state(id {ID}, conversation_id {INT} NOT NULL, user_id {INT} NOT NULL,
            last_read_id {INT} NOT NULL DEFAULT 0, last_email_at {INT} NOT NULL DEFAULT 0, hidden {INT} NOT NULL DEFAULT 0,
            UNIQUE(conversation_id, user_id))""",
        "CREATE INDEX IF NOT EXISTS conversation_state_user_idx ON conversation_state(user_id)",
        f"""CREATE TABLE IF NOT EXISTS messages(id {ID}, conversation_id {INT} NOT NULL, sender_id {INT} NOT NULL,
            body TEXT NOT NULL, created_at {INT} NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages(conversation_id, id)",
        "CREATE INDEX IF NOT EXISTS messages_sender_idx ON messages(sender_id, created_at)",
        f"""CREATE TABLE IF NOT EXISTS user_blocks(id {ID}, blocker_id {INT} NOT NULL, blocked_id {INT} NOT NULL,
            created_at {INT} NOT NULL, UNIQUE(blocker_id, blocked_id))""",
        "CREATE INDEX IF NOT EXISTS user_blocks_blocked_idx ON user_blocks(blocked_id)",
        f"""CREATE TABLE IF NOT EXISTS message_reports(id {ID}, message_id {INT}, conversation_id {INT},
            reporter_user_id {INT}, reported_user_id {INT}, reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '', ip_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
            created_at {INT} NOT NULL)""",
    ]:
        store.q(s)
    ucols = ({r[0] for r in store.q("SELECT column_name FROM information_schema.columns WHERE table_name='users'")} if pg
             else {r[1] for r in store.q("PRAGMA table_info(users)")})
    if "message_emails" not in ucols:
        store.q(f"ALTER TABLE users ADD COLUMN message_emails {INT} NOT NULL DEFAULT 1")


# ---------------------------------------------------------------- helpers
def clean_body(s):
    """Plain text: NFC, control characters dropped, runs of blank lines collapsed, trimmed to MAX_BODY."""
    import webapp
    return webapp.clean(s, MAX_BODY, multiline=True)


def preview(body, n=PREVIEW):
    s = re.sub(r"\s+", " ", body or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def name_of(uid):
    r = one("SELECT display_name FROM users WHERE id=:u", u=uid)
    return (r[0] if r and r[0] else "A BarksBuds member") if r else ""


def user_exists(uid):
    return bool(one("SELECT 1 FROM users WHERE id=:u", u=uid))


def other(conv, uid):
    return conv["user_hi"] if conv["user_lo"] == uid else conv["user_lo"]


# ---------------------------------------------------------------- blocks
def blocked(blocker, blocked_id):
    return bool(one("SELECT 1 FROM user_blocks WHERE blocker_id=:a AND blocked_id=:b", a=blocker, b=blocked_id))


def either_blocked(a, b):
    return bool(one("SELECT 1 FROM user_blocks WHERE (blocker_id=:a AND blocked_id=:b) OR (blocker_id=:b AND blocked_id=:a)", a=a, b=b))


def block(blocker, blocked_id):
    if blocker == blocked_id:
        return
    q("INSERT INTO user_blocks(blocker_id,blocked_id,created_at) VALUES(:a,:b,:t) ON CONFLICT DO NOTHING", a=blocker, b=blocked_id, t=A.now())
    c = find(blocker, blocked_id)
    if c:
        q("UPDATE conversation_state SET hidden=1 WHERE conversation_id=:c AND user_id=:u", c=c["id"], u=blocker)


def unblock(blocker, blocked_id):
    q("DELETE FROM user_blocks WHERE blocker_id=:a AND blocked_id=:b", a=blocker, b=blocked_id)
    c = find(blocker, blocked_id)
    if c:
        q("UPDATE conversation_state SET hidden=0 WHERE conversation_id=:c AND user_id=:u", c=c["id"], u=blocker)


def blocked_list(uid):
    """[{user_id, name}] of members this member has blocked, newest first."""
    return [dict(user_id=r[0], name=r[1] or "A BarksBuds member") for r in q(
        """SELECT b.blocked_id, u.display_name FROM user_blocks b JOIN users u ON u.id=b.blocked_id
           WHERE b.blocker_id=:u ORDER BY b.id DESC""", u=uid)]


# ---------------------------------------------------------------- conversations
C_COLS = "id,user_lo,user_hi,created_by,created_at,last_message_at,last_message_id"


def _conv(r):
    return dict(zip(C_COLS.split(","), r)) if r else None


def get(cid):
    return _conv(one(f"SELECT {C_COLS} FROM conversations WHERE id=:c", c=cid))


def find(a, b):
    lo, hi = min(a, b), max(a, b)
    return _conv(one(f"SELECT {C_COLS} FROM conversations WHERE user_lo=:l AND user_hi=:h", l=lo, h=hi))


def is_participant(conv, uid):
    return bool(conv and uid in (conv["user_lo"], conv["user_hi"]))


def get_or_create(a, b):
    """(conversation, created) for the pair. Creating is idempotent under races (unique pair)."""
    c = find(a, b)
    if c:
        return c, False
    lo, hi = min(a, b), max(a, b)
    r = one("""INSERT INTO conversations(user_lo,user_hi,created_by,created_at) VALUES(:l,:h,:a,:t)
               ON CONFLICT DO NOTHING RETURNING id""", l=lo, h=hi, a=a, t=A.now())
    c = find(a, b)
    for uid in (lo, hi):
        q("INSERT INTO conversation_state(conversation_id,user_id) VALUES(:c,:u) ON CONFLICT DO NOTHING", c=c["id"], u=uid)
    return c, bool(r)


def started_today(uid):
    return one("SELECT COUNT(*) FROM conversations WHERE created_by=:u AND created_at>:t", u=uid, t=A.now() - 86400)[0]


def state(cid, uid):
    r = one("SELECT last_read_id, last_email_at, hidden FROM conversation_state WHERE conversation_id=:c AND user_id=:u", c=cid, u=uid)
    return dict(last_read_id=r[0], last_email_at=r[1], hidden=r[2]) if r else dict(last_read_id=0, last_email_at=0, hidden=0)


def add_message(conv, sender, body):
    """Store a message (caller validated it and checked blocks/limits). Returns the message id."""
    t = A.now()
    mid = one("INSERT INTO messages(conversation_id,sender_id,body,created_at) VALUES(:c,:s,:b,:t) RETURNING id",
              c=conv["id"], s=sender, b=body, t=t)[0]
    q("UPDATE conversations SET last_message_at=:t, last_message_id=:m WHERE id=:c", t=t, m=mid, c=conv["id"])
    # the sender has read everything up to their own message
    q("UPDATE conversation_state SET last_read_id=:m WHERE conversation_id=:c AND user_id=:u", m=mid, c=conv["id"], u=sender)
    return mid


def mark_read(cid, uid):
    q("""UPDATE conversation_state SET last_read_id=(SELECT COALESCE(MAX(id),0) FROM messages WHERE conversation_id=:c)
         WHERE conversation_id=:c AND user_id=:u""", c=cid, u=uid)


def messages(cid, limit=PAGE):
    """[{id, sender_id, body, created_at}] oldest first (the newest `limit`), and whether older ones were left out."""
    rows = q("SELECT id, sender_id, body, created_at FROM messages WHERE conversation_id=:c ORDER BY id DESC LIMIT :n",
             c=cid, n=limit + 1)
    more = len(rows) > limit
    return [dict(id=r[0], sender_id=r[1], body=r[2], created_at=r[3]) for r in reversed(rows[:limit])], more


def message(mid):
    r = one("SELECT id, conversation_id, sender_id, body, created_at FROM messages WHERE id=:m", m=mid)
    return dict(id=r[0], conversation_id=r[1], sender_id=r[2], body=r[3], created_at=r[4]) if r else None


_UNREAD = """SELECT COUNT(*) FROM messages m JOIN conversation_state s ON s.conversation_id=m.conversation_id AND s.user_id=:u
             WHERE s.hidden=0 AND m.sender_id<>:u AND m.id>s.last_read_id
             AND NOT EXISTS(SELECT 1 FROM user_blocks b WHERE b.blocker_id=:u AND b.blocked_id=m.sender_id)"""


def unread_total(uid):
    r = one(_UNREAD, u=uid)
    return int(r[0]) if r else 0


def unread_in(cid, uid):
    return int(one(_UNREAD + " AND m.conversation_id=:c", u=uid, c=cid)[0])


def inbox(uid, limit=200):
    """Conversations with at least one message, newest first: [{id, other_id, other_name, last_body, last_sender,
    last_at, unread}]. Hidden ones (this member blocked the other) are left out."""
    rows = q("""SELECT c.id, CASE WHEN c.user_lo=:u THEN c.user_hi ELSE c.user_lo END AS oid, c.last_message_at,
                       s.last_read_id, m.body, m.sender_id
                FROM conversations c JOIN conversation_state s ON s.conversation_id=c.id AND s.user_id=:u
                JOIN messages m ON m.id=c.last_message_id
                WHERE (c.user_lo=:u OR c.user_hi=:u) AND s.hidden=0
                ORDER BY c.last_message_at DESC, c.id DESC LIMIT :n""", u=uid, n=limit)
    if not rows:
        return []
    ids = ",".join(str(int(r[0])) for r in rows)
    unread = {r[0]: int(r[1]) for r in q(f"""SELECT m.conversation_id, COUNT(*) FROM messages m
                JOIN conversation_state s ON s.conversation_id=m.conversation_id AND s.user_id=:u
                WHERE m.conversation_id IN ({ids}) AND m.sender_id<>:u AND m.id>s.last_read_id GROUP BY m.conversation_id""", u=uid)}
    oids = ",".join(sorted({str(int(r[1])) for r in rows}))
    names = {r[0]: r[1] or "A BarksBuds member" for r in q(f"SELECT id, display_name FROM users WHERE id IN ({oids})")}
    mine_blocked = {r[0] for r in q("SELECT blocked_id FROM user_blocks WHERE blocker_id=:u", u=uid)}
    out = []
    for cid, oid, at, _lr, body, sender in rows:
        if oid in mine_blocked:
            continue
        out.append(dict(id=cid, other_id=oid, other_name=names.get(oid, "A BarksBuds member"), last_body=body,
                        last_sender=sender, last_at=at, unread=unread.get(cid, 0)))
    return out


def other_dogs(uid):
    """[(slug, name)] of a member's visible dogs (owned or co-owned), for context on the conversation page."""
    return [(r[0], r[1]) for r in q(
        """SELECT d.slug, d.name FROM dogs d WHERE d.hidden=0 AND (d.user_id=:u OR d.id IN
           (SELECT dog_id FROM dog_owners WHERE user_id=:u)) ORDER BY d.id LIMIT 6""", u=uid)]


# ---------------------------------------------------------------- notification emails
def claim_email_slot(cid, uid):
    """True (and records the send time) if no notification went to this recipient for this conversation in the last
    EMAIL_EVERY seconds. Atomic, so two quick messages can't both email."""
    t = A.now()
    return bool(one("""UPDATE conversation_state SET last_email_at=:t WHERE conversation_id=:c AND user_id=:u
                       AND last_email_at<=:cut RETURNING user_id""", t=t, c=cid, u=uid, cut=t - EMAIL_EVERY))


def unsub_token(uid):
    return hmac.new(A.SECRET, f"message-emails:{int(uid)}".encode(), hashlib.sha256).hexdigest()[:32]


def check_unsub(uid, tok):
    return str(uid).isdigit() and bool(tok) and hmac.compare_digest(unsub_token(int(uid)), tok)


def set_emails(uid, on):
    q("UPDATE users SET message_emails=:v WHERE id=:u", v=1 if on else 0, u=uid)


def emails_on(uid):
    r = one("SELECT message_emails FROM users WHERE id=:u", u=uid)
    return bool(r and r[0])


def contact(uid):
    """(email, display_name, message_emails on) for sending a notification. The email is never shown on the site."""
    r = one("SELECT email, display_name, message_emails FROM users WHERE id=:u", u=uid)
    return (r[0], r[1] or "", bool(r[2])) if r else (None, "", False)


# ---------------------------------------------------------------- reports
def add_report(msg, reporter, reason, details, ip):
    q("""INSERT INTO message_reports(message_id,conversation_id,reporter_user_id,reported_user_id,reason,details,body,ip_hash,created_at)
         VALUES(:m,:c,:r,:s,:re,:d,:b,:i,:t)""", m=msg["id"], c=msg["conversation_id"], r=reporter, s=msg["sender_id"],
      re=reason, d=details, b=msg["body"], i=A.ip_hash(ip), t=A.now())


def list_reports(limit=300):
    return [dict(id=r[0], message_id=r[1], conversation_id=r[2], reporter=r[3], reported=r[4], reason=r[5], details=r[6],
                 body=r[7], status=r[8], created_at=r[9], reporter_name=r[10] or "", reported_name=r[11] or "", live=bool(r[12])) for r in q(
        """SELECT r.id, r.message_id, r.conversation_id, r.reporter_user_id, r.reported_user_id, r.reason, r.details, r.body,
                  r.status, r.created_at, a.display_name, b.display_name, m.id FROM message_reports r
           LEFT JOIN users a ON a.id=r.reporter_user_id LEFT JOIN users b ON b.id=r.reported_user_id
           LEFT JOIN messages m ON m.id=r.message_id
           ORDER BY CASE WHEN r.status='open' THEN 0 ELSE 1 END, r.id DESC LIMIT :n""", n=limit)]


def set_report_status(rid, status):
    q("UPDATE message_reports SET status=:s WHERE id=:i", s=status, i=rid)


def delete_reported_message(rid):
    """Moderation: remove the reported message from its conversation (the report keeps its copy) and resolve the report."""
    r = one("SELECT message_id, conversation_id FROM message_reports WHERE id=:i", i=rid)
    if not r or not r[0]:
        return False
    q("DELETE FROM messages WHERE id=:m", m=r[0])
    last = one("SELECT id, created_at FROM messages WHERE conversation_id=:c ORDER BY id DESC LIMIT 1", c=r[1])
    q("UPDATE conversations SET last_message_id=:m, last_message_at=:t WHERE id=:c",
      m=last[0] if last else 0, t=last[1] if last else 0, c=r[1])
    set_report_status(rid, "resolved")
    return True


# ---------------------------------------------------------------- account deletion
def purge_user(uid):
    """Delete every conversation the member is in (both sides' copies, all messages), their blocks and read state,
    and anonymize reports that mention them (the reported text is dropped too)."""
    cids = [r[0] for r in q("SELECT id FROM conversations WHERE user_lo=:u OR user_hi=:u", u=uid)]
    for cid in cids:
        q("DELETE FROM messages WHERE conversation_id=:c", c=cid)
        q("DELETE FROM conversation_state WHERE conversation_id=:c", c=cid)
        q("DELETE FROM conversations WHERE id=:c", c=cid)
    q("DELETE FROM messages WHERE sender_id=:u", u=uid)  # belt and braces
    q("DELETE FROM conversation_state WHERE user_id=:u", u=uid)
    q("DELETE FROM user_blocks WHERE blocker_id=:u OR blocked_id=:u", u=uid)
    q("UPDATE message_reports SET reporter_user_id=NULL, ip_hash='' WHERE reporter_user_id=:u", u=uid)
    q("UPDATE message_reports SET reported_user_id=NULL, body='', details='' WHERE reported_user_id=:u", u=uid)
