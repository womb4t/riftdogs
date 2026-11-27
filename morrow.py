"""Chief Engineer Ada Morrow of the Proving Ground, who designed the galaxy and runs its trials.

Pure module: no SDL, no game import. She is the one person in the galaxy who knows it is a test: the alpha notice is
hers, so Herbert stays in-world. Calm, exact, quietly proud of the work; instructions are literal (keys, no jokes).
"""
import random

NAME = 'CHIEF ENGINEER MORROW'
FACES = ('neutral', 'speaking', 'pleased', 'concerned', 'intrigued')

LINES = {
    # Once per pilot, after Herbert's guided trip ends.
    'alpha': (
        "Morrow, Proving Ground. This galaxy is still on trial, Commander. If it misbehaves, press Ctrl+0. "
        "It comes straight to me, and I read every one.",
    ),
}

_FACE_OF = {'alpha': 'speaking'}


def face_for(key):
    """Which of her faces she wears saying this line; neutral for anything unlisted."""
    return _FACE_OF.get(key, 'neutral')


def line(key, rng=random, **fmt):
    """One of the key's lines at random, its placeholders filled."""
    return rng.choice(LINES[key]).format(**fmt)
