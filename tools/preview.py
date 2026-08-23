"""Python model of the Z80 renderer.

Draws a frame using exactly the span primitives the Z80 will consume, into a
160x200 buffer of pen indices, then writes a PNG.  This is where the geometry,
draw order, depth shading and door behaviour get validated -- getting it wrong
here is cheap, getting it wrong in assembly is not.
"""

import sys
from PIL import Image

import cpchw as cpc
import geom
import world
from geom import Rect, Spans, FRONT, SIDE

BORDER_PEN = 0

# Mirrors the USE_OCCLUDER ifdef in src/main.asm.  The shipped engine does not
# define it -- render_frame deliberately skips find_occluder -- so this defaults
# to False and the model matches what actually ships.  Flip it (or pass
# --occluder to cost.py) to evaluate an USE_OCCLUDER build.
USE_OCCLUDER = False


def new_frame():
    return [[BORDER_PEN] * cpc.SCR_W_BYTES * 2 for _ in range(cpc.SCR_H)]


def _row_span(buf, y, xb, npush, pen):
    """One PUSH DE run: npush pushes = npush*2 bytes = npush*4 pixels."""
    if not (0 <= y < cpc.SCR_H):
        return
    row = buf[y]
    for b in range(xb, xb + npush * 2):
        if 0 <= b < cpc.SCR_W_BYTES:
            row[b * 2] = pen
            row[b * 2 + 1] = pen


def draw_rect(buf, r, pen, bias=0, hclip=None):
    """`bias` shifts the view horizontally for the turn whip-pan; `hclip`
    truncates the height, which is how a door retracts upwards."""
    h = r.h if hclip is None else min(r.h, hclip)
    for i in range(h):
        xb, n = _bias_clip(r.xb, r.npush, bias)
        if n:
            _row_span(buf, r.y0 + i, xb, n, pen)


def draw_spans(buf, s, pen, bias=0):
    for i, (xb, n) in enumerate(s.lines):
        xb, n = _bias_clip(xb, n, bias)
        if n:
            _row_span(buf, s.y0 + i, xb, n, pen)


def _bias_clip(xb, npush, bias):
    """Shift a span by `bias` bytes and clip it to the viewport."""
    if bias:
        xb += bias
    x0 = max(xb, geom.VP_BX)
    x1 = min(xb + npush * 2, geom.VP_BX + geom.VP_BW)
    n = (x1 - x0) // 2
    return x0, max(0, n)


