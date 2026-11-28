"""The Riftdogs fleet: six ship hulls as wireframe solids, and who flies which. Pure maths, no SDL and no game
import, so the game, the tests and tools can all use it.

Ship-local metres: the nose points +z, up is +y and right is +x. The camera's frame is x right, y DOWN the screen,
z ahead, so an upright ship's +y maps to camera -y (see basis and paint).
Each model is centred on its middle along z. Every hull is built from small convex solids (boxes, tapered
sections, cylinders, slab fins, a dish), each face a convex planar polygon with its outward unit normal, its
corners in order anticlockwise seen from outside. Thin parts with no faces (antennas, masts, truss bracing, claw
fingers) are bare `lines`.
"""
import collections
import functools
import math
import random
import zlib

from stations import _cross, _dot, _unit

NAMES = ('kestrel', 'longreach', 'harrier', 'wayfarer', 'tr47', 'claw')
TRADERS = ('longreach', 'wayfarer', 'tr47', 'claw')
PILOT = 'kestrel'
POLICE = 'harrier'

# verts: (x, y, z) floats; faces: ((vertex indices round a convex planar polygon), outward unit normal);
# lines: (i, j) edges on no face; length: nose-to-tail extent in metres.
Model = collections.namedtuple('Model', 'verts faces lines length')


def trader_model(shipment_id):
    """A computer trader's hull, fixed by its shipment so every game shows the same ship for it."""
    return TRADERS[zlib.crc32(str(shipment_id).encode()) % len(TRADERS)]


def pirate_model(rng=random):
    """Pirates fly anything."""
    return rng.choice(NAMES)


def disabled_model(rng=random):
    """A disabled ship is anything but a police Harrier."""
    return rng.choice([n for n in NAMES if n != POLICE])


# ---- the builder --------------------------------------------------------------------------------------------------

def _key(x, y, z):
    return (round(x, 6) + 0.0, round(y, 6) + 0.0, round(z, 6) + 0.0)


def _plane_normal(points):
    """The unit normal of a planar polygon (Newell's method), by the right-hand rule round its corners."""
    n = [0.0, 0.0, 0.0]
    for i, (x, y, z) in enumerate(points):
        u, v, w = points[(i+1) % len(points)]
        n[0] += (y - v) * (z + w); n[1] += (z - w) * (x + u); n[2] += (x - u) * (y + v)
    length = math.sqrt(sum(a*a for a in n))
    return tuple(a / length + 0.0 for a in n)


