"""Side-by-side EXACT vs TILE pictures, and a motion strip, so the
argument can be LOOKED AT and not just tabulated.

    python3 engine2/tools/tileshot.py                # picks corridor states
"""
import os
import sys

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import tilecount as tc                                        # noqa: E402
import tilelook as tl                                         # noqa: E402
import pacescan                                               # noqa: E402

SCALE = 4
COL = {0: (0, 0, 64), 1: (68, 108, 255), 2: (0, 0, 0)}


def img(buf, grid=False):
    im = Image.new("RGB", (tc.VP_PW, tc.VP_H))
    px = im.load()
    for y in range(tc.VP_H):
        for x in range(tc.VP_PW):
            px[x, y] = COL[buf[y][x]]
    im = im.resize((tc.VP_PW * SCALE * 2, tc.VP_H * SCALE), Image.NEAREST)
    return im


def strip(images, gap=8):
    w = sum(i.width for i in images) + gap * (len(images) - 1)
    h = max(i.height for i in images)
    out = Image.new("RGB", (w, h), (40, 40, 40))
    x = 0
    for i in images:
        out.paste(i, (x, 0))
        x += i.width + gap
    return out


def main():
    solid, pos = pacescan.positions()
    outdir = os.path.join(_HERE, "..", "..", "build")
    # a state looking down a corridor, and an angled one
    picks = [(0x0C80, 0x0680, 0), (3568, 2480, 38), (1976, 1584, 54)]
    for n, (px, py, a) in enumerate(picks):
        if not pacescan.coll_free(solid, px, py):
            continue
        faces = tc.quads_and_faces(solid, px, py, a)
        e = tl.render_exact(faces)
        t = tl.render_tile(faces)
        p = os.path.join(outdir, f"tile_cmp{n}.png")
        strip([img(e), img(t)]).save(p)
        print("wrote", os.path.abspath(p), f"exact|tile  state {px,py,a}")

    # motion strip: four consecutive walk frames, exact on top, tile below
    px, py, a = picks[1]
    seq = tl.walk(solid, px, py, a, 3)
    ex, ti = [], []
    for (qx, qy, qa) in seq:
        f = tc.quads_and_faces(solid, qx, qy, qa)
        ex.append(img(tl.render_exact(f)))
        ti.append(img(tl.render_tile(f)))
    top, bot = strip(ex), strip(ti)
    out = Image.new("RGB", (top.width, top.height * 2 + 8), (40, 40, 40))
    out.paste(top, (0, 0))
    out.paste(bot, (0, top.height + 8))
    p = os.path.join(outdir, "tile_motion.png")
    out.save(p)
    print("wrote", os.path.abspath(p), "walk: exact row / tile row")


if __name__ == "__main__":
    main()
