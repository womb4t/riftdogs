"""The four station types: which system gets which, their wireframe models, the ports at both ends and the
docking frame. Pure maths, no SDL and no game import, so the game, the tests and tools can all use it.

Station-local coordinates: the long axis is +z, port A's centre is at z = 0 and port B's at z = LENGTH; x and y
run across the station. Every model is symmetrical round its long axis (a quarter turn about z maps it onto
itself): the design rule, no aerials, masts, dishes, cranes or spikes.

Camera-relative placement uses three numbers: `centre`, where port A's centre is relative to the camera (the
camera is at the origin); `axis`, the unit vector from port A towards port B; and `spin`, the station's roll round
its axis (the game's station_angle). Local x/y are laid out round the axis from the camera's up direction (as a
look-at camera does), so the layout is smooth everywhere except when the axis points straight up or down the
screen, which an approach to a port never does.
"""
import collections
import functools
import math

TYPES = ('hub', 'industrial', 'research', 'frontier')
TYPE_NAMES = {'hub': 'Orbital (hub)', 'industrial': 'Industrial', 'research': 'Research', 'frontier': 'Frontier'}

LENGTH = 400.0          # metres from port A to port B along the axis
PORT_RADIUS = 40.0      # the port's octagon
APPROACH_CONE = math.radians(30)  # dock only within this angle of a port's axis, never through the tube's side
SLOT_HALF_LONG, SLOT_HALF_SHORT = 14.0, 6.0  # today's 28 x 12 m slot: |x| <= 14, |y| <= 6
RIM_DEPTH = 14.0        # how deep a ring's rim is, inwards from its radius, for a laser hit
SPAR = 4.0              # half the thickness of a spoke or fin, for a laser hit


def station_type(government, tech, economy, *, lawless=('Anarchy', 'Feudal')):
    """Lawless government -> frontier; else tech 11 or more -> research; else an industrial economy ->
    industrial; else the orbital hub."""
    if government in lawless: return 'frontier'
    if tech >= 11: return 'research'
    if economy == 'Industrial': return 'industrial'
    return 'hub'


# ---- models -----------------------------------------------------------------------------------------------------

OCT = math.pi / 8   # an octagon with flat faces square to x and y (vertices at 22.5 deg + k*45 deg)
PIECE = 40.0        # a tube section is cut into faces at most this long along z

# A face of the station's surface: `points`, the corners of a convex planar polygon in order; `normal`, its unit
# outward normal, or None for a two-sided face (never culled); `lines`, the ((x,y,z), (x,y,z), gold) segments lying
# on it; `port`, 0.0 or LENGTH for the two end caps, else None.
Face = collections.namedtuple('Face', 'points normal lines port')


def _key(x, y, z):
    """A point rounded as the builder rounds its vertices."""
    return (round(x, 6) + 0.0, round(y, 6) + 0.0, round(z, 6) + 0.0)


def _plane_normal(points):
    """The unit normal of a planar polygon (Newell's method, about its centroid), turning as its corners do."""
    c = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
    rel = [tuple(p[i] - c[i] for i in range(3)) for p in points]
    n = [0.0, 0.0, 0.0]
    for i, (x, y, z) in enumerate(rel):
        u, v, w = rel[(i+1) % len(rel)]
        n[0] += (y - v) * (z + w); n[1] += (z - w) * (x + u); n[2] += (x - u) * (y + v)
    length = math.sqrt(sum(a*a for a in n))
    n = [a / length for a in n]
    n = [0.0 if abs(a) < 1e-12 else a for a in n]
    length = math.sqrt(sum(a*a for a in n))
    return tuple(a / length + 0.0 for a in n)


