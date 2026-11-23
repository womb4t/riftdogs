"""A seal over an offline save, so hand-editing it can be noticed.

This is a deterrent, not security: the key is a constant in public source, so anyone who reads this file can
re-seal an edited save. It stops casual editing of credits, cargo or storage, no more. A broken seal never
stops a save loading; it only marks the pilot `edited`.

What is covered: the whole save dict except `_seal` and `edited`. `edited` is left out because it is the
result of checking the seal, not part of what is sealed. The flag still can't be cleared by hand in any useful
way: an editor who sets `edited` to false without touching anything else keeps a valid seal (nothing of value
changed, so nothing is lost), but one who changes a value AND clears `edited` breaks the seal again, and the
next load sets `edited` back to true. Once true it stays true: the game writes it, and the server refuses to
import a save carrying it.
"""
import hashlib
import hmac

from save_sync import canonical

KEY = bytes.fromhex('f4a1c97e03b25d68a9e07c3b51d4f862b7c0e9a3158d46f2e0b97a6c3d1850fe')
assert len(KEY) == 32
EXCLUDED = ('_seal', 'edited')


def sign(save):
    body = {key: value for key, value in save.items() if key not in EXCLUDED}
    return hmac.new(KEY, canonical(body), hashlib.sha256).hexdigest()


def verify(save):
    """True if the seal matches, False if it doesn't, None if the save has no seal (before 0.10)."""
    seal = save.get('_seal')
    if seal is None: return None
    try: return hmac.compare_digest(str(seal), sign(save))
    except (ValueError, TypeError): return False


def sealed(save):
    """A copy of `save` carrying a fresh seal."""
    out = {key: value for key, value in save.items() if key != '_seal'}
    out['_seal'] = sign(out)
    return out
