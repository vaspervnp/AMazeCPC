"""Bit-exact Python model of engine2/src/project.asm.

This file is the SPEC.  Every integer operation here has a one-to-one
counterpart in the Z80, and the emulator test asserts that the Z80 reproduces
this model EXACTLY (not approximately).  A second test then measures this
model against prototype/free-angle/free.py:project_face(), which is float
ground truth, and reports the discrepancy in screen pixels.

Fixed point (identical to engine2/tools/gentab.py, which owns the tables):
    VIEW  int16 Q6.10   xv (lateral, +right) and z (depth, +forward), cells
    ZQ    uint16        (z_q10 + 2) >> 2, clamped to [ZNEAR_Q8 .. 2047]
    SX    int16 Q12.4   screen x in HALF-BYTE units (1 mode-0 pixel)
    SY    int16 Q12.4   screen y in scanlines

THE PROJECTOR TAKES VIEW-SPACE ENDPOINTS.  project_face() is handed
(xv, z) for both ends of the wall face; the march is what carries them,
incrementally, two adds per cell step.  Frame.view() below is the STUB that
stands in until that march lands -- it is the old lattice table, kept only
so the harnesses and the shipped kernel keep working:

    xv(i,j) = i*rgtx + j*rgty - xv0        xv0 = (fx*rgtx + fy*rgty) >> 8
    z (i,j) = i*fwdx + j*fwdy - z0         z0  = (fx*fwdx + fy*fwdy) >> 8

ONE ENDPOINT = TWO TABLE LOOKUPS AND ONE MULTIPLY
    zq = (z+2)>>2, clamped                       (the depth index)
    hh = HTAB[zq]                                projected HALF-height, Q12.4
    pm, sh = PXT[zq]                             pre-normalised FOCAL_H/z
    xs = CX_Q4 +- round((|xv| * pm) >> sh)       ONE 16x8 multiply
    ytop = CY_Q4 - hh,  ybot = CY_Q4 + hh        no multiply at all
The camera is at wall mid-height with no pitch, so the top and bottom edges
are mirror images about the horizon CY: only hh is ever interpolated.

CLIPPING
    NEAR plane, in VIEW space: a point at or behind the eye does not project
    at all, so this one has to happen before the projection.  The survivor
    lands on z = ZNEAR exactly and only its xv is interpolated.

    SIDES, in SCREEN space: the projection of a straight 3D line is a
    straight 2D line, so the wall's top and bottom edges are straight in
    screen space and clipping them is an EXACT linear interpolation of hh
    against xs -- no re-projection, no view-space lerp of z.

    An endpoint far outside the frustum has an unbounded xs, so proj_point
    REJECTS any endpoint whose |xs - CX| would reach 16384 Q12.4 (1024
    half-byte units).  A face with ANY visible part cannot get there: with
    both endpoints at z >= ZNEAR = 0.125, a face one cell long that touches
    the frustum has |xs - CX| <= 665*(K*0.125 + max_s(K*s + sqrt(1-s^2)))
    = 816 half-byte units = 13056 Q12.4, a 25% margin.  That bound also
    keeps xb - xa inside int16, which the clip interpolation needs.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import gentab                                              # noqa: E402

# ---------------------------------------------------------------- tables ---
QSQ = gentab.t_qsq()
HTAB = gentab.t_htab()
PROJ = gentab.t_proj()
PXT = gentab.t_pxt()
BITLEN = gentab.t_bitlen()
RCP = gentab.t_rcp()
BASIS = gentab.t_basis()

VQ_ONE = gentab.VQ_ONE          # 1024
ZQ_ONE = gentab.ZQ_ONE          # 256
ZNEAR_Q10 = gentab.ZNEAR_Q10    # 128
ZNEAR_Q8 = gentab.ZNEAR_Q8      # 32
ZFAR_Q8 = gentab.ZQ_N - 1       # 2047
CX_Q4 = int(gentab.CX) * 16     # 768
CY_Q4 = int(gentab.CY) * 16     # 1024
XMAX_Q4 = gentab.VP_PW * 16     # 1536, the right edge of the viewport
XSAT = 16384                    # |xs - CX| this big = far outside, reject

NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3


# ------------------------------------------------------------- primitives --
def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def mul8x8u(a, b):
    """QSQ[a+b] - QSQ[|a-b|]; exact for 0 <= a,b <= 255."""
    assert 0 <= a <= 255 and 0 <= b <= 255
    return QSQ[a + b] - QSQ[abs(a - b)]


def mul16x8u(a16, b8):
    """Unsigned 16x8 -> 24-bit, as the Z80 does it: two quarter-square 8x8s."""
    assert 0 <= a16 <= 0xFFFF and 0 <= b8 <= 255
    return mul8x8u(a16 & 0xFF, b8) + (mul8x8u(a16 >> 8, b8) << 8)


def norm16(v):
    """Left-shift count s so that (v << s) has bit 15 set.  v > 0."""
    n = (v >> 8) or 0
    ln = 8 + BITLEN[n] if n else BITLEN[v & 0xFF]
    return 16 - ln


# ---------------------------------------------------------- clip lerp -----
def lerp(a, b, na, nb):
    """a + (b-a) * na/(na+nb), all integers, na,nb >= 0, na+nb > 0.

    na and nb are |signed distance| to the plane for the two endpoints, so
    na/(na+nb) is the clip parameter.  Precision path, matching the Z80:
      * normalise D = na+nb to bit 15, take the top byte as the divisor n
      * t_q15 = (An * RCP[n]) >> 8   with RCP[n] = 32768/n, split as
        (An >> 1) + ((An * (RCP[n]-128)) >> 8) so it is one 16x8 multiply
      * (b-a)*t_q15 >> 15 done as ONE 16x8 on the high half of t plus one
        8x8 on the low half -- that second term is at most |b-a| >> 8, so
        feeding it |b-a| >> 8 instead of |b-a| costs under one LSB and
        turns a 142 us multiply into a 55 us one.
    """
    d = na + nb
    if d == 0:
        return a
    s = norm16(d)
    dn = (d << s) & 0xFFFF
    an = (na << s) & 0xFFFF
    n = (dn + 128) >> 8
    if n > 255:
        n = 255
    r = RCP[n] - 128                    # 0..128
    t15 = (an >> 1) + (mul16x8u(an, r) >> 8)
    if t15 > 32767:
        t15 = 32767
    delta = b - a
    ad = abs(delta)
    th, tl = t15 >> 7, t15 & 127
    q = (mul16x8u(ad, th) >> 8) + ((mul8x8u(ad >> 8, tl) << 1) >> 8)
    return a - q if delta < 0 else a + q


# ------------------------------------------------------------- per frame ---
class Frame:
    """Per-frame lattice tables; the Z80 equivalent is proj_setup."""

    def __init__(self, px, py, ang):
        self.px, self.py, self.ang = px, py, ang
        rgtx, rgty, fwdx, fwdy = BASIS[ang * 4:ang * 4 + 4]
        rgtx, rgty, fwdx, fwdy = (s16(rgtx), s16(rgty), s16(fwdx), s16(fwdy))
        self.ipx, self.ipy = int(math.floor(px)), int(math.floor(py))
        self.fx = int(round((px - self.ipx) * 256)) & 0xFF
        self.fy = int(round((py - self.ipy) * 256)) & 0xFF

        def m(v, f):                    # (v * f) >> 8, signed 16 x unsigned 8
            p = mul16x8u(abs(v), f) >> 8
            return -p if v < 0 else p

        xv0 = m(rgtx, self.fx) + m(rgty, self.fy)
        z0 = m(fwdx, self.fx) + m(fwdy, self.fy)
        self.XR = [i * rgtx - xv0 for i in range(-8, 9)]
        self.XF = [i * fwdx - z0 for i in range(-8, 9)]
        self.YR = [j * rgty for j in range(-8, 9)]
        self.YF = [j * fwdy for j in range(-8, 9)]

    def view(self, i, j):
        return (self.XR[i + 8] + self.YR[j + 8],
                self.XF[i + 8] + self.YF[j + 8])


def khalf_z(z):
    """0.578125*z by shifts: z/2 + z/16 + z/64 (KHALF = 0.57735, 0.13% wide)."""
    return (z >> 1) + (z >> 4) + (z >> 6)


def shr_round(v, sh):
    """v >> sh, round to nearest, EXACTLY as proj_pt does it.

    For sh >= 8 the Z80 drops the whole low byte first (rounding there),
    then shifts the remaining 16 bits and rounds again, because that is
    two register moves instead of eight shifts of a 24-bit value.  The
    double rounding costs at most 1 Q12.4 unit = 1/16 of a pixel, so the
    model reproduces it rather than the code paying for exactness.
    """
    if sh < 8:
        return (v >> sh) + ((v >> (sh - 1)) & 1)
    v = (v >> 8) + ((v >> 7) & 1)
    k = sh - 8
    if k:
        v = (v >> k) + ((v >> (k - 1)) & 1)
    return v


# ------------------------------------------------------------ projection ---
def project_point(xv, z):
    """(xv, z) Q6.10 -> (xs Q12.4, hh Q12.4), or None if far outside.

    Two table lookups and one 16x8 multiply.  hh is the projected HALF
    height; the caller turns it into ytop/ybot with one subtract and one
    add, because the horizon is exactly CY.
    """
    zq = (z + 2) >> 2
    if zq < ZNEAR_Q8:
        zq = ZNEAR_Q8
    elif zq > ZFAR_Q8:
        zq = ZFAR_Q8
    v = PXT[zq]
    off = shr_round(mul16x8u(abs(xv), v & 0xFF), v >> 8)
    if off >= XSAT:                 # the Z80 tests H >= #40 (and A != 0)
        return None
    return (CX_Q4 - off if xv < 0 else CX_Q4 + off), HTAB[zq]


# --------------------------------------------------------- the whole face --
def face_endpoints(wx, wy, face_dir):
    """Same as free.py."""
    if face_dir == NORTH:
        return (wx, wy), (wx + 1, wy), (0, -1)
    if face_dir == SOUTH:
        return (wx, wy + 1), (wx + 1, wy + 1), (0, 1)
    if face_dir == WEST:
        return (wx, wy), (wx, wy + 1), (-1, 0)
    return (wx + 1, wy), (wx + 1, wy + 1), (1, 0)


# Backface test in lattice terms.  The face lies on an integer grid line; the
# player is inside cell 0 at fraction f in [0,1), so "player on the outward
# side" reduces to a comparison of the line's integer index against 0.
#   NORTH  normal (0,-1): need py <  ay  ->  j >= 1
#   EAST   normal (+1,0): need px >  ax  ->  i <= 0
#   SOUTH  normal (0,+1): need py >  ay  ->  j <= 0
#   WEST   normal (-1,0): need px <  ax  ->  i >= 1
_CULL = {NORTH: (1, +1), EAST: (0, -1), SOUTH: (1, -1), WEST: (0, +1)}


def project_face_screen(xa, za, xb, zb, i0, j0, face_dir):
    """View-space endpoints A and B (Q6.10) -> SCREEN space, or None.

    (i0, j0) is the cell offset of endpoint A, used ONLY by the backface
    test; the march has it anyway.

    -> (sxa, hha, sxb, hhb): screen x in Q12.4 half-byte units and the
    projected HALF height there in Q12.4 scanlines, LEFT endpoint first.
    This is the full-precision screen-space result, which is what the
    float reference in prototype/free-angle/free.py can be compared
    against; project_face() below packs it into the record the rasteriser
    is actually handed, which is coarser on purpose.
    """
    axis, sense = _CULL[face_dir]
    v = (j0 if axis else i0)
    if sense > 0:
        if v < 1:
            return None
    else:
        if v > 0:
            return None

    # --- near plane, in VIEW space: z >= ZNEAR, survivor keeps z = ZNEAR ---
    da, db = za - ZNEAR_Q10, zb - ZNEAR_Q10
    if da < 0 and db < 0:
        return None
    if da < 0:
        xa, za = lerp(xa, xb, -da, db), ZNEAR_Q10
    elif db < 0:
        xb, zb = lerp(xb, xa, -db, da), ZNEAR_Q10

    # --- cheap side REJECT, before paying for two projections.  Only
    #     "both endpoints outside the SAME plane" kills a face; anything
    #     that merely crosses a plane is clipped later, in screen space.
    #     Endpoint B is not even looked at unless A is outside something.
    #     K = 0.578125 is 0.13% WIDER than tan(30), so this cannot throw
    #     away a face with a visible pixel.  The new march carries these
    #     two half-plane values incrementally -- this is the stand-in.
    ka = khalf_z(za)
    if ka - xa < 0:
        if khalf_z(zb) - xb < 0:
            return None
    elif ka + xa < 0:
        if khalf_z(zb) + xb < 0:
            return None

    pa = project_point(xa, za)
    if pa is None:
        return None
    pb = project_point(xb, zb)
    if pb is None:
        return None
    sxa, hha = pa
    sxb, hhb = pb
    if sxa > sxb:
        sxa, hha, sxb, hhb = sxb, hhb, sxa, hha
    if sxb - sxa < 1:
        return None

    # --- sides, in SCREEN space.  hh is linear in xs along the edge, so
    #     clamping xs and interpolating hh is exact.  Sequential, like
    #     Sutherland-Hodgman: the second clip runs on the already-clipped
    #     segment, which is the same straight line. ---
    if sxb <= 0 or sxa >= XMAX_Q4:
        return None                     # wholly off one side
    if sxa < 0:
        hha = lerp(hha, hhb, -sxa, sxb)
        sxa = 0
    if sxb > XMAX_Q4:
        hhb = lerp(hhb, hha, sxb - XMAX_Q4, XMAX_Q4 - sxa)
        sxb = XMAX_Q4
    if sxb - sxa < 1:
        return None
    return (sxa, hha, sxb, hhb)


def byte_lo(x_q4):
    """Q12.4 half-byte units -> whole screen bytes, rounded DOWN (a LEFT
    edge).  One byte is two half-byte units = 32 in Q12.4, so this is
    x>>5 -- which the Z80 does as three ADD HL,HL and then takes H."""
    return (x_q4 << 3) >> 8


def byte_hi(x_q4):
    """...and rounded UP, for a RIGHT edge: (x+31)>>5.

    Rounding OUTWARD rather than to nearest is what keeps two faces that
    meet at a depth step from leaving a 2-pixel gap between them once the
    run lengths are forced even.  x is clamped to [0, XMAX_Q4] before it
    gets here and rounding is monotone, so 0 <= byte_lo(sxa) <=
    byte_hi(sxb) <= VP_BW."""
    return ((x_q4 + 31) << 3) >> 8


def pack_quad(s):
    """(sxa, hha, sxb, hhb) -> the 4 geometry fields of a quad record.

    -> (blo, bhi, hlo, hhi): byte columns and half heights, ordered by
    HEIGHT rather than by x, because the taller endpoint's column is the
    edge that is pinned in both of the rasteriser's wedges.  A tie counts
    as "right endpoint taller", which is what the Z80's JR C does.
    """
    sxa, hha, sxb, hhb = s
    ba, bb = byte_lo(sxa), byte_hi(sxb)
    if ba == 0 and (bb & 1):
        # column 0 is the one edge a run cannot be widened to the left of;
        # an even bb means it never has to be.  project.asm:pf_bok.
        bb += 1
    if hhb < hha:                       # LEFT endpoint taller
        return (bb, ba, hhb, hha)
    return (ba, bb, hha, hhb)           # RIGHT endpoint taller


def project_face(xa, za, xb, zb, i0, j0, face_dir):
    """View-space endpoints A and B (Q6.10) -> quad record, or None.

    -> (blo, bhi, hlo, hhi), exactly the six bytes project.asm:pf_emit
    leaves at pf_blo and kernel.asm copies into QUADS.
    """
    s = project_face_screen(xa, za, xb, zb, i0, j0, face_dir)
    return None if s is None else pack_quad(s)


def project_face_ij(frame, i0, j0, i1, j1, face_dir):
    """STUB caller: lattice indices -> view space -> project_face."""
    xa, za = frame.view(i0, j0)
    xb, zb = frame.view(i1, j1)
    return project_face(xa, za, xb, zb, i0, j0, face_dir)


def project_face_ij_screen(frame, i0, j0, i1, j1, face_dir):
    """The same, stopping at full-precision screen space."""
    xa, za = frame.view(i0, j0)
    xb, zb = frame.view(i1, j1)
    return project_face_screen(xa, za, xb, zb, i0, j0, face_dir)


def screen_xy(s):
    """(sxa, hha, sxb, hhb) -> the old (xa, yat, yab, xb, ybt, ybb) form.

    Nothing computes this any more -- ytop and ybot are CY_Q4 -+ hh and
    the rasteriser only ever wanted hh -- but the float-reference
    comparisons in check_proj.py and run_proj_test.py are written in it.
    """
    sxa, hha, sxb, hhb = s
    return (sxa, CY_Q4 - hha, CY_Q4 + hha, sxb, CY_Q4 - hhb, CY_Q4 + hhb)
