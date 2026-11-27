"""Herbert, the old hauler who calls every brand-new commander and talks them through one trade trip.

Pure module: no SDL, no game import. The game builds a small context dict, reports events, and shows whatever
lines come back through the communicator. Herbert only ever talks: nothing here touches credits, cargo, fuel or
equipment.

A trip is docking at a station in a different system from the one last left. The guided trip is trip 1; he stays
on call for trips 2 and 3 and signs off on docking at the end of trip 3, whether or not he was waved off.
"""
import random

STEPS = ('buy', 'launch', 'course', 'jump', 'clearance', 'dock', 'sell')
CALL_DELAY = 4.0      # seconds after the new-commander intro closes before he calls
IDLE_NUDGE = 90.0     # seconds on one guided step before his single nudge
ON_CALL_TRIPS = 3     # he signs off on docking at the end of this trip
RESUME_DELAY = 3.0   # seconds after loading a game mid-trip before he repeats the current step
LOW_FUEL = 1.0        # units in the tank (of 8; 2,500 L a unit) he calls low even without a course set

STAGES = ('waiting', 'offered', 'guiding', 'on_call', 'gone')
EVENTS = ('bought', 'launched', 'course', 'jumped', 'clearance', 'docked', 'sold')
STATE_KEYS = ('stage', 'step', 'trips', 'last_left', 'waved_off', 'plan', 'last_line', 'idle', 'nudged', 'since_intro')
OPTIONAL_KEYS = ('alpha_said',)   # set once the pilot has been told about the alpha test (now by Ada Morrow); older saves lack it

CALL_LINE = "Ah. Fresh meat. Herbert's the name: forty years hauling freight, thirty-eight of them legally. Want me to show you how it's done?"
END_LINE = "That's the job. Now do it again without me. I'll be on the radio if you get stuck."
GOODBYE_LINE = "Clear skies, full holds. You're on your own now, rookie."