def fill_box(buf, x0b, y0, wb, h, pen):
    for y in range(y0, y0 + h):
        _row_span(buf, y, x0b, wb // 2, pen)


# ------------------------------------------------------------- 3D view ----

def build_facelist(grid, px, py, facing, substep, doors):
    """Faces to draw this frame, already in painter's order.

    Returns (faces, occluder) where `occluder` is the scanline range covered by
    the nearest full-viewport-width front face, if any.  Background fill under
    that band is pure waste, and skipping it is what brings the worst-case
    frame back inside budget.
    """
    off = geom.substep_offset(substep)
    seen = world.visible_cells(grid, px, py, facing, doors,
                               geom.L_MAX, geom.F_MAX)
    faces = []
    occluder = None

    for kind, l, f in geom.slots():
        mx, my = world.view_to_maze(px, py, facing, l, f)
        cell = world.cell_at(grid, mx, my)
        if cell == world.FLOOR:
            continue
        # A face only exists if the player can see into the cell it faces.
        # Testing the *specific* neighbour, rather than any of them, culls
        # every face buried against another wall -- most of them, in a maze.
        if kind == FRONT:
            neighbour = (l, f - 1)
        else:
            neighbour = (l - 1, f) if l > 0 else (l + 1, f)
        if neighbour not in seen:
            continue

        is_door = cell == world.DOOR
        g = (geom.front_face(l, f, off) if kind == FRONT
             else geom.side_face(l, f, off))
        if g is None:
            continue

        hclip = None
        if is_door and kind == FRONT:
            openness = doors.get((mx, my), 0)          # 0..4, 4 = retracted
            if openness >= 4:
                continue
            if isinstance(g, Rect):
                hclip = int(g.h * (1.0 - openness / 4.0))
                if hclip <= 0:
                    continue

        pen = world.wall_pen(max(f, 1), kind == SIDE, is_door)
        faces.append((kind, g, pen, hclip))

        # A full-width opaque front face hides every background pixel behind it.
        if kind == FRONT and isinstance(g, Rect) and g.npush * 2 == geom.VP_BW:
            h = g.h if hclip is None else hclip
            band = (g.y0, g.y0 + h)
            if occluder is None or (band[1] - band[0]) > (occluder[1] - occluder[0]):
                occluder = band

    return faces, occluder


def _band(buf, y0, y1, pen, occ):
    """Fill scanlines [y0, y1) across the viewport, minus the occluded band."""
    if occ:
        if occ[0] <= y0 and occ[1] >= y1:
            return
        if occ[0] <= y0 < occ[1]:
            y0 = occ[1]
        elif occ[0] < y1 <= occ[1]:
            y1 = occ[0]
    if y1 > y0:
        fill_box(buf, geom.VP_BX, y0, geom.VP_BW, y1 - y0, pen)


def render_view(buf, grid, px, py, facing, substep, doors, bias=0):
    off = geom.substep_offset(substep)
    faces, occ = build_facelist(grid, px, py, facing, substep, doors)
    if not USE_OCCLUDER:
        occ = None

    # Ceiling and floor as four abutting bands -- brightness increases towards
    # the bottom of the floor and the top of the ceiling, so the light reads as
    # coming from the player rather than from behind the walls.  The bands must
    # not overlap: every wasted scanline here is ~19us of pure overhead.
    top, bot = geom.VP_Y, geom.VP_Y + geom.VP_H
    mid = geom.VP_Y + geom.VP_H // 2
    yc = geom.horizon_y(2, off, True) or mid
    yf = geom.horizon_y(2, off, False) or mid
    yc = max(top, min(mid, yc))
    yf = max(mid, min(bot, yf))

    _band(buf, top, yc, world.CEIL_NEAR, occ)
    _band(buf, yc, mid, world.CEIL_FAR, occ)
    _band(buf, mid, yf, world.FLOOR_FAR, occ)
    _band(buf, yf, bot, world.FLOOR_NEAR, occ)

    for kind, g, pen, hclip in faces:
        if isinstance(g, Rect):
            draw_rect(buf, g, pen, bias, hclip)
        else:
            draw_spans(buf, g, pen, bias)


# ----------------------------------------------------------------- HUD ----

def render_hud(buf, px, py, facing):
    vx0, vy0 = geom.VP_BX, geom.VP_Y
    vw, vh = geom.VP_BW, geom.VP_H

    # Bevel around the viewport.
    fill_box(buf, vx0 - 2, vy0 - 2, vw + 4, 2, world.HUD_FRAME)
    fill_box(buf, vx0 - 2, vy0 + vh, vw + 4, 2, world.HUD_FRAME)
    for y in range(vy0 - 2, vy0 + vh + 2):
        _row_span(buf, y, vx0 - 2, 1, world.HUD_FRAME)
        _row_span(buf, y, vx0 + vw, 1, world.HUD_FRAME)

    # Compass rose: a lit block on the faced side of a 3x3 cluster.
    cx, cy = 4, 150
    fill_box(buf, cx, cy, 24, 24, world.HUD_FRAME)
    off = {0: (8, 0), 1: (16, 8), 2: (8, 16), 3: (0, 8)}[facing]
    fill_box(buf, cx + off[0] // 2 * 2, cy + off[1], 8, 8, world.HUD_TEXT)

    # Bottom status bar.
    fill_box(buf, 0, 190, cpc.SCR_W_BYTES, 4, world.HUD_FRAME)


# --------------------------------------------------------------- output ----

def to_image(buf, scale_x=4, scale_y=2):
    w, h = cpc.SCR_W_BYTES * 2, cpc.SCR_H
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = cpc.ink_rgb(world.PEN_INK[buf[y][x]])
    return img.resize((w * scale_x, h * scale_y), Image.NEAREST)


def main():
    grid, sx, sy = world.load_maze()
    DOOR = (4, 9)
    shots = [
        # name          x   y  facing sub  doors        bias
        ("corridor",    sx, sy, 1, 0, {},               0),
        ("corr-mid",    sx, sy, 1, 4, {},               0),
        ("wall-ahead",  sx, sy, 0, 4, {},               0),
        ("door-shut",    2,  9, 1, 0, {},               0),
        ("door-half",    2,  9, 1, 0, {DOOR: 2},        0),
        ("door-open",    2,  9, 1, 0, {DOOR: 4},        0),
        ("whip-pan",    sx, sy, 1, 0, {},             -10),
    ]
    out = []
    for name, x, y, fac, sub, dr, bias in shots:
        buf = new_frame()
        render_view(buf, grid, x, y, fac, sub, dr, bias)
        render_hud(buf, x, y, fac)
        img = to_image(buf)
        path = f"build/preview_{name}.png"
        img.save(path)
        out.append(path)
        print("wrote", path)
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
