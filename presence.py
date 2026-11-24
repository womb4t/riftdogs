"""First shared-universe test stage: authenticated live player presence, not PvP authority."""
import math
import threading
import time
import uuid


MAX_LISTED = 64
HISTORY_KEEP = 300.


class PresenceBusy(RuntimeError): pass


class SharedPresence:
    def __init__(self):
        self.lock = threading.Lock()
        self.players = {}
        self.docked = {}   # {player_id: {system: last seen docked}}, outlives the 10 s roster
        self.flying = {}

    def exchange(self, player_id, name, data):
        if type(data) is not dict: raise ValueError('Presence object required')
        system,mode = data.get('system'),data.get('mode')
        session,sequence,epoch = data.get('session'),data.get('sequence'),data.get('epoch')
        if type(system) is not int or not 0 <= system < 8: raise ValueError('Unknown system')
        if mode not in ('flight','docked','transit','deep-space','destroyed'): raise ValueError('Unknown mode')
        if any(type(v) is not str or len(v) != 32 or any(c not in '0123456789abcdef' for c in v) for v in (session,epoch)): raise ValueError('Invalid session')
        if type(sequence) is not int or sequence < 0: raise ValueError('Invalid sequence')
        position,velocity = data.get('position'),data.get('velocity')
        for vector,limit in ((position,1000000),(velocity,400)):
            if type(vector) is not list or len(vector) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector): raise ValueError('Invalid vector')
            if math.sqrt(sum(v*v for v in vector)) > limit: raise ValueError('Vector outside testing limits')
        now = time.monotonic()
        with self.lock:
            old = self.players.get(player_id)
            if old and now-old['seen'] < 10:
                if old['session'] != session: raise PresenceBusy('This player is already online on another computer')
                if sequence <= old['sequence']: raise ValueError('Out of order update')
                if old['system'] == system and old['epoch'] == epoch and old['mode'] == mode == 'flight':
                    maximum = (now-old['seen'])*400+100
                    if math.dist(position,old['position']) > maximum: raise ValueError('Movement update too large')
            self.players[player_id] = dict(id=player_id,name=name,system=system,mode=mode,
                position=list(position),velocity=list(velocity) if mode == 'flight' else [0.,0.,0.],
                session=session,sequence=sequence,epoch=epoch,seen=now)
            self.players = {key:value for key,value in self.players.items() if now-value['seen'] < 10}
            if mode in ('docked','flight'): (self.docked if mode == 'docked' else self.flying).setdefault(player_id,{})[system] = now
            for history in (self.docked,self.flying):
                for pid in list(history):
                    history[pid] = {s:t for s,t in history[pid].items() if now-t < HISTORY_KEEP}
                    if not history[pid]: del history[pid]
            public = []
            for player in list(self.players.values())[:MAX_LISTED]:
                item = {key:player[key] for key in ('id','name','system','mode','position','velocity')}
                age = min(.75,max(0,now-player['seen']))
                item['position'] = [p+v*age for p,v in zip(player['position'],player['velocity'])]
                public.append(item)
            return dict(protocol=1,you=player_id,players=public)

    def forget(self, player_id):
        """A deleted account leaves the roster and its docking history at once."""
        with self.lock:
            for book in (self.players,self.docked,self.flying): book.pop(player_id,None)

    def _recent(self, history, player_id, system, window):
        with self.lock:
            seen = history.get(player_id,{}).get(system)
            return seen is not None and time.monotonic()-seen <= window

    def docked_recently(self, player_id, system, window=120.):
        return self._recent(self.docked,player_id,system,window)

    def flying_recently(self, player_id, system, window=60.):
        return self._recent(self.flying,player_id,system,window)


class PresenceClient:
    def __init__(self, remote, comms=None):
        from comms import CommsLog
        self.remote = remote
        self.comms = comms if comms is not None else CommsLog()
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.snapshot = dict(players=[],you=None)
        self.status = 'Universe: connecting'
        self.pending = None
        self.condition = threading.Condition()
        self.stopping = False
        self.thread = threading.Thread(target=self.run,name='shared-presence',daemon=True)
        self.thread.start()

    def offer(self, state):
        with self.condition:
            self.pending = state
            self.condition.notify()

    def run(self):
        next_send = 0
        while True:
            with self.condition:
                while not self.stopping and (self.pending is None or time.monotonic() < next_send):
                    self.condition.wait(max(.02,next_send-time.monotonic()) if self.pending else None)
                if self.stopping: return
                state,self.pending = self.pending,None
            self.sequence += 1
            state = dict(state,session=self.session,sequence=self.sequence,comms=self.comms.payload())
            try:
                result = self.remote.request(state,endpoint='/v1/presence')
                if result.get('protocol') != 1 or type(result.get('players')) is not list or len(result['players']) > MAX_LISTED: raise ValueError('Invalid presence response')
                self.snapshot = result
                self.comms.receive(result.get('comms'))
                self.status = f'Universe: {len(result["players"])} players connected'
            except (OSError,RuntimeError,ValueError,KeyError):
                self.snapshot = dict(players=[],you=None)
                self.status = 'Universe unavailable — check server update/connection'
            if getattr(self.remote,'update_required',None): return  # the server wants a newer game; stop asking
            next_send = time.monotonic()+.25

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        self.thread.join(timeout=6)