# Placeholders: {good} and {port} are the planned good and port, {here} the system just docked at,
# {profit} and {loss} whole credits. Docked lines fit the panel; a line under a FLIGHT_KEYS key fits the card.
LINES = {
    'call': (CALL_LINE,),
    'trip_done': (END_LINE,),
    # Said straight after the offer is answered, as its own line, so a new pilot knows where he lives.
    'call_hint': (
        "I'm on comms, 5, flying or docked. Ctrl+H if you want me sooner.",
        "You'll find me on comms: press 5. Ctrl+H and I'll say it again.",
    ),
    'goodbye': (GOODBYE_LINE,),
    # Turning the guided trip down, and being asked again later.
    'decline': (
        "Suit yourself. Most people learn the expensive way.",
        "Fair enough. I taught myself too. Took me three ships.",
    ),
    'reoffer': (
        "Changed your mind? Want me to show you the ropes?",
        "Back again? Shall I talk you through a trip this time?",
    ),
    'reoffer_later': (
        "Not mid-flight. Call me once you're docked and I'll show you the ropes.",
        "Can't teach you out here. Ask again once you're docked.",
    ),

    # The guided trip, one instruction per step.
    'step_buy': (
        "Now, the reason we're all here. Money. {port} pays well for {good}: pick it with UP/DOWN or a click, "
        "and B buys a tonne.",
        "Buy where it's plentiful, sell where it isn't. {good} for {port}: UP/DOWN or a click to pick it, "
        "B buys a tonne a press.",
    ),
    'step_buy_poor': (
        "Slim pickings today. Best I can find is {good} for {port}, and it's thin. UP/DOWN or a click to pick it, "
        "B buys a tonne.",
        "Nothing here pays much. {good} to {port} will do, just. Pick it with UP/DOWN or a click; B buys a tonne.",
    ),
    'step_buy_broke': (
        "Hard to buy cargo with no credits. Press 3 for Money: J finds you a station job. We'll shop after.",
        "Empty wallet. Happens to the best of us; happened to me twice. 3 for Money, J for a station job, then we shop.",
    ),
    'step_launch': (
        "Right. L asks control to let you out. Wait for the nod, then L again. Keep the pointy end away from "
        "anything expensive.",
        "Time to go. L for clearance, wait for it, then L again. Take your time. Space isn't going anywhere.",
    ),
    'step_course': (
        "1 for the chart. Find {port} and lock it with Enter. Check you've the fuel first.",
        "Chart's on 1. Click {port}, or Enter, to lock the course. Mind the fuel figure.",
    ),
    'step_jump': (
        "W for thrust, out past 5 km. Then hold H through the countdown. Let go and it stops.",
        "Gently, now. W, out past 5 km from the station. Then hold H for the jump.",
    ),
    'step_clearance': (
        "There's the station. Y for guidance. Inside 2.5 km on the Docking page, R for clearance.",
        "Y for guidance; you work the throttle. Under 2.5 km on the Docking page, R for clearance.",
    ),
    'step_dock': (
        "Line up: within 14 m across, 6 m up or down, roll within 14 degrees, under 25. Small corrections.",
        "Steady, rookie. 14 m across, 6 m up or down, under 25. Clearance lasts 120 s; R again if it lapses.",
    ),
    'step_sell': (
        "Here's the good bit. Pick your cargo with UP/DOWN, then S sells a tonne at a time.",
        "Right. S sells a tonne at a time; keep at it till the hold's empty and we'll see what you made.",
    ),

    # His reaction when a step is done, before the next instruction.
    'done_buy': (
        "Cargo aboard. Don't spend every credit, mind: a full hold and an empty tank is just a very expensive "
        "warehouse.",
        "Lovely. Now let's find someone who wants all that rubbish.",
    ),
    'done_launch': (
        "Out, and nothing scraped. Not entirely incompetent.",
        "Clear of the station. Almost looks like you've done this before.",
    ),
    'done_course': (
        "Course plotted. Lovely.",
        "Course plotted. You're now marginally more useful than the ship's previous owner.",
    ),
    'done_jump': (
        "And here we are. Still in one piece, too.",
        "Jump done. Stomach still where you left it?",
    ),
    'done_clearance': (
        "They'll have you. Any disagreement between your ship and the station will be settled in the station's "
        "favour.",
        "Cleared. The station isn't going to move out of your way.",
    ),
    'done_dock': (
        "Well, we're inside, and the ship is broadly the same shape as when we started. I'll take that.",
        "Very tidy. Don't make a habit of showing off.",
    ),
    'launched_empty': (
        "Empty hold? We're running a freight business, not a sightseeing service. Still, I'll show you the way.",
        "Nothing in the hold. Flying for the view, then. Fine, carry on.",
    ),
    'came_back': (
        "Back home already? Forget your sandwiches? Launch again when you're ready.",
        "Same station you left. That's not a trip, that's a lap. Off you go again.",
    ),
    'left_unsold': (
        "Leaving with it all still aboard? Your cargo, your call. Find a port that pays better.",
        "Not selling here, then. Somewhere else had better want it.",
    ),
    'pick_up': (
        "Ah. Still alive, then? We'll carry on from where you are.",
        "Right, where were we. New start, same job.",
    ),
    'dock_elsewhere': (
        "{here}? Not where I said, but it's a port. Sell what you've got.",
        "{here}. Not the port I had in mind. Never mind, they've got a market.",
    ),
    'nothing_to_sell': (
        "{here}, with an empty hold. Sightseeing. Still counts as a trip, I suppose.",
        "Made {here} with nothing to sell. You can fly, anyway. That's half of it.",
    ),
    'profit': (
        "Look at that. Actual profit: {profit} cr. Don't get excited, there's still maintenance to pay.",
        "{profit} cr to the good. I'd have been pleased with that myself.",
    ),
    'loss': (
        "Down {loss} cr. You've effectively paid someone to take your money. Check what it fetches before you buy.",
        "Lost {loss} cr on that. Everyone does it once. Twice and I start worrying.",
    ),
    'even': (
        "Broke even. Could be worse. Could be dead.",
        "Not a credit made. Still, the ship's in one piece, and so are you.",
    ),
    'nudge': (
        "Take your time. Space isn't going anywhere. Ctrl+H if you're stuck.",
        "Waiting for a favourable wind, rookie? Here it is again, and Ctrl+H any time.",
        "Still on this bit? No shame in that. Ctrl+H if you're stuck; I'm not going anywhere.",
    ),
    'wave_off': (
        "Suit yourself. 5 for comms if it goes wrong. When it goes wrong.",
        "Know what you're doing? Lovely. I'm on comms, 5, for when you don't.",
    ),

    # "Call Herbert" answers, by situation.
    'call_attack': (
        "Less talking. More flying. SPACE for lasers, or brake hard and let him overshoot.",
        "Fight or run, don't dither. SPACE fires, M sends a missile. A dead hero earns nothing.",
    ),
    'call_fuel': (
        "Not enough fuel for that. Pick a nearer port and refuel there: 2, then F. Don't run dry.",
        "Running dry is slow and boring. Make for a port you can reach and refuel: 2, F.",
    ),
    'call_fuel_docked': (
        "Have you considered putting some fuel in your spaceship? 2 for VMS, then F.",
        "Tank's low. 2 for VMS, F fills her up. I once waited three days for a tug. They charged me for the "
        "sandwiches.",
    ),
    'call_buy_plan': (
        "Buy where it's plentiful, sell where it isn't. {good} to {port} looks decent today. B buys.",
        "Try {good}. Cheap here, and {port} pays better. B to buy, then off you go.",
    ),
    'call_buy': (
        "Empty hold earns nothing. B buys. Look for something cheap here that sells dear next door.",
        "Buy low here, sell high elsewhere. B buys. Food to an industrial world rarely goes wrong.",
    ),
    'call_cargo': (
        "You've cargo aboard. If it pays better here, S sells. If not, L, and take it somewhere that does.",
        "Turn a profit, not a statement. S sells if the price is right; otherwise L and find a better market.",
    ),
    'call_lost': (
        "Lost? 1 for the chart. Pick a port, Enter locks it, then hold H.",
        "No course set. 1 opens the chart. Pick somewhere and lock it in, rookie.",
    ),
    'call_course': (
        "Course is set. Hold H to jump. At the far end, Y for guidance, then R inside 2.5 km.",
        "You know where you're going. Hold H to jump; there, Y for guidance and R once inside 2.5 km.",
    ),
    'clearance_now': (
        "Inside 2.5 km. Ask nicely now: R for clearance. You'll have 120 seconds.",
        "Close enough. R for clearance, and mind the clock: 120 seconds to get in.",
    ),
}