class _Builder:
    def __init__(self):
        self.verts, self.edges, self.index, self.seen = [], [], {}, set()
        self.solids = []   # what a laser ray hits: see `inside`
        self.faces = []    # Face records without lines: see `surfaces`
        self.tubes = []    # each tube's (z, r) sections, turned into faces by `finish`

    def face(self, points, inside=None, port=None):
        """A face; its normal points away from the point `inside`, or None (two-sided) without one."""
        points = tuple(_key(*p) for p in points)
        normal = None
        if inside is not None:
            normal = _plane_normal(points)
            c = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
            if _dot(normal, tuple(c[i] - inside[i] for i in range(3))) < 0:
                normal = tuple(-a + 0.0 for a in normal)
        self.faces.append(Face(points, normal, (), port))

    def at(self, indices):
        return [self.verts[i] for i in indices]

    def vertex(self, x, y, z):
        key = (round(x, 6) + 0.0, round(y, 6) + 0.0, round(z, 6) + 0.0)
        if key not in self.index:
            self.index[key] = len(self.verts)
            self.verts.append(key)
        return self.index[key]

    def edge(self, a, b):
        if a != b and frozenset((a, b)) not in self.seen:
            self.seen.add(frozenset((a, b)))
            self.edges.append((a, b))

    def ring(self, r, z, n=8, phase=OCT, closed=True):
        """n points round the axis (n a multiple of 4 keeps the quarter-turn symmetry), joined into a loop."""
        pts = [self.vertex(r*math.cos(phase + 2*math.pi*i/n), r*math.sin(phase + 2*math.pi*i/n), z) for i in range(n)]
        if closed:
            for i in range(n): self.edge(pts[i], pts[(i+1) % n])
        return pts

    def join(self, a, b):
        for p, q in zip(a, b): self.edge(p, q)

    def zigzag(self, a, b):
        """Triangulate between two rings whose second is turned half a step: the geodesic look."""
        n = len(a)
        for i in range(n):
            self.edge(a[i], b[i]); self.edge(a[(i+1) % n], b[i])

    def tube(self, sections):
        """A segmented octagonal tube from (z, r) sections; equal z values make a step (a flat shoulder)."""
        prev = None
        for z, r in sections:
            ring = self.ring(r, z)
            if prev is not None and prev[0] != z:
                self.join(prev[1], ring)
                self.solids.append(('cone', prev[0], z, prev[2], r))
            prev = (z, ring, r)
        self.tubes.append(tuple((float(z), float(r)) for z, r in sections))

    def finish(self):
        """The tubes' faces: each section cut into equal pieces at most PIECE long, the flat shoulders where two
        sections meet, and the two end caps (a tube end that stops inside the station gets no cap)."""
        def octagon(r, z):
            return [(r*math.cos(OCT + math.pi/4*i), r*math.sin(OCT + math.pi/4*i), z) for i in range(8)]
        for sections in self.tubes:
            for (z0, r0), (z1, r1) in zip(sections, sections[1:]):
                if z0 != z1:
                    n = math.ceil((z1 - z0) / PIECE - 1e-9)
                    for k in range(n):
                        za, zb = z0 + (z1 - z0)*k/n, z0 + (z1 - z0)*(k+1)/n
                        a = octagon(r0 + (r1 - r0)*k/n, za)
                        b = octagon(r0 + (r1 - r0)*(k+1)/n, zb)
                        for i in range(8):
                            j = (i+1) % 8
                            self.face((a[i], a[j], b[j], b[i]), inside=(0.0, 0.0, (za + zb)/2))
                else:   # a shoulder: inside is 1 m into the wider side (the earlier section is the r0 side)
                    a, b = octagon(r0, z0), octagon(r1, z0)
                    step = -1.0 if r0 > r1 else 1.0
                    for i in range(8):
                        j = (i+1) % 8
                        quad = (a[i], a[j], b[j], b[i])
                        c = tuple(sum(p[m] for p in quad) / 4 for m in range(3))
                        self.face(quad, inside=(c[0], c[1], c[2] + step))
            for (z, r), inward in ((sections[0], 1.0), (sections[-1], -1.0)):
                if z in (0.0, LENGTH):
                    self.face(octagon(r, z), inside=(0.0, 0.0, z + inward), port=z)

    def end_ports(self):
        """Both ports: the octagon, a frame octagon round it with four struts, and the slot's light-bar points
        (all four quarter turns of them, so the vertex set stays symmetrical; only the two along x are lit)."""
        for z in (0.0, LENGTH):
            port = self.ring(PORT_RADIUS, z)
            frame = self.ring(PORT_RADIUS + 12, z)
            for i in range(0, 8, 2): self.edge(port[i], frame[i])
            for sx in (-1, 1):
                for sy in (-1, 1):
                    self.vertex(sx*SLOT_HALF_LONG, sy*SLOT_HALF_SHORT, z)
                    self.vertex(sy*SLOT_HALF_SHORT, sx*SLOT_HALF_LONG, z)

    def fins(self, r0, r1, near, far, half=None):
        """A solid: four flat fins square to x and y from radius r0 to r1, spanning `near` (z0, z1) along the
        axis at r0 and `far` at r1."""
        self.solids.append(('fins', r0, r1, near, far, SPAR if half is None else half))

    def band(self, r, z):
        """A seam round an octagonal section of radius r (no new longerons: it sits on the existing ones)."""
        self.ring(r, z)

    def windows(self, r, z0, z1, n=8, phase=0.0):
        """Short lit-window dashes on each flat face of an octagonal section, all the way round."""
        rm = r * math.cos(OCT) + 0.5
        for i in range(n):
            t = phase + 2*math.pi*i/n
            c, s = math.cos(t), math.sin(t)
            self.edge(self.vertex(rm*c, rm*s, z0), self.vertex(rm*c, rm*s, z1))

    def plates(self, r, z0, z1, half_width, phase=0.0, n=4):
        """Rectangular plates proud of the hull, n round the axis."""
        rm = r * math.cos(OCT) + 1.0
        for i in range(n):
            t = phase + 2*math.pi*i/n
            c, s = math.cos(t), math.sin(t)
            pts = [self.vertex(rm*c - w*s, rm*s + w*c, z) for w, z in ((-half_width, z0), (half_width, z0), (half_width, z1), (-half_width, z1))]
            for k in range(4): self.edge(pts[k], pts[(k+1) % 4])

    def wheel(self, r, z, width, n, spokes_from=None, crossbars=1):
        """A ring of radius r, `width` deep along the axis, n segments (a multiple of 4), crossbars on every
        `crossbars`-th segment, and four spokes square to x and y from radius spokes_from to the rim's middle."""
        front = self.ring(r, z - width/2, n, phase=0.0)
        back = self.ring(r, z + width/2, n, phase=0.0)
        for i in range(0, n, crossbars): self.edge(front[i], back[i])
        for i in range(n):
            j = (i+1) % n
            self.face(self.at((front[i], front[j], back[j], back[i])))
        self.solids.append(('ring', z - width/2, z + width/2, r - RIM_DEPTH, r))
        if spokes_from is not None:
            self.solids.append(('fins', spokes_from, r, (z - SPAR, z + SPAR), (z - SPAR, z + SPAR), SPAR))
            for k in range(4):
                c, s = math.cos(math.pi/2 * k), math.sin(math.pi/2 * k)
                self.edge(self.vertex(spokes_from*c, spokes_from*s, z), self.vertex(r*c, r*s, z))


