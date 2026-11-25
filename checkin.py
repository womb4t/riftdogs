"""Check-in: every copy of the game registers with an email and checks in with the Riftdogs server.

One background thread does all the network work, so the game window never waits. The install key and the
join claim are secrets: they live only in 0600 files, and nothing here logs, prints or puts them in an error."""
import copy
import json
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from startup import DEFAULT_SERVER, config_path

EMAIL = re.compile(r'[^@\s]{1,64}@[^@\s]+\.[^@\s]+')
BAD_EMAIL = 'That email address does not look right.'
TIMEOUT = 5
MAX_REPORTS = 10
MAX_NOTICES = 100
BACKOFF_FIRST, BACKOFF_MAX = 60, 1800
BODY_BUDGET = 60000   # the server refuses check-ins over 64 KB; stay under
ACCOUNT_REFUSED = 'Could not use your account here. Type an email.'
STATE_FILE = config_path().with_name('install.json')
KEY_FILE = config_path().with_name('install.key')
_AUTO = object()


def _paths(folder):
    if folder is None: return STATE_FILE, KEY_FILE
    return Path(folder)/'install.json', Path(folder)/'install.key'


def _write(path, data):
    from save_sync import atomic
    atomic(path, data)


def default_state():
    return dict(email=None, news=False, install=None, registered=False, place=None, admitted=False,
                joined_elsewhere=False, claim=None, must_update=None, recommended=None, since=0,
                notices=[], register_error=None)


def _text(value, limit=200):
    return value if type(value) is str and value and len(value) <= limit else None


def load_state(folder=None):
    state = default_state()
    try: saved = json.loads(_paths(folder)[0].read_text(encoding='utf-8'))
    except (OSError, ValueError): return state
    if type(saved) is not dict: return state
    for key in ('email', 'install', 'claim', 'must_update', 'recommended', 'register_error'):
        if key in saved and (saved[key] is None or type(saved[key]) is str): state[key] = saved[key]
    for key in ('news', 'registered', 'admitted', 'joined_elsewhere'):
        if type(saved.get(key)) is bool: state[key] = saved[key]
    if type(saved.get('place')) is int and not isinstance(saved['place'], bool): state['place'] = saved['place']
    if type(saved.get('since')) is int and not isinstance(saved['since'], bool): state['since'] = saved['since']
    notices = [_notice(n) for n in saved.get('notices', [])] if type(saved.get('notices')) is list else []
    state['notices'] = [n for n in notices if n][-MAX_NOTICES:]
    return state


def _notice(n, read=None):
    if type(n) is not dict or type(n.get('id')) is not int or isinstance(n['id'], bool) or type(n.get('text')) is not str: return None
    created = n.get('created')
    return dict(id=n['id'], text=n['text'][:2000], important=n.get('important') is True,
                created=float(created) if type(created) in (int, float) else 0.,
                read=n.get('read') is True if read is None else read)


def save_state(state, folder=None):
    _write(_paths(folder)[0], json.dumps(state, indent=1).encode())


def read_key(folder=None):
    try: key = _paths(folder)[1].read_text().strip()
    except OSError: return None
    return key or None


def write_key(key, folder=None):
    _write(_paths(folder)[1], (key+'\n').encode())


def needs_email(state):
    return state['email'] is None


def set_email(state, email, news, account=False):
    """Store the address the player typed. With an online account a blank address is allowed: it means
    'use my account's email'."""
    email = (email or '').strip().lower()
    if not email and account: state['email'] = ''
    elif not email or len(email) > 254 or not EMAIL.fullmatch(email): raise ValueError(BAD_EMAIL)
    else: state['email'] = email
    state['news'] = bool(news)
    state['register_error'] = None


def forget_local(folder=None):
    for path in _paths(folder):
        try: path.unlink()
        except OSError: pass


def find_account(url):
    """(name, token) of this computer's online login for `url`, or None."""
    from startup import load_connection
    try:
        config = load_connection()
        if config['server'].rstrip('/') != url.rstrip('/'): return None
        token_file = Path(config['token_file']).expanduser()
        token = token_file.read_text().strip()
    except (OSError, ValueError): return None
    from save_sync import valid_token
    return (token_file.stem, token) if valid_token(token) and token_file.stem else None


