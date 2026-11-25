"""One entry point for offline and private-server play. Stores paths, never tokens."""
import ctypes as C
import gzip
import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse

# The one community server for now; an invite code fills in everything else.
DEFAULT_SERVER = 'https://141-147-67-78.sslip.io'
INVITE_PREFIX = 'RIFTDOGS-INVITE:'
INVITE_PREFIXES = (INVITE_PREFIX,)
EMAIL_CONSENT = "We'll only email you Riftdogs news. Remove it any time from Connection settings."


def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'riftdogs/connection.json'


def load_connection():
    defaults = dict(server=DEFAULT_SERVER,token_file=str(config_path().with_name('player.token')),allow_lan=True,import_local_save=True,last_mode='',fallback_servers=[])
    try:
        saved = json.loads(config_path().read_text())
        for key in defaults:
            if type(saved.get(key)) is type(defaults[key]): defaults[key] = saved[key]
        defaults['fallback_servers'] = [s for s in defaults['fallback_servers'] if type(s) is str][:4]
    except (OSError,ValueError,AttributeError): pass
    return defaults


def save_connection(config):
    path = config_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config,indent=2)+'\n')
    temp.chmod(0o600)
    temp.replace(path)


def make_invite(server, name, token=None, claim=None):
    """One pasteable code holding the server, a player's name and either a single-use claim (invites from the
    server's `invite` command) or, in older invites, the login token itself. Send it privately either way."""
    if (token is None) == (claim is None): raise ValueError('An invite holds a token or a claim')
    secret = dict(claim=claim) if claim is not None else dict(token=token)
    data = json.dumps(dict(v=2 if claim is not None else 1,server=server.rstrip('/'),name=name,**secret),separators=(',',':')).encode()
    return INVITE_PREFIX+base64.urlsafe_b64encode(data).decode().rstrip('=')


def read_invite(code):
    """dict(server, name, token) for an old invite, or dict(server, name, claim) for a single-use one."""
    code = ''.join(code.split())
    prefix = next((p for p in INVITE_PREFIXES if code.startswith(p)),None)
    if prefix is None: raise ValueError('That is not a Riftdogs invite code.')
    try:
        raw = code[len(prefix):]
        data = json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
        server,name = data['server'],data['name']
        kind = 'claim' if 'claim' in data else 'token'
        secret = data[kind]
    except (ValueError,KeyError,TypeError): raise ValueError('The invite code is incomplete. Copy all of it and try again.') from None
    parsed = urllib.parse.urlsplit(server) if type(server) is str else None
    if not parsed or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path not in ('','/'):
        raise ValueError('The invite code has an invalid server address.')
    if type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',name): raise ValueError('The invite code has an invalid player name.')
    if type(secret) is not str or not 20 <= len(secret) <= 200 or any(c.isspace() for c in secret): raise ValueError(f'The invite code has an invalid {kind}.')
    return dict(server=server.rstrip('/'),name=name,**{kind:secret})