def _hub(b):
    # A segmented tube with one wide ring on four spokes; lit windows round the core.
    b.tube([(0, 52), (36, 52), (36, 32), (150, 32), (150, 66), (250, 66), (250, 32), (364, 32), (364, 52), (400, 52)])
    for z in (74, 112, 288, 326): b.band(32, z)
    b.wheel(175, 200, 30, 16, spokes_from=66*math.cos(OCT))
    b.windows(66, 160, 184); b.windows(66, 216, 240)


def _industrial(b):
    # Twin rings and a band of ore tanks round the hull between them.
    b.tube([(0, 52), (40, 52), (40, 34), (360, 34), (360, 52), (400, 52)])
    for z in (80, 320): b.band(34, z)
    for z in (130, 270):
        b.wheel(150, z, 26, 12, spokes_from=34*math.cos(OCT), crossbars=3)
    for k in range(8):   # eight tanks lying along the hull: square ends, the two outer sides drawn
        t = OCT + math.pi/4 * k
        c, s = math.cos(t), math.sin(t)
        ends = []
        for z in (162, 238):
            pts = [b.vertex(r*c - w*s, r*s + w*c, z) for r, w in ((32, -10), (52, -10), (52, 10), (32, 10))]
            for i in range(4): b.edge(pts[i], pts[(i+1) % 4])
            ends.append(pts)
        b.edge(ends[0][1], ends[1][1]); b.edge(ends[0][2], ends[1][2])
        centre = (42*c, 42*s, 200.0)
        e0, e1 = ends
        for quad in (e0, e1, (e0[1], e0[2], e1[2], e1[1]), (e0[0], e0[1], e1[1], e1[0]), (e0[3], e0[2], e1[2], e1[3])):
            b.face(b.at(quad), inside=centre)
    b.solids.append(('cone', 162, 238, 52, 52))   # the tanks, nearly all the way round