class _Builder:
    def __init__(self):
        self.verts, self.index = [], {}
        self.faces = []    # (points, normal, centre of the solid the face belongs to)
        self.lines = []    # (a, b) point pairs

    def solid(self, polygons):
        """A convex solid from its faces' corner lists; each normal points away from the solid's centre (the mean
        of its distinct corners), and a face wound the other way is turned round."""
        corners = {_key(*p) for poly in polygons for p in poly}
        centre = tuple(sum(p[i] for p in corners) / len(corners) for i in range(3))
        for poly in polygons:
            poly = [_key(*p) for p in poly]
            normal = _plane_normal(poly)
            middle = tuple(sum(p[i] for p in poly) / len(poly) for i in range(3))
            if sum(normal[i] * (middle[i] - centre[i]) for i in range(3)) < 0:
                poly.reverse()
                normal = tuple(-a + 0.0 for a in normal)
            self.faces.append((poly, normal, centre))

    def prism(self, rings):
        """A solid between corresponding rings of corners (each ring a planar convex polygon, consecutive rings
        with parallel matching sides, so every side face is a planar trapezoid), capped at both ends."""
        polys = [rings[0], rings[-1]]
        for a, b in zip(rings, rings[1:]):
            n = len(a)
            polys += [(a[i], a[(i+1) % n], b[(i+1) % n], b[i]) for i in range(n)]
        self.solid(polys)

    def box(self, x0, x1, y0, y1, z0, z1):
        self.prism([[(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)] for z in (z0, z1)])

    def taper(self, sections, chamfer=0.3):
        """A hull along z through (z, half_w, y_low, y_high) sections: a flattened octagon with 45-degree corners
        cut `chamfer` of the way into the smaller half-size, or a plain rectangle when chamfer is 0."""
        rings = []
        for z, w, lo, hi in sections:
            c = chamfer * min(w, (hi - lo) / 2)
            if c:
                rings.append([(w-c, hi, z), (w, hi-c, z), (w, lo+c, z), (w-c, lo, z),
                              (c-w, lo, z), (-w, lo+c, z), (-w, hi-c, z), (c-w, hi, z)])
            else:
                rings.append([(w, hi, z), (w, lo, z), (-w, lo, z), (-w, hi, z)])
        self.prism(rings)

    def cylinder(self, z0, z1, r, n=8, axis='z', at=(0.0, 0.0)):
        """An n-sided cylinder running from z0 to z1 along `axis`; `at` gives the other two coordinates in order
        (x, y for a z axis; y, z for x; x, z for y). Corners sit half a step off the axes, so an 8-sided one has
        flat sides square to both."""
        def point(t, u, v):
            return {'z': (u, v, t), 'x': (t, u, v), 'y': (u, t, v)}[axis]
        rings = []
        for t in (z0, z1):
            rings.append([point(t, at[0] + r*math.cos(math.pi*(2*i+1)/n), at[1] + r*math.sin(math.pi*(2*i+1)/n))
                          for i in range(n)])
        self.prism(rings)

    def fin(self, points, plane='zy', at=0.0, thick=2.0):
        """A slab from a convex 2D outline, `thick` metres through, centred on `at`: in the 'zy' plane (a
        vertical fin, outline as (z, y), through x) or the 'xz' plane (a wing, outline as (x, z), through y)."""
        def point(p, d):
            return (at + d, p[1], p[0]) if plane == 'zy' else (p[0], at + d, p[1])
        self.prism([[point(p, d) for p in points] for d in (-thick/2, thick/2)])

    def dish(self, centre, r, n=8):
        """A shallow bowl opening upwards, its rim round `centre`."""
        x, y, z = centre
        rings = []
        for rr, yy in ((r * 0.35, y - r * 0.3), (r, y)):
            rings.append([(x + rr*math.cos(math.pi*(2*i+1)/n), yy, z + rr*math.sin(math.pi*(2*i+1)/n))
                          for i in range(n)])
        self.prism(rings)

    def line(self, a, b):
        self.lines.append((_key(*a), _key(*b)))

    def finish(self):
        """The Model, moved to centre it along z, and each face's solid centre (for the tests)."""
        zs = [p[2] for poly, _, _ in self.faces for p in poly] + [p[2] for line in self.lines for p in line]
        shift = -(max(zs) + min(zs)) / 2
        verts, index = [], {}

        def vertex(p):
            key = _key(p[0], p[1], p[2] + shift)
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            return index[key]
        faces = tuple((tuple(vertex(p) for p in poly), normal) for poly, normal, _ in self.faces)
        centres = tuple(_key(c[0], c[1], c[2] + shift) for _, _, c in self.faces)
        on_faces = {frozenset((idx[k], idx[(k+1) % len(idx)])) for idx, _ in faces for k in range(len(idx))}
        lines, seen = [], set(on_faces)
        for a, b in self.lines:
            pair = (vertex(a), vertex(b))
            if frozenset(pair) not in seen:
                seen.add(frozenset(pair))
                lines.append(pair)
        return Model(tuple(verts), faces, tuple(lines), max(zs) - min(zs)), centres


# ---- the six hulls (laid out tail at z = 0, nose at +z; centred afterwards) ------------------------------------------

def _drive_and_tail(b, z_hull, fin_z, fin_top, wing_z, wing_y, wing_span, hull_w):
    """The Riftdogs family's back end: a round main drive, a swept tail fin and short swept wings."""
    b.cylinder(0, z_hull, 9, at=(0.0, 1.0))
    b.fin([(fin_z, 10), (fin_z + 18, 10), (fin_z + 6, fin_top), (fin_z - 2, fin_top)])
    for s in (1, -1):
        b.fin([(s*hull_w, wing_z), (s*hull_w, wing_z + 16), (s*wing_span, wing_z - 3)], plane='xz', at=wing_y)


def _kestrel(b):
    # RD-1: drive, an aft block, an open truss carrying two pods on the starboard side (model -x), a big forward hull, wedge nose.
    _drive_and_tail(b, 12, 15, 22, 14, -6, 26, 11)
    b.taper([(12, 11, -9, 10), (34, 11, -9, 10)])
    b.box(-4, 4, 6, 10, 34, 60)                       # the spine over the truss
    for x in (-6, 6):                                  # the truss: two lower rails, cross-braced on the port side (model +x)
        b.line((x, -8, 34), (x, -8, 60))
    b.line((6, -8, 34), (4, 6, 47)); b.line((4, 6, 47), (6, -8, 60))
    b.line((6, -8, 47), (4, 6, 34)); b.line((4, 6, 60), (6, -8, 47))
    b.box(-22, -6, -8, 6, 35, 47); b.box(-22, -6, -8, 6, 47, 59)   # two cargo pods, starboard (model -x)
    b.taper([(60, 13, -11, 12), (92, 13, -11, 12), (120, 3, -7, -1)])
    b.taper([(84, 7, 11, 16), (100, 4, 7, 9)], chamfer=0)          # the canopy, down the nose's slope
    b.box(-4, 4, -16, -11, 66, 86)                     # the belly pod
    for x in (-3, 0):                                  # twin antennas
        b.line((x, 10, 40 + x), (x, 26 + 2*x, 40 + x))
    b.line((3, 12, 76), (3, 17, 76))                   # the small dish on its post
    b.dish((3, 19, 76), 5, n=6)


