"""THE WALL TEXTURES, MAGNIFIED, WITH NO RENDERER IN THE WAY.

    python3 engine2/tools/texshot.py     # -> build/tex_wall.png, tex_door.png

WHY THIS EXISTS, AND WHY IT SHOULD HAVE EXISTED FIRST.  The walls on the
booted disc look broken along their horizontal courses, and three separate
fixes went into the RENDERER chasing it -- an exact silhouette, a centred
sample, a CTABT indexed four times finer.  All three are real improvements
and none of them changed the picture, which is the signature of debugging
the wrong component.

There are only two candidates: either the art has breaks in it, or the
renderer puts them there.  This tool answers that in one picture by
drawing walltex.py's output directly, so anything visible here is the ART
and anything visible only on the disc is the RENDERER.

MODE 0 PIXELS ARE DOUBLE WIDTH, so every texel is drawn two units across
and one down -- a 32x64 texture comes out 64x64, which is the square it is
meant to read as.  Getting that wrong makes the courses look twice as tall
as they are and would send the next investigation off in its own wrong
direction.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import gridshot                                             # noqa: E402
import pal                                                  # noqa: E402
import walltex                                              # noqa: E402
import cpchw                                                # noqa: E402

SCALE = 6
TILE_X, TILE_Y = 2, 2           # ...and repeated, so the seam shows too


def rgb_of(pen):
    return tuple(cpchw.ink_rgb(pal.PEN_INK[pen]))


def image(rows, pens):
    """-> pixel rows, aspect-corrected and scaled, tiled TILE_X x TILE_Y."""
    out = []
    for _ty in range(TILE_Y):
        for r in rows:
            line = []
            for _tx in range(TILE_X):
                for v in r:
                    c = rgb_of(pens[v])
                    line += [c, c]          # Mode 0: two units wide
            wide = [p for p in line for _ in range(SCALE)]
            for _ in range(SCALE):
                out.append(wide)
    return out


def main():
    out = os.path.join(_ROOT, "build")
    os.makedirs(out, exist_ok=True)
    for name, rows, pens in (
            ("wall", walltex.wall(), pal.WALL_TEX_PENS),
            ("door", walltex.door(), pal.DOOR_TEX_PENS)):
        path = os.path.join(out, f"tex_{name}.png")
        gridshot.png(image(rows, pens), path)
        n = len(rows) * len(rows[0])
        mix = [sum(r.count(p) for r in rows) for p in range(4)]
        print(f"{name}: {walltex.TEX_W}x{walltex.TEX_H} Mode 0 px "
              f"({walltex.TEX_W * 2}x{walltex.TEX_H} as it reads), "
              f"pens {pens}")
        print(f"   mix " + "  ".join(f"{100.0 * v / n:4.1f}%" for v in mix)
              + f"   -> {path}")
    cs = walltex._courses()
    n = sum(len(js) for _y, js, _v in cs)
    print(f"\nwall: {len(cs)} courses, {n} stones, "
          f"MORTAR_PX {walltex.MORTAR_PX}")
    for y0, js, vo in cs:
        w = [(js[(k + 1) % len(js)] - j) % walltex.TEX_W
             for k, j in enumerate(js)]
        print(f"  y {y0:2d}  joints {js}  rides {vo}  "
              f"stones {[v * 2 for v in w]} apparent")
    # the heights each stone actually ends up with, neighbour by neighbour
    bs = walltex._bounds()
    for c in range(walltex.COURSE_N):
        hh = sorted({(bs[x][(c + 1) % walltex.COURSE_N]
                      + (walltex.TEX_H if c + 1 == walltex.COURSE_N else 0)
                      - bs[x][c]) for x in range(walltex.TEX_W)})
        print(f"  course {c} stone heights: {hh}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------
#  ...AND THE SAME TEXTURE AS THE RENDERER LAYS IT DOWN.
#
#  The art above is clean, so whatever breaks the courses on the disc is
#  in engine2/src/rastcol.asm.  colmodel.py is byte-exact against that
#  Z80 (emu_rcol.py, 192 screens), so rendering through the MODEL and
#  looking at the result is the same picture the machine draws -- without
#  booting anything.
#
#  Two faces, because they separate the two candidates:
#     FLAT   ha == hb, so every pair gets the same j, step and idx0.  If
#            this is clean the vertical walk is fine.
#     RAKED  ha != hb, so each pair gets its own.  If only this breaks,
#            it is the per-pair mapping and nothing else.
# ---------------------------------------------------------------------
_UNPEN = None


def unpen():
    global _UNPEN
    if _UNPEN is None:
        _UNPEN = {}
        for a in range(16):
            for b in range(16):
                _UNPEN[cpchw.mode0_byte(a, b)] = (a, b)
    return _UNPEN


def shot_face(name, q, scale=6):
    import colmodel
    import rastermodel as rm
    c = rm.cfg()
    scr, st = colmodel.render([q], c)
    inv = unpen()
    rows = []
    for r in range(c.VP_H):
        y = c.VP_Y + r
        base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
        line = []
        for x in range(c.VP_BW):
            for p in inv[scr[base + x]]:
                col = rgb_of(p)
                line += [col, col]          # Mode 0: two units wide
        wide = [p for p in line for _ in range(scale)]
        for _ in range(scale):
            rows.append(wide)
    path = os.path.join(_ROOT, "build", f"tex_{name}.png")
    gridshot.png(rows, path)
    print(f"  {name:18s} {st['pairs']:3d} bands {st['painted']:5d} bytes"
          f"   -> {path}")


def faces():
    import rastermodel as rm
    import emu_rast
    c = rm.cfg()
    X, CY = c.XMAX_Q4, c.CY_Q4
    print("\nthrough the renderer's own model:")
    shot_face("flat", emu_rast.q(0, CY, X, CY, 0, 1, c))
    shot_face("raked", emu_rast.q(0, CY // 3, X, CY, 0, 1, c))