def _research(b):
    # A large geodesic dome round the forward hull, a ring, and a small dome aft.
    b.tube([(0, 52), (34, 52), (34, 30), (366, 30), (366, 52), (400, 52)])

    def dome(zc, radius, lats, outlined):
        """A lattice sphere round the hull: rings of eight, each turned half a step from the last and joined
        by a zigzag; only the `outlined` rings get their own loop, the rest show as the lattice's diamonds."""
        rings = []
        for k, deg in enumerate(lats):
            a = math.radians(deg)
            rings.append(b.ring(radius*math.sin(a), zc - radius*math.cos(a), 8, phase=OCT + (k % 2)*OCT,
                                closed=k in outlined))
        for p, q in zip(rings, rings[1:]):
            b.zigzag(p, q)
            for i in range(8):
                j = (i+1) % 8
                b.face(b.at((p[i], p[j], q[i])), inside=(0.0, 0.0, zc))
                b.face(b.at((q[i], q[j], p[j])), inside=(0.0, 0.0, zc))
        b.solids.append(('sphere', zc, radius))
    dome(140, 100, (20, 50, 90, 130, 160), outlined=(0, 2, 4))
    b.wheel(160, 262, 24, 12, spokes_from=30*math.cos(OCT), crossbars=3)
    dome(322, 48, (40, 90, 140), outlined=(0, 2))


def _frontier(b):
    # A patched bare tube, a boxy core with four short fins; no ring.
    b.tube([(0, 52), (34, 52), (34, 26), (150, 26)])
    b.tube([(250, 26), (366, 26), (366, 52), (400, 52)])
    for z in (66, 104, 296, 334): b.band(26, z)
    half = 64.0   # the core is a box, its faces square to x and y
    box = [b.ring(half*math.sqrt(2), z, 4, phase=math.pi/4) for z in (150, 200, 250)]
    b.join(box[0], box[1]); b.join(box[1], box[2])
    middle = (0.0, 0.0, 200.0)
    for p, q in zip(box, box[1:]):
        for i in range(4): b.face(b.at((p[i], p[(i+1) % 4], q[(i+1) % 4], q[i])), inside=middle)
    for square in (box[0], box[2]): b.face(b.at(square), inside=middle)
    b.solids.append(('box', 150, 250, half))
    for k in range(4):   # short fins square to the box faces
        t = math.pi/2 * k
        c, s = math.cos(t), math.sin(t)
        quad = [b.vertex(r*c, r*s, z) for r, z in ((half, 168), (104, 186), (104, 224), (half, 242))]
        for i in range(3): b.edge(quad[i], quad[i+1])
        b.face(b.at(quad))
    b.fins(half, 104, (168, 242), (186, 224))
    # Bolted-on patches: plates on alternate faces of the bare tube, staggered between the two ends.
    b.plates(26, 76, 98, 7, phase=0.0)
    b.plates(26, 302, 324, 7, phase=math.pi/4)


_SHAPES = {'hub': _hub, 'industrial': _industrial, 'research': _research, 'frontier': _frontier}


@functools.lru_cache(maxsize=None)
def _model(kind):
    b = _Builder()
    b.end_ports()
    _SHAPES[kind](b)
    b.finish()
    return b.verts, b.edges, b.index, tuple(b.solids), tuple(b.faces)


def model(kind):
    """(vertices, edges) in station-local metres. Shared and cached: don't change the lists."""
    verts, edges = _model(kind)[:2]
    return verts, edges


def slots():
    """The two docking slots as solid black openings, {z: [4 station-local corners]}: the 28 x 12 m slot in each
    port's plane, so the entrance reads as a hole and hides the lines behind it."""
    return {z: [(-SLOT_HALF_LONG, -SLOT_HALF_SHORT, z), (SLOT_HALF_LONG, -SLOT_HALF_SHORT, z),
                (SLOT_HALF_LONG, SLOT_HALF_SHORT, z), (-SLOT_HALF_LONG, SLOT_HALF_SHORT, z)] for z in (0.0, LENGTH)}


def port_lights(kind):
    """The two light bars across each port, along local x at y = +-6 m and 28 m long: they show the slot's roll."""
    index = _model(kind)[2]
    bars = []
    for z in (0.0, LENGTH):
        for y in (-SLOT_HALF_SHORT, SLOT_HALF_SHORT):
            bars.append((index[(-SLOT_HALF_LONG, y, z)], index[(SLOT_HALF_LONG, y, z)]))
    return bars