def _longreach(b):
    # RD-2: the Kestrel stretched; a long open cargo frame round a row of containers, boxes on top, a belly tank.
    _drive_and_tail(b, 12, 15, 24, 14, -6, 26, 12)
    b.taper([(12, 12, -10, 10), (34, 12, -10, 10)])
    z0, z1 = 34, 100
    for x in (-12, 12):                                # the frame: four rails, a zigzag down each side
        for y in (-10, 10):
            b.line((x, y, z0), (x, y, z1))
        for k in range(5):
            za, zc = z0 + (z1 - z0) * k / 5, z0 + (z1 - z0) * (k + 1) / 5
            ya, yc = (-10, 10) if k % 2 == 0 else (10, -10)
            b.line((x, ya, za), (x, yc, zc))
    for za, zc in ((35, 57), (57, 78), (78, 99)):      # containers in the frame, a row of boxes on top
        b.box(-10, 10, -9, 9, za, zc)
        b.box(-8, 8, 10, 15, za, zc)
    b.taper([(100, 13, -11, 12), (122, 13, -11, 12), (145, 3, -7, -1)])
    b.taper([(108, 7, 11, 16), (124, 4, 7, 9)], chamfer=0)
    b.cylinder(50, 90, 5, n=6, at=(0.0, -15.0))       # the belly tank


def _wayfarer(b):
    # RD-4: a chunky block hull, crates stacked on both sides, boxes on top and a big dish on a mast.
    _drive_and_tail(b, 12, 15, 26, 16, -8, 30, 14)
    b.taper([(12, 14, -12, 12), (100, 14, -12, 12), (125, 4, -8, 1)], chamfer=0.25)
    for s in (1, -1):                                  # crates on each side: a row of two, one stacked on top
        b.box(s*14, s*22, -12, 0, 30, 50); b.box(s*14, s*22, -12, 0, 50, 70)
        b.box(s*14, s*21, 0, 9, 34, 62)
    b.box(-8, 8, 12, 17, 26, 46); b.box(-8, 8, 12, 17, 70, 90)   # boxes on top
    b.line((0, 12, 58), (0, 26, 58))                   # the mast
    b.dish((0, 30, 58), 18)


def _harrier(b):
    # RD-3: a sleek wedge, long canopy, swept delta wings with intakes, twin raked tail fins, small fins below.
    b.taper([(0, 5, -4, 4), (22, 7, -5, 5), (42, 5, -4, 3), (60, 1, -2, -1)])
    b.taper([(26, 3.5, 4, 7), (46, 2, 2, 4)], chamfer=0)               # the long canopy
    for s in (1, -1):
        b.fin([(s*5, 6), (s*5, 36), (s*23, 6), (s*23, 1)], plane='xz', at=-2.0, thick=1.2)   # swept delta wings
        b.box(s*6, s*10, -4, 2, 20, 34)                                 # the intakes
        b.fin([(2, 3), (12, 3), (5, 17), (0, 17)], plane='zy', at=s*4, thick=1.2)   # raked tail fins
        b.fin([(6, -4), (16, -4), (8, -10)], plane='zy', at=s*3, thick=1.0)      # small fins underneath


def _tr47(b):
    # TR-47 Mastiff: a long hull, a docking ring amidships, two cargo pods by a truss, twin engines and a tall tail fin.
    for x in (-9, 9):                                  # the twin engines
        b.cylinder(0, 20, 8, at=(x, 0.0))
    b.box(-14, 14, -7, 7, 20, 30)                      # the engine mount
    b.fin([(20, 7), (32, 7), (26, 28), (19, 28)])      # the tall tail fin
    z0, z1 = 30, 78
    for x in (-5, 5):                                  # the truss between the pods
        for y in (-5, 5):
            b.line((x, y, z0), (x, y, z1))
    for k in range(4):
        za, zc = z0 + (z1 - z0) * k / 4, z0 + (z1 - z0) * (k + 1) / 4
        b.line((5, -5, za), (5, 5, zc)); b.line((-5, 5, za), (-5, -5, zc))
        b.line((-5, 5, za), (5, 5, zc))
    for s in (1, -1):                                  # the two cargo pods
        b.box(s*6, s*20, -9, 8, 33, 76)
    b.cylinder(-14, 14, 11, at=(0.0, 86.0), axis='x')  # the docking ring
    b.taper([(78, 10, -10, 9), (112, 10, -10, 9), (124, 8, -9, 6), (132, 4, -6, 0)], chamfer=0.35)
    b.line((0, 9, 100), (0, 22, 100))                  # the sensor mast and its dish
    b.line((0, 9, 100), (-4, 14, 100))
    b.dish((-4, 16, 100), 4, n=6)


