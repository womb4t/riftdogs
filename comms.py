"""The communicator's rules and storage (server side): ship numbers, contacts, blocks, messages, reports.

Pure functions over a sqlite3 connection `db`; the caller owns the transaction. Plain text only. Numbers belong to
the account, are never reused (a deleted account's number stays in `ships` under a negative tombstone), and
blocking is silent: a blocked sender is never told.
"""
import json
import random
import re
import unicodedata

PRIORITIES = ('distress', 'urgency', 'safety', 'routine')
MAX_TEXT = 280
KEEP_DAYS = 30
NUMBER_RE = re.compile(r'RD-\d{4}')
CH16 = 'ch16'
INBOX_LIMIT = 50        # most rows one inbox call returns (the cursor pages the rest)
INBOX_BYTES = 100_000   # and at most about this much JSON, as the server encodes it (the game refuses a reply over 300 kB)
LIST_LIMIT = 200        # most contacts, or blocked ships, one reply lists
REQUEST_LIMIT = 50      # most contact requests one reply lists (the newest)


def encoded_size(value):
    """Bytes `value` takes in a server reply (encoded as the server does: ASCII JSON, so non-ASCII text is escaped)."""
    return len(json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')))


def clean_text(text):
    """Plain text, control characters removed, stripped, 1..MAX_TEXT characters; else ValueError."""
    if type(text) is not str: raise ValueError('Message is empty or too long.')
    text = ''.join(c for c in text if unicodedata.category(c) != 'Cc').strip()
    if not 1 <= len(text) <= MAX_TEXT: raise ValueError('Message is empty or too long.')
    return text


def schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS ships (player INTEGER PRIMARY KEY, number TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS contacts (owner INTEGER, other INTEGER, PRIMARY KEY(owner, other));
        CREATE TABLE IF NOT EXISTS requests (sender INTEGER, recipient INTEGER, at REAL, PRIMARY KEY(sender, recipient));
        CREATE TABLE IF NOT EXISTS blocks (owner INTEGER, other INTEGER, PRIMARY KEY(owner, other));
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, client_id TEXT, sender INTEGER, recipient INTEGER, system INTEGER,
            kind TEXT DEFAULT 'text', priority TEXT, text TEXT, at REAL, deliver_at REAL, UNIQUE(sender, client_id));
        CREATE INDEX IF NOT EXISTS messages_recipient ON messages(recipient, id);
        CREATE INDEX IF NOT EXISTS messages_system ON messages(system, id);
        CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, reporter INTEGER, message INTEGER, at REAL);
        CREATE TABLE IF NOT EXISTS comm_keys (player INTEGER PRIMARY KEY, granted REAL);''')


# ---- ship numbers

def issue_number(db):
    """A free ship number, picked at random, without reserving it: never one in `ships` (a deleted pilot's number
    stays there), and never one an older account uses as its login."""
    taken = {r[0] for r in db.execute('SELECT number FROM ships')}
    taken |= {r[0] for r in db.execute("SELECT upper(name) FROM players WHERE upper(name) LIKE 'RD-%'")}
    free = [f'RD-{n}' for n in range(1000, 10000) if f'RD-{n}' not in taken]
    if not free: raise RuntimeError('No ship numbers left.')
    return random.choice(free)


def number_for(db, player):
    """The player's ship number, issued (random, free, never a reserved one) on the first call."""
    row = db.execute('SELECT number FROM ships WHERE player=?', (player,)).fetchone()
    if row: return row[0]
    number = issue_number(db)
    db.execute('INSERT INTO ships(player, number) VALUES (?,?)', (player, number))
    return number


def player_for_number(db, number):
    if type(number) is not str or not NUMBER_RE.fullmatch(number): return None
    row = db.execute('SELECT player FROM ships WHERE number=? AND player>0', (number,)).fetchone()
    return row[0] if row else None


def _resolve(db, number):
    player = player_for_number(db, number)
    if player is None: raise ValueError('No ship with that number.')
    return player


def login(db, player):
    """The account login, for the operator's CLI only: other pilots are never shown it."""
    row = db.execute('SELECT name FROM players WHERE id=?', (player,)).fetchone()
    return row[0] if row else '(deleted)'


def _name(db, player):
    import names
    if db.execute('SELECT 1 FROM players WHERE id=?', (player,)).fetchone() is None: return '(deleted)'
    return names.display(db, player)


# ---- contacts and blocks

def _blocked(db, owner, other):
    return db.execute('SELECT 1 FROM blocks WHERE owner=? AND other=?', (owner, other)).fetchone() is not None


def _contacts(db, a, b):
    return (db.execute('SELECT 1 FROM contacts WHERE owner=? AND other=?', (a, b)).fetchone() is not None
            and db.execute('SELECT 1 FROM contacts WHERE owner=? AND other=?', (b, a)).fetchone() is not None)


def offer_contact(db, sender, recipient, now):
    if sender == recipient or recipient is None or recipient <= 0: return
    if _blocked(db, recipient, sender) or _contacts(db, sender, recipient): return
    db.execute('INSERT OR REPLACE INTO requests(sender, recipient, at) VALUES (?,?,?)', (sender, recipient, now))


def request_contact(db, sender, number, now):
    offer_contact(db, sender, _resolve(db, number), now)


def accept_contact(db, owner, other):
    if not db.execute('SELECT 1 FROM requests WHERE sender=? AND recipient=?', (other, owner)).fetchone(): return False
    db.execute('DELETE FROM requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)', (other, owner, owner, other))
    db.execute('INSERT OR IGNORE INTO contacts(owner, other) VALUES (?,?)', (owner, other))
    db.execute('INSERT OR IGNORE INTO contacts(owner, other) VALUES (?,?)', (other, owner))
    return True


def introduce(db, a, b):
    if a == b or _blocked(db, a, b) or _blocked(db, b, a): return
    db.execute('DELETE FROM requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)', (a, b, b, a))
    db.execute('INSERT OR IGNORE INTO contacts(owner, other) VALUES (?,?)', (a, b))
    db.execute('INSERT OR IGNORE INTO contacts(owner, other) VALUES (?,?)', (b, a))


def block(db, owner, other):
    if owner == other: return
    db.execute('INSERT OR IGNORE INTO blocks(owner, other) VALUES (?,?)', (owner, other))
    db.execute('DELETE FROM contacts WHERE (owner=? AND other=?) OR (owner=? AND other=?)', (owner, other, other, owner))
    db.execute('DELETE FROM requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)', (owner, other, other, owner))


def unblock(db, owner, other):
    db.execute('DELETE FROM blocks WHERE owner=? AND other=?', (owner, other))


def ignore(db, owner, other):
    """Drop a contact request from `other` without answering it (the sender is not told; they may ask again)."""
    db.execute('DELETE FROM requests WHERE sender=? AND recipient=?', (other, owner))


def _listed(db, rows):
    """Contacts and blocks as other pilots are named: by commander name, never by login, in name then number order."""
    import names
    return sorted((dict(number=n, name=names.display(db, other)) for n, other in rows), key=lambda r: (r['name'].lower(), r['number']))


def blocked_of(db, player):
    rows = db.execute('SELECT s.number, b.other FROM blocks b JOIN ships s ON s.player=b.other JOIN players p ON p.id=b.other '
                      'WHERE b.owner=? ORDER BY p.name LIMIT ?', (player, LIST_LIMIT)).fetchall()
    return _listed(db, rows)


def contacts_of(db, player):
    rows = db.execute('SELECT s.number, c.other FROM contacts c JOIN ships s ON s.player=c.other JOIN players p ON p.id=c.other '
                      'WHERE c.owner=? ORDER BY p.name LIMIT ?', (player, LIST_LIMIT)).fetchall()
    return _listed(db, rows)


def requests_for(db, player):
    import names
    rows = db.execute('SELECT s.number, r.sender, r.at FROM requests r JOIN ships s ON s.player=r.sender JOIN players p ON p.id=r.sender '
                      'WHERE r.recipient=? ORDER BY r.at DESC LIMIT ?', (player, REQUEST_LIMIT)).fetchall()
    return [dict(number=n, name=names.display(db, other), at=at) for n, other, at in reversed(rows)]


# ---- messages

def send(db, sender, client_id, to, priority, text, system, now, flare_until=0):
    """Store a message; returns its id, or None when silently dropped (not mutual contacts, or blocked).
    `to` is a ship number or 'ch16'. ValueError: bad text, unknown priority, unknown number format."""
    if priority not in PRIORITIES: raise ValueError('Unknown priority.')
    text = clean_text(text)
    channel = to == CH16
    if not channel and (type(to) is not str or not NUMBER_RE.fullmatch(to)): raise ValueError('No ship with that number.')
    if channel and system is None: raise ValueError('No system for channel 16.')
    old = db.execute('SELECT id FROM messages WHERE sender=? AND client_id=?', (sender, client_id)).fetchone()
    if old: return old[0]
    recipient = None
    deliver = now
    if not channel:
        recipient = player_for_number(db, to)
        if recipient is None or recipient == sender: return None
        if _blocked(db, recipient, sender) or not _contacts(db, sender, recipient): return None
        deliver = max(now, flare_until or 0)
    cur = db.execute('INSERT INTO messages(client_id, sender, recipient, system, kind, priority, text, at, deliver_at) '
                     "VALUES (?,?,?,?,'text',?,?,?,?)",
                     (client_id, sender, recipient, system if channel else None, priority, text, now, deliver))
    return cur.lastrowid


def inbox(db, player, system, since, now):
    return inbox_page(db, player, system, since, now)[0]


def inbox_page(db, player, system, since, now):
    """What `player` should see: direct messages to them, and channel 16 for `system`, oldest delivery first, and
    whether more are waiting. `since` is the cursor [deliver_at, id] of the last row already seen (None or [0, 0]
    for a first poll); each row carries its own 'cursor'. A first poll shows only the last hour of channel 16; direct
    mail goes back the full retention. At most INBOX_LIMIT rows and about INBOX_BYTES of JSON (always at least one
    row), so a long backlog is paged without gaps and no reply grows past what the game accepts."""
    at, last = since if since else (0, 0)
    first = (at, last) == (0, 0)
    rows = db.execute(
        'SELECT m.id, s.number, m.sender, m.recipient, m.priority, m.text, m.at, m.deliver_at FROM messages m '
        'LEFT JOIN ships s ON s.player=m.sender '
        'WHERE (m.deliver_at>? OR (m.deliver_at=? AND m.id>?)) AND m.deliver_at<=? AND m.sender<>? '
        'AND (m.recipient=? OR (m.recipient IS NULL AND m.system=? AND (?=0 OR m.at>=?))) '
        'AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.owner=? AND b.other=m.sender) '
        'ORDER BY m.deliver_at ASC, m.id ASC LIMIT ?',
        (at, at, last, now, player, player, system, first, now - 3600, player, INBOX_LIMIT + 1)).fetchall()
    found, size = [], 2
    for i, number, sender, recipient, priority, text, sent, deliver in rows[:INBOX_LIMIT]:
        row = dict(id=i, sender_number=number, sender_name=_name(db, sender), channel='direct' if recipient else CH16,
                   priority=priority, text=text, at=sent, cursor=[deliver, i])
        size += encoded_size(row) + 1
        if found and size > INBOX_BYTES: return found, True
        found.append(row)
    return found, len(rows) > INBOX_LIMIT


def reported(db, reporter, message_id):
    return db.execute('SELECT 1 FROM reports WHERE reporter=? AND message=?', (reporter, message_id)).fetchone() is not None


def report(db, reporter, message_id, now):
    """File a report; the same reporter reporting the same message again (a resend) changes nothing."""
    if reported(db, reporter, message_id): return
    db.execute('INSERT INTO reports(reporter, message, at) VALUES (?,?,?)', (reporter, message_id, now))


def reports(db):
    return db.execute('SELECT id, reporter, message, at FROM reports ORDER BY id').fetchall()


# ---- keys

def grant_key(db, player, now):
    db.execute('INSERT OR REPLACE INTO comm_keys(player, granted) VALUES (?,?)', (player, now))


def revoke_key(db, player):
    db.execute('DELETE FROM comm_keys WHERE player=?', (player,))


def has_key(db, player):
    return db.execute('SELECT 1 FROM comm_keys WHERE player=?', (player,)).fetchone() is not None


# ---- housekeeping

def expire(db, now):
    cutoff = now - KEEP_DAYS * 86400
    return sum(db.execute(f'DELETE FROM {table} WHERE at<?', (cutoff,)).rowcount for table in ('messages', 'requests', 'reports'))


def forget(db, player):
    """Delete everything about a player except their number, which stays reserved under a negative tombstone."""
    db.execute('DELETE FROM reports WHERE reporter=? OR message IN (SELECT id FROM messages WHERE sender=? OR recipient=?)',
               (player, player, player))
    db.execute('DELETE FROM messages WHERE sender=? OR recipient=?', (player, player))
    db.execute('DELETE FROM contacts WHERE owner=? OR other=?', (player, player))
    db.execute('DELETE FROM requests WHERE sender=? OR recipient=?', (player, player))
    db.execute('DELETE FROM blocks WHERE owner=? OR other=?', (player, player))
    db.execute('DELETE FROM comm_keys WHERE player=?', (player,))
    db.execute('UPDATE ships SET player=? WHERE player=?', (-player, player))


# ---- game side: the log that rides on the presence thread

STRIP_SECONDS = 8
LOG_CAP = 500
OUT_CAP = 50   # unsent messages kept while the server is unreachable
BATCH = 10     # the server's per-request limit for both lists
ACTIONS = ('request', 'offer', 'accept', 'ignore', 'block', 'unblock', 'report')


class CommsLog:
    """What the player has heard, and what is waiting to be sent. Touched by the presence thread (payload/receive)
    and the game thread (everything else), so every method takes the lock. Never raises on a malformed reply."""

    def __init__(self, clock=None):
        import threading
        import time
        self.lock = threading.RLock()
        self.clock = clock or time.monotonic
        self.messages = []      # newest last; each carries 'n' (arrival order) and 'seen' (clock at arrival)
        self.number, self.contacts, self.requests, self.blocked, self.key = None, [], [], [], False
        self.errors = []        # the server's last error strings (shown by the UI)
        self.since = None       # cursor [deliver_at, id] of the last server message received
        self._out, self._actions, self._sent_actions = [], [], 0
        self._ids, self._n, self._read = set(), 0, 0
        self._backlog = True    # the session's first poll (and its further pages) bring mail that is not news

    # ---- sending
    def queue(self, to, text, priority='routine'):
        """Queue a message for the next exchange; returns its client id. ValueError when it can never be sent."""
        import uuid
        text = clean_text(text)
        if priority not in PRIORITIES: raise ValueError('Unknown priority.')
        if to != CH16 and (type(to) is not str or not NUMBER_RE.fullmatch(to)): raise ValueError('No ship with that number.')
        with self.lock:
            if len(self._out) >= OUT_CAP: raise ValueError('Too many unsent messages.')
            cid = uuid.uuid4().hex
            self._out.append(dict(id=cid, to=to, priority=priority, text=text))
            return cid

    def act(self, do, **fields):
        if do not in ACTIONS: raise ValueError('Unknown action.')
        with self.lock:
            if len(self._actions) >= OUT_CAP: raise ValueError('Too many pending actions.')
            self._actions.append(dict(fields, do=do))

    def payload(self):
        """The request's `comms` object. Unacknowledged messages are resent until the server says it has them."""
        with self.lock:
            actions = [dict(a) for a in self._actions[:BATCH]]
            self._sent_actions = len(actions)
            return dict(since=list(self.since) if self.since else None,
                        out=[dict(m) for m in self._out[:BATCH]], actions=actions)

    # ---- receiving
    def receive(self, reply):
        try: self._receive(reply)
        except Exception: pass   # a malformed reply is ignored; the presence thread must live

    def _receive(self, reply):
        if type(reply) is not dict: return
        with self.lock:
            done = set(x for k in ('accepted', 'rejected') if type(reply.get(k)) is list for x in reply[k] if type(x) is str)
            self._out = [m for m in self._out if m['id'] not in done]
            del self._actions[:self._sent_actions]   # the exchange that carried them completed
            self._sent_actions = 0
            if type(reply.get('number')) is str: self.number = reply['number']
            if type(reply.get('contacts')) is list: self.contacts = reply['contacts']
            if type(reply.get('requests')) is list: self.requests = reply['requests']
            if type(reply.get('blocked')) is list: self.blocked = reply['blocked']
            if type(reply.get('key')) is bool: self.key = reply['key']
            if type(reply.get('errors')) is list: self.errors = [e for e in reply['errors'] if type(e) is str]
            backlog, self._backlog = self._backlog, self._backlog and reply.get('more') is True
            for raw in reply.get('messages') if type(reply.get('messages')) is list else []:
                cursor = raw.get('cursor') if type(raw) is dict else None
                if (type(cursor) is not list or len(cursor) != 2 or any(type(c) not in (int, float) for c in cursor)
                        or type(raw.get('id')) is not int or type(raw.get('text')) is not str
                        or raw.get('priority') not in PRIORITIES): continue
                self.since = list(cursor)
                if raw['id'] in self._ids: continue
                self._add(dict(raw, old=backlog))   # old: already read, and kept off the strip

    def _add(self, message):
        self._n += 1
        message.setdefault('channel', CH16)
        message.setdefault('sender_name', '')
        message.update(n=self._n, seen=self.clock())
        self.messages.append(message)
        self._ids.add(message['id'])
        if len(self.messages) > LOG_CAP:
            del self.messages[:len(self.messages) - LOG_CAP]
            self._ids = {m['id'] for m in self.messages}

    def local(self, sender_name, text, priority='routine', channel=CH16):
        """A scripted character's line: shown in the log, never sent."""
        with self.lock:
            self._add(dict(id='local-%d' % (self._n + 1), sender_number=None, sender_name=sender_name, channel=channel,
                           priority=priority, text=text, at=None, cursor=None))

    # ---- reading
    def unread(self):
        with self.lock: return sum(m['n'] > self._read and not m.get('old') for m in self.messages)

    def needs_you(self, quiet_senders=(), always=()):
        """An unread direct message, Mayday or Pan-Pan (not your own): the cockpit's Comms page lights for one.
        Direct lines from quiet_senders don't count, unless their text is one of `always`."""
        with self.lock:
            # the game's own rows (YOU, HERBERT...) have no sender number; a pilot's always has one, whatever their name
            return any(m['n'] > self._read and not m.get('old')
                       and not (m.get('sender_name') == 'YOU' and m.get('sender_number') is None)
                       and (m['priority'] in ('distress', 'urgency')
                            or (m['channel'] == 'direct'
                                and (m.get('sender_name') not in quiet_senders or m.get('sender_number') is not None
                                     or m.get('text') in always)))
                       for m in self.messages)

    def mark_read(self):
        with self.lock: self._read = self._n

    def view(self):
        """A locked snapshot for drawing: copies only, so the presence thread can never change it mid-frame."""
        with self.lock:
            return dict(messages=[dict(m) for m in self.messages],
                        contacts=[dict(c) for c in self.contacts if type(c) is dict],
                        requests=[dict(r) for r in self.requests if type(r) is dict],
                        blocked=[dict(b) for b in self.blocked if type(b) is dict],
                        number=self.number, key=self.key, errors=list(self.errors),
                        unread=self.unread(), strip=self.strip())

    def contact_list(self):
        """Just the contacts (copies), for the many small lookups a frame makes without building a whole view()."""
        with self.lock: return [dict(c) for c in self.contacts if type(c) is dict]

    def strip(self):
        """Messages worth showing on the cockpit strip: direct, distress and urgency ones from the last few seconds."""
        with self.lock:
            now = self.clock()
            return [dict(m) for m in self.messages if now - m['seen'] <= STRIP_SECONDS and not m.get('old')
                    and (m['channel'] == 'direct' or m['priority'] in ('distress', 'urgency'))]