FACES = ('smiling', 'speaking', 'amused', 'serious', 'thinking')
FACE_OF = {}
for _face, _keys in (
        ('smiling', 'call reoffer trip_done goodbye profit'),
        ('speaking', 'call_hint step_buy step_launch step_course step_jump step_clearance step_dock step_sell pick_up '
                     'nudge reoffer_later call_lost call_course clearance_now'),
        ('amused', 'done_buy done_launch done_course done_jump done_clearance done_dock launched_empty came_back '
                   'nothing_to_sell even wave_off decline'),
        ('serious', 'step_buy_broke left_unsold loss call_attack call_fuel call_fuel_docked'),
        ('thinking', 'step_buy_poor dock_elsewhere call_buy_plan call_buy call_cargo')):
    for _key in _keys.split(): FACE_OF[_key] = _face

# Keys whose line can be the last of a batch said in flight (the card shows the last line).
FLIGHT_KEYS = ('call_hint', 'wave_off', 'decline', 'reoffer_later', 'step_course', 'step_jump', 'step_clearance',
               'step_dock', 'call_attack', 'call_fuel', 'call_lost', 'call_course', 'clearance_now')


# The note he leaves once the licence is issued: one page of his docked panel a line, shown in order.
NOTE_FACE = 'amused'
NOTE_LINES = (
    "Well, rookie. The STA has made it official: you're a licensed Trade Dog. Varga doesn't sign many, so I'd "
    "frame it. I'd have said this in person, but you know me and goodbyes.",
    "Training's never free, and I've settled my account for yours. Call it my fee. Forty years in this trade "
    "teaches a man to collect, and I was always thorough with the paperwork.",
    "I've left you what a pilot needs to start: the basic ship, 400 credits, a tonne of food in the hold and a "
    "full tank. Same as I started with. More, frankly.",
    "You're on your own now. If you've questions, you can always send me a message. "
    "Clear skies, full holds. Herbert.",
)


class Said(str):
    """A line he said: the text, plus which line it was and the face he wore saying it."""
    key = face = None