def store_account(config, server, name, token):
    token_file = config_path().with_name(name.lower()+'.token')
    token_file.parent.mkdir(parents=True,exist_ok=True)
    fd = os.open(token_file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out: out.write(token+'\n')
    token_file.chmod(0o600)
    # A new account starts a new commander; fallbacks belonged to the previous server.
    config.update(server=server,token_file=str(token_file),allow_lan=True,import_local_save=False,fallback_servers=[])
    save_connection(config)


def redeem_claim(server, claim):
    """Swap a single-use invite's claim for the login token at the server: (name, token). Online only.
    RuntimeError carries words for the player (used, expired, unreachable...)."""
    from save_sync import claim_invite
    try: return claim_invite(server,claim,allow_lan=True)
    except OSError: raise RuntimeError('Could not reach the server to accept the invite. Check your connection and try again.') from None


def apply_invite(config, code):
    invite = read_invite(code)
    if 'claim' in invite:
        # The claim works once, so check the login can be saved before using it up.
        folder = config_path().parent
        folder.mkdir(parents=True,exist_ok=True)
        if not os.access(folder,os.W_OK): raise OSError('Config folder is not writable')
        name,token = redeem_claim(invite['server'],invite['claim'])
    else: name,token = invite['name'],invite['token']
    store_account(config,invite['server'],name,token)
    return name


PRIVACY_LINK = (995,688,90,30)   # x, y, w, h of the start screen's Privacy and Terms links
TERMS_LINK = (1095,688,80,30)


JOINED_ELSEWHERE = 'This email joined the galaxy from another computer. Use Connection settings to sign in there.'


def queue_wait_message(state):
    """Online play on the Riftdogs server before this install is let in, for the check-in state as the queue line
    reads it (under the start screen's 94 characters)."""
    if state['joined_elsewhere']: return JOINED_ELSEWHERE
    if not state['registered']: return "Online: waiting to reach the Riftdogs server. Play offline till you're in."
    where = f"You're number {state['place']} in the queue" if state['place'] else "You're joining the queue"
    return f"{where}. Play offline till you're in. Invite? Connection settings."


def open_document(name):
    """Open PRIVACY.md or TERMS.md from the game folder with the system's opener: no network needed.
    Returns the status line for the player."""
    path = Path(__file__).resolve().parent/name
    if not path.is_file(): return f'{name} is missing from the game folder. Reinstall Riftdogs to get it back.'
    try:
        if sys.platform == 'win32': os.startfile(str(path))
        else: subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open',str(path)],stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    except OSError: return f'Read {name} in the game folder: {path}'
    return f'Opened {name}.'


SPLASH_SECONDS = 4   # the splash art holds this long before online play connects by itself
RELAY_MASTHEAD = 'THE RELAY · News at the speed of the next jump'


def relay_lines(news, width=90):
    """The Relay's start-screen headlines: the newest Council decree, the STA Tally's first point, the latest Act."""
    import textwrap
    if not isinstance(news, dict): return ['THE RELAY · no signal']
    items = []
    decrees = news.get('decrees') or []
    if decrees: items.append('COUNCIL: '+decrees[-1]['text'])
    tally = news.get('tally')
    if tally and tally.get('points'): items.append('STA TALLY: '+tally['points'][0])
    if news.get('acts'): items.append('ACT OF THE STA (Sovereign Trade Assembly): '+news['acts'][-1]['title'])
    items += ['COUNCIL: '+d['text'] for d in reversed(decrees[:-1])]
    return [RELAY_MASTHEAD]+[textwrap.shorten(item, width, placeholder='…') for item in items[:3]]


def fetch_news(server, timeout=3):
    """The Relay's news from the server (no token needed), or None offline."""
    import urllib.request
    try:
        with urllib.request.urlopen(server.rstrip('/')+'/v1/news', timeout=timeout) as reply: return json.loads(reply.read())
    except (OSError, ValueError): return None


GOLD_PREFIXES = ("You're number","You're joining",'Welcome','Invite accepted','Signing up','Installing','Opened','Accepting','Removing','Joining','Your email is removed','Deleting','Deleted')
WELCOME_PRIVACY_X = 70+len('[ ] I agree to the privacy notice (required)')*11+20
UNREAD_BOX = (40,478,1020,114)


def _ck():
    import checkin   # imported late: checkin itself imports this module
    return checkin


class StartScreen:
    deleting = None   # 'Delete my account' open: the commander name typed so far
    save_root = None  # the game's data folder (holds servers/<slot>); None: riftdogs.SAVE's folder
    welcome = None    # the email screen's form (email, news, privacy, account) while it is open
    checkin = None    # the CheckinClient, or None
    joining = False   # the signup form is the Join the galaxy name form
    skipped_update = None   # the release the player answered Not now to: U asks again
    _state = None     # last read check-in state when there is no client
    def __init__(self, display, config, error='', update=None, checkin=None):
        self.d,self.config,self.error = display,dict(config),error
        # A newer release must be answered before anything else: Enter installs, N or Esc plays this version until next launch.
        self.update,self.installing = update,False
        self.selected = 0
        self.settings = False
        self.signup = None
        # Players who last played online go straight back in unless they press something.
        ready = self.config.get('last_mode') == 'online' and self.config['server'] and Path(self.config['token_file']).expanduser().is_file()
        self.auto_at = time.monotonic()+SPLASH_SECONDS if ready and not error and not update else None
        self.field = 0
        self.news, self.news_started = None, False
        self.replace_field = False
        self.texture = None
        asset = Path(__file__).resolve().parent/'assets/riftdogs-splash.bmp.gz'
        try:
            raw = gzip.decompress(asset.read_bytes())
            buffer = C.create_string_buffer(raw)
            from riftdogs import bind
            rw = bind(display.sdl,'SDL_RWFromConstMem',C.c_void_p,[C.c_void_p,C.c_int])(buffer,len(raw))
            surface = bind(display.sdl,'SDL_LoadBMP_RW',C.c_void_p,[C.c_void_p,C.c_int])(rw,1) if rw else None
            if surface:
                self.texture = display.texture(display.r,surface)
                display.free(surface)
        except (OSError,ValueError,EOFError): pass
        self.start_checkin(checkin)

    # --- check-in
    def start_checkin(self, client):
        self.checkin = client
        self._state = _ck().load_state(self.folder())
        self.welcome = None
        if _ck().needs_email(self._state): self.open_welcome()

    def folder(self):
        return self.checkin.folder if self.checkin else None

    def state(self):
        if self.checkin: return self.checkin.snapshot()
        return self._state or _ck().default_state()

    def edit_state(self, change):
        if self.checkin: return self.checkin.edit(change)
        state = _ck().load_state()
        change(state)
        _ck().save_state(state)
        self._state = state

    def has_token(self, saved=False):
        """Is there a login file? `saved`: the one in the saved settings, not unsaved edits in the fields."""
        return Path((load_connection() if saved else self.config)['token_file']).expanduser().is_file()

    def open_welcome(self):
        self.welcome = dict(email='',news=False,privacy=False,account=bool(_ck().find_account(DEFAULT_SERVER)))
        self.field,self.replace_field,self.auto_at = 0,False,None

    def reopen_welcome(self):
        """The server refused the email while the player was on this screen: ask again."""
        if self.welcome is None and not (self.settings or self.signup or self.deleting is not None) and _ck().needs_email(self.state()):
            self.open_welcome()

    def welcome_event(self, kind, value):
        w = self.welcome
        if kind == 'click':
            x,y = value
            if not 70 <= x <= 1030: return
            if 320 <= y <= 364: self.field,self.replace_field = 0,False
            elif 405 <= y <= 440: self.field = 1; w['news'] = not w['news']
            elif 445 <= y <= 480:
                if WELCOME_PRIVACY_X <= x <= WELCOME_PRIVACY_X+len('Privacy')*11: self.error = open_document('PRIVACY.md')
                else: self.field = 2; w['privacy'] = not w['privacy']
        elif kind == 'down' and value == 9: self.field,self.replace_field = (self.field+1)%3,False
        elif kind == 'down' and value == 13: self.submit_welcome()
        elif self.field and ((kind == 'down' and value == 32) or (kind == 'text' and value == ' ')):
            key = ('news','privacy')[self.field-1]
            w[key] = not w[key]
        elif self.field == 0: self.form_event(kind,value,w,('email',),(254,))

    def submit_welcome(self):
        ck,w = _ck(),self.welcome
        try: ck.set_email(ck.default_state(),w['email'],w['news'],account=w['account'])   # only checks the address
        except ValueError as error: self.error = str(error); return
        if not w['privacy']: self.error = 'Tick the box to agree to the privacy notice.'; return
        try:
            if self.checkin: self.checkin.set_email(w['email'],w['news'],account=w['account'])
            else:
                state = ck.load_state()
                ck.set_email(state,w['email'],w['news'],account=w['account'])
                ck.save_state(state)
                self._state = state
        except OSError: self.error = 'Could not save your email on this computer. Check folder permissions.'; return
        self.welcome,self.error,self.field = None,'',0
        if self.checkin: self.checkin.revive()

    def unread(self):
        return [n for n in self.state()['notices'] if not n['read']]

    def mark_read(self):
        unread = self.unread()
        if not unread: return
        newest = unread[-1]['id']
        self.edit_state(lambda state: [n.update(read=True) for n in state['notices'] if n['id'] == newest])

    def on_riftdogs(self):
        """Is the chosen server the Riftdogs one? Only then do the queue, Join the galaxy and Riftdogs' minimum
        version apply: a friend's server is neither blocked nor hidden by them."""
        return self.config['server'].strip().rstrip('/') == DEFAULT_SERVER

    def can_join(self):
        return bool(self.state()['claim']) and self.on_riftdogs() and not self.has_token()

    def queue_line(self):
        """(text, colour or None) for the line above the buttons, or None. A required update comes first."""
        from riftdogs import GOLD
        state,riftdogs = self.state(),self.on_riftdogs()
        how = ' Press U to update.' if self.skipped_update else ''
        if riftdogs and state['must_update']:
            return f"Riftdogs {state['must_update']} or newer is needed for online play.{how or ' Offline play still works.'}",GOLD
        if riftdogs and not self.has_token():
            if state['claim']: return "You're in! Choose Join the galaxy to pick your galaxy name.",GOLD
            if state['joined_elsewhere']: return JOINED_ELSEWHERE,None
            if state['place']: return f"Online: you're number {state['place']} in the queue.",None
            if not state['registered']: return 'Online: waiting to reach the Riftdogs server.',None
        if state['recommended']: return f"Update {state['recommended']} is recommended.{how}",GOLD
        return None

    def must_update_error(self):
        """Show the forced-update message and return True when online play on the Riftdogs server is not allowed."""
        version = self.state()['must_update']
        if not version or not self.on_riftdogs(): return False
        self.error = (f'Riftdogs {version} or newer is needed online. Press U to update; Offline play still works.' if self.skipped_update else
                      f'Riftdogs {version} or newer is needed for online play. Update to play online; Offline play still works.')
        return True

    def open_join(self):
        self.signup,self.joining = dict(name=''),True
        self.settings,self.field,self.replace_field,self.error = False,0,False,''

    def submit_join(self):
        ck = _ck()
        name,claim = self.signup['name'].strip(),self.state()['claim']
        if not name: self.error = 'Choose a galaxy name: letters, numbers, _ or -.'; return
        if not claim: self.error = 'Your place is not ready yet. Try again after the next check-in.'; return
        folder = config_path().parent
        try:   # the claim works once, so check the login can be saved before using it up
            folder.mkdir(parents=True,exist_ok=True)
            if not os.access(folder,os.W_OK): raise OSError('Config folder is not writable')
        except OSError: self.error = 'Could not save your login. Check folder permissions.'; return
        self.error = 'Joining the galaxy...'
        self.draw()
        try: player,token = ck.join_galaxy(claim,name)
        except (ValueError,OSError) as error: self.error = str(error); return
        try: store_account(self.config,DEFAULT_SERVER,player,token)
        except OSError: self.error = 'Joined, but your login could not be saved. Check folder permissions.'; return
        self.edit_state(lambda state: state.update(claim=None))
        self.signup,self.joining = None,False
        self.error = f'Welcome aboard, {player}! Choose Online play.'

    def forget_computer(self):
        before,self.error = self.error,'Forgetting this computer...'
        self.draw()
        if self.checkin: confirmed = self.checkin.forget()
        else: _ck().forget_local(); confirmed = True
        self._state = _ck().load_state(self.folder())
        self.settings = False
        self.open_welcome()
        self.error = before
        if not confirmed: self.error = 'Could not reach the server to forget this computer there; it is forgotten here.'

    def forget_or_remove(self):
        if self.has_token(saved=True) and not self.remove_email(): return
        self.forget_computer()

    def close(self):
        if self.texture:
            self.d.destroy(self.texture)
            self.texture = None

    def activate(self, index):
        if index == 0:
            if self.must_update_error(): return None
            if self.can_join():
                self.open_join()
                return None
            if not self.config['server']:
                self.settings = True
                self.error = 'Enter your server address and private token file path.'
                return None
            if not Path(self.config['token_file']).expanduser().is_file():
                if self.on_riftdogs():   # new pilots come in through the queue here, never the friends' sign-up form
                    self.error = queue_wait_message(self.state())
                    return None
                self.open_signup('New pilot? Copy your invite code and click Paste invite, or sign up on the host\'s Wi-Fi.')
                return None
            return 'online'
        if index == 1: return 'offline'
        self.settings = True
        self.error = ''
        return None

    def open_signup(self, message=''):
        self.signup = dict(name='',email=self.state()['email'] or '')   # the address from the email screen, not typed twice
        self.settings = False
        self.field,self.replace_field = 0,False
        self.error = message

    def submit_signup(self):
        from save_sync import signup
        name,email = self.signup['name'].strip(),self.signup['email'].strip()
        if not name: self.error = 'Choose a pilot name: letters, numbers, _ or -.'; return None
        self.error = 'Signing up...'
        self.draw()
        try:
            token = signup(self.config['server'],name,email,allow_lan=True)
            store_account(self.config,self.config['server'].rstrip('/'),name,token)
        except (RuntimeError,ValueError) as error: self.error = str(error); return None
        except OSError: self.error = 'Could not reach the server. Check your connection, or play offline.'; return None
        self.signup = None
        self.error = f'Welcome aboard, {name}! Choose Online play.'
        return None

    def form_event(self, kind, value, record, keys, limits):
        if kind == 'down':
            if value == 9: self.field = (self.field+1)%len(keys); self.replace_field = False
            elif value == 8:
                key = keys[self.field]
                record[key] = '' if self.replace_field else record[key][:-1]
                self.replace_field = False
            else: return False
            return True
        if kind == 'clipboard' and value == 'select_all': self.replace_field = True; return True
        if kind == 'text' or (kind == 'clipboard' and value == 'paste'):
            try: text = value if kind == 'text' else self.d.clipboard_text()
            except RuntimeError: self.error = 'Clipboard unavailable.'; return True
            key = keys[self.field]
            record[key] = (('' if self.replace_field else record[key])+text.replace('\n','').replace('\r',''))[:limits[self.field]]
            self.replace_field = False
            return True
        return False

    def event(self, kind, value):
        from riftdogs import UP,DOWN,LEFT,RIGHT
        if kind == 'quit': return 'quit'
        if self.update:
            # Nothing else on the start screen works until the player answers the update question.
            if (kind == 'down' and value in (13,ord('u'),ord('y'))) or (kind == 'click' and 110 <= value[0] <= 530 and 655 <= value[1] <= 699): return 'update'
            if (kind == 'down' and value in (27,ord('n'))) or (kind == 'click' and 570 <= value[0] <= 990 and 655 <= value[1] <= 699):
                from riftdogs import VERSION
                self.skipped_update,self.update = self.update,None
                self.error = f'Update skipped for now: playing v{VERSION}. You will be asked again next launch.'
            return None
        if kind == 'down' and value == 27: return 'quit'
        if kind in ('down','click','text'): self.auto_at = None
        if self.welcome is not None:
            self.welcome_event(kind,value)   # the main buttons wait until the email is answered
            return None
        if kind == 'click' and not self.settings and self.deleting is None:
            for rect,name in ((PRIVACY_LINK,'PRIVACY.md'),(TERMS_LINK,'TERMS.md')):
                if rect[0] <= value[0] <= rect[0]+rect[2] and rect[1] <= value[1] <= rect[1]+rect[3]:
                    self.error = open_document(name)
                    return None
        if self.deleting is not None:
            if kind == 'click':
                x,y = value
                if 70 <= x <= 370 and 550 <= y <= 596: self.submit_delete()
                elif 730 <= x <= 1030 and 550 <= y <= 596: self.deleting = None; self.error = ''
            elif kind == 'down' and value == 13: self.submit_delete()
            else:
                record = dict(name=self.deleting)
                self.field = 0
                if self.form_event(kind,value,record,('name',),(32,)): self.deleting = record['name']
            return None
        if self.joining:
            if kind == 'click':
                x,y = value
                if 70 <= x <= 370 and 550 <= y <= 596: self.submit_join()
                elif 730 <= x <= 1030 and 550 <= y <= 596: self.signup,self.joining = None,False; self.error = ''
            elif kind == 'down' and value == 13: self.submit_join()
            else: self.form_event(kind,value,self.signup,('name',),(32,))
            return None
        if self.signup is not None:
            if kind == 'click':
                x,y = value
                if 70 <= x <= 1030 and 200 <= y <= 244: self.field,self.replace_field = 0,False
                elif 70 <= x <= 1030 and 295 <= y <= 339: self.field,self.replace_field = 1,False
                elif 70 <= x <= 370 and 550 <= y <= 596: return self.submit_signup()
                elif 390 <= x <= 710 and 550 <= y <= 596: self.invite_from_signup()
                elif 730 <= x <= 1030 and 550 <= y <= 596: self.signup = None; self.error = ''
            elif kind == 'down' and value == 13: return self.submit_signup()
            elif kind == 'text' and value.strip().startswith(INVITE_PREFIXES): self.invite_from_signup(value)
            elif kind == 'clipboard' and value == 'paste': self.invite_from_signup()
            else: self.form_event(kind,value,self.signup,('name','email'),(32,254))
            return None
        if self.settings:
            keys = ('server','token_file')
            if kind == 'click':
                x,y = value
                if 70 <= x <= 1030 and 200 <= y <= 244: self.field,self.replace_field = 0,False
                elif 70 <= x <= 1030 and 295 <= y <= 339: self.field,self.replace_field = 1,False
                elif 70 <= x <= 1030 and 380 <= y <= 414: self.config['allow_lan'] = not self.config['allow_lan']
                elif 70 <= x <= 1030 and 435 <= y <= 469: self.config['import_local_save'] = not self.config['import_local_save']
                elif 70 <= x <= 370 and 550 <= y <= 596: self.save_settings()
                elif 390 <= x <= 710 and 550 <= y <= 596: self.paste_invite()
                elif 70 <= x <= 370 and 490 <= y <= 530: self.open_signup()
                elif 390 <= x <= 710 and 490 <= y <= 530: self.forget_or_remove()
                elif 730 <= x <= 1030 and 490 <= y <= 530: self.deleting,self.replace_field = '',False; self.error = ''
                elif 730 <= x <= 1030 and 550 <= y <= 596: self.settings = False; self.error = ''
            elif kind == 'down':
                if value == 9: self.field = 1-self.field; self.replace_field = False
                elif value == 8:
                    key = keys[self.field]
                    self.config[key] = '' if self.replace_field else self.config[key][:-1]
                    self.replace_field = False
                elif value == 13: self.save_settings()
            elif kind == 'clipboard' and value == 'select_all': self.replace_field = True
            elif kind == 'text' or (kind == 'clipboard' and value == 'paste'):
                try: text = value if kind == 'text' else self.d.clipboard_text()
                except RuntimeError: self.error = 'Clipboard unavailable.'; return None
                if text.strip().startswith(INVITE_PREFIXES): return self.paste_invite(text)
                key = keys[self.field]
                self.config[key] = (('' if self.replace_field else self.config[key])+text.replace('\n','').replace('\r',''))[:1024]
                self.replace_field = False
            return None
        if kind == 'down':
            if value in (UP,LEFT): self.selected = (self.selected-1)%3
            elif value in (DOWN,RIGHT,9): self.selected = (self.selected+1)%3
            elif value in (13,32): return self.activate(self.selected)
            elif value == ord('o'): return self.activate(0)
            elif value == ord('f'): return self.activate(1)
            elif value == ord('m'): self.mark_read()
            elif value == ord('u') and self.skipped_update: self.update = self.skipped_update   # the update question again
        elif kind == 'click':
            x,y = value
            bx,by,bw,bh = UNREAD_BOX
            if bx <= x <= bx+bw and by <= y <= by+bh and self.unread(): self.mark_read(); return None
            for index in range(3):
                if 110+index*300 <= x <= 390+index*300 and 631 <= y <= 679:
                    self.selected = index
                    return self.activate(index)
        return None

    def invite_from_signup(self, code=None):
        self.paste_invite(code)
        if self.error.startswith('Invite accepted'): self.signup = None

    def paste_invite(self, code=None):
        try:
            if code is None: code = self.d.clipboard_text() or ''
        except RuntimeError: self.error = 'Clipboard unavailable.'; return None
        try:
            if 'claim' in read_invite(code):
                self.error = 'Accepting invite...'
                self.draw()
            name = apply_invite(self.config,code)
        except (ValueError,RuntimeError) as error: self.error = str(error); return None
        except OSError: self.error = 'Could not save the invite. Check folder permissions.'; return None
        self.settings = False
        self.error = f'Invite accepted: you are {name}. Choose Online play.'
        return None

    def account(self):
        """(server, token file) of the SAVED login on this computer, or None (and the reason on the status line).
        Unsaved edits in the fields never pick which account is changed."""
        saved = load_connection()
        server = saved['server'].strip().rstrip('/')
        token_file = str(Path(os.path.expandvars(saved['token_file'].strip())).expanduser())
        if not server or not Path(token_file).is_file():
            self.error = 'No online login on this computer: there is no account to change.'
            return None
        return server,token_file

    def remove_email(self):
        from save_sync import remove_email
        account = self.account()
        if account is None: return False
        self.error = 'Removing your email...'
        self.draw()
        try: remove_email(*account,allow_lan=True)
        except (RuntimeError,ValueError) as error: self.error = str(error); return False
        except OSError: self.error = 'Could not reach the server. Your email was not removed; try again later.'; return False
        self.error = 'Your email is removed from the server. You will get no Riftdogs news.'
        return True

    def submit_delete(self):
        from save_sync import delete_account
        name = self.deleting.strip()
        if not name: self.error = 'Type your commander name to confirm.'; return
        account = self.account()
        if account is None: return
        self.error = 'Deleting your account...'
        self.draw()
        try: delete_account(*account,name,allow_lan=True)
        except (RuntimeError,ValueError) as error: self.error = str(error); return
        except OSError: self.error = 'Could not reach the server. Nothing was deleted; try again later.'; return
        # The server account is gone: forget its login and the local copy of its online save too.
        import shutil
        from save_sync import read_token,slot_name
        try:
            root = self.save_root
            if root is None:
                from riftdogs import SAVE
                root = SAVE.parent
            shutil.rmtree(Path(root)/'servers'/slot_name(read_token(account[1])),ignore_errors=True)
        except (OSError,ValueError): pass
        try: Path(account[1]).unlink(missing_ok=True)
        except OSError: pass
        self.config = load_connection()
        self.config.update(token_file=str(config_path().with_name('player.token')),last_mode='',fallback_servers=[])
        try: save_connection(self.config)
        except OSError: pass
        forgotten = True
        if account[0] == DEFAULT_SERVER:   # a Riftdogs account's email is gone: this computer's install, which carries it, goes too
            try:
                if self.checkin: forgotten = self.checkin.forget()
                else: _ck().forget_local()
            except OSError: forgotten = False
            self._state = _ck().load_state(self.folder())
        self.deleting = None
        self.error = (f'Deleted {name} and its save from the server; its login and save copy are removed from this computer.' if forgotten else
                      f'Deleted {name}; this computer could not be forgotten on Riftdogs yet.')

    def save_settings(self):
        self.config['server'] = self.config['server'].strip().rstrip('/')
        self.config['token_file'] = str(Path(os.path.expandvars(self.config['token_file'].strip())).expanduser())
        try:
            save_connection(self.config)
            self.settings = False
            self.error = ''
        except OSError: self.error = 'Could not save connection settings.'

    def draw(self):
        from riftdogs import W,H,GOLD,GREEN,RED
        d = self.d
        d.color(d.r,0,0,0,255); d.clear(d.r)
        if self.texture:
            # Fit the entire 16:9 artwork; black bars preserve its edges and title.
            width,height = C.c_int(),C.c_int()
            d.query(self.texture,None,None,C.byref(width),C.byref(height))
            scale = min(W/width.value,600/height.value)
            w,h = int(width.value*scale),int(height.value*scale)
            rect = (C.c_int*4)((W-w)//2,(600-h)//2,w,h)
            d.copy(d.r,self.texture,None,rect)
        else: d.text(440,250,'RIFTDOGS',GOLD)
        if self.deleting is not None:
            d.fill(40,90,1020,545,(5,15,25))
            d.text(70,110,'DELETE MY ACCOUNT / '+self.config['server'],RED)
            d.text(70,155,'This deletes your commander, save, trade records and email from the server.')
            d.text(70,185,'It cannot be undone. Your offline pilot on this computer is not touched.')
            d.text(70,250,'Type your commander name to confirm')
            d.rect(70,295,960,44,RED)
            if self.replace_field and self.deleting: d.fill(76,301,len(self.deleting)*11+8,32,(70,20,20))
            d.text(80,305,self.deleting+('_' if int(time.monotonic()*2)%2 == 0 else ''),GOLD)
            d.text(70,420,'Enter deletes. ESC closes the game; Back keeps your account.')
            d.rect(70,550,300,46,RED); d.text(85,562,'Delete account',RED)
            d.rect(730,550,300,46,GREEN); d.text(745,562,'Back',GREEN)
        elif self.joining:
            d.fill(40,90,1020,545,(5,15,25))
            d.text(70,110,'CHOOSE YOUR GALAXY NAME',GOLD)
            d.text(70,155,'Letters, numbers, _ or -. Other pilots see this name.')
            d.rect(70,200,960,44,GOLD)
            text = self.signup['name'][-81:]
            if self.replace_field and text: d.fill(76,206,len(text)*11+8,32,(20,65,70))
            d.text(80,210,text+('_' if int(time.monotonic()*2)%2 == 0 else ''),GOLD)
            d.text(70,495,'Enter joins. ESC closes the game.')
            d.rect(70,550,300,46,GREEN); d.text(85,562,'Join',GREEN)
            d.rect(730,550,300,46,GREEN); d.text(745,562,'Back',GREEN)
        elif self.signup is not None:
            d.fill(40,90,1020,545,(5,15,25))
            d.text(70,110,'NEW PILOT SIGN-UP / '+self.config['server'],GOLD)
            d.text(70,155,'Pilot name (letters, numbers, _ or -). Other pilots see this name.')
            d.text(70,250,'Email for Riftdogs news (optional)')
            for i,key in enumerate(('name','email')):
                y = 200+i*95
                d.rect(70,y,960,44,GOLD if self.field == i else GREEN)
                text = self.signup[key][-81:]
                if self.field == i:
                    if self.replace_field and text: d.fill(76,y+6,len(text)*11+8,32,(20,65,70))
                    d.text(80,y+10,text+('_' if int(time.monotonic()*2)%2 == 0 else ''),GOLD)
                else: d.text(80,y+10,text or ('(click to enter)' if i == 0 else '(leave blank for no news)'))
            d.text(70,380,EMAIL_CONSENT)
            d.text(70,420,'Your private login is saved on this computer automatically.')
            d.text(70,495,'Click a field or TAB. Enter signs up. ESC closes.')
            for x,w,label in ((70,300,'Sign up'),(390,320,'Paste invite'),(730,300,'Back')):
                d.rect(x,550,w,46,GREEN); d.text(x+15,562,label,GREEN)
        elif self.settings:
            d.fill(40,90,1020,545,(5,15,25))
            d.text(70,110,'ONLINE CONNECTION',GOLD)
            d.text(70,155,'Server address')
            d.text(70,250,'Private token FILE path — paste the path, not the token itself')
            for i,key in enumerate(('server','token_file')):
                y = 200+i*95
                d.rect(70,y,960,44,GOLD if self.field == i else GREEN)
                if self.field == i:
                    # The focused field shows its text and a blinking cursor, never the placeholder.
                    text = self.config[key][-81:]
                    if self.replace_field and text: d.fill(76,y+6,len(text)*11+8,32,(20,65,70))
                    d.text(80,y+10,text+('_' if int(time.monotonic()*2)%2 == 0 else ''),GOLD)
                else: d.text(80,y+10,self.config[key][-82:] or '(click to enter)')
            for y,key,label in ((380,'allow_lan','Allow HTTP on a trusted home network'),(435,'import_local_save','Import offline pilot only if this server account is empty')):
                d.text(70,y,('[X] ' if self.config[key] else '[ ] ')+label,GREEN)
            for x,label in ((70,'New pilot? Sign up'),(390,'Remove my email' if self.has_token(saved=True) else 'Forget this computer'),(730,'Delete my account')):
                d.rect(x,490,300 if x != 390 else 320,40,GREEN); d.text(x+15,500,label,GREEN)
            for x,w,label in ((70,300,'Save settings'),(390,320,'Paste invite'),(730,300,'Back')):
                d.rect(x,550,w,46,GREEN); d.text(x+15,562,label,GREEN)
        elif self.update:
            from riftdogs import VERSION
            d.fill(90,590,920,128,(5,15,25)); d.rect(90,590,920,128,GOLD)
            d.text(110,605,f'UPDATE {self.update} IS READY. Install it before you play? (you are on v{VERSION})',GOLD)
            d.text(110,630,'Your saved game and settings are kept.',GREEN)
            d.rect(110,655,420,44,GOLD); d.text(125,667,'Update now (Enter / U)',GOLD)
            d.rect(570,655,420,44,GREEN); d.text(585,667,'Not now (N / Esc)',GREEN)
        elif self.welcome is not None:
            self.draw_welcome()
        else:
            unread = self.unread()
            if unread:
                import textwrap
                d.fill(40,478,1020,114,(5,15,25))
                d.text(55,486,f'FROM RIFTDOGS ({len(unread)} unread)',GOLD)
                d.text(820,486,'M or click: mark read',GREEN)
                for row,line in enumerate(textwrap.wrap(unread[-1]['text'],90,max_lines=3,placeholder='…')):
                    d.text(55,512+row*24,line,GREEN)
            elif self.news_started:
                d.fill(40,478,1020,114,(5,15,25))
                for row,line in enumerate(relay_lines(self.news if isinstance(self.news,dict) else None) if self.news else [RELAY_MASTHEAD]):
                    d.text(55,486+row*26,line,GOLD if row == 0 else GREEN)
            queue = self.queue_line()
            if queue:   # between the box (ends 592) and the buttons (start 631), lined up with the buttons
                d.fill(40,596,1020,30,(5,15,25))
                d.text(110,600,*(queue[0],) if queue[1] is None else queue)
            join = self.can_join()
            for index,label in enumerate(('Join the galaxy' if join else 'Online play','Offline play','Connection settings')):
                x = 110+index*300
                d.rect(x,631,280,48,GOLD if index == self.selected else GREEN)
                d.text(x+15,646,label,GOLD if index == self.selected else GREEN)
            if self.installing: pass
            elif self.auto_at: d.text(110,693,f'Connecting to online play in {max(0,self.auto_at-time.monotonic()):.0f}s - press any key to choose',GOLD)
            else: d.text(110,693,'Arrows choose / Enter opens / Click to play / ESC closes')
        if not self.settings and self.deleting is None and not self.update and self.welcome is None and not self.joining:
            for (x,y,w,h),label in ((PRIVACY_LINK,'Privacy'),(TERMS_LINK,'Terms')):
                d.text(x+5,y+5,label,GREEN); d.fill(x+5,y+h-4,len(label)*11,1,GREEN)
        if self.error and self.welcome is None: d.text(45,727,self.error[:94],GOLD if self.error.startswith(GOLD_PREFIXES) else RED)
        d.present(d.r)

    def draw_welcome(self):
        import textwrap
        from riftdogs import GOLD,GREEN,RED
        d,w = self.d,self.welcome
        d.fill(40,200,1020,490,(5,15,25))   # below the logo band of the splash art
        d.text(70,215,'WELCOME, COMMANDER',GOLD)
        prompt = 'Your email (required). We use it for your place in the online queue, replies to your bug reports and essential notices about the game.'
        for row,line in enumerate(textwrap.wrap(prompt,86)): d.text(70,255+row*26,line)
        d.rect(70,320,960,44,GOLD if self.field == 0 else GREEN)
        text = w['email'][-81:]
        if self.field == 0:
            if self.replace_field and text: d.fill(76,326,len(text)*11+8,32,(20,65,70))
            d.text(80,330,text+('_' if int(time.monotonic()*2)%2 == 0 else ''),GOLD)
        else: d.text(80,330,text or '(click to enter)')
        if w['account']: d.text(70,374,'Leave the email blank to use the one on your account.')
        for y,key,field,label in ((410,'news',1,'Email me Riftdogs news too (optional)'),(455,'privacy',2,'I agree to the privacy notice (required)')):
            d.text(70,y,('[X] ' if w[key] else '[ ] ')+label,GOLD if self.field == field else GREEN)
        d.text(WELCOME_PRIVACY_X,455,'Privacy',GREEN); d.fill(WELCOME_PRIVACY_X,477,len('Privacy')*11,1,GREEN)
        message = self.error or self.state()['register_error']
        if message: d.text(70,510,message[:94],GOLD if message.startswith(GOLD_PREFIXES) else RED)
        d.text(70,640,'Enter continues. ESC closes.')

    def install(self, run):
        """Run the update in the background while the window keeps drawing; False leaves the current version playable."""
        from riftdogs import VERSION
        latest,done = self.update,[]
        self.update,self.installing,self.auto_at = None,True,None
        self.error = f'Installing update {latest}… your saved game is kept'
        def work():
            try: done.append(run(latest))
            except Exception: done.append(False)
        threading.Thread(target=work,daemon=True).start()
        while not done:
            for _ in self.d.events(): pass  # The installer cannot be safely interrupted.
            self.draw()
            time.sleep(1/30)
        self.installing = False
        if done[0]: return True
        self.error = f'Update {latest} could not be installed; playing v{VERSION}. Details: update.log'
        return False

    def ask_update(self):
        """Only the update question (for --offline launches): 'update', 'skip' or 'quit'."""
        while self.update:
            for kind,value in self.d.events():
                choice = self.event(kind,value)
                if choice: return choice
                if not self.update: return 'skip'
            self.draw()
            time.sleep(1/60)
        return 'skip'

    def ask_email(self):
        """Only the email screen (for --offline launches): 'ok' or 'quit'."""
        while self.welcome is not None:
            for kind,value in self.d.events():
                if self.event(kind,value) == 'quit': return 'quit'
                if self.welcome is None: return 'ok'
            self.draw()
            time.sleep(1/60)
        return 'ok'

    def remember(self, mode):
        self.auto_at = None
        if self.config.get('last_mode') == mode: return
        self.config['last_mode'] = mode
        try: save_connection(self.config)
        except OSError: pass

    def fetch_relay(self):
        """Fetch The Relay's headlines in the background; the start screen never waits for them."""
        if self.news_started or not self.config.get('server'): return
        self.news_started = True
        threading.Thread(target=lambda: setattr(self, 'news', fetch_news(self.config['server']) or 'offline'), daemon=True).start()

    def choose(self):
        self.fetch_relay()
        while True:
            self.reopen_welcome()
            for kind,value in self.d.events():
                choice = self.event(kind,value)
                if choice:
                    if choice in ('online','offline'): self.remember(choice)
                    return choice
            if self.auto_at and time.monotonic() >= self.auto_at:
                if self.must_update_error(): self.auto_at = None   # a forced update arrived: do not connect by itself
                else:
                    self.remember('online')
                    return 'online'
            self.draw()
            time.sleep(1/60)
