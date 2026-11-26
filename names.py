"""Commander names: the rules, and the server's public name history (one row per name a pilot has had)."""
import json
import re

import comms

MAX_LEN = 20
RENAME_FEE = 500
RENAME_WAIT = 7*86400
HOWS = ('chosen', 'renamed', 'reset')
MESSAGE = "Names are 1 to 20 letters, numbers, spaces, - or '."
_OK = re.compile(r"[A-Za-z0-9 '-]{1,%d}" % MAX_LEN)
# The fixed senders in the comms log (your own lines, the DSC console, the game's notices, the radio voices, the
# tutor and the examiner): a pilot by one of these names would pass for the ship's computer.
RESERVED = frozenset({'YOU', 'DSC', 'RIFTDOGS', 'STATION CONTROL', 'POLICE', 'UNKNOWN SHIP', 'DISABLED SHIP',
                      'HERBERT', 'VARGA', 'EXAMINER VARGA'})
RESERVED_MESSAGE = "That name is taken by the ship's computer."
# No pilot may pass for Riftdogs itself: a name is refused if it reads as "riftdog" anywhere once case, spaces,
# hyphens, apostrophes and look-alike digits are taken out (Rift-Dogs, R1ftd0g, The Riftdog...).
BRAND = 'riftdog'
BRAND_MESSAGE = 'Riftdogs is the name of the game, not a pilot. Choose another.'
_LOOKALIKE = str.maketrans('0134578l|!', 'oieastbiii')


def _brand(text):
    return BRAND in re.sub(r'[^a-z]', '', text.lower().translate(_LOOKALIKE))


def clean(text):
    """The name as it will be kept: trimmed, runs of spaces collapsed. Raises ValueError if it breaks the rules."""
    if type(text) is not str: raise ValueError(MESSAGE)
    text = re.sub(r' +', ' ', text.strip())
    if not _OK.fullmatch(text): raise ValueError(MESSAGE)
    if _brand(text): raise ValueError(BRAND_MESSAGE)
    if text.upper() in RESERVED: raise ValueError(RESERVED_MESSAGE)
    return text


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS names (player INTEGER NOT NULL, name TEXT NOT NULL, at REAL NOT NULL, how TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS names_player ON names(player, at)')


def record(db, player, name, how, now):
    if how not in HOWS: raise ValueError('Unknown name change.')
    db.execute('INSERT INTO names(player, name, at, how) VALUES (?,?,?,?)', (player, clean(name), now, how))


def _rows(db, player):
    return db.execute('SELECT name, at, how FROM names WHERE player=? ORDER BY at DESC, rowid DESC', (player,)).fetchall()


def current(db, player):
    rows = db.execute('SELECT name FROM names WHERE player=? ORDER BY at DESC, rowid DESC LIMIT 1', (player,)).fetchone()
    return rows[0] if rows else None


def history(db, player):
    return [{'name': n, 'at': at, 'how': how} for n, at, how in _rows(db, player)]


def display(db, player):
    return current(db, player) or f'Pilot {comms.number_for(db, player)}'


def seen(db, player):
    """(display name, pilot number) as other pilots see them; a new number is issued only when none exists yet."""
    row = db.execute('SELECT number FROM ships WHERE player=?', (player,)).fetchone()
    if row is None:
        db.execute('BEGIN IMMEDIATE') if not db.in_transaction else None
        try: number = comms.number_for(db, player)
        except RuntimeError: return current(db, player) or 'Pilot', None   # every ship number is taken
    else: number = row[0]
    return current(db, player) or f'Pilot {number}', number


def next_rename(db, player):
    row = db.execute("SELECT MAX(at) FROM names WHERE player=? AND how='renamed'", (player,)).fetchone()
    return None if row[0] is None else row[0] + RENAME_WAIT


def seed(db, now):
    """Name every player who has no name yet: the save's name if it is valid, else their login (a player whose login breaks the rules, or is a name the ship's computer uses, is skipped). Returns how many."""
    count = 0
    for player, login, save in db.execute('SELECT id, name, save FROM players WHERE id NOT IN (SELECT player FROM names)').fetchall():
        name = None
        try:
            saved = json.loads(save).get('name') if save else None
            if type(saved) is str: name = clean(saved)
        except (ValueError, AttributeError): pass
        if name is None:
            try: name = clean(login)
            except ValueError: continue   # unusable login: stays unnamed, asked on first login
        record(db, player, name, 'chosen', now)
        count += 1
    return count


def forget(db, player):
    db.execute('DELETE FROM names WHERE player=?', (player,))