def _claw(b):
    # The claw freighter: a flat wedge hull, three crates slung on the right, engine pods on booms, two claw arms.
    b.taper([(0, 16, -5, 5), (62, 20, -6, 6), (84, 13, -6, 5), (96, 6, -5, 0)])
    b.taper([(68, 9, 4, 10), (84, 6, 2, 7)], chamfer=0)        # the raised cockpit
    for za in (10, 32, 54):                            # three crates slung on the right
        b.box(22, 34, -16, -2, za, za + 20)
        b.line((19, 4, za + 10), (28, -2, za + 10))
    for s in (1, -1):                                  # engine pods out on booms
        b.cylinder(-6, 16, 6, at=(s*32, 4.0))
        b.line((s*16, 2, 6), (s*27, 4, 4)); b.line((s*17, 2, 16), (s*27, 4, 12))
        elbow, wrist = (s*14, -12, 102), (s*12, -12, 114)  # a claw arm forward, two fingers
        b.line((s*9, -5, 88), elbow); b.line(elbow, wrist)
        b.line(wrist, (s*16, -10, 122)); b.line(wrist, (s*8, -10, 122))
    b.line((0, 6, 44), (0, 9, 44))
    b.dish((0, 11, 44), 8, n=6)


_SHAPES = {'kestrel': _kestrel, 'longreach': _longreach, 'harrier': _harrier, 'wayfarer': _wayfarer,
           'tr47': _tr47, 'claw': _claw}


@functools.lru_cache(maxsize=None)
def _built(name):
    b = _Builder()
    _SHAPES[name](b)
    return b.finish()


def model(name):
    """The named hull's Model. Shared and cached: don't change it."""
    return _built(name)[0]


def _face_centres(name):
    """For each face of the model, the centre of the solid it belongs to (its normal points away from it)."""
    return _built(name)[1]


@functools.lru_cache(maxsize=None)
def edges(name):
    """Every face edge and every bare line of the model, each once."""
    m, out, seen = model(name), [], set()
    pairs = [(idx[k], idx[(k+1) % len(idx)]) for idx, _ in m.faces for k in range(len(idx))] + list(m.lines)
    for i, j in pairs:
        if frozenset((i, j)) not in seen:
            seen.add(frozenset((i, j)))
            out.append((i, j))
    return tuple(out)


@functools.lru_cache(maxsize=None)
def _top_layout(name, width, height):
    """top_view's working: ({vertex index: (x, y) on screen}, the (i, j) edges drawn). Cached."""
    m = model(name)
    up = [idx for idx, normal in m.faces if normal[1] > 0]
    on_top = {i for idx in up for i in idx}
    seen, pairs = set(), []
    candidates = [(idx[k], idx[(k+1) % len(idx)]) for idx in up for k in range(len(idx))]
    candidates += [(i, j) for i, j in m.lines if i in on_top and j in on_top]
    for i, j in candidates:
        if frozenset((i, j)) not in seen:
            seen.add(frozenset((i, j)))
            pairs.append((i, j))
    if not pairs:
        return {}, ()
    flat = {i: (-m.verts[i][0], -m.verts[i][2]) for i in on_top}
    xs = [p[0] for p in flat.values()]; ys = [p[1] for p in flat.values()]
    w, h = max(xs)-min(xs), max(ys)-min(ys)
    k = min(width/w if w else math.inf, height/h if h else math.inf)
    cx, cy = (max(xs)+min(xs))/2, (max(ys)+min(ys))/2
    return {i: ((x-cx)*k, (y-cy)*k) for i, (x, y) in flat.items()}, tuple(pairs)


@functools.lru_cache(maxsize=None)
def top_view(name, width, height):
    """The model seen from above, nose up, as ((x1, y1), (x2, y2)) segments scaled to fit width x height and centred
    on (0, 0): the edges of the faces that look up, plus the bare lines that run between them. Seen from above with
    the nose up the starboard side is on the right, so model -x is screen +x. Cached."""
    pt, pairs = _top_layout(name, width, height)
    return tuple((pt[i], pt[j]) for i, j in pairs)


# ---- painting a model for the camera ------------------------------------------------------------------------------

def _finite(v):
    return all(isinstance(c, (int, float)) and math.isfinite(c) for c in v)


