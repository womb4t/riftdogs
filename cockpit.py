"""The 0.14 cockpit's layout: the top bar of screen keys, the content area under it and the flight cockpit's panels.
Plain numbers and a little arithmetic; nothing here draws. Run the tests with python3 -m unittest -v test_chrome."""

TOP_BAR_Y = 6       # the top bar's buttons: y and height
TOP_BAR_H = 32
# The area below the top bar and above the status, message and ticker rows: x, y, width, height.
CONTENT = (12, 52, 1176, 650)

# The flight cockpit (x, y, width, height). The forward view sits in the canopy, centre top; the TARGET and SHIP
# panels to its left; RADAR, TARGET BEARING and HEAT to its right; the bottom row under them all.
VIEW = (274, 52, 652, 448)
VIEW_CENTRE = (VIEW[0]+VIEW[2]//2, VIEW[1]+VIEW[3]//2)   # (600, 276)
VIEW_SCALE = 420      # pixels a unit of x/z: an object 1 m across at 420 m is a pixel wide
TARGET_PANEL = (12, 52, 250, 212)
SHIP_PANEL = (12, 276, 250, 224)
RADAR = (938, 52, 250, 194)
BEARING = (938, 258, 250, 118)
HEAT = (938, 388, 250, 112)
SHIP_ICON = (12, 512, 170, 178)
GAUGES = (194, 512, 170, 178)
MIDDLE = (376, 512, 528, 178)
MODES = (916, 512, 140, 178)
HOLD = (1068, 512, 120, 178)
STATUS_Y = 700        # the status line: speed, fuel, weapon, missiles, course, key hints
MESSAGE_Y = 726       # the ship's message line; The Relay's ticker stays below it

TITLE = 'RIFTDOGS'
TITLE_X = 12
CHAR_W = 11         # the monospace font's glyph width
PAD = 5             # a button's text sits this far in from each side
GAP = 6             # between buttons
STATUS_X = 900      # the system / economy and credits block starts here, at the top bar's right end
BADGE = ' 9+'       # the most the 5 COMMS button's unread count adds to its label
# The number-row screens, left to right.
LABELS = ((1, '1 NAV'), (2, '2 VMS'), (3, '3 MONEY'), (4, '4 MENU'), (5, '5 COMMS'),
          (6, '6 LEDGER'), (7, '7 CARGO'), (8, '8 ENG'), (9, '9 MAN'))


def button_width(label, key=None):
    """Wide enough for the label (and, on 5 COMMS, the unread count) with PAD either side."""
    chars = len(label)+(len(BADGE) if key == 5 else 0)
    return chars*CHAR_W+2*PAD


def top_bar():
    """The top bar's buttons, left to right after the title: [(x, width, label, key)]."""
    x = TITLE_X+len(TITLE)*CHAR_W+2*GAP
    buttons = []
    for key, label in LABELS:
        w = button_width(label, key)
        buttons.append((x, w, label, key))
        x += w+GAP
    assert buttons[-1][0]+buttons[-1][1] < STATUS_X, 'the top bar runs into the status block'
    return buttons


# ---------- the middle screen: seven pages the pilot picks ----------
# It never turns its own page. A page that needs you lights up in the mode list; \ jumps to the first lit one in
# JUMP_ORDER. Viewing a page clears its light until its condition ends and comes back.
PAGES = ('docking', 'target', 'comms', 'nav', 'cargo', 'market', 'combat')
PAGE_NAMES = {page: page.upper() for page in PAGES}
JUMP_ORDER = ('combat', 'comms', 'docking')
DOCKING_RANGE = 10000   # metres: within station control range the Docking page lights
CORRIDOR_RANGE = 2500   # metres: the Docking page's approach corridor runs from the port out to here
MODE_ROW_H = 24         # the mode list: a row a page, under a 6 px margin
ARROW_W = 26            # the middle screen header's back and forward arrows: hit areas this wide, the header's height
HEADER_H = 24


def mode_rows():
    """The mode list's rows: [(page, (x, y, w, h))], top to bottom."""
    x, y, w, _ = MODES
    return [(page, (x+2, y+4+i*MODE_ROW_H, w-4, MODE_ROW_H)) for i, page in enumerate(PAGES)]


def page_arrows():
    """The middle screen header's arrows: (back, forward) rectangles."""
    x, y, w, _ = MIDDLE
    return (x+2, y+2, ARROW_W, HEADER_H-2), (x+w-2-ARROW_W, y+2, ARROW_W, HEADER_H-2)


class MiddleScreen:
    """Which page is shown and which are lit. The game hands update() each page's condition every tick."""
    def __init__(self, page='docking'):
        self.page = 'docking'
        self.lit = set()
        self._on = set()     # pages whose condition is true now
        self._seen = set()   # of those, the ones viewed since their condition came on
        self.select(page)

    def select(self, page):
        if page not in PAGES: raise ValueError(f'no such page: {page!r}')
        self.page = page
        if page in self._on: self._seen.add(page)
        self.lit.discard(page)

    def step(self, delta):
        """[ and ]: the previous or next page, wrapping round."""
        self.select(PAGES[(PAGES.index(self.page)+delta) % len(PAGES)])

    def update(self, conditions):
        for page in PAGES:
            if not conditions.get(page):
                self._on.discard(page); self._seen.discard(page); self.lit.discard(page)
                continue
            self._on.add(page)
            if page == self.page: self._seen.add(page)
            if page in self._seen: self.lit.discard(page)
            else: self.lit.add(page)

    def jump(self):
        """\\: to the first lit page in JUMP_ORDER; False when none is lit."""
        for page in JUMP_ORDER:
            if page in self.lit:
                self.select(page)
                return True
        return False
