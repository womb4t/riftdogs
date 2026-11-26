"""qr.py: a small QR encoder: byte mode, versions 1-4, error correction level M. Pure stdlib.

encode(text) returns the module grid (list of rows, True = dark) with no quiet zone."""

# ISO 18004 Table 9, level M: version -> (blocks, data codewords per block, ec codewords per block)
BLOCKS = {1: (1, 16, 10), 2: (1, 28, 16), 3: (1, 44, 26), 4: (2, 32, 18)}
ALIGN = {2: 18, 3: 22, 4: 26}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def rs_ecc(data, n):
    """The n Reed-Solomon error-correction codewords for data (GF(256), polynomial 0x11D)."""
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _mul(gen[i + 1], f)
    return rem


def _codewords(raw, version):
    nblocks, dlen, elen = BLOCKS[version]
    total = nblocks * dlen
    bits = [0, 1, 0, 0]
    bits += [(len(raw) >> (7 - i)) & 1 for i in range(8)]
    for b in raw:
        bits += [(b >> (7 - i)) & 1 for i in range(8)]
    bits += [0] * min(4, total * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(data) < total:
        data.append(pad[(len(data) - len(bits) // 8) % 2])
    blocks = [data[i * dlen:(i + 1) * dlen] for i in range(nblocks)]
    eccs = [rs_ecc(b, elen) for b in blocks]
    out = [b[i] for i in range(dlen) for b in blocks]
    out += [e[i] for i in range(elen) for e in eccs]
    return out


def _format_bits(mask):
    data = (0b00 << 3) | mask  # level M = 00
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _penalty(m):
    n = len(m)
    score = 0
    lines = [row for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
    for line in lines:
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
        s = ''.join('1' if v else '0' for v in line)
        score += 40 * (s.count('10111010000') + s.count('00001011101'))
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(sum(row) for row in m)
    score += 10 * int(abs(dark * 100 / (n * n) - 50) // 5)
    return score


_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _build(version, codewords):
    n = 4 * version + 17
    m = [[False] * n for _ in range(n)]
    fn = [[False] * n for _ in range(n)]

    def put(x, y, v):
        m[y][x] = v
        fn[y][x] = True

    for i in range(n):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                x, y = ox + dx, oy + dy
                if 0 <= x < n and 0 <= y < n:
                    put(x, y, 0 <= dx <= 6 and 0 <= dy <= 6 and max(abs(dx - 3), abs(dy - 3)) != 2)
    if version in ALIGN:
        c = ALIGN[version]
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                put(c + dx, c + dy, max(abs(dx), abs(dy)) != 1)
    for i in range(15):  # reserve format areas
        for x, y in _format_cells(n, i):
            fn[y][x] = True
    put(8, n - 8, True)  # dark module at row 4V+9, column 8
    bits = [(cw >> (7 - i)) & 1 for cw in codewords for i in range(8)]
    k = 0
    x = n - 1
    up = True
    while x > 0:
        if x == 6:
            x -= 1
        for step in range(n):
            y = n - 1 - step if up else step
            for xx in (x, x - 1):
                if not fn[y][xx]:
                    m[y][xx] = k < len(bits) and bits[k] == 1
                    k += 1
        up = not up
        x -= 2
    return m, fn


def _format_cells(n, i):
    """The two (x, y) cells holding format bit i."""
    if i < 6:
        a = (8, i)
    elif i == 6:
        a = (8, 7)
    elif i == 7:
        a = (8, 8)
    elif i == 8:
        a = (7, 8)
    else:
        a = (14 - i, 8)
    b = (n - 1 - i, 8) if i < 8 else (8, n - 15 + i)
    return a, b


def encode(text):
    raw = text.encode('utf-8')
    for version in (1, 2, 3, 4):
        nblocks, dlen, _ = BLOCKS[version]
        if len(raw) <= nblocks * dlen - 2:
            break
    else:
        raise ValueError('too long for a version 4-M QR code (62 bytes): %d' % len(raw))
    base, fn = _build(version, _codewords(raw, version))
    n = len(base)
    best = None
    for mask in range(8):
        m = [row[:] for row in base]
        for y in range(n):
            for x in range(n):
                if not fn[y][x] and _MASKS[mask](x, y):
                    m[y][x] = not m[y][x]
        f = _format_bits(mask)
        for i in range(15):
            for x, y in _format_cells(n, i):
                m[y][x] = bool((f >> i) & 1)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]
