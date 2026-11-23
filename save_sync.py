"""Optional private progress sync; offline saves remain independent."""
import hashlib
import ipaddress
import json
import re
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class UpdateRequired(RuntimeError):
    """The server needs a newer game than this one; the message is the server's own words."""


def update_message(error):
    try: message = json.loads(error.read(4096)).get('error')
    except (ValueError,AttributeError,OSError): message = None
    return message if type(message) is str and message else 'This server needs a newer Driftdogs. Update the game.'


def version_headers():
    from driftdogs import VERSION
    return {'X-Driftdogs-Version':VERSION}


EDITED_IMPORT = "Edited saves can't be imported."


class Conflict(RuntimeError):
    pass


class Rejected(RuntimeError):
    """The server's audit refused this save; .message is the server's own explanation."""
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Refused(RuntimeError):
    """The server answered a call() with a clear refusal (not docked, bad request, too many requests...):
    nothing was settled. .message is the server's own words; .status the HTTP status (None if unknown)."""
    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a player's bearer credential to a redirect target.


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def saved_at(save):
    """When the game wrote this save; 0 for saves from before timestamps."""
    try: return float(save['_session']['saved_at'])
    except (KeyError,TypeError,ValueError): return 0.


def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(f'{path.name}.{threading.get_ident()}.tmp')  # per-thread, so the game and sync threads never share one
    temp.write_bytes(data)
    temp.chmod(0o600)
    temp.replace(path)


def check_server(url, allow_lan=False):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Server must be an http(s) origin, e.g. http://192.168.1.20:8765')
    if parsed.scheme == 'http':
        try:
            address = ipaddress.ip_address(parsed.hostname)
            permitted = address.is_loopback or (allow_lan and (address in ipaddress.ip_network('192.168.0.0/16') or address in ipaddress.ip_network('10.0.0.0/8') or address in ipaddress.ip_network('172.16.0.0/12')))
        except ValueError:
            permitted = parsed.hostname == 'localhost' or (allow_lan and parsed.hostname.endswith('.local'))
        if not permitted: raise ValueError('HTTP is limited to localhost or --allow-lan private addresses; use HTTPS elsewhere')
    return url.rstrip('/')


def reachable(url, allow_lan=False, timeout=4):
    try:
        url = check_server(url,allow_lan)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(url+'/health',timeout=timeout) as response:
            return json.loads(response.read(4096)).get('service') == 'driftdogs-saves'
    except (OSError,ValueError,AttributeError): return False


def pick_server(servers, allow_lan=False):
    """The first server that answers, in order; the first one if none do, so its error is shown."""
    servers = [s for s in servers if s]
    return next((s for s in servers if reachable(s,allow_lan)),servers[0] if servers else '')