def basis(facing, up):
    """Camera-relative unit vectors (ex, ey, ez) for the ship's local x, y and z: ez along `facing`, ey `up` made
    perpendicular to it, ex = ey x ez. A bad or parallel `up` is replaced by any perpendicular."""
    if len(facing) != 3 or not _finite(facing) or _dot(facing, facing) <= 0 or not math.isfinite(_dot(facing, facing)):
        raise ValueError(f'a ship needs a facing, not {facing!r}')
    ez = _unit(facing)
    ey = None
    if len(up) == 3 and _finite(up):
        d = _dot(up, ez)
        v = tuple(u - d*e for u, e in zip(up, ez))
        if _dot(v, v) > 1e-12 * max(1.0, _dot(up, up)):
            ey = _unit(v)
    if ey is None:
        least = min(range(3), key=lambda i: abs(ez[i]))
        axis = tuple(1.0 if i == least else 0.0 for i in range(3))
        ey = _unit(_cross(ez, axis))
    ex = _cross(ey, ez)
    return ex, ey, ez


def _to_view(m, centre, ex, ey, ez):
    cx, cy, cz = centre
    return [[cx + x*ex[0] + y*ey[0] + z*ez[0], cy + x*ex[1] + y*ey[1] + z*ez[1], cz + x*ex[2] + y*ey[2] + z*ez[2]]
            for x, y, z in m.verts]


# ---- hidden surfaces: a BSP tree per hull ----------------------------------------------------------------------
# The hulls are overlapping convex solids, which no sort by depth can draw correctly from every side. A binary
# space partition, built once per hull, can: every face is filed against the planes of the others (split where it
# crosses one), and walking the tree away from the camera's side of each plane gives an exact far-to-near order.

_EPS = 1e-6


class _Node:
    __slots__ = ('n', 'd', 'same', 'opp', 'lines', 'front', 'back', 'front_rest', 'back_rest')

    def __init__(self, n, d):
        self.n, self.d = n, d
        self.same, self.opp, self.lines = [], [], []   # pieces facing along n, against it; bare lines in the plane
        self.front = self.back = None
        self.front_rest = self.back_rest = ()   # bare lines in a half-space with no faces


class _Verts:
    """The hull's vertices (the model's first, index for index), plus the points where pieces were split."""
    def __init__(self, verts):
        self.list = list(verts)
        self.index = {v: i for i, v in enumerate(self.list)}

    def add(self, p):
        key = _key(*p)
        if key not in self.index:
            self.index[key] = len(self.list)
            self.list.append(key)
        return self.index[key]


def _split_face(piece, n, d, verts):
    """A piece (idx, real, face) against the plane n.p = d: (front, back), either None. `real[k]` is the model edge
    (its ends' indices, low first) that the piece's edge from idx[k] to the next lies on, or None along a cut made by
    a split (not drawn)."""
    idx, real, face = piece
    pts = verts.list
    side = [_dot(n, pts[i]) - d for i in idx]
    if all(s >= -_EPS for s in side): return piece, None
    if all(s <= _EPS for s in side): return None, piece
    count = len(idx)
    front, back = ([], []), ([], [])   # corner indices, and whether the edge leaving each is real
    for k in range(count):
        a, b, sa, sb, r = idx[k], idx[(k+1) % count], side[k], side[(k+1) % count], real[k]
        if sa > _EPS:
            front[0].append(a); front[1].append(r)
        elif sa < -_EPS:
            back[0].append(a); back[1].append(r)
        else:   # on the plane: in both; its edge onwards is real on the side b lies (or both, b on the plane too)
            front[0].append(a); front[1].append(r if sb >= -_EPS else None)
            back[0].append(a); back[1].append(r if sb <= _EPS else None)
        if (sa > _EPS and sb < -_EPS) or (sa < -_EPS and sb > _EPS):
            t = sa / (sa - sb)
            c = verts.add(tuple(pts[a][i] + t*(pts[b][i] - pts[a][i]) for i in range(3)))
            front[0].append(c); front[1].append(r if sb > 0 else None)   # c on to b is the rest of a real edge;
            back[0].append(c); back[1].append(r if sb < 0 else None)     # on the other side it runs along the cut
    out = []
    for ids, flags in (front, back):
        keep = [k for k in range(len(ids)) if ids[k] != ids[(k+1) % len(ids)]]   # drop repeated corners
        ids, flags = [ids[k] for k in keep], [flags[k] for k in keep]
        out.append((tuple(ids), tuple(flags), face) if len(set(ids)) >= 3 else None)
    return out[0], out[1]


