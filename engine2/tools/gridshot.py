"""RENDER THE HONEST GRID, so the look can be judged and not asserted.

Paints one player state four ways, from the bit-exact models, into a
side-by-side PNG at the real Mode 0 pixel aspect (2:1):

    flat          what ships: one colour, plus the free vertical GRAIN
    +joints       the two course boundaries, raster_joint's own geometry
    +columns      the face's END COLUMNS -- real projected cell corners
    grid          both

    python3 engine2/tools/gridshot.py [px py heading] [out.png]
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import cpchw as cpc                                         # noqa: E402
import pal                                                  # noqa: E402
import rastermodel as rm                                     # noqa: E402

MORTAR_PEN = 3          # ink 2 (0,0,255): DARK against the wall's sky blue
                        # and, unlike pal.MORTAR's ink 1, NOT the ceiling's
                        # own colour -- which matters the moment anything
                        # draws a vertical mark, because a face's end column
                        # runs all the way up to where the ceiling starts.


_DEC = {}
for _l in range(16):
    for _r in range(16):
        _DEC[cpc.mode0_byte(_l, _r)] = (_l, _r)


def pens(b):
    """One Mode 0 byte -> its (left, right) pen.  cpchw only encodes."""
    return _DEC[b]


def quads(px, py, a):
    import emu_frame as ef
    import marchmodel as mm
    import projmodel as pm
    _grid, solid = ef.load()
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is not None:
            out.append(q + (door, k))
    return out


def paint(qs, c, joints, columns):
    """Back to front, exactly the order raster_frame draws in.

    The END COLUMNS are the two pushes at the ends of every run, so they
    are applied per RUN, to the run's first and last BYTE -- one Mode 0
    pixel each, the left pixel of the leftmost byte and the right pixel of
    the rightmost.  That is what a substituted PUSH IX / PUSH IY writes."""
    W, H = c.VP_BW, c.VP_H
    fb = bytearray(W * H)
    for x in range(W):
        for y in range(H):
            fb[y * W + x] = cpc.mode0_byte(11 if y < c.CYH else 12,
                                           11 if y < c.CYH else 12)
    mc = rm.joint_colour()
    for q in qs:
        e, d = rm.fill_word(q)
        for (r, end, n) in rm.raster_quad(q, c):
            s = end - 2 * n
            for x in range(s, end):
                fb[r * W + x] = e if (x - s) % 2 == 0 else d
            if columns:
                lo = fb[r * W + s]
                fb[r * W + s] = cpc.mode0_byte(MORTAR_PEN,
                                               pens(lo)[1])
                hi = fb[r * W + end - 1]
                fb[r * W + end - 1] = cpc.mode0_byte(pens(hi)[0],
                                                     MORTAR_PEN)
        if joints:
            for (r, end, n) in rm.joint_runs(q, c):
                for x in range(end - 2 * n, end):
                    fb[r * W + x] = mc
    return fb


def to_rgb(fb, c, scale=4):
    W, H = c.VP_BW, c.VP_H
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            for p in pens(fb[y * W + x]):
                row += [cpc.ink_rgb(pal.PEN_INK[p])] * (2 * scale)
        for _ in range(scale):
            rows.append(row)
    return rows


def png(rows, path):
    import struct
    import zlib
    h = len(rows)
    w = len(rows[0])
    raw = b"".join(b"\0" + bytes(v for px in r for v in px) for r in rows)

    def chunk(t, data):
        return (struct.pack(">I", len(data)) + t + data
                + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF))
    out = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    open(path, "wb").write(out)


def main():
    av = [a for a in sys.argv[1:] if a != "nograin"]
    if "nograin" in sys.argv[1:]:
        # pal.GRAIN is the FREE vertical stripe the fill word gives away --
        # a 4-pixel screen-space repeat that does not foreshorten.  It is
        # the exact thing this architecture is trying not to do, and it
        # costs nothing in either direction, so the honest grid has to be
        # judged with it OFF or it is judged against its own competitor.
        pal.GRAIN = None
    st = (int(av[0]), int(av[1]), int(av[2])) if len(av) >= 3 \
        else (0x0780, 0x0380, 2)
    out = av[3] if len(av) > 3 else "/tmp/gridshot.png"
    c = rm.cfg()
    qs = quads(*st)
    panes = [paint(qs, c, j, k) for (j, k) in
             ((0, 0), (1, 0), (0, 1), (1, 1))]
    imgs = [to_rgb(p, c) for p in panes]
    gap = [(24, 24, 24)] * 16
    rows = [sum(([*a, *gap] for a in row[:-1]), []) + row[-1]
            for row in zip(*imgs)]
    png(rows, out)
    print(f"{st} {len(qs)} quads -> {out}   "
          f"(flat | +joints | +end columns | grid)")


if __name__ == "__main__":
    main()