def account_request(url, endpoint, body, method='POST', token=None, allow_lan=False):
    """One JSON request outside a game session (sign-up, invites, account settings). RuntimeError holds the
    server's own words; UpdateRequired on 426; OSError when the server can't be reached."""
    url = check_server(url,allow_lan)
    headers = {'Content-Type':'application/json',**version_headers()}
    if token is not None: headers['Authorization'] = 'Bearer '+token
    req = urllib.request.Request(url+endpoint,data=canonical(body),method=method,headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(req,timeout=8) as response: return json.loads(response.read(4096))
    except urllib.error.HTTPError as error:
        try: message = json.loads(error.read(4096)).get('error')
        except (ValueError,AttributeError,OSError): message = None
        error.close()
        if error.code == 426: raise UpdateRequired(message if type(message) is str and message else 'This server needs a newer Driftdogs. Update the game.') from None
        raise RuntimeError(message if type(message) is str else f'Server returned HTTP {error.code}') from None
    except ValueError: raise RuntimeError('The server sent an invalid reply') from None


def valid_token(token):
    return type(token) is str and 20 <= len(token) <= 200 and not any(c.isspace() for c in token)


def signup(url, name, email='', allow_lan=False):
    """Create a pilot account on the server and return its new private token."""
    data = account_request(url,'/v1/signup',dict(name=name.strip(),email=email.strip() or None),allow_lan=allow_lan)
    token = data.get('token') if type(data) is dict else None
    if not valid_token(token): raise RuntimeError('Server sent an invalid sign-up reply')
    return token


def claim_invite(url, claim, allow_lan=False):
    """Swap a single-use invite's claim for this player's login: (name, token). The claim is used up."""
    data = account_request(url,'/v1/claim',dict(claim=claim),allow_lan=allow_lan)
    name,token = (data.get('player'),data.get('token')) if type(data) is dict else (None,None)
    if type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',name) or not valid_token(token):
        raise RuntimeError('Server sent an invalid invite reply')
    return name,token


def read_token(token_file):
    token = Path(token_file).expanduser().read_text().strip()
    if not valid_token(token): raise ValueError('Invalid token file')
    return token


def remove_email(url, token_file, allow_lan=False):
    """'Remove my email': the server forgets this account's email and consent."""
    account_request(url,'/v1/account/email',dict(email=None),token=read_token(token_file),allow_lan=allow_lan)


def delete_account(url, token_file, confirm, allow_lan=False):
    """'Delete my account': `confirm` must be the commander name exactly. Cannot be undone."""
    account_request(url,'/v1/account',dict(confirm=confirm),method='DELETE',token=read_token(token_file),allow_lan=allow_lan)


def pending_payment(value, now=None):
    """A payment code create saved in sync.json, checked: dict(amount, request_id, at), or None if it is malformed,
    out of range or older than payments.EXPIRY (by then any code it made has been refunded)."""
    import payments
    now = time.time() if now is None else now
    if type(value) is not dict: return None
    amount,request_id,at = value.get('amount'),value.get('request_id'),value.get('at')
    if type(amount) is not int or not payments.MIN_AMOUNT <= amount <= payments.MAX_AMOUNT: return None
    if type(request_id) is not str or not re.fullmatch(r'[0-9a-f]{32}',request_id): return None
    if type(at) not in (int,float) or not now-payments.EXPIRY < at <= now+86400: return None
    return dict(amount=amount,request_id=request_id,at=at)


def slot_name(token):
    """The folder (under <data>/servers) holding this login's local copy of its online save."""
    return digest(('account\n'+token).encode())[:24]


class RemoteSave:
    def __init__(self, url, token_file, root, allow_lan=False):
        self.url = check_server(url,allow_lan)
        self.token = Path(token_file).read_text().strip()
        if not 20 <= len(self.token) <= 200 or any(c.isspace() for c in self.token): raise ValueError('Invalid token file')
        # The slot follows the login, not the address, so a server that changes IP keeps your progress.
        slot = slot_name(self.token)
        self.save_path = Path(root)/'servers'/slot/'save.json'
        self.meta_path = self.save_path.with_name('sync.json')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.revision = 0
        self.player_name = None
        self.status = 'Server: connecting'
        self.pending = None
        self.condition = threading.Condition()
        self.stopping = False
        self.conflicted = False
        self.update_required = None
        self.rolled_back = None       # the server's last good save, for the game to adopt after a refusal
        self.rejected_message = None
        self.refused_notice = None    # one-time text for the player when a refusal could not be rolled back
        self.thread = None
        self.uploading = False        # the sync thread has taken `pending` and its upload is in flight
        self.urgent = False           # call() wants the pending upload now, not after a retry delay
        self.calling = False          # call() is posting: the sync thread starts no upload meanwhile
        self.settle_unknown = False   # a call() had no clear answer: an upload conflict means a settlement, take it
        self.last_upload_ok = None    # the latest upload attempt reached the server (None: none yet)
        self.pending_payment = None   # dict(amount, request_id, at): a payment code create still without a clear answer
        self.meta_lock = threading.RLock()   # sync.json is written from the game, sync and payment threads
        self.market = None            # the game's MarketClient: each upload first waits for its queued trades (flush_and_wait)
        self.halted = False           # a refused first save with no server copy: no more uploads this session

    def request(self, data=None, endpoint='/v1/save', method=None):
        raw = canonical(data) if data is not None else None
        req = urllib.request.Request(self.url+endpoint,data=raw,method=method or ('PUT' if raw else 'GET'),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json',**version_headers()})
        try:
            with self.opener.open(req,timeout=5) as response:
                raw = response.read(300000)
                if len(raw) >= 300000: raise ValueError('Server response too large')
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            if error.code == 426:
                message = update_message(error); error.close()
                self.update_required = message
                self.status = message
                raise UpdateRequired(message) from None
            if error.code == 422 and endpoint == '/v1/save':
                try: message = json.loads(error.read(4096)).get('error')
                except (ValueError,AttributeError,OSError): message = None
                error.close()
                raise Rejected(message if type(message) is str and message else "The server couldn't account for this save, so it wasn't saved. Your last good save is kept.") from None
            if method == 'POST' and 400 <= error.code < 500 and error.code != 409:
                try: message = json.loads(error.read(4096)).get('error')
                except (ValueError,AttributeError,OSError): message = None
                error.close()
                raise Refused(message if type(message) is str and message else f'Server returned HTTP {error.code}',error.code) from None
            error.close()
            if error.code == 409 and method == 'POST': raise Conflict('The server save changed; resyncing.') from None
            if error.code == 409 and endpoint != '/v1/save': raise RuntimeError('This player is already online on another computer') from None
            if error.code == 409: raise Conflict('Server save changed on another computer. Local progress retained; reconnect to resolve.') from None
            if error.code == 401: raise RuntimeError('Server rejected the player token') from None
            raise RuntimeError(f'Server returned HTTP {error.code}') from None

    def metadata(self, saved_hash):
        with self.meta_lock:
            atomic(self.meta_path,canonical(self.meta(revision=self.revision,hash=saved_hash,settle_unknown=self.settle_unknown)))

    def meta(self, **fields):
        """sync.json's fields, plus the unanswered payment code create if there is one (never a code)."""
        if self.pending_payment is not None: fields['pending_payment'] = self.pending_payment
        return fields

    def set_pending_payment(self, value):
        """Remember (in sync.json too, so a restart can ask again) a create that has no clear answer yet:
        dict(amount, request_id, at), or None once the server has answered it clearly."""
        with self.meta_lock:
            self.pending_payment = value
            try:
                meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else dict(revision=self.revision,hash=None)
                meta.pop('pending_payment',None)
                if value is not None: meta['pending_payment'] = value
                atomic(self.meta_path,canonical(meta))
            except (OSError,ValueError,TypeError,AttributeError): pass

    def mark_settle_unknown(self, value=True):
        """Remember (in sync.json too, so a restart honours it) that a settlement may have happened unseen."""
        with self.meta_lock:
            self.settle_unknown = value
            try:
                meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else dict(revision=self.revision,hash=None)
                meta['settle_unknown'] = value
                atomic(self.meta_path,canonical(meta))
            except (OSError,ValueError,TypeError,AttributeError): pass

    def prepare(self, import_path=None, restore=False, offline=False):
        meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else None
        local = json.loads(self.save_path.read_text()) if self.save_path.exists() else None
        self.settle_unknown = bool(meta and meta.get('settle_unknown'))
        self.pending_payment = pending_payment(meta.get('pending_payment') if type(meta) is dict else None)
        try: remote = self.request()
        except (OSError,RuntimeError,ValueError):
            if not offline or local is None or meta is None: raise
            self.revision = meta['revision']
            self.status = 'Server: unavailable; saving locally, retrying'
            return
        self.revision = remote['revision']
        if type(remote.get('player')) is str and 0 < len(remote['player']) <= 32: self.player_name = remote['player']
        remote_save = remote['save']
        local_hash = digest(canonical(local)) if local is not None else None
        remote_hash = digest(canonical(remote_save)) if remote_save is not None else None
        replace_local = restore
        if local is not None and not restore and self.settle_unknown and meta['revision'] != self.revision and remote_save is not None:
            # A settlement may have landed unseen before the last quit: the server's copy holds it, whatever the
            # local one's age. Local is kept as a backup below.
            replace_local = True
            self.settle_unknown = False
        elif local is not None and not restore:
            if local_hash == remote_hash:
                self.metadata(local_hash)
            elif meta is None or (meta['revision'] != self.revision and local_hash != meta['hash']):
                # Both copies changed (or a reply was lost). The most recently played one wins;
                # the other is kept beside the save as a backup.
                if remote_save is None or saved_at(local) >= saved_at(remote_save):
                    if remote_save is not None:
                        atomic(self.save_path.with_name(f'save.server-copy-{time.time_ns()}.json'),canonical(remote_save))
                    with self.meta_lock: atomic(self.meta_path,canonical(self.meta(revision=self.revision,hash=None)))
                    self.status = 'Server: newer local progress waiting to upload'
                    return
                replace_local = True
            elif meta['revision'] == self.revision:
                self.status = 'Server: local progress waiting to upload'
                return
        if replace_local and local is not None:
            backup = self.save_path.with_name(f'save.before-restore-{time.time_ns()}.json')
            atomic(backup,self.save_path.read_bytes())
        if remote_save is not None:
            atomic(self.save_path,canonical(remote_save))
            self.metadata(remote_hash)
        elif local is not None and not restore:
            # Known unsynced local progress against an unchanged server revision.
            return
        else:
            if restore and self.save_path.exists(): self.save_path.unlink()
            if import_path is not None and Path(import_path).exists():
                import seal
                imported = json.loads(Path(import_path).read_bytes())
                if type(imported) is dict and (imported.get('edited') is True or seal.verify(imported) is False):
                    raise RuntimeError(EDITED_IMPORT)
                if type(imported) is dict: imported.pop('_seal',None)
                atomic(self.save_path,canonical(imported))
            self.metadata(None)
        self.status = 'Server: connected'

    def start(self):
        self.thread = threading.Thread(target=self.run,name='save-sync',daemon=True)
        self.thread.start()

    def offer(self, data):
        with self.condition:
            self.pending = json.loads(canonical(data))
            self.pending.pop('_seal',None)   # a seal belongs to offline saves only; it never goes to a server
            self.condition.notify()

    def run(self):
        try: self.upload_loop()
        finally:
            with self.condition:
                self.uploading = False
                self.condition.notify_all()

    def upload_loop(self):
        next_attempt = 0
        while True:
            with self.condition:
                self.uploading = False
                self.condition.notify_all()   # call() may be waiting for this upload to finish
                # Never upload while a call() holds uploads, even when stopping: it would overwrite a settlement.
                while self.calling or (not self.stopping and (self.pending is None or (time.monotonic() < next_attempt and not self.urgent))):
                    if self.stopping: return   # quitting mid-call: settle_unknown is on disk; the next start resolves it
                    self.condition.wait(max(.05,next_attempt-time.monotonic()) if self.pending and not self.calling else None)
                if self.conflicted: return
                data = self.pending
                if data is None and self.stopping: return
                self.pending = None
                self.uploading = True
                self.urgent = False
            try:
                self.market_barrier()
                response = self.request(dict(revision=self.revision,save=data))
                self.revision = response['revision']
                self.settle_unknown = False
                self.last_upload_ok = True
                self.metadata(digest(canonical(data)))
                self.status = 'Server: progress saved'
            except Rejected as refused:
                next_attempt = time.monotonic()+(1 if self.roll_back(data,refused.message) else 60)
                if self.stopping or self.halted: return
                continue
            except Conflict:
                if self.settle_unknown and self.resync():
                    # The conflict is a settlement whose reply was lost: the game adopts the server copy.
                    self.settle_unknown = False
                    next_attempt = time.monotonic()+1
                    continue
                # Usually our own earlier upload whose reply was lost. If the server copy is
                # not newer than this one, take over its revision and send ours straight away.
                try:
                    remote = self.request()
                    theirs = remote['save']
                    if theirs is None or saved_at(theirs) <= saved_at(data):
                        self.revision = remote['revision']
                        with self.condition:
                            if self.pending is None: self.pending = data
                        next_attempt = time.monotonic()+.5
                        continue
                except (OSError,RuntimeError,ValueError,KeyError,TypeError):
                    self.status = 'Server: unavailable — progress saved locally'
                    self.last_upload_ok = False
                    with self.condition:
                        if self.pending is None: self.pending = data
                        if self.stopping: return
                    next_attempt = time.monotonic()+5
                    continue
                self.conflicted = True
                self.status = 'Server: newer save on another computer — local save retained; reconnect'
                return
            except (OSError,RuntimeError,ValueError,KeyError):
                self.status = 'Server: unavailable — progress saved locally'
                self.last_upload_ok = False
                with self.condition:
                    if self.pending is None: self.pending = data
                    if self.stopping: return
            next_attempt = time.monotonic()+(60 if self.update_required else 5)
            if self.stopping:
                next_attempt = 0

    def market_barrier(self, timeout=5.):
        """Before an upload: let the market send every trade queued so far and wait (bounded) for its answer, so the
        server has booked the trades this save reflects before it audits the save. If the market can't be reached
        in time the save goes anyway (the server checks it as usual) and the trades stay queued."""
        market = self.market
        if market is None: return
        try: market.flush_and_wait(timeout)
        except (OSError,RuntimeError,ValueError,AttributeError,TypeError): pass

    def discard_market(self):
        """The server's save is being adopted: market trades not yet sent belong to the discarded branch."""
        market = self.market
        if market is None: return
        try: market.discard_queued()
        except (OSError,RuntimeError,ValueError,AttributeError,TypeError): pass

    def call(self, endpoint, body, timeout=8., hold=False):
        """POST `body` plus the current revision to a server endpoint that settles the save (the inbox, payment
        codes). Blocking: the game runs it on a worker thread. The pending save upload goes first, so the server
        settles against this game's own state, and no upload starts until the reply is in; the returned revision
        is adopted. With `hold`, uploads stay held after a successful reply (offers are kept, not sent) until
        release(), so the game can mirror the settlement before anything uploads.
        Errors (nothing to apply in any case):
          Refused: a clear refusal from the server; nothing settled.
          Conflict: the server's save changed (409); its copy is fetched for the game to adopt (rolled_back).
          RuntimeError/OSError/ValueError: no clear answer. The server may have settled, so settle_unknown makes
          the next upload conflict take the server copy rather than overwrite it.
        Fails fast when the last upload attempt could not reach the server."""
        deadline = time.monotonic()+timeout
        with self.condition:
            if self.last_upload_ok is False: raise RuntimeError('Server: unavailable')
            self.urgent = True
            self.condition.notify_all()
            while self.pending is not None or self.uploading:
                if self.conflicted or self.last_upload_ok is False or not (self.thread and self.thread.is_alive()): break
                left = deadline-time.monotonic()
                if left <= 0: break
                self.condition.wait(left)
            self.urgent = False
            if self.pending is not None or self.uploading or self.conflicted or self.update_required or self.rolled_back is not None:
                raise RuntimeError('Server: the save could not be uploaded first')
            self.calling = True
        held = False
        try:
            try:
                response = self.request(dict(body,revision=self.revision),endpoint,method='POST')
                if type(response) is not dict or type(response.get('revision')) is not int or response['revision'] < self.revision:
                    raise ValueError('Server sent an invalid reply')
            except Conflict:
                if not self.resync(): self.mark_settle_unknown()   # the next upload conflict takes the server copy
                raise
            except Refused: raise
            except (OSError,RuntimeError,ValueError):
                self.check_settled()   # a lost reply may hide a settlement: never upload over it
                raise
            # The settled save is the server's; sync.json keeps the last uploaded state, so a crash before the game
            # mirrors and saves makes the next start take the server's copy rather than upload the unsettled one.
            self.revision = response['revision']
            held = hold
            return response
        finally:
            if not held: self.release()

    def release(self):
        """Let uploads resume after call(hold=True)."""
        with self.condition:
            self.calling = False
            self.condition.notify_all()

    def check_settled(self):
        """After a call() failed without a clear answer: if the server's revision moved, take its copy (resync).
        If the server can't even be asked, the next upload conflict takes the server copy instead of overwriting."""
        # Even if the revision hasn't moved, the server may still be committing it: stay wary until an upload succeeds.
        self.mark_settle_unknown()
        try: changed = self.request()['revision'] != self.revision
        except (OSError,RuntimeError,ValueError,KeyError,TypeError): return
        if changed and self.resync(): self.settle_unknown = False

    def resync(self):
        """Fetch the server's save and revision for the game to adopt (rolled_back), keeping the local copy aside."""
        try:
            remote = self.request()
            good = remote['save']
            if type(good) is not dict or type(remote.get('revision')) is not int: raise ValueError('no server save')
            if self.save_path.exists(): atomic(self.save_path.with_name(f'save.before-resync-{time.time_ns()}.json'),self.save_path.read_bytes())
            atomic(self.save_path,canonical(good))
            self.revision = remote['revision']
            self.settle_unknown = False   # taking the server's copy resolves it
            self.metadata(digest(canonical(good)))
        except (OSError,RuntimeError,ValueError,KeyError,TypeError):
            self.status = 'Server: save changed elsewhere; reconnect to resolve'
            return False
        self.status = 'Server: save changed elsewhere; took the server copy'
        self.rejected_message = 'Your save changed on the server, so the game loaded the server copy.'
        self.discard_market()
        self.rolled_back = good
        return True

    def keep_rejected(self, data):
        """Write the refused save beside the real one (newest 5 kept); False if it could not be kept."""
        try:
            atomic(self.save_path.with_name(time.strftime('save.rejected-%Y%m%d-%H%M%S.json')),canonical(data))
            for old in sorted(self.save_path.parent.glob('save.rejected-*.json'))[:-5]: old.unlink()
            return True
        except (OSError,ValueError): return False

    def roll_back(self, data, message):
        """Keep the refused local save aside (never uploaded), then take the server's last good save and revision.
        Returns True when rolled back. Otherwise the local save is left untouched."""
        with self.condition: self.pending = None   # anything queued came from the refused state
        if not self.keep_rejected(data):
            self.status = 'Server: refused a save; could not keep a copy, local save left as it is'
            self.refused_notice = "The server refused this save and a copy couldn't be kept, so nothing was rolled back. Progress is kept locally; reconnect later."
            return False
        try:
            remote = self.request()
            good = remote['save']
            if good is None and type(remote.get('revision')) is int:
                # The server answered, and holds no save: a refused first save has nothing to roll back to.
                # Retrying can't help (the same save is refused again), so uploads stop for this session.
                self.halted = True
                self.status = 'Server: refused your first save; uploads stopped for this session'
                self.refused_notice = f'{message} Ask the host to allow an import of your pilot, or start a fresh online pilot.'
                return False
            if type(good) is not dict: raise ValueError('no server save')
            atomic(self.save_path,canonical(good))
            self.revision = remote['revision']
            self.metadata(digest(canonical(good)))
        except (OSError,RuntimeError,ValueError,KeyError,TypeError):
            self.status = 'Server: refused a save; could not fetch the last good one'
            self.refused_notice = "The server refused this save and couldn't be reached to restore the last good one. Progress is kept locally; reconnect later."
            return False
        self.status = 'Server: refused a save; rolled back to your last good save'
        self.rejected_message = message
        self.discard_market()
        self.rolled_back = good
        return True

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        if self.thread: self.thread.join(timeout=7)


class FeedbackUploader:
    """Sends logged bug reports and suggestions, oldest first, deleting each once the server has it."""
    def __init__(self, remote, outbox, interval=30):
        self.remote,self.outbox,self.interval = remote,Path(outbox),interval
        self.stop = threading.Event()
        self.thread = None
        self.sent = 0

    def start(self):
        self.thread = threading.Thread(target=self.run,name='feedback',daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            self.send_all()
            self.stop.wait(self.interval)

    def send_all(self):
        try: paths = sorted(self.outbox.glob('*.json'),key=lambda path:path.stat().st_mtime)
        except OSError: return
        for path in paths:
            if self.stop.is_set(): return
            try: entry = json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):
                try: path.rename(path.with_suffix('.unreadable'))
                except OSError: pass
                continue
            try: self.remote.request(entry,endpoint='/v1/feedback')
            except RuntimeError as error:
                if 'HTTP 400' in str(error):
                    # The server rejected this entry outright; keep it aside rather than retrying forever.
                    try: path.rename(path.with_suffix('.rejected'))
                    except OSError: pass
                    continue
                return
            except (OSError,ValueError): return
            try: path.unlink()
            except OSError: pass
            self.sent += 1

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=7)