# His four short lessons, asked for from the licence screen: (intro, step lines..., done line). Said together
# (the docked panel holds them all; the flight card shows the last), so the step (its last) stands on its own.
LESSONS = {
    'combat': ("Pirates turn up in flight, when you've something worth having. A bounty is 35 cr a head.",
               "SPACE fires the lasers, M a missile if you've bought one. Nose on him, trigger down.",
               "Well fought. I'd have done it quicker, but I'd have been younger."),
    'scooping': ("The ECS is 480 cr at outfitting (U on the VMS screen): ore, canisters, even the sun.",
                 "Under 50, ore within 260 m: the ECS draws it in. Asteroid Energy Weapon, 700 cr: optional.",
                 "Ore in the hold. An honest living, rocks, if not a quick one."),
    'dsc': ("A DSC comms console is 450 cr at outfitting, yard grade 3 and up. Somebody's always worse off.",
            "Fitted, alerts show on the Distress tab: Ctrl+5 for the comms page. Acknowledge one to track it.",
            "There, you heard one. Whether you go is your own business."),
    'rescue': ("A disabled ship shows as a gold contact. Close within 1,500 m and press N to hail it.",
               "To repair: within 350 m, under 30 speed, select it (5), then 8 and H. R is for your own ship.",
               "Another ship still flying. Do try to remember who fixed it."),
}
LESSON_FACES = ('serious', 'speaking', 'amused')   # intro, step, done


def lesson_lines(skill, step=None):
    """His lesson for a skill: step None is the whole lesson (intro and steps); 0 is the intro; len-1 the done line
    (so step -1 is it too). Each line is a Said carrying its face. Unknown skill: nothing."""
    parts = LESSONS.get(skill)
    if not parts: return []
    picks = parts[:-1] if step is None else [parts[step]]
    said = []
    faces = LESSON_FACES if step is None else (LESSON_FACES[step],)
    for text, face in zip(picks, faces):
        line = Said(text)
        line.key, line.face = 'lesson_'+skill, face
        said.append(line)
    return said


# What he says when the game hasn't told him a name.
DEFAULT_NAMES = {'good': 'something cheap', 'port': 'a port nearby', 'here': 'This place', 'profit': '0', 'loss': '0'}


def new_state():
    return {'stage': 'waiting', 'step': 0, 'trips': 0, 'last_left': None, 'waved_off': False,
            'plan': None, 'last_line': None, 'idle': 0.0, 'nudged': False, 'since_intro': None}


def alpha_due(state):
    """Ada Morrow's alpha notice is owed: the guided trip is finished and the pilot has not been told yet."""
    return state['step'] >= len(STEPS) and state['stage'] in ('on_call', 'gone') and not state.get('alpha_said')


def retired_state():
    state = new_state()
    state['stage'] = 'gone'
    return state


def _int(v): return isinstance(v, int) and not isinstance(v, bool)
def _num(v): return isinstance(v, (int, float)) and not isinstance(v, bool)


def valid_state(value):
    """True for a dict with exactly Herbert's keys and sane types (used when loading a save)."""
    if not isinstance(value, dict) or not set(STATE_KEYS) <= set(value) <= set(STATE_KEYS+OPTIONAL_KEYS): return False
    v = value
    plan = v['plan']
    return (v['stage'] in STAGES
            and _int(v['step']) and 0 <= v['step'] <= len(STEPS)
            and _int(v['trips']) and v['trips'] >= 0
            and (v['last_left'] is None or _int(v['last_left']))
            and isinstance(v['waved_off'], bool)
            and (plan is None or (isinstance(plan, dict) and set(plan) in ({'good', 'system'}, {'good', 'system', 'pays'})
                                  and isinstance(plan['good'], str) and _int(plan['system'])
                                  and isinstance(plan.get('pays', True), bool)))
            and (v['last_line'] is None or isinstance(v['last_line'], str))
            and _num(v['idle']) and v['idle'] >= 0
            and isinstance(v['nudged'], bool)
            and isinstance(v.get('alpha_said', False), bool)
            and (v['since_intro'] is None or (_num(v['since_intro']) and v['since_intro'] >= 0)))


def say(key, state, **names):
    """One of LINES[key], filled in, never the same as the last line he said (when there is a choice)."""
    names = {**DEFAULT_NAMES, **{k: v for k, v in names.items() if v}}
    filled = [line.format(**names) for line in LINES[key]]
    fresh = [line for line in filled if line != state.get('last_line')] or filled
    line = random.choice(fresh)
    state['last_line'] = line
    said = Said(line)
    said.key, said.face = key, FACE_OF[key]
    return said