class CheckinClient:
    def __init__(self, outbox, folder=None, url=DEFAULT_SERVER, interval=1800, opener=None, account=_AUTO):
        self.outbox, self.folder, self.url, self.interval = Path(outbox), folder, url.rstrip('/'), interval
        self.opener = opener
        self.find = account is _AUTO   # look again each round: a login made after registration still counts
        self.account = find_account(self.url) if self.find else account
        self.lock, self.round_lock, self.stop = threading.Lock(), threading.Lock(), threading.Event()
        self.thread = None
        self.state = load_state(folder)
        self.new_notices = []
        self.failures = 0
        self.delay = interval
        self.status = ''

    # --- threads
    def start(self):
        self.thread = threading.Thread(target=self.run, name='checkin', daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            self.check_now()
            self.stop.wait(self.delay)

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=7)

    # --- what the game reads and does
    def snapshot(self):
        with self.lock: return copy.deepcopy(self.state)

    def take_new_notices(self):
        with self.lock: got, self.new_notices = self.new_notices, []
        return copy.deepcopy(got)

    def set_email(self, email, news, account=False):
        with self.lock:
            set_email(self.state, email, news, account=account)
            save_state(self.state, self.folder)

    def edit(self, change):
        """Change the state under the lock and save it (read marks, a used claim)."""
        with self.lock:
            change(self.state)
            save_state(self.state, self.folder)

    def revive(self):
        """After a new email: start the thread again if it had stopped, or run a round now instead of waiting."""
        if self.stop.is_set():
            if self.thread: self.thread.join(timeout=7)
            self.stop.clear()
            self.failures, self.delay = 0, self.interval
            self.start()
        elif self.thread and self.thread.is_alive():
            threading.Thread(target=self.check_now, name='checkin-now', daemon=True).start()

    def forget(self):
        with self.round_lock:   # a check-in round cannot straddle the forget: a round already running finishes first, and its result is wiped
            key, confirmed = read_key(self.folder), True
            if self.state['registered'] and key:
                try: confirmed = self._post('/v1/install/forget', None, key)[0] == 200
                except Exception: confirmed = False
            with self.lock:
                forget_local(self.folder)
                self.state = default_state()
            return confirmed

    # --- network
    def _post(self, path, body, key=None):
        from save_sync import NoRedirect, check_server, canonical, version_headers
        headers = {'Content-Type': 'application/json', **version_headers()}
        if key: headers['Authorization'] = 'Bearer '+key
        try: url = check_server(self.url, allow_lan=True)
        except ValueError: raise OSError('bad server address') from None
        request = urllib.request.Request(url+path, data=canonical(body) if body is not None else b'', method='POST', headers=headers)
        opener = self.opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=TIMEOUT) as response: return 200, self._json(response)
        except urllib.error.HTTPError as error:
            try: return error.code, self._json(error)
            finally: error.close()

    @staticmethod
    def _json(response):
        try: data = json.loads(response.read(262144))
        except (ValueError, OSError): return None
        return data if type(data) is dict else None

    def _version(self):
        try: from riftdogs import VERSION
        except Exception: return '0'
        return VERSION

    # --- one round
    def _fail(self, status):
        self.failures += 1
        self.delay = min(BACKOFF_MAX, BACKOFF_FIRST*2**(self.failures-1))
        self.status = status
        return False

    def _ok(self):
        self.failures, self.delay, self.status = 0, self.interval, ''
        return True

    def check_now(self):
        with self.round_lock:
            if self.stop.is_set(): return False
            try:
                with self.lock: state = copy.deepcopy(self.state)
                if not state['registered']:
                    if needs_email(state): return False   # waits for the email screen
                    if not self._register(state): return False
                    with self.lock: state = copy.deepcopy(self.state)
                return self._checkin(state)
            except Exception:   # a network library error must never end the thread; it is just a failed round
                return self._fail('Cannot reach the server. Trying again later.')

    def _register(self, state):
        body = dict(news=state['news'], privacy=True, version=self._version(), platform=sys.platform)
        if state['email']: body['email'] = state['email']
        if self.account: body['account'] = dict(name=self.account[0], token=self.account[1])
        try: status, data = self._post('/v1/install', body)
        except OSError: return self._fail('Cannot reach the server. Trying again later.') and False
        if status in (200, 201) and (data is None or not (_text(data.get('key'), 500) and _text(data.get('install'), 100))):
            return self._fail('The server sent an unexpected reply. Trying again later.')
        data = data or {}
        if status in (200, 201) and _text(data.get('key'), 500) and _text(data.get('install'), 100):
            write_key(data['key'], self.folder)
            with self.lock:
                self.state.update(install=data['install'], registered=True, register_error=None)
                save_state(self.state, self.folder)
            return True
        if status == 404:
            self.delay, self.status = self.interval, ''
            return False
        if status not in (400, 401): return self._fail('The server is busy. Trying again later.')
        message = _text(data.get('error')) if status == 400 else ACCOUNT_REFUSED
        with self.lock:   # refused: show why, reopen the email screen, and wait for a new answer
            self.state.update(email=None, register_error=message or 'Registration was not accepted. Check your email and try again.')
            save_state(self.state, self.folder)
        self.delay, self.status = self.interval, ''
        return False

    def _read_outbox(self):
        try: paths = sorted(self.outbox.glob('*.json'), key=lambda p: p.stat().st_mtime)
        except OSError: return []
        entries, used = [], 0
        for path in paths:
            if len(entries) >= MAX_REPORTS: break
            try:
                if path.stat().st_size > BODY_BUDGET:   # could never fit in one check-in
                    self._set_aside(path, '.rejected'); continue
                entry = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError): entry = None
            if type(entry) is not dict or type(entry.get('id')) is not str or not entry['id']:
                self._set_aside(path, '.unreadable' if entry is None else '.rejected')
                continue
            size = len(json.dumps(entry)) + 1
            if size > BODY_BUDGET - 1000:   # alone it would not fit with the rest of the request
                self._set_aside(path, '.rejected'); continue
            if used + size > BODY_BUDGET - 1000: break   # the rest go next round
            used += size
            entries.append((path, entry))
        return entries

    @staticmethod
    def _set_aside(path, suffix):
        try: path.rename(path.with_suffix(suffix))
        except OSError: pass

    def _checkin(self, state):
        key = read_key(self.folder)
        if not key:
            forget_local(self.folder)
            with self.lock: self.state = default_state()
            return False
        entries = self._read_outbox()
        body = dict(version=self._version(), platform=sys.platform, since=state['since'], reports=[e for _, e in entries])
        if self.find: self.account = find_account(self.url)
        if self.account: body['account'] = dict(name=self.account[0], token=self.account[1])   # links the install to it
        status, data = self._post('/v1/checkin', body, key)
        if status == 401:
            forget_local(self.folder)
            with self.lock: self.state = default_state()
            self.stop.set()
            return False
        if status == 404:
            self.delay, self.status = self.interval, ''
            return False
        if status != 200: return self._fail('The server is busy. Trying again later.')
        if data is None: return self._fail('The server sent an unexpected reply. Trying again later.')
        received = {i for i in data.get('received', []) if type(i) is str} if type(data.get('received')) is list else set()
        rejected = {i for i in data.get('rejected', []) if type(i) is str} if type(data.get('rejected')) is list else set()
        for path, entry in entries:
            if entry['id'] in received:
                try: path.unlink()
                except OSError: pass
            elif entry['id'] in rejected: self._set_aside(path, '.rejected')
        self._merge(data)
        return self._ok()

    def _merge(self, data):
        with self.lock:
            s = self.state
            if 'place' in data:
                place = data['place']
                s['place'] = place if type(place) is int and not isinstance(place, bool) else None
            for key in ('admitted', 'joined_elsewhere'):
                if key in data: s[key] = data[key] is True
            for key in ('must_update', 'recommended'):
                if key in data: s[key] = _text(data[key], 500)
            if _text(data.get('claim'), 500): s['claim'] = data['claim']   # the server sends a fresh one each check-in
            if not s['admitted'] or s['joined_elsewhere'] or data.get('joined') is True: s['claim'] = None   # a held claim goes only when it is no use
            have = {n['id'] for n in s['notices']}
            for raw in data.get('notices', []) if type(data.get('notices')) is list else []:
                n = _notice(raw, read=False)
                if n is None or n['id'] in have or n['id'] <= s['since']: continue
                have.add(n['id'])
                s['notices'].append(n); self.new_notices.append(n)
                s['since'] = max(s['since'], n['id'])
            s['notices'] = s['notices'][-MAX_NOTICES:]
            save_state(s, self.folder)


