"""Herbert on screen: the docked COMMS // HERBERT panel and the small flight card, with their line-art portraits.
Layout, word wrap and drawing only; what he says lives in herbert.py and the game decides when to show him."""
import ctypes as C
import gzip
from pathlib import Path

import cockpit
import examiner
from herbert import FACES

ASSETS = Path(__file__).resolve().parent/'assets'

# Colours: the game's GREEN and GOLD, the line-art cream, and the near-black the screens are cleared to.
GREEN, GOLD = (68, 227, 182), (255, 206, 113)
CREAM, ORANGE, BG = (243, 230, 200), (224, 108, 40), (4, 9, 18)
LINE_H, PAD = 21, 14
STA_BLUE = (127, 167, 198)

# Who is on screen: key -> (name, frame colour, faces, asset prefix).
SPEAKERS = {'herbert': ('HERBERT', ORANGE, FACES, 'herbert'),
            'varga': ('EXAMINER VARGA', STA_BLUE, examiner.FACES, 'varga')}

# The docked panel: under the goods table, above the Buy/Sell buttons (y >= 668).
MARKET_LIST = (24, 90, 860, 372)          # the goods table: names, prices, the selected row
PANEL = (12, 466, 1176, 196)              # x, y, w, h
PANEL_PORTRAIT = (224, 168)
PANEL_ROWS = 4
PANEL_CHARS = (PANEL[2]-PANEL_PORTRAIT[0]-PAD*2-PAD-16)//cockpit.CHAR_W

# The flight card: inside the canopy view, above its bottom rows (the guidance row is at y 450).
CARD = (286, 350, 628, 94)
CARD_PORTRAIT = (64, 48)
CARD_ROWS = 3
CARD_CHARS = (CARD[2]-CARD_PORTRAIT[0]-PAD*2-8)//cockpit.CHAR_W

# The card's place on non-flight screens while flying (the chart and the rest). On the chart (screen 1) the course
# details run down the right column to "Docking: allowed" (y 520, fuel figures included) and the "Planet profile"
# button starts at y 590, so the only free strip is between them: x 700-1190, y 522-588. A full-width card would
# cover the chart or those figures. This one has no title row (the portrait says who it is) and holds three rows of
# 35 characters. In flight the card is shown only on the flight view (CARD) and the chart (CARD_CHART); on every
# other screen it is hidden (see card_rect_for).
CARD_CHART = (700, 522, 490, 66)


def wrap(text, chars):
    """Word wrap to rows of at most `chars`; a word is split only when it is longer than a whole row."""
    rows, row = [], ''
    for word in str(text).split():
        while len(word) > chars:
            if row: rows.append(row); row = ''
            rows.append(word[:chars]); word = word[chars:]
        if not row: row = word
        elif len(row)+1+len(word) <= chars: row += ' '+word
        else: rows.append(row); row = word
    if row: rows.append(row)
    return rows


def card_chars(rect=CARD):
    return (rect[2]-CARD_PORTRAIT[0]-PAD*2-8)//cockpit.CHAR_W


def _titled(rect):
    return rect[3] >= 84          # a card too short for a title row goes without