# ---- faces: the station as an opaque surface -------------------------------------------------------------------
# Each line (model edge or port light bar) attaches to every face it lies on, so a renderer can fill a face and draw
# its own lines straight after it; the parts lying on no face (spokes, mostly) are loose.

PROUD = 1.5     # a one-sided face holds lines up to this far in front of it (window dashes 0.5 m, plates 1 m proud)
ON = 0.01       # metres: how close counts as in a face's plane or on its boundary
SLIVER = 0.05   # metres: a line's part on a face no longer than this (a neighbour's edge grazing a corner) is left off


def _clip_to_face(a, b, points, normal):
    """The (t0, t1) part of segment a-b inside the convex polygon, in its plane (Cyrus-Beck, boundary inclusive
    within ON), or None."""
    c = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
    d = tuple(b[i] - a[i] for i in range(3))
    t0, t1 = 0.0, 1.0
    for k, p in enumerate(points):
        q = points[(k+1) % len(points)]
        m = _cross(normal, tuple(q[i] - p[i] for i in range(3)))
        length = math.sqrt(_dot(m, m))
        m = tuple(x / length for x in m)
        if _dot(tuple(c[i] - p[i] for i in range(3)), m) < 0: m = tuple(-x for x in m)
        num = _dot(tuple(a[i] - p[i] for i in range(3)), m) + ON   # inside while num + t*den >= 0
        den = _dot(d, m)
        if abs(den) < 1e-12:
            if num < 0: return None
        elif den > 0: t0 = max(t0, -num/den)
        else: t1 = min(t1, -num/den)
        if t0 > t1: return None
    return t0, t1


def _on_plane(a, b, points, normal, one_sided):
    """Do both ends lie in the face's plane: up to PROUD in front of a one-sided face, within ON of a two-sided one?"""
    for p in (a, b):
        d = _dot(tuple(p[i] - points[0][i] for i in range(3)), normal)
        if not (-ON <= d <= PROUD if one_sided else abs(d) <= ON): return False
    return True


@functools.lru_cache(maxsize=None)
def surfaces(kind):
    """(faces, loose): the station's faces (Face records, their lines attached) and the line parts lying on no face,
    each line ((x,y,z), (x,y,z), gold). Gold: in a port's plane (both ends at z 0 or both at LENGTH) or a port
    light bar. Shared and cached."""
    verts, edges, _, _, bare = _model(kind)
    segments = [(verts[a], verts[b], verts[a][2] == verts[b][2] and verts[a][2] in (0.0, LENGTH)) for a, b in edges]
    segments += [(verts[a], verts[b], True) for a, b in port_lights(kind)]
    planes = [f.normal if f.normal is not None else _plane_normal(f.points) for f in bare]
    lines = [[] for _ in bare]
    loose = []
    for a, b, gold in segments:
        length = math.dist(a, b)
        at = lambda t: tuple(a[i] + t*(b[i] - a[i]) for i in range(3))
        covered = []
        for n, (f, normal) in enumerate(zip(bare, planes)):
            if not _on_plane(a, b, f.points, normal, f.normal is not None): continue
            part = _clip_to_face(a, b, f.points, normal)
            if part is None or (part[1] - part[0]) * length <= ON: continue
            t0, t1 = part
            if (t1 - t0) * length > SLIVER: lines[n].append((at(t0) if t0 > 0.0 else a, at(t1) if t1 < 1.0 else b, gold))
            covered.append(part)
        end = 0.0   # the gaps between the covered parts are loose
        for t0, t1 in sorted(covered) + [(1.0, 1.0)]:
            if (t0 - end) * length > ON: loose.append((at(end) if end > 0.0 else a, at(t0) if t0 < 1.0 else b, gold))
            end = max(end, t1)
    faces = tuple(f._replace(lines=tuple(ls)) for f, ls in zip(bare, lines))
    return faces, tuple(loose)


def clip_polygon_near(points, depth, near):
    """Sutherland-Hodgman: the part of a polygon (camera-relative points) in front of the near plane."""
    out = []
    for i,a in enumerate(points):
        b = points[(i+1)%len(points)]
        za,zb = depth(a)-near,depth(b)-near
        if za > 0: out.append(a)
        if (za > 0) != (zb > 0):
            t = za/(za-zb)
            out.append([p+t*(q-p) for p,q in zip(a,b)])
    return out