def _split_line(line, n, d, verts):
    """A bare line (a, b, which) against the plane n.p = d: (front, back), either None; `which` names the model line."""
    a, b, which = line
    pts = verts.list
    sa, sb = _dot(n, pts[a]) - d, _dot(n, pts[b]) - d
    if sa >= -_EPS and sb >= -_EPS: return line, None
    if sa <= _EPS and sb <= _EPS: return None, line
    t = sa / (sa - sb)
    c = verts.add(tuple(pts[a][i] + t*(pts[b][i] - pts[a][i]) for i in range(3)))
    return ((a, c, which), (c, b, which)) if sa > 0 else ((c, b, which), (a, c, which))


def _build(pieces, lines, planes, verts):
    """The tree over these face pieces and bare lines; `planes[face]` is (n, d) of each model face."""
    if not pieces:
        return None, lines
    best, chosen = None, None
    seen = set()
    for piece in pieces:
        n, d = planes[piece[2]]
        key = (_key(*n), round(d, 6))
        if key in seen: continue
        seen.add(key)
        front = back = cut = 0
        for other in pieces:
            side = [_dot(n, verts.list[i]) - d for i in other[0]]
            f, b = any(s > _EPS for s in side), any(s < -_EPS for s in side)
            cut += f and b; front += f and not b; back += b and not f
        score = 8*cut + abs(front - back)
        if best is None or score < best:
            best, chosen = score, (n, d)
    n, d = chosen
    node = _Node(n, d)
    fronts, backs, front_lines, back_lines = [], [], [], []
    for piece in pieces:
        pn, pd = planes[piece[2]]
        if all(abs(_dot(n, verts.list[i]) - d) <= _EPS for i in piece[0]):
            (node.same if _dot(pn, n) > 0 else node.opp).append(piece)
            continue
        f, b = _split_face(piece, n, d, verts)
        if f: fronts.append(f)
        if b: backs.append(b)
    for line in lines:
        if all(abs(_dot(n, verts.list[i]) - d) <= _EPS for i in line[:2]):
            node.lines.append(line)
            continue
        f, b = _split_line(line, n, d, verts)
        if f: front_lines.append(f)
        if b: back_lines.append(b)
    node.front, rest_f = _build(fronts, front_lines, planes, verts)
    node.back, rest_b = _build(backs, back_lines, planes, verts)
    # lines left over in an empty half-space (no faces there) stay with this node, drawn on its side
    node.front_rest, node.back_rest = rest_f, rest_b
    return node, []


class _Tree:
    """A hull's BSP tree flattened: `verts`, the hull's vertices and the split points; the planes of its nodes in
    preorder (`nx`, `ny`, `nz`, `d`); `loose`, bare lines outside every node; and `orders`, a cache of drawing
    orders keyed by which side of each plane the camera is on (the order changes only when it crosses one)."""
    __slots__ = ('verts', 'planes', 'root', 'nodes', 'nx', 'ny', 'nz', 'd', 'loose', 'orders')

    def order(self, cam, dropped=frozenset()):
        """For a camera at `cam` in the hull's frame: (steps, tidy), every step as (op, face) (face None for a
        bare line), and the ops alone, tidied (see _tidy), leaving out the faces in `dropped` and their edges."""
        x, y, z = cam
        sides = tuple([(a*x + b*y + c*z > e) - (a*x + b*y + c*z < e)
                       for a, b, c, e in zip(self.nx, self.ny, self.nz, self.d)])
        got = self.orders.get((sides, dropped))
        if got is not None: return got
        steps = [(op, None) for op in self.loose]
        add, extend = steps.append, steps.extend
        def walk(k):
            node = self.nodes[k]
            side = sides[k]
            if side > 0:
                if node.back is not None: walk(node.back)
                extend(node.back_rest); extend(node.lines); extend(node.same); extend(node.front_rest)
                if node.front is not None: walk(node.front)
            else:
                if node.front is not None: walk(node.front)
                extend(node.front_rest); extend(node.lines)
                if side < 0: extend(node.opp)
                extend(node.back_rest)
                if node.back is not None: walk(node.back)
        if self.nodes: walk(0)
        kept = _tidy([(op, face) for op, face in steps if face not in dropped] if dropped else steps,
                     self.planes, self.verts)
        if len(self.orders) >= 64: self.orders.clear()
        got = self.orders[(sides, dropped)] = (steps, kept)
        return got


