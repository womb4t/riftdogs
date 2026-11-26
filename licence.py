"""The Trade Dog Licence rules: nine logbook skills, the check flight, STA dates, reputation stars, and the
numbers for Herbert's departure.

Pure module: no SDL, no game import. The game and the server import it; nothing here touches the Pilot directly.
`departure` only works out what the pilot is left with.
"""
import time

SKILLS = ('trading', 'jump', 'cruise', 'combat', 'scooping', 'views', 'rescue', 'dsc', 'comms')
SKILL_NAMES = {
    'trading': 'Trading', 'jump': 'Jump flight', 'cruise': 'Non-jump flight', 'combat': 'Combat',
    'scooping': 'Mining and scooping', 'views': 'Views', 'rescue': 'Rescue', 'dsc': 'DSC', 'comms': 'Comms',
}
SKILL_HINTS = {
    'trading': 'Sell cargo for more than you paid.',
    'jump': 'Complete a hyperspace jump to another system.',
    'cruise': 'Complete an interstellar cruise (T).',
    'combat': 'Destroy a pirate.',
    'scooping': 'Scoop loose ore or a cargo canister into the hold (needs scoops).',
    'views': 'In one flight, look through the rear view (4) and pick a target from the radar or with TAB.',
    'rescue': 'Reach a disabled ship and complete its repair.',
    'dsc': 'Acknowledge a distress call on the DSC console (needs a DSC set).',
    'comms': 'Send a radio message on channel 16 or to a contact (online).',
}
LESSON_SKILLS = ('combat', 'scooping', 'dsc', 'rescue')

SKILL_POINTS = 10
CHECK_PARTS = ('launch', 'beacon', 'distress', 'dock')
PART_MAX = 10
PASS_MARK = 115
RETAKE_SECONDS = 1800
STA_YEAR_OFFSET = 1281
CLASS = 'TRADER'

PUBLIC_FIELDS = ('name', 'skills', 'check')
DEFAULT_PUBLIC = {'name': False, 'skills': False, 'check': False}

RECORD_KEYS = ('skills', 'assessment', 'check', 'last_attempt', 'passed', 'number', 'issued', 'stars', 'public',
               'lesson', 'departed', 'note_pending', 'rescues')

# What the pilot keeps when the old instructor departs.
LEFT_CREDITS = 400
LEFT_FOOD = 1
LEFT_MISSILES = 3
LEFT_LASER = 'pulse'
LEFT_FUEL = 7.0

_MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')


def new_record():
    return {
        'skills': {s: None for s in SKILLS}, 'assessment': 0, 'check': None, 'last_attempt': None,
        'passed': False, 'number': None, 'issued': None, 'stars': None, 'public': dict(DEFAULT_PUBLIC),
        'lesson': None, 'departed': False, 'note_pending': False, 'rescues': 0,
    }


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def valid_record(value):
    """True only for a well-formed record: exact key sets and right types. Guards save loading."""
    if not isinstance(value, dict) or set(value) != set(RECORD_KEYS):
        return False
    sk = value['skills']
    if not isinstance(sk, dict) or set(sk) != set(SKILLS):
        return False
    for v in sk.values():
        if v is None:
            continue
        if not (isinstance(v, dict) and set(v) == {'at', 'place'} and _num(v['at']) and isinstance(v['place'], str)):
            return False
    if not _int(value['assessment']) or not _int(value['rescues']):
        return False
    ck = value['check']
    if ck is not None:
        if not (isinstance(ck, dict) and set(ck) == {'best', 'at', 'parts'} and _int(ck['best']) and _num(ck['at'])):
            return False
        p = ck['parts']
        if not (isinstance(p, dict) and set(p) == set(CHECK_PARTS) and all(_int(x) for x in p.values())):
            return False
    if value['last_attempt'] is not None and not _num(value['last_attempt']):
        return False
    for k in ('passed', 'departed', 'note_pending'):
        if not isinstance(value[k], bool):
            return False
    if value['number'] is not None and not isinstance(value['number'], str):
        return False
    if value['issued'] is not None and not _num(value['issued']):
        return False
    if value['stars'] is not None and not _int(value['stars']):
        return False
    pub = value['public']
    if not (isinstance(pub, dict) and set(pub) == set(PUBLIC_FIELDS) and all(isinstance(x, bool) for x in pub.values())):
        return False
    if value['lesson'] is not None and value['lesson'] not in SKILLS:
        return False
    return True


def record_skill(record, skill, when, place):
    """Log a skill the first time only. Returns True if newly recorded."""
    if skill not in SKILLS or record['passed'] or record['skills'].get(skill) is not None:
        return False
    record['skills'][skill] = {'at': when, 'place': place}
    record['assessment'] += SKILL_POINTS
    return True


def can_book(record, now):
    if record['passed']:
        return False, 'You already hold the licence.'
    for s in SKILLS:
        if record['skills'].get(s) is None:
            return False, 'Logbook incomplete: %s.' % SKILL_NAMES[s]
    last = record['last_attempt']
    if last is not None and now - last < RETAKE_SECONDS:
        return False, 'Wait %d seconds before another check flight.' % int(RETAKE_SECONDS - (now - last) + 0.999)
    return True, ''


def finish_check(record, parts, now):
    """Store a check-flight attempt (best total kept). Returns True when the licence is earned."""
    if record['passed']:
        return True
    total = sum(max(0, min(PART_MAX, int(parts.get(p, 0)))) for p in CHECK_PARTS)
    best = record['check']['best'] if record['check'] else -1
    if total > best:
        record['check'] = {'best': total, 'at': now,
                           'parts': {p: max(0, min(PART_MAX, int(parts.get(p, 0)))) for p in CHECK_PARTS}}
    record['last_attempt'] = now
    if len(SKILLS) * SKILL_POINTS + record['check']['best'] >= PASS_MARK:
        record['passed'] = True
    return record['passed']


def sta_date(t):
    g = time.gmtime(t)
    return '%d %s %d' % (g.tm_mday, _MONTHS[g.tm_mon - 1], g.tm_year + STA_YEAR_OFFSET)


def expires(t):
    g = time.gmtime(t)
    year = g.tm_year + STA_YEAR_OFFSET + 5
    day = g.tm_mday
    if g.tm_mon == 2 and day == 29 and not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        day = 28
    return '%d %s %d' % (day, _MONTHS[g.tm_mon - 1], year)


def stars(trips, bounties, rescues, offences, fined):
    n = 1 + min(2, trips // 20) + min(1, bounties // 10) + min(1, rescues // 5) - min(2, offences) - (1 if fined else 0)
    return max(0, min(5, n))


def profile_url(number):
    return f'https://riftdogs.com/pilot/{number}'


def departure(save_fields):
    """Herbert's departure: the fields to set so the pilot keeps only the basics, and what was taken."""
    n = len(save_fields.get('cargo', ()))
    paid = len(save_fields.get('cargo_paid', ()))
    held = (save_fields.get('credits', 0) + save_fields.get('bank_balance', 0) + save_fields.get('crymto', 0))
    cargo = [0] * n
    if n:
        cargo[0] = LEFT_FOOD
    return {
        'fields': {
            'credits': LEFT_CREDITS, 'bank_balance': 0, 'crymto': 0, 'cargo': cargo, 'cargo_paid': [0] * paid,
            'equipment': [], 'missiles': LEFT_MISSILES, 'laser': LEFT_LASER, 'rear_laser': LEFT_LASER,
            'mines': 0, 'fuel': LEFT_FUEL,
        },
        'taken': max(0, int(held - LEFT_CREDITS)),
    }