def paint(kind, centre, axis, spin, rear=False, near=6.0):
    """The station as an opaque surface, in painter's order (far first): a list of
    ('face', points) to fill with the background, ('slot', points, port_z) to fill with the slot's black and
    ('line', a, b, gold), all camera-relative (as `to_view`) and unclipped. Only the faces turned towards the camera
    (two-sided ones always), each followed by its slot (an end cap) and the lines on it; a line on no face goes by
    itself. Each group is placed by the mean of its points' depths (z, or -z when `rear`), clamped at `near`;
    a face's group goes before a loose line at the same depth, ties keep the model's order."""
    faces, loose = surfaces(kind)
    ex, ey, ez = _basis(axis, spin)
    cx, cy, cz = centre
    cache = {}
    def view(p):
        q = cache.get(p)
        if q is None:
            x, y, z = p
            q = cache[p] = [cx + x*ex[0] + y*ey[0] + z*ez[0], cy + x*ex[1] + y*ey[1] + z*ez[1],
                            cz + x*ex[2] + y*ey[2] + z*ez[2]]
        return q
    sign = -1.0 if rear else 1.0
    groups = []
    slot_corners = slots()
    for f in faces:
        pts = [view(p) for p in f.points]
        if f.normal is not None:
            nx, ny, nz = f.normal
            n = (nx*ex[0] + ny*ey[0] + nz*ez[0], nx*ex[1] + ny*ey[1] + nz*ez[1], nx*ex[2] + ny*ey[2] + nz*ez[2])
            if _dot(n, pts[0]) >= 0: continue
        depths = [sign*p[2] for p in pts]
        if max(depths) <= near: continue
        group = [('face', pts)]
        if f.port is not None: group.append(('slot', [view(p) for p in slot_corners[f.port]], f.port))
        group += [('line', view(a), view(b), gold) for a, b, gold in f.lines]
        groups.append((-sum(max(d, near) for d in depths)/len(depths), -1, len(groups), group))
    for a, b, gold in loose:
        a, b = view(a), view(b)
        key = (max(sign*a[2], near) + max(sign*b[2], near)) / 2
        groups.append((-key, 0, len(groups), [('line', a, b, gold)]))
    groups.sort(key=lambda g: g[:3])
    return [item for g in groups for item in g[3]]


# ---- the solid outline: what a laser ray hits ------------------------------------------------------------------
# Each shape records simple solids as it is built: the hull's sections ('cone'), each ring's rim ('ring', RIM_DEPTH
# deep, so the open space between the hull and the rim is empty), domes ('sphere'), the frontier's box and its fins
# and the rings' spokes ('fins', SPAR either side of the fin's plane). Shots through the gaps miss.

def inside(kind, point, slack=0.0):
    """Is the station-local point inside the station's solid (grown by `slack` metres)?"""
    x, y, z = point
    r = math.hypot(x, y)
    for solid in _model(kind)[3]:
        shape = solid[0]
        if shape == 'cone':
            _, z0, z1, r0, r1 = solid
            if z0-slack <= z <= z1+slack:
                f = min(1.0, max(0.0, (z-z0)/(z1-z0)))
                if r <= r0+(r1-r0)*f+slack: return True
        elif shape == 'ring':
            _, z0, z1, rin, rout = solid
            if z0-slack <= z <= z1+slack and rin-slack <= r <= rout+slack: return True
        elif shape == 'sphere':
            _, zc, radius = solid
            if r*r+(z-zc)**2 <= (radius+slack)**2: return True
        elif shape == 'box':
            _, z0, z1, half = solid
            if z0-slack <= z <= z1+slack and abs(x) <= half+slack and abs(y) <= half+slack: return True
        else:   # 'fins': four of them, square to x and y
            _, r0, r1, (a0, a1), (b0, b1), half = solid
            for u, w in ((x, y), (y, x), (-x, y), (-y, x)):
                if abs(w) <= half+slack and r0-slack <= u <= r1+slack:
                    f = min(1.0, max(0.0, (u-r0)/(r1-r0)))
                    if a0+(b0-a0)*f-slack <= z <= a1+(b1-a1)*f+slack: return True
    return False


@functools.lru_cache(maxsize=None)
def _bound(kind):
    """The radius of a sphere round the station's middle that holds every vertex, with room to spare."""
    verts = _model(kind)[0]
    return max(math.sqrt(x*x+y*y+(z-LENGTH/2)**2) for x, y, z in verts) + 10.0