def _tidy(steps, planes, verts):
    """The ops of `steps` ((op, face) in drawing order) with no line drawn for nothing. A line piece that later
    lines wholly cover is left out: it is drawn there, after the nearer face, where it stays on screen. And pieces
    of one straight line that meet or overlap become one line, drawn where the later piece is, if every fill drawn
    between them has the earlier piece on its front side (`planes[face]`, (n, d)): a face can only hide what lies
    behind it, and lines hide nothing. A line op is ('line', i, j, which, ti, tj): see _line_op."""
    covered, kept = {}, []
    for op, face in reversed(steps):
        if op[0] == 'line':
            lo, hi = (op[4], op[5]) if op[4] <= op[5] else (op[5], op[4])
            spans = covered.setdefault(op[3], [])
            reach = lo   # how far the spans already cover from lo, joined end to end
            for a, b in sorted(spans):
                if a <= reach + 1e-6: reach = max(reach, b)
            if reach >= hi - 1e-6: continue
            spans.append((lo, hi))
        kept.append((op, face))
    out, open_ = [], {}   # open_: straight line -> indices in out of pieces still free to move later
    for op, face in reversed(kept):
        if op[0] != 'line':
            (nx, ny, nz), d = planes[face]
            for which, pieces in list(open_.items()):
                free = []
                for k in pieces:
                    i, j = out[k][1], out[k][2]
                    a, b = verts[i], verts[j]
                    if nx*a[0] + ny*a[1] + nz*a[2] - d >= -1e-6 and nx*b[0] + ny*b[1] + nz*b[2] - d >= -1e-6:
                        free.append(k)
                if free: open_[which] = free
                else: del open_[which]
            out.append(op)
            continue
        same = open_.setdefault(op[3], [])
        lo, hi = min(op[4], op[5]), max(op[4], op[5])
        ends = [(op[4], op[1]), (op[5], op[2])]
        for k in list(same):   # join every free piece it meets or overlaps, end to end
            prev = out[k]
            if min(prev[4], prev[5]) <= hi + 1e-6 and lo <= max(prev[4], prev[5]) + 1e-6:
                ends += [(prev[4], prev[1]), (prev[5], prev[2])]
                lo, hi = min(lo, prev[4], prev[5]), max(hi, prev[4], prev[5])
                out[k] = None
                same.remove(k)
        ends.sort()
        (ti, i), (tj, j) = ends[0], ends[-1]
        same.append(len(out))
        out.append(op if len(ends) == 2 else ('line', i, j, op[3], ti, tj))
    return [op for op in out if op is not None]


def _line_op(i, j, verts, ends):
    """('line', i, j, which, ti, tj) for a line from vertex i to j along the model edge or line between `ends`:
    `which` names the infinite straight line it lies on (so collinear edges share it), ti and tj are i's and j's
    places along it, in metres."""
    a, b = (verts[k] for k in ends)
    u = [b[k] - a[k] for k in range(3)]
    size = math.sqrt(_dot(u, u))
    u = [c/size for c in u]
    first = next(c for c in u if abs(c) > 1e-9)
    if first < 0: u = [-c for c in u]
    along = _dot(a, u)
    foot = [a[k] - along*u[k] for k in range(3)]   # the line's point nearest the model's origin
    which = tuple(round(c, 6) + 0.0 for c in u) + tuple(round(c, 4) + 0.0 for c in foot)
    return ('line', i, j, which, _dot(verts[i], u), _dot(verts[j], u))


def _ops(piece, verts):
    """A piece's drawing steps as (op, face): its fill, and its real edges."""
    idx, real, face = piece
    edges = []
    for k in range(len(idx)):
        if real[k] is not None:
            edges.append((_line_op(idx[k], idx[(k+1) % len(idx)], verts, real[k]), face))
    return (('face', idx), face), edges


@functools.lru_cache(maxsize=None)
def _tree(name):
    """The hull's BSP tree, built once. Cached."""
    m = model(name)
    verts = _Verts(m.verts)
    planes = [(n, _dot(n, m.verts[idx[0]])) for idx, n in m.faces]
    pieces = [(idx, tuple((min(idx[k], idx[(k+1) % len(idx)]), max(idx[k], idx[(k+1) % len(idx)]))
                          for k in range(len(idx))), f) for f, (idx, _) in enumerate(m.faces)]
    root, rest = _build(pieces, [(a, b, ('line', k)) for k, (a, b) in enumerate(m.lines)], planes, verts)
    V = verts.list
    bare = lambda lines: tuple((_line_op(a, b, V, m.lines[which[1]]), None) for a, b, which in lines)
    def steps(group):   # the pieces of one plane: every fill, then every edge (fills there never overlap edges)
        ops = [_ops(p, V) for p in group]
        return tuple(fill for fill, _ in ops) + tuple(edge for _, edges in ops for edge in edges)
    nodes = []
    def number(node):   # preorder; children become indices
        if node is None: return None
        k = len(nodes)
        nodes.append(node)
        node.same, node.opp = steps(node.same), steps(node.opp)
        node.lines, node.front_rest, node.back_rest = bare(node.lines), bare(node.front_rest), bare(node.back_rest)
        node.front, node.back = number(node.front), number(node.back)
        return k
    number(root)
    tree = _Tree()
    tree.verts, tree.planes, tree.root, tree.nodes = tuple(verts.list), planes, root, nodes
    tree.nx, tree.ny, tree.nz = (tuple(node.n[i] for node in nodes) for i in range(3))
    tree.d = tuple(node.d for node in nodes)
    tree.loose = tuple(op for op, _ in bare(rest))
    tree.orders = {}
    return tree