def pick_trade(here, goods, buy_price, sell_price, reachable, credits, capacity, food_good, industrial):
    """The first trade to suggest: the most profit on the whole trip, sold elsewhere.

    A good scores its margin a tonne times the tonnes the player can carry: the free hold (`capacity`) or what the
    credits buy, whichever is less. Ties go to the nearer system (earlier in `reachable`). With nothing profitable,
    food to the first reachable industrial port (else the first reachable port), with margin None.
    """
    best, best_score = None, 0
    for system in reachable:
        if system == here: continue
        for good in goods:
            buy = buy_price(good)
            if buy is None or buy <= 0: continue
            tonnes = min(capacity, int(credits // buy))
            if tonnes < 1: continue
            sell = sell_price(system, good)
            if sell is None: continue
            margin = sell-buy
            if margin > 0 and margin*tonnes > best_score:
                best, best_score = {'good': good, 'system': system, 'margin': margin}, margin*tonnes
    if best: return best
    away = [s for s in reachable if s != here] or list(reachable) or [here]
    ports = [s for s in away if s in industrial] or away
    return {'good': food_good, 'system': ports[0], 'margin': None}


class Tutor:
    """Herbert's behaviour over a state dict, which it changes in place (the pilot's save holds the same dict)."""

    def __init__(self, state):
        self.state = state

    # -- helpers ---------------------------------------------------------------------------------------------

    def _say(self, key, ctx=None, **extra):
        ctx = ctx or {}
        return say(key, self.state, good=ctx.get('plan_good_name'), port=ctx.get('plan_system_name'),
                   here=ctx.get('system_name'), **extra)

    def _pays(self):
        """False only when the plan is the fallback because nothing paid (plans saved without the flag pay)."""
        plan = self.state['plan']
        return plan is None or plan.get('pays', True)

    def _instruction(self, ctx):
        step = self.state['step']
        if step >= len(STEPS): return []
        key = 'step_'+STEPS[step]
        if key == 'step_buy' and ctx.get('can_afford') is False: key = 'step_buy_broke'   # no tonne of anything
        elif key == 'step_buy' and not self._pays(): key = 'step_buy_poor'
        return [self._say(key, ctx)]

    def _done(self, step, event, ctx):
        """Whether a step still to come is already done, judged from the game as it is now and this event."""
        if step == 'buy': return ctx.get('cargo', 0) > 0 or not ctx.get('docked')    # can't buy once out
        if step == 'launch': return not ctx.get('docked')
        if step == 'course': return bool(ctx.get('course_set')) or event in ('course', 'jumped')
        if step == 'jump': return event == 'jumped'
        if step == 'clearance': return event == 'clearance'
        return False

    def _settle(self, event, ctx):
        """Move to the first step not yet done (dock and sell are moved by their own events).

        A later step done early isn't a reason to skip the ones before it: a course locked while docked counts
        once the player has bought and launched, because the course is still set then."""
        state = self.state
        new = state['step']
        while new < STEPS.index('dock') and self._done(STEPS[new], event, ctx): new += 1
        self._move(new)

    def _move(self, step):
        if step != self.state['step']:
            self.state['idle'], self.state['nudged'] = 0.0, False
        self.state['step'] = step

    def _trip_end(self, ctx):
        """His sign-off for a finished guided trip. The word about the alpha test follows from Ada Morrow (alpha_due)."""
        return [self._say('trip_done', ctx)]

    def _finish_guided_trip(self):
        state = self.state
        state['stage'], state['step'] = 'on_call', len(STEPS)
        state['idle'], state['nudged'] = 0.0, False

    # -- what the game calls ---------------------------------------------------------------------------------

    def set_plan(self, trade):
        """Store a pick_trade() result as the guided trip's plan: good, destination and whether it pays at all."""
        self.state['plan'] = {'good': trade['good'], 'system': trade['system'], 'pays': trade.get('margin') is not None}

    def intro_closed(self):
        if self.state['stage'] == 'waiting' and self.state['since_intro'] is None:
            self.state['since_intro'] = 0.0

    def can_call(self):
        stage = self.state['stage']
        return stage == 'guiding' or (stage in ('offered', 'on_call') and self.state['trips'] < ON_CALL_TRIPS)

    def offering(self):
        return self.state['stage'] == 'offered'

    def _call(self, ctx):
        """He rings and offers to guide the trip; nothing is guided until the pilot accepts."""
        state = self.state
        state['stage'], state['since_intro'] = 'offered', None
        state['idle'], state['nudged'] = 0.0, False
        return [self._say('call', ctx)]

    def accept(self, ctx):
        state = self.state
        if state['stage'] != 'offered': return []
        state['stage'], state['waved_off'] = 'guiding', False
        state['idle'], state['nudged'] = 0.0, False
        self._move(0)
        self._settle(None, ctx)
        return [self._say('call_hint', ctx)]+self._instruction(ctx)

    def decline(self, ctx):
        """No to the offer: the first time, his farewell and where to find him. No to a re-offer (the pilot already
        said no or waved him off, so knows where he lives): his usual help for where they are, as a call gives."""
        state = self.state
        if state['stage'] != 'offered': return []
        again = state['waved_off']
        state['stage'], state['waved_off'] = 'on_call', True
        state['idle'], state['nudged'] = 0.0, False
        if again: return self._answer(ctx)
        return [self._say('decline', ctx), self._say('call_hint', ctx)]

    def later(self, ctx):
        """Asked for in flight while his call is counting down: call me once docked. The offer still comes there."""
        if self.state['stage'] != 'waiting' or self.state['since_intro'] is None: return []
        return [self._say('reoffer_later', ctx)]

    def ring(self, ctx):
        """Bring the call forward while its countdown runs (the pilot is leaving, or asked for him), so the first
        trip is still the guided one."""
        if self.state['stage'] != 'waiting' or self.state['since_intro'] is None: return []
        return self._call(ctx)

    def clearance_now(self, ctx):
        """Guiding at the clearance step and inside the approach corridor without clearance: ask now."""
        if self.state['stage'] != 'guiding' or STEPS[self.state['step']] != 'clearance': return []
        return [self._say('clearance_now', ctx)]

    def reminder(self, ctx):
        """The current step again (after loading a game mid-trip)."""
        return self._instruction(ctx) if self.state['stage'] == 'guiding' else []

    def tick(self, dt, ctx):
        state = self.state
        if state['stage'] == 'waiting':
            if state['since_intro'] is None: return []
            state['since_intro'] += dt
            if state['since_intro'] < CALL_DELAY: return []
            return self._call(ctx)
        if state['stage'] != 'guiding' or state['nudged']: return []
        state['idle'] += dt
        if state['idle'] < IDLE_NUDGE: return []
        state['nudged'] = True
        return [self._say('nudge', ctx)]+self._instruction(ctx)

    def event(self, name, ctx):
        """React to a game event. Trips are counted in every stage but 'gone'; lines come only while guiding,
        apart from the goodbye."""
        state = self.state
        if state['stage'] == 'gone' or name not in EVENTS: return []
        guiding = state['stage'] == 'guiding'
        before = state['step']
        lines = []

        if state['stage'] == 'offered' and name != 'docked':
            # Unanswered offer: leaving is a no; anything else says nothing.
            if name != 'launched': return []
            state['last_left'] = ctx.get('system')
            if state['waved_off']:
                # A re-offer left unanswered: back on call quietly (he said his farewell the first time).
                state['stage'] = 'on_call'
                return []
            return self.decline(ctx)

        if state['stage'] == 'waiting' and name != 'docked':
            # Before his call: only remember where the player left from, so trips count right. The call settles the steps.
            if name == 'launched': state['last_left'] = ctx.get('system')
            return []

        if name == 'launched':
            state['last_left'] = ctx.get('system')
            if before == STEPS.index('sell'):
                # Off again from the far end without selling: the cargo is still aboard, so back to setting a course.
                self._move(0)
                if guiding: lines.append(self._say('left_unsold', ctx))
            self._settle('launched', ctx)
            if guiding and before == STEPS.index('buy') and ctx.get('cargo', 0) == 0:
                lines.append(self._say('launched_empty', ctx))
            elif guiding and before <= STEPS.index('launch'):
                lines.append(self._say('done_launch', ctx))

        elif name == 'docked':
            left, state['last_left'] = state['last_left'], None
            if left is None or ctx.get('system') == left:
                # Back at the station just left (or never launched): not a trip. Pick the guidance back up from the station.
                if guiding and STEPS.index('launch') <= before < STEPS.index('sell'):
                    self._move(0)
                    self._settle(None, ctx)
                    return [self._say('came_back', ctx)]+self._instruction(ctx)
                return []
            state['trips'] += 1
            if state['trips'] >= ON_CALL_TRIPS:
                state['stage'] = 'gone'
                return [self._say('goodbye', ctx)]
            if not guiding or before >= STEPS.index('sell'): return []
            plan = state['plan']
            if ctx.get('cargo', 0) <= 0:
                # Nothing aboard to sell: the trip is flown, so the guided trip ends here rather than stalling.
                self._finish_guided_trip()
                return [self._say('nothing_to_sell', ctx)]+self._trip_end(ctx)
            self._move(STEPS.index('sell'))
            if plan is not None: elsewhere = ctx.get('system') != plan['system']
            else: elsewhere = bool(ctx.get('plan_system_name')) and ctx.get('system_name') != ctx['plan_system_name']
            if elsewhere:
                lines.append(self._say('dock_elsewhere', ctx))
            else:
                lines.append(self._say('done_dock', ctx))

        elif name == 'sold':
            if not guiding or before != STEPS.index('sell'): return []
            profit = ctx.get('profit')
            if profit is None or round(profit) == 0: remark = self._say('even', ctx)
            elif profit > 0: remark = self._say('profit', ctx, profit=f'{round(profit):,}')
            else: remark = self._say('loss', ctx, loss=f'{round(-profit):,}')
            self._finish_guided_trip()
            return [remark]+self._trip_end(ctx)

        else:
            step = {'bought': 'buy', 'course': 'course', 'jumped': 'jump', 'clearance': 'clearance'}[name]
            done = name != 'bought' or ctx.get('cargo', 0) > 0
            if done: self._settle(name, ctx)
            if guiding and done and before <= STEPS.index(step) < state['step']:
                lines.append(self._say('done_'+step, ctx))

        if not guiding: return []
        if state['step'] == before: return []
        return lines+self._instruction(ctx)

    def resync(self, ctx):
        """The game moved the pilot without a trip (a replacement ship, a salvage tow): carry the guidance on from
        where they are now. Nothing is counted. A sell step docked with cargo aboard still fits and stays."""
        state = self.state
        if state['stage'] != 'guiding' or state['step'] >= len(STEPS): return []
        before = state['step']
        if not (STEPS[before] == 'sell' and ctx.get('docked') and ctx.get('cargo', 0) > 0):
            self._move(0)
            self._settle(None, ctx)
        if state['step'] == before: return []
        return [self._say('pick_up', ctx)]+self._instruction(ctx)

    def call(self, ctx):
        """The "Call Herbert" answer for where the player is right now."""
        if not self.can_call(): return []
        state = self.state
        if state['stage'] == 'offered': return [self._say('call', ctx)]
        if state['stage'] == 'on_call' and state['waved_off']:
            if ctx.get('docked'):
                state['stage'] = 'offered'
                return [self._say('reoffer', ctx)]
            return self._answer(ctx)+[self._say('reoffer_later', ctx)]
        return self._answer(ctx)

    def _answer(self, ctx):
        fuel, needed = ctx.get('fuel', 8.0), ctx.get('fuel_needed')
        if ctx.get('under_attack'): return [self._say('call_attack', ctx)]
        if (needed is not None and fuel < needed) or fuel < LOW_FUEL:
            return [self._say('call_fuel_docked' if ctx.get('docked') else 'call_fuel', ctx)]
        if self.state['stage'] == 'guiding' and self.state['step'] < len(STEPS):
            return self._instruction(ctx)
        if ctx.get('docked'):
            if ctx.get('cargo', 0) > 0: return [self._say('call_cargo', ctx)]
            if ctx.get('can_afford') is False: return [self._say('step_buy_broke', ctx)]
            named = ctx.get('plan_good_name') and ctx.get('plan_system_name')
            key = 'call_buy_plan' if named and self._pays() else 'call_buy'
            return [self._say(key, ctx)]
        if not ctx.get('course_set'): return [self._say('call_lost', ctx)]
        return [self._say('call_course', ctx)]

    def wave_off(self):
        """Waved off ("I know what I'm doing"): guidance ends, but he stays on call and trips still count."""
        state = self.state
        if state['stage'] != 'guiding': return []
        state['stage'], state['waved_off'] = 'on_call', True
        state['idle'], state['nudged'] = 0.0, False
        return [self._say('wave_off')]
