"""Rasterise a free-angle frame into a Mode 0 pen buffer and write a PNG.

The buffer is the real 160x200 Mode 0 screen; only the 36x104-byte viewport
is written and only that region is cropped out for the image, so the pixels
you see are exactly the pixels the PUSH DE runs would land on.
"""

from PIL import Image

import cpchw as cpc
import geom
import world
from geom import Rect

import free


def new_frame():
    return [[0] * cpc.SCR_W_BYTES * 2 for _ in range(cpc.SCR_H)]


def _row(buf, y, xb, npush, pen):
    if not (0 <= y < cpc.SCR_H):
        return
    r = buf[y]
    for b in range(xb, xb + npush * 2):
        if 0 <= b < cpc.SCR_W_BYTES:
            r[b * 2] = pen
            r[b * 2 + 1] = pen


def draw(buf, frame):
    for y0, y1, pen in frame["bands"]:
        for y in range(y0, y1):
            _row(buf, y, geom.VP_BX, geom.VP_BW // 2, pen)
    for g, pen in frame["faces"]:
        if isinstance(g, Rect):
            for i in range(g.h):
                _row(buf, g.y0 + i, g.xb, g.npush, pen)
        else:
            for i, (xb, n) in enumerate(g.lines):
                _row(buf, g.y0 + i, xb, n, pen)


def crop_viewport(buf, sx=8, sy=6):
    """Crop to the 72x104-pixel viewport and scale up (NEAREST)."""
    w, h = geom.VP_BW * 2, geom.VP_H
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            pen = buf[geom.VP_Y + y][geom.VP_BX * 2 + x]
            px[x, y] = cpc.ink_rgb(world.PEN_INK[pen])
    return img.resize((w * sx, h * sy), Image.NEAREST)


def render_png(grid, px_, py_, a_idx, path, doors=None, sx=8, sy=6):
    fr = free.build_frame(grid, px_, py_, a_idx, doors)
    buf = new_frame()
    draw(buf, fr)
    crop_viewport(buf, sx, sy).save(path)
    return fr