def warm():
    """Build every hull's BSP tree now (each takes a moment), so none is built mid-flight."""
    for name in NAMES:
        _tree(name)


class Painted(list):
    """paint's items, with how they were made: `points`, the hull's vertices camera-relative, index for index (the
    items share these objects), and `order`, the same items by vertex index: ('face', idx) or
    ('line', i, j, which, ti, tj), as _tidy describes. An empty Painted with an order is paint's lean form: the
    order and points alone."""
    __slots__ = ('points', 'order')


def _area(points):
    """The area of a polygon of screen points (x, y, ...), by the shoelace formula."""
    return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def paint(name, centre, facing, up, rear=False, near=6.0, once=False, lod=None, items=True):
    """The ship as an opaque solid in painter's order (far first): ('face', points) to fill with the background and
    ('line', a, b), camera-relative and unclipped. The order comes from the hull's BSP tree, so it is exact: nothing
    drawn later is hidden by a face drawn before it. Only faces turned towards the camera are kept (split where the
    tree cut them), each followed by its own real edges; bare lines go in their place in the tree. Anything wholly
    at or behind `near` (depth z, or -z when `rear`) is left out.
    With `once`, no line is drawn for nothing (see _tidy): an edge two kept pieces share comes only after the later
    (nearer) one, where it is left on screen, and pieces of a line that meet with no fill between are drawn as one.
    `lod` (project, size, share): if every model vertex projects (project: point -> (sx, sy, ...) or None) and the
    ship is under `size` px across on screen (its bounding box's larger side), faces under `share` of that size
    squared (in px² there) are left out, with the edges only they have.
    Returns a Painted list; with `items` False, an empty one carrying only its `order` and `points` (all
    draw_solid needs), which is quicker to make."""
    m = model(name)
    tree = _tree(name)
    ex, ey, ez = basis(facing, up)
    cx, cy, cz = centre
    (ex0, ex1, ex2), (ey0, ey1, ey2), (ez0, ez1, ez2) = ex, ey, ez
    pts = [[cx + x*ex0 + y*ey0 + z*ez0, cy + x*ex1 + y*ey1 + z*ez1, cz + x*ex2 + y*ey2 + z*ez2]
           for x, y, z in tree.verts]
    depth = [-p[2] for p in pts] if rear else [p[2] for p in pts]
    dropped = frozenset()
    if lod is not None:
        project, size, share = lod
        shown = [project(p) for p in pts[:len(m.verts)]]
        if None not in shown:
            across = max(max(p[k] for p in shown) - min(p[k] for p in shown) for k in (0, 1))
            if across < size:
                least = share*across*across
                dropped = frozenset(f for f, (idx, _) in enumerate(m.faces) if _area([shown[i] for i in idx]) < least)
    # the camera (the origin) in the hull's own frame
    cam = (-(cx*ex0 + cy*ex1 + cz*ex2), -(cx*ey0 + cy*ey1 + cz*ey2), -(cx*ez0 + cy*ez1 + cz*ez2))
    steps, kept = tree.order(cam, dropped)
    if once and min(depth) > near:
        order = kept   # the usual case, cached whole
    else:
        kept = []
        for op, face in steps:
            if op[0] == 'face':
                if face in dropped or max([depth[i] for i in op[1]]) <= near: continue
            elif face in dropped or (depth[op[1]] <= near and depth[op[2]] <= near): continue
            kept.append((op, face))
        order = _tidy(kept, tree.planes, tree.verts) if once else [op for op, _ in kept]
    out = Painted(('face', [pts[i] for i in op[1]]) if op[0] == 'face' else ('line', pts[op[1]], pts[op[2]])
                  for op in order) if items else Painted()
    out.points, out.order = pts, order
    return out


def screen_length(name, centre, facing, up, project):
    """The pixel distance between the projected nose and tail; 0.0 if either end is behind the camera.
    `project` takes a camera-relative [x, y, z] and returns (sx, sy, scale) or None."""
    ez = basis(facing, up)[2]
    half = model(name).length / 2
    ends = []
    for s in (half, -half):
        p = project([c + s*e for c, e in zip(centre, ez)])
        if p is None:
            return 0.0
        ends.append(p)
    return math.hypot(ends[0][0] - ends[1][0], ends[0][1] - ends[1][1])
