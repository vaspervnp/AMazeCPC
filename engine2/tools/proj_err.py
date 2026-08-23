"""Worst-case SCREEN error of the projection tables, in pixels.

    python3 engine2/tools/proj_err.py

gentab.py prints the error banded by depth over the whole frustum, which
includes endpoints that project far outside the window.  What actually
matters for the picture is the error of the pixels you can SEE, so this
tool reports both:

  x    the PXT route (one 16x8 multiply, what project.asm runs).  Error
       counted only where the true xs lands inside [0, VP_PW].
  y    HTAB, the projected half-height.  A wall edge is inside the
       viewport only when hh <= CY, i.e. z >= FOCAL_V/(2*CY) = 1 cell;
       nearer than that both edges are off-screen and clamped by the
       rasteriser, so their error cannot be seen.

One mode-0 pixel is one half-byte unit, and the PUSH DE rasteriser can
only start and end a run on a whole BYTE, so anything under 2 half-byte
units of x error is already below what the fill can express.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gentab                                                # noqa: E402

VQ_ONE, ZQ_SHIFT, ZQ_N = gentab.VQ_ONE, gentab.ZQ_SHIFT, gentab.ZQ_N
CX, CY = gentab.CX, gentab.CY
FH, FV = gentab.FOCAL_H, gentab.FOCAL_V
K = gentab.KHALF


def main():
    htab, pxt = gentab.t_htab(), gentab.t_pxt()
    zmin = gentab.ZNEAR_Q10
    zmax = (ZQ_N << ZQ_SHIFT) - 1

    wx = wx_seen = wh = wh_seen = 0.0
    at = {}
    for z10 in range(zmin, zmax, 1):
        z = z10 / VQ_ONE
        zq = min(ZQ_N - 1, max(gentab.ZNEAR_Q8, (z10 + 2) >> ZQ_SHIFT))
        pm, sh = pxt[zq] & 0xFF, pxt[zq] >> 8
        eh = abs(htab[zq] / 16.0 - 0.5 * FV / z)
        wh = max(wh, eh)
        if 0.5 * FV / z <= CY:                  # the edge is on screen
            wh_seen = max(wh_seen, eh)
        for k in range(-64, 65):                # across the whole frustum
            xv = K * z * k / 64.0
            xq = int(round(xv * VQ_ONE))
            p = abs(xq) * pm
            off = (p >> sh) + ((p >> (sh - 1)) & 1)
            got = (CX * 16 + (-off if xq < 0 else off)) / 16.0
            true = CX + xv * FH / z
            e = abs(got - true)
            wx = max(wx, e)
            if 0.0 <= true <= 2 * CX:
                if e > wx_seen:
                    wx_seen, at = e, dict(z=z, xv=xv, xs=true)

    print(f"viewport {gentab.VP_BW}x{gentab.VP_H} bytes "
          f"({gentab.VP_PW}x{gentab.VP_H} px), FOCAL_H {FH:.3f} "
          f"FOCAL_V {FV:.0f}, CX {CX:.0f} CY {CY:.0f}")
    print(f"  x, whole frustum        {wx:6.3f} half-byte units "
          f"= {wx:.3f} mode-0 pixels")
    print(f"  x, ON SCREEN only       {wx_seen:6.3f} pixels "
          f"(at z={at['z']:.3f}, xs={at['xs']:.1f})")
    print(f"  y, all depths           {wh:6.3f} scanlines")
    print(f"  y, edge ON SCREEN only  {wh_seen:6.3f} scanlines "
          f"(z >= {FV / (2 * CY):.2f} cells)")
    print(f"  rasteriser quantum      2.000 pixels (PUSH DE writes whole "
          f"bytes), 1.000 scanlines")


if __name__ == "__main__":
    main()
