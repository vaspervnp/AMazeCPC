"""MODE 0 vs MODE 1, the SAME picture, off the SAME quad list.

Renders the reference look -- flat blue walls, black mortar in BOTH axes,
blocks foreshortening to the vanishing point -- into the two samplings the
CPC can offer for the SAME 44x96 bytes of screen:

    mode 0    88 x 96 pixels, 16 pens      (what the engine is)
    mode 1   176 x 96 pixels,  4 pens

and writes both out at the same PHYSICAL size, so the only difference on
screen is the sampling.  Geometry and quad list come from marchmodel /
projmodel / rastermodel -- the real engine's, not a mock-up.

    python3 m1shot.py <outdir> [px py heading]
"""
import os
import struct
import sys
import zlib

_T = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _T)

import marchmodel as mm            # noqa: E402
import projmodel as pm             # noqa: E402
import rastermodel as rm           # noqa: E402
import pacescan                    # noqa: E402

CFG = rm.cfg()
VP_BW, VP_H, CYH = CFG.VP_BW, CFG.VP_H, CFG.CYH

NBLOCK = 4            # stone blocks across one wall cell
NCOURSE = 3           # courses up one wall cell (odd: see rastermodel)

# RGB, deliberately the same colours in both modes so only sampling differs
C_STONE = (0, 128, 255)      # ink 11 sky blue -- pal.py's THE WALL
C_MORT = (0, 0, 0)           # black mortar
C_CEIL = (0, 0, 128)         # ink 1
C_FLOOR = (128, 128, 0)      # ink 12


def png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xFFFFFFFF)
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def faces(px, py, a):
    """-> [(quad record, full-precision screen tuple)] in march order."""
    solid, _ = pacescan.positions()
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        s = pm.project_face_screen(v[0], v[1], v[2], v[3],
                                   ax - ipx, ay - ipy, fd)
        if s is None:
            continue
        q = pm.pack_quad(s)
        out.append((q + (door, k), s))
    return out


def joint_x(sxa, wa, sxb, wb, u):
    """Screen x of wall parameter u, PERSPECTIVE CORRECT.

    hh is proportional to 1/z, so t = u*wa / (wb*(1-u) + wa*u) and
    x = sxa + t*(sxb-sxa).  Same six bytes raster_joint uses; the
    engine would do this with one 8-bit divide (tst_m1.asm:s_jcol)."""
    den = wb * (1.0 - u) + wa * u
    if den <= 0:
        return None
    t = u * wa / den
    return sxa + t * (sxb - sxa)


def render(px, py, a, ppb):
    """ppb = PIXELS PER BYTE: 2 for mode 0, 4 for mode 1.

    -> a [VP_H][VP_BW*ppb] array of RGB tuples, painted exactly where
    rastermodel.raster_quad says the engine writes, and textured with the
    pattern a baked-immediate fill would carry."""
    W = VP_BW * ppb
    img = [[C_CEIL if r < CYH else C_FLOOR for _ in range(W)]
           for r in range(VP_H)]
    for q, s in faces(px, py, a):
        sxa, hha, sxb, hhb = s          # Q12.4 half-byte units / scanlines
        xa, xb = sxa / 16.0, sxb / 16.0     # in mode-0 pixels
        if xb - xa < 1e-6:
            continue
        # --- the vertical mortar columns, in mode-0 pixel units ---
        vjoint = [xa, xb]
        for i in range(1, NBLOCK):
            jx = joint_x(xa, hha, xb, hhb, i / float(NBLOCK))
            if jx is not None:
                vjoint.append(jx)
        # --- paint exactly the runs raster_quad emits ---
        for (row, end, npush) in rm.raster_quad(q, CFG):
            b0, b1 = end - 2 * npush, end
            # hh at a screen x is LINEAR -- that is the free axis
            for pxl in range(b0 * ppb, b1 * ppb):
                if not (0 <= pxl < W):
                    continue
                x0 = pxl * 2.0 / ppb        # mode-0 pixel units
                t = (x0 - xa) / (xb - xa)
                hh = (hha + (hhb - hha) * t) / 16.0
                top, bot = CYH - hh, CYH + hh
                if not (top - 0.5 <= row <= bot + 0.5):
                    continue
                col = C_STONE
                # horizontal course joints: v = i/NCOURSE, linear in y
                v = (row - top) / max(bot - top, 1e-6)
                for i in range(1, NCOURSE):
                    if abs(v - i / float(NCOURSE)) * (bot - top) < 0.5:
                        col = C_MORT
                # vertical mortar: one PIXEL wide in whatever mode this is
                for jx in vjoint:
                    if abs(x0 - jx) < 1.0 / ppb:
                        col = C_MORT
                img[row][pxl] = col
    return img


def emit(path, img, ppb, zoom=4):
    """Both modes out at the SAME physical size: a mode-0 pixel is twice
    as wide as a mode-1 one, and both are 1 scanline tall."""
    W = len(img[0])
    xs = zoom * (4 // ppb) * 2          # mode0 -> 8*zoom/2, mode1 -> 4*zoom/2
    rows = []
    for r in img:
        line = []
        for c in r:
            line += list(c) * xs
        for _ in range(zoom * 2):
            rows.append(line)
    png(path, W * xs, len(rows), rows)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    if len(sys.argv) > 4:
        px, py, a = (int(x) for x in sys.argv[2:5])
    else:
        px, py, a = 3384, 1352, 52       # wallarea.py's worst-painted state
    for ppb, name in ((2, "mode0"), (4, "mode1")):
        img = render(px, py, a, ppb)
        p = os.path.join(out, f"{name}_{px}_{py}_{a}.png")
        emit(p, img, ppb)
        print("wrote", p, len(img[0]), "x", len(img), "pixels")


if __name__ == "__main__":
    main()