def card_rows(rect=CARD):
    """Rows of text a card of this size holds (a titled card spends one row on the title)."""
    return max(1, min(CARD_ROWS, (rect[3]-3)//LINE_H-(1 if _titled(rect) else 0)))


def fits_card(text):
    """Does the text fit, uncut, in the card on the flight view and in the one on the chart?"""
    return all(len(wrap(text, card_chars(r))) <= card_rows(r) for r in (CARD, CARD_CHART))


def card_rect_for(mode):
    """Where the flight card goes on a screen: the flight view or the chart; None (hidden) anywhere else."""
    return {'flight': CARD, 'cruise': CARD, 'map': CARD_CHART}.get(mode)


def bind(lib, name, restype, args):
    """As riftdogs.bind (not imported from there: run as a script, the game is __main__, not riftdogs)."""
    f = getattr(lib, name)
    f.restype, f.argtypes = restype, args
    return f


def load_portraits(display, who='herbert'):
    """face -> texture, from assets/<who>-<face>.bmp.gz. A missing or bad file is left out, never an error."""
    portraits = {}
    try: bind(display.sdl, 'SDL_SetHint', C.c_int, [C.c_char_p, C.c_char_p])(b'SDL_RENDER_SCALE_QUALITY', b'1')   # smooth when shrunk
    except (AttributeError, C.ArgumentError): pass
    _, _, faces, prefix = SPEAKERS[who]
    for face in faces:
        try:
            raw = gzip.decompress((ASSETS/f'{prefix}-{face}.bmp.gz').read_bytes())
            buffer = C.create_string_buffer(raw)
            rw = bind(display.sdl, 'SDL_RWFromConstMem', C.c_void_p, [C.c_void_p, C.c_int])(buffer, len(raw))
            surface = bind(display.sdl, 'SDL_LoadBMP_RW', C.c_void_p, [C.c_void_p, C.c_int])(rw, 1) if rw else None
            if not surface: continue
            texture = display.texture(display.r, surface)
            display.free(surface)
            if texture: portraits[face] = texture
        except (OSError, ValueError, EOFError, C.ArgumentError): pass
    return portraits


def _portrait(d, portraits, face, x, y, w, h, frame=CREAM):
    """The face in a cream frame, or just the frame when it is missing; scanlines over it when it is there."""
    texture = portraits.get(face)
    d.fill(x, y, w, h, BG)
    if texture:
        d.copy(d.r, texture, None, (C.c_int*4)(x, y, w, h))
        bind(d.sdl, 'SDL_SetRenderDrawBlendMode', C.c_int, [C.c_void_p, C.c_int])(d.r, 1)
        d.color(d.r, 0, 0, 0, 55)
        for row in range(y+1, y+h, 3): d.drawline(d.r, x, row, x+w-1, row)
        bind(d.sdl, 'SDL_SetRenderDrawBlendMode', C.c_int, [C.c_void_p, C.c_int])(d.r, 0)
    d.rect(x, y, w, h, frame)


def _title(d, x, y, small=False, who='herbert'):
    name, colour = SPEAKERS[who][:2]
    if not small: d.text(x, y, 'COMMS //', ORANGE if who == 'herbert' else colour); x += 9*cockpit.CHAR_W
    d.text(x, y, name, GOLD if who == 'herbert' else CREAM)


def draw_panel(d, portraits, face, lines, choices, selected, who='herbert'):
    """The docked comms panel. Returns [((x, y, w, h), index)] for each choice's button."""
    px, py, pw, ph = PANEL
    d.fill(px, py, pw, ph, BG)
    colour = SPEAKERS[who][1]
    inner = (96, 52, 24) if who == 'herbert' else tuple(c*2//5 for c in colour)
    d.rect(px, py, pw, ph, colour)
    d.rect(px+2, py+2, pw-4, ph-4, inner)
    _portrait(d, portraits, face, px+PAD, py+PAD, *PANEL_PORTRAIT)
    x0 = px+PAD*2+PANEL_PORTRAIT[0]+PAD-PAD//2
    _title(d, x0, py+10, who=who)
    d.line(x0, py+36, px+pw-16, py+36, inner)
    rows = [row for line in lines for row in wrap(line, PANEL_CHARS)][-PANEL_ROWS:]
    for i, row in enumerate(rows): d.text(x0, py+42+i*LINE_H, row, CREAM)
    hits, x, y = [], x0, py+134
    for i, label in enumerate(choices):
        w = len(label)*cockpit.CHAR_W+20
        if x+w > px+pw-16 and x > x0: x, y = x0, y+30
        on = i == selected
        d.fill(x, y, w, 26, (40, 28, 14) if on else BG)
        d.rect(x, y, w, 26, GOLD if on else GREEN)
        d.text(x+10, y+2, label, GOLD if on else GREEN)
        hits.append(((x, y, w, 26), i))
        x += w+10
    return hits


def draw_card(d, portraits, face, text, rect=CARD, who='herbert'):
    """The small card shown over the canopy or the chart while flying."""
    x, y, w, h = rect
    d.fill(x, y, w, h, BG)
    d.rect(x, y, w, h, SPEAKERS[who][1])
    px, py = x+PAD//2, y+(h-CARD_PORTRAIT[1])//2
    _portrait(d, portraits, face, px, py, *CARD_PORTRAIT)
    tx = px+CARD_PORTRAIT[0]+PAD-4
    titled = _titled(rect)
    if titled: _title(d, tx, y+3, small=True, who=who)
    chars, rows = card_chars(rect), wrap(text, card_chars(rect))
    if len(rows) > card_rows(rect):
        rows = rows[:card_rows(rect)]
        rows[-1] = rows[-1][:chars-3].rstrip()+'...'
    # Untitled (the chart's short card): a little tighter, so the third row's letters clear the frame.
    top, pitch = (y+3, LINE_H) if titled else (y+1, LINE_H-1)
    for i, row in enumerate(rows): d.text(tx, top+(i+titled)*pitch, row, CREAM)
