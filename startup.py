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


PRIVACY_LINK = (995,680,90,30)   # x, y, w, h of the start screen's Privacy and Terms links
TERMS_LINK = (1095,680,80,30)


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


class StartScreen:
    deleting = None   # 'Delete my account' open: the commander name typed so far
    save_root = None  # the game's data folder (holds servers/<slot>); None: riftdogs.SAVE's folder
    def __init__(self, display, config, error='', update=None):
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

    def close(self):
        if self.texture:
            self.d.destroy(self.texture)
            self.texture = None

    def activate(self, index):
        if index == 0:
            if not self.config['server']:
                self.settings = True
                self.error = 'Enter your server address and private token file path.'
                return None
            if not Path(self.config['token_file']).expanduser().is_file():
                self.open_signup('New pilot? Copy your invite code and click Paste invite, or sign up on the host\'s Wi-Fi.')
                return None
            return 'online'
        if index == 1: return 'offline'
        self.settings = True
        self.error = ''
        return None

    def open_signup(self, message=''):
        self.signup = dict(name='',email='')
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
                self.update = None
                self.error = f'Update skipped for now: playing v{VERSION}. You will be asked again next launch.'
            return None
        if kind == 'down' and value == 27: return 'quit'
        if kind in ('down','click','text'): self.auto_at = None
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
                elif 390 <= x <= 710 and 490 <= y <= 530: self.remove_email()
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
        elif kind == 'click':
            x,y = value
            for index in range(3):
                if 110+index*300 <= x <= 390+index*300 and 615 <= y <= 663:
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
        if account is None: return
        self.error = 'Removing your email...'
        self.draw()
        try: remove_email(*account,allow_lan=True)
        except (RuntimeError,ValueError) as error: self.error = str(error); return
        except OSError: self.error = 'Could not reach the server. Your email was not removed; try again later.'; return
        self.error = 'Your email is removed from the server. You will get no Riftdogs news.'

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
        self.deleting = None
        self.error = f'Deleted {name} and its save from the server; its login and save copy are removed from this computer.'

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
            for x,label in ((70,'New pilot? Sign up'),(390,'Remove my email'),(730,'Delete my account')):
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
        else:
            if self.news_started:
                d.fill(40,478,1020,114,(5,15,25))
                for row,line in enumerate(relay_lines(self.news if isinstance(self.news,dict) else None) if self.news else [RELAY_MASTHEAD]):
                    d.text(55,486+row*26,line,GOLD if row == 0 else GREEN)
            for index,label in enumerate(('Online play','Offline play','Connection settings')):
                x = 110+index*300
                d.rect(x,615,280,48,GOLD if index == self.selected else GREEN)
                d.text(x+15,630,label,GOLD if index == self.selected else GREEN)
            if self.installing: pass
            elif self.auto_at: d.text(110,685,f'Connecting to online play in {max(0,self.auto_at-time.monotonic()):.0f}s - press any key to choose',GOLD)
            else: d.text(110,685,'Arrows choose / Enter opens / Click to play / ESC closes')
        if not self.settings and self.deleting is None and not self.update:
            for (x,y,w,h),label in ((PRIVACY_LINK,'Privacy'),(TERMS_LINK,'Terms')):
                d.text(x+5,y+5,label,GREEN); d.fill(x+5,y+h-4,len(label)*11,1,GREEN)
        if self.error: d.text(45,727,self.error[:94],GOLD if self.error.startswith(('Welcome','Invite accepted','Signing up','Installing','Opened','Accepting','Removing','Your email is removed','Deleting','Deleted')) else RED)
        d.present(d.r)

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
            for kind,value in self.d.events():
                choice = self.event(kind,value)
                if choice:
                    if choice in ('online','offline'): self.remember(choice)
                    return choice
            if self.auto_at and time.monotonic() >= self.auto_at:
                self.remember('online')
                return 'online'
            self.draw()
            time.sleep(1/60)