JOIN_FAILED = 'Could not join the galaxy right now. Try again later.'


def join_galaxy(claim, name, opener=None):
    """Swap the claim for an account at the Riftdogs server: (name, token). ValueError holds the server's words when
    it refuses the name; any other failure is a plain OSError. The claim never appears in an error."""
    from save_sync import NoRedirect, check_server, canonical, version_headers, valid_token
    try: url = check_server(DEFAULT_SERVER, allow_lan=True)
    except ValueError: raise OSError(JOIN_FAILED) from None
    request = urllib.request.Request(url+'/v1/join', data=canonical(dict(claim=claim, name=name)), method='POST',
                                     headers={'Content-Type': 'application/json', **version_headers()})
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT) as response: status, data = 200, CheckinClient._json(response)
    except urllib.error.HTTPError as error:
        try: status, data = error.code, CheckinClient._json(error)
        finally: error.close()
    except Exception: raise OSError(JOIN_FAILED) from None
    if status in (400, 409):
        raise ValueError(_text(data.get('error') if data else None) or 'That name was not accepted. Try another.')
    if status == 403: raise OSError(_text(data.get('error') if data else None) or JOIN_FAILED)   # e.g. the server is full
    player, token = (data.get('player'), data.get('token')) if data else (None, None)
    if status in (200, 201) and type(player) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,32}', player) and valid_token(token):
        return player, token
    raise OSError(JOIN_FAILED)