def ray_hit(kind, centre, axis, spin, direction, step=1.0):
    """How far along a ray from the camera (the origin) in the unit `direction` it first meets the station's
    solid, or None. The station is placed by centre (port A's centre), axis and spin, as in `to_view`."""
    ex, ey, ez = _basis(axis, spin)
    rel = tuple(-c for c in centre)
    o = (_dot(rel, ex), _dot(rel, ey), _dot(rel, ez))
    d = (_dot(direction, ex), _dot(direction, ey), _dot(direction, ez))
    m = (o[0], o[1], o[2]-LENGTH/2)
    b = _dot(m, d)
    c = _dot(m, m) - _bound(kind)**2
    if b*b - c < 0: return None
    root = math.sqrt(b*b - c)
    t, end = max(0.0, -b-root), -b+root
    if end < 0: return None
    at = lambda t: (o[0]+t*d[0], o[1]+t*d[1], o[2]+t*d[2])
    if inside(kind, at(t)): return t
    while t < end:
        nxt = min(end, t+step)
        if inside(kind, at(nxt)):
            lo, hi = t, nxt   # narrow it down to a centimetre
            while hi-lo > 0.01:
                mid = (lo+hi)/2
                lo, hi = (lo, mid) if inside(kind, at(mid)) else (mid, hi)
            return hi
        t = nxt
    return None


# ---- placing the station relative to the camera -------------------------------------------------------------

DIM_FLOOR = 0.35


def depth_colour(base, z, near, far):
    """base at full brightness at depth `near`, fading to 35 % at `far`; clamped outside, never dimmer than 35 %."""
    if far <= near: return tuple(base)
    t = min(1.0, max(0.0, (z-near)/(far-near)))
    k = 1.0-(1.0-DIM_FLOOR)*t
    return tuple(int(c*k+.5) for c in base)


def _unit(v):
    n = math.sqrt(sum(c*c for c in v))
    return tuple(c/n for c in v)


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _basis(axis, spin):
    """Camera-relative unit vectors for local x, y, z."""
    a = _unit(axis)
    up = (0.0, 1.0, 0.0) if abs(a[1]) < 1 - 1e-9 else (1.0, 0.0, 0.0)
    e1 = _unit(_cross(up, a))
    e2 = _cross(a, e1)
    c, s = math.cos(spin), math.sin(spin)
    ex = tuple(c*p + s*q for p, q in zip(e1, e2))
    ey = tuple(-s*p + c*q for p, q in zip(e1, e2))
    return ex, ey, a


def to_view(point_local, centre, axis, spin):
    """A station-local point, camera-relative."""
    ex, ey, ez = _basis(axis, spin)
    x, y, z = point_local
    return tuple(centre[i] + x*ex[i] + y*ey[i] + z*ez[i] for i in range(3))


def ports(centre, axis):
    """Both ports' camera-relative centres and outward unit vectors (pointing away from the station)."""
    a = _unit(axis)
    return {'A': {'position': tuple(centre), 'outward': tuple(-c for c in a)},
            'B': {'position': tuple(c + LENGTH*d for c, d in zip(centre, a)), 'outward': a}}


def nearer_port(centre, axis):
    p = ports(centre, axis)
    return min('AB', key=lambda k: _dot(p[k]['position'], p[k]['position']))


def approach_angle(port):
    """Radians between the port's outward vector and the direction from the port to the camera."""
    to_camera = tuple(-c for c in port['position'])
    d = math.sqrt(_dot(to_camera, to_camera))
    if d == 0: return 0.0
    return math.acos(max(-1.0, min(1.0, _dot(port['outward'], to_camera) / d)))


def port_offset(centre, axis, spin, port):
    """The camera (at the origin) in the named port's frame: x, y across the port, turned with the spin so the
    slot's long side (the light bars) is x; z the distance out along the port's outward vector (positive in
    front of the port). Today's docking check applies unchanged: |x| <= 14, |y| <= 6."""
    ex, ey, ez = _basis(axis, spin)
    rel = tuple(-c for c in centre)   # camera relative to port A's centre
    x, y, z = _dot(rel, ex), _dot(rel, ey), _dot(rel, ez)
    return (x, y, -z) if port == 'A' else (x, y, z - LENGTH)
