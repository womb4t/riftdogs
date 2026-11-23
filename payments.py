"""Payment codes: one-time codes the save server issues and settles, so players can pay each other credits.

A code is `FH-` plus two groups of 4 characters from ALPHABET. The server stores only its hash (code_hash).
The sender pays amount plus fee() when the code is made; whoever redeems it first gets the amount; an unused
code is refunded to the sender's inbox after EXPIRY, without the fee (the fee leaves the economy).

Codes made by the server come from derive_code: an HMAC of the sender and the client's request id under a
secret kept in a file beside the database (never in it). A retried create (its reply lost) gets the same code
back without a second charge, and the plain code is never stored: only code_hash, an HMAC under the same
secret, so a copy of the database alone can't be searched for live codes. new_code() is the random form."""
import hashlib
import hmac
import secrets

ALPHABET = '23456789ABCDEFGHJKMNPQRSTVWXYZ'   # no 0/O, 1/I/L or U
PREFIX = 'FH'
LENGTH = 8                 # characters after the prefix, as two groups of 4
MIN_AMOUNT = 10
MAX_AMOUNT = 50000
DAILY_CODES = 5            # codes a sender may make in any 24 h
DAILY_SENT = 100000        # cr a sender may put into codes in any 24 h
DAILY_REDEEMED = 10        # codes a pilot may redeem in any 24 h
DAY = 86400
EXPIRY = 7*86400           # s: an unused code is refunded after this
MIN_AGE = 86400            # s: younger accounts can redeem but not create
CLOSED = 'Payment codes are not open yet.'


def _format(chars):
    return f'{PREFIX}-{chars[:4]}-{chars[4:]}'


def new_code():
    """A random code, FH-XXXX-XXXX."""
    return _format(''.join(secrets.choice(ALPHABET) for _ in range(LENGTH)))


def derive_code(secret, sender, request_id, attempt=0):
    """The code for sender `sender`'s create request `request_id`: the same inputs always give the same code.
    `attempt` picks another one if a code with that hash already exists."""
    digest = hmac.new(secret.encode(),f'code|{sender}|{request_id}|{attempt}'.encode(),hashlib.sha256).digest()
    number = int.from_bytes(digest,'big')
    chars = []
    for _ in range(LENGTH):
        number,index = divmod(number,len(ALPHABET))
        chars.append(ALPHABET[index])
    return _format(''.join(chars))


def normalise(text):
    """The canonical FH-XXXX-XXXX form of what a player typed, or None if it can't be a code. Uppercases,
    ignores spaces and dashes (so a missing dash is fine), and accepts the 8 characters without the FH."""
    if type(text) is not str or len(text) > 40: return None
    chars = ''.join(text.split()).replace('-','').upper()
    if len(chars) == LENGTH+len(PREFIX) and chars.startswith(PREFIX): chars = chars[len(PREFIX):]
    if len(chars) != LENGTH or any(c not in ALPHABET for c in chars): return None
    return _format(chars)


def code_hash(code, secret):
    """What the server stores instead of the code: HMAC-SHA256 hex of its canonical form under `secret`."""
    return hmac.new(secret.encode(),f'hash|{code}'.encode(),hashlib.sha256).hexdigest()


def fee(amount):
    """1%, rounded up, at least 1 cr."""
    return max(1,-(-amount//100))
