"""Examiner Varga, examining officer of the Sovereign Trade Assembly, who runs the Trade Dog check flight.

Pure module: no SDL, no game import. Formal, dry, short sentences, praise only when earned, never a joke. Herbert
mutters his asides in the pilot's ear during her test; she never hears him. Placeholders: {skill} is the skill the
pilot has yet to show, {minutes} the wait before a retake. Every line fits Herbert's flight card, so each fits the panel too.
"""
import random

FACES = ('neutral', 'noting', 'sceptical', 'approving', 'stern')

LINES = {
    'booked': (
        "Your check flight is booked. Launch within two minutes, Commander.",
        "Booked. You have two minutes to launch, Commander. Do not keep me waiting.",
    ),
    'brief_launch': (
        "Part one. Launch, and call station control on the radio. Do it properly.",
    ),
    'brief_beacon': (
        "Part two. Fly to the marker beacon. The jump drive stays cold.",
    ),
    'brief_distress': (
        "Part three. A distress call will come in on DSC. Answer it, and reach the ship in time.",
    ),
    'brief_dock': (
        "Part four. Return and dock within five minutes. Speed 20 or under. Square in the slot.",
    ),
    'part_good': (
        "That part was acceptable.",
        "Correct. Proceed.",
    ),
    'part_poor': (
        "That part was below standard. Noted.",
        "Not to standard. Continue.",
    ),
    'pass': (
        "You have passed, Commander. The Assembly will record it.",
        "Passed. Do not mistake that for a reason to relax.",
    ),
    'fail': (
        "You have not passed. Not every part was to standard.",
        "Not today, Commander. Some of it was below standard. Book again.",
    ),
    'aborted': (
        "The check flight is ended. You will book another.",
    ),
    'not_ready': (
        "You are not ready, Commander. {skill} is not yet shown.",
        "I will not examine an unprepared pilot. {skill} first.",
    ),
    'online_only': (
        "I examine online pilots only, Commander. Connect to a server first.",
    ),
    'wait': (
        "You may sit again in {minutes} minutes. Not before.",
        "Rules are rules. {minutes} minutes, Commander.",
    ),
}

_FACE_OF = {}
for _face, _keys in (
        ('neutral', 'booked brief_launch brief_beacon brief_distress brief_dock'),
        ('noting', 'part_good'),
        ('sceptical', 'part_poor not_ready online_only'),
        ('approving', 'pass'),
        ('stern', 'fail aborted wait')):
    for _key in _keys.split(): _FACE_OF[_key] = _face


def face_for(key):
    """Which of her faces she wears saying this line; neutral for anything unlisted."""
    return _FACE_OF.get(key, 'neutral')


def line(key, rng=random, **fmt):
    """One of the key's lines at random, its placeholders filled."""
    return rng.choice(LINES[key]).format(**fmt)


# What Herbert mutters on his card during her test: she cannot hear him.
HERBERT_ASIDES = (
    "She can't hear me, rookie. Throttle back.",
    "Easy does it. She's watching the speed.",
    "Breathe, rookie. You've done harder.",
    "Mind the slot. She'll want it dead centre.",
    "Don't rush it. Nobody ever failed for being slow.",
    "Eyes on the beacon, not on her.",
)
