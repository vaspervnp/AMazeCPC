"""engine2 table generator -- emits the RAM-bank-4 image and the asm include.

engine2 is the FREE-MOVEMENT / FREE-ROTATION engine: the player sits at an
arbitrary (x, y) and one of 72 headings, so nothing about a wall's screen
shape can be precalculated.  What CAN be precalculated is the arithmetic the
runtime kernel needs: trig, reciprocals, a multiply table, and the screen
address map.  All of it lives in one 16K bank at &4000.

    python3 engine2/tools/gentab.py            # write build/TABLES.BIN + src/tab_equ.inc
    python3 engine2/tools/gentab.py --check    # self-check the table contracts only


=======================================================================
FIXED-POINT CONVENTIONS  (these ARE the contract; the kernel must match)
=======================================================================

  name      C type        meaning
  --------  ------------  ------------------------------------------------
  ANG       uint8  0..71  heading index, 5 degrees per step
  WPOS      uint16 Q6.10  player x / y in cells (1024 = one cell)
  VIEW      int16  Q6.10  view-space xv (right) and z (forward), in cells.
                          1024 = one cell.  z < 8 cells, so z_q10 < 8192;
                          |xv| <= KHALF*z < 4730 inside the frustum.
  ZQ        uint16        = (z_q10 + 2) >> 2, i.e. round(z*256).  THE index
                          into HTAB and PROJ.  The kernel must clamp z to
                          [ZNEAR_Q10 .. 8189], i.e. zq to [32 .. 2047].
                          The +2 is `inc hl / inc hl` before the two shifts
                          and halves the depth quantisation error -- keep it.
  SX        int16  Q12.4  screen x in HALF-BYTE units (16 = one half-byte)
  SY        int16  Q12.4  screen y in scanlines   (16 = one scanline)

Why xv is finer (Q10) than the depth index (Q8): the projected x error is
   d(xs) = FOCAL_H/z * d(xv)  +  (xs-CX) * d(z)/z
The first term needs ABSOLUTE precision in xv and blows up as z shrinks, so
xv is carried at 1/1024 cell.  The second only needs RELATIVE precision in z,
so a 1/256-cell table index is enough: at the near plane z = 0.125 it costs
0.5/32 = 1.6% * CX = 0.69 half-byte units.  Both terms stay under the
0.5-byte quantisation floor the PUSH DE rasteriser has anyway.

World convention (identical to prototype/free-angle/free.py):
    x to the right, y DOWNWARD (row index), cell size 1.0
    heading h degrees:  forward = (cos h,  sin h)
                        right   = (-sin h, cos h)
    view space:  xv = d . right,  z = d . forward,  where d = world - player

Viewport: OWNED BY engine2/src/vpcfg.inc, which the Z80 includes and this
    script parses -- it is the only place the numbers appear.  The amaze3
    build is Mode 0, 44x96 BYTES at VP_BX=18, VP_Y=0, i.e. 88x96 pixels:
    CX = 44 half-byte units, CY = 48 scanlines
    FOCAL_H = CX / tan(30 deg) = 76.210  -> 60 degree horizontal FOV
    FOCAL_V = 96                         -> a wall one cell away exactly
                                            fills the viewport height
    Every zv-indexed table below scales with FOCAL_H / FOCAL_V, so the
    tables MUST be regenerated whenever vpcfg.inc changes.


=======================================================================
TABLE CONTRACTS
=======================================================================

QSQ      512 x uint16.  QSQ[t] = floor(t*t/4), t = 0..511.
         For any 0 <= a,b <= 255:   a*b = QSQ[a+b] - QSQ[|a-b|]   EXACTLY.
         (Both sums have the same parity, so the two floors cancel.)
         This is the only multiply primitive in the engine.

HTAB     2048 x uint16, indexed by ZQ.  Projected HALF-height of a
         wall in Q12.4 scanlines:
             HTAB[zq] = round(16*(FOCAL_V/2)*256 / zq),  clamped to 65535
                      = round(196608 / zq)              at FOCAL_V = 96
         because  hs = 0.5*FOCAL_V/z = 48/z = 48*256/zq, and Q4 scales by 16.
         Kernel: hs_q4 = HTAB[zq];  wall top = CY*16 - hs_q4,
                                    wall bot = CY*16 + hs_q4.
         Sanity: z = 1 cell -> zq = 256 -> HTAB = 768 = 48.0 scanlines,
                 so the wall is 96 scanlines tall = the whole viewport.

PROJ     2048 x uint16, indexed by ZQ.  Horizontal projection factor
         FOCAL_H/z in Q12.4 half-byte-units per cell:
             PROJ[zq] = round(16 * FOCAL_H * 256 / zq),  clamped to 65535
         Kernel:  xs_q4 = CX*16 + ((xv_q10 * PROJ[zq]) >> 10)    [signed]
         The product needs 32 bits (it reaches 2^20) even though the RESULT
         is bounded by +-CX*16 = +-768 inside the frustum.

PXT      2048 x uint16, indexed by ZQ -- PROJ[] PRE-NORMALISED, so the
         runtime never normalises anything.  This is the table the cheap
         projector (engine2/src/project.asm:proj_pt) actually reads:
             low  byte = pm, an 8-bit mantissa, ALWAYS in [128, 255]
             high byte = sh, the right shift, in [4, 10]
             pm = round(PROJ[zq] >> e),  e = bitlen(PROJ[zq]) - 8
             sh = 10 - e
         so    off_q4 = round((|xv_q10| * pm) >> sh)
               xs_q4  = CX_Q4 +- off_q4
         with ONE 16x8 multiply and no runtime bit-length/normalise loop
         (that loop cost ~80 us per endpoint).  The mantissa is normalised,
         so the relative error of the projection factor is <= 0.5/128 =
         0.39% worst / 0.2% typical whatever the depth, which is why the
         table can be this small; see the error table this script prints.
         Entries below ZNEAR_Q8 repeat the ZNEAR entry (the kernel clamps
         zq, so they are never read).

PROJN    65 x uint16, and
HTN      65 x uint16 -- the NORMALISED (mantissa) form of PROJ and HTAB.
         PROJ/HTAB cost a full 16x16 multiply because their value is 16 bits
         wide.  Normalising z into one octave first makes the multiplier
         9 bits and the multiplicand 8, i.e. ONE quarter-square product:

             s  = BITLEN(z_q10) - 7            ; s in 1..6 for legal z
             zn = round(z_q10 >> s)            ; in [64, 128]  -> 65 entries
             j  = zn - 64
             xn = round(|xv_q10| >> s)         ; |xn| <= KHALF*zn < 74
             hs_q4 = HTN[j] >> s
             xs_q4 = CX_Q4 +- ((|xn| * PROJN[j]) >> 4)

             PROJN[j] = round(256 * FOCAL_H / (64+j))          ; 152..305
             HTN[j]   = round(16*(FOCAL_V/2)*1024 / (64+j))    ; 6144..12288
         Both "round(v >> s)" are `shift s-1 times, INC, shift once more`.

         Measured on the emulator this is ~2x faster than the PROJ/HTAB
         route and about 3x less accurate (still inside the rasteriser's
         own half-byte quantisation).  Both are provided; the kernel picks.

BASIS    72 x { dw rgtx, rgty, fwdx, fwdy } in Q6.10, = 4 int16 per heading.
             rgtx = -1024*sin(a)   rgty = 1024*cos(a)
             fwdx =  1024*cos(a)   fwdy = 1024*sin(a)
         Stored pre-signed so the march never has to negate anything:
         stepping one cell in world +x adds (rgtx, fwdx) to (xv, z);
         stepping one cell in world +y adds (rgty, fwdy).

RCP      256 x uint16.  RCP[n] = round(32768/n) for n >= 1, RCP[0] = 0.
         Kernel: v/n ~= (v * RCP[n]) >> 15.  Used for the wedge slope
         (rise over an n-half-byte run) and for clip parameters.
         Exact for n a power of two; worst relative error 1.5e-5 elsewhere.

LINETAB  200 x uint16.  Address of the LEFTMOST byte of scanline y in the
         &C000 buffer:  &C000 + (y&7)*&800 + (y>>3)*80.
         VP_BX is NOT folded in -- add it, or add the run's start byte.
         The back buffer at &8000 is reached with RES 6,H, as in src/.

BITLEN   256 x uint8.  BITLEN[b] = index of the highest set bit + 1
         (0 for b = 0).  Normalises a 16-bit value before an RCP lookup
         when the divisor exceeds 255.

PUSHENT  VP_BW+1 x uint8, indexed by run width in BYTES (0..VP_BW):
             PUSHENT[w] = MAXPUSH - (w >> 1)
         which is the LOW BYTE of the entry point into the page-aligned
         MAXPUSH-long unrolled PUSH DE block.  Odd widths round DOWN, so
         a run never overruns the width the rasteriser asked for.

M0SOLID  16 x uint8.  Mode 0 byte with both pixels set to pen p.

RAMPTAB  24 x uint8.  Depth-shaded solid byte for a wall face:
             index = door*12 + side*6 + (depth-1),  depth in 1..6
         `side` = the face is North/South facing (one ramp step darker),
         matching pal.wall_pen() so the Python model and the Z80 agree.

BANDPEN  4 x uint8: CEIL_NEAR, CEIL_FAR, FLOOR_FAR, FLOOR_NEAR solid bytes,
         in the order the background painter uses them (top to bottom).

MORTAR   1 x uint8.  The solid byte raster.asm:raster_joint paints a course
         boundary in -- pal.MORTAR, one dedicated dark pen, the same at
         every depth.  See pal.py for why it is ink 1 and not a ramp step.

DIV3     256 x uint8, DIV3[v] = v // 3, page aligned.
         raster_joint needs the SCANLINE ROW a course boundary falls on,
         which is floor(h / 48) for a half height h in Q12.4 -- the two
         boundaries of a three-course wall sit at u = h/3 above and below
         the horizon, and a row is 16 units of u.  h >> 4 is free (it is
         the row index the rasteriser already forms); the divide by three
         is not, so it is a lookup.  Indexed by h >> 4, which the caller
         has already rejected above 3*CYH+2 -- past that the whole joint
         is off the viewport.

GUNPIX   the first-person weapon.  engine2/tools/gunart.py owns the ART;
GUNBAND  these four tables are only its encoding, and they are in BANK 4
BOBV     rather than in an asm include because engine2/src/main3.asm has
BOBH     under 250 bytes left below the march's working RAM at #2700 and
         this is 340 bytes of data.  They are emitted AFTER DIV3, which is
         page aligned and last, so no address in tab_equ.inc moves.

         GUNPIX   one CONTIGUOUS RUN PER SCANLINE, top row first, runs
                  concatenated with no gaps or padding.  A row is a plain
                  byte copy because the silhouette has no holes.

         GUNBAND  the sprite is not 46 independent rows, it is a handful
                  of BANDS of consecutive rows that share a run (the same
                  x0 and the same length).  Grouping them is what makes
                  the blit affordable: engine2/src/gun.asm sets up the
                  copy ONCE per band and its per-row loop is then 27 us
                  of stepping plus 4 us a byte.  Five bytes a band,
                  terminated by a zero row count:

                      db  rows            rows in this band
                      db  2*(MAXN-n)      offset into gun.asm's unrolled
                                          LDI block that copies n bytes
                      db  (256-n)&255     added to E after every row, to
                                          undo the LDI's advance
                      dw  x0next - x0     signed, applied ONCE at the end
                                          of the band

         BOBV     BOTH tables are a SWING about a rest position and BOTH
         BOBH     are BIASED so the Z80 eases towards them with the same
                  unsigned compare: BOBV is GUN_BOBVN entries biased by
                  GUN_BOBVA (0..2*GUN_BOBVA, rest GUN_BOBVA) and BOBH is
                  GUN_BOBHN entries biased by GUN_BOBHA.  The vertical
                  used to be an unsigned RISE, 0..GUN_BOBVA upward only,
                  which put the resting position at the bottom of the
                  travel and made the weapon read as floating; it now
                  swings both ways about an anchor that hangs GUN_CUT
                  scanlines below the viewport.  The periods are mutually
                  prime, which is the whole point -- see gunart.py.
"""

import argparse
import json
import math
import os
import re
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))          # repo root
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                       # noqa: E402
import pal                                                # noqa: E402
sys.path.insert(0, _HERE)
import gunart                                             # noqa: E402

# ------------------------------------------------------------- geometry ----

#
# The viewport is NOT declared here.  engine2/src/vpcfg.inc owns it -- one
# file, included by the Z80 and parsed below -- so the tables and the code
# cannot drift apart.  Everything below follows from those nine numbers;
# FOCAL_H is a float and never reaches the asm except as FOCAL_H_Q8 in the
# generated tab_equ.inc.

VPCFG = os.path.join(_ROOT, "engine2", "src", "vpcfg.inc")


def load_vpcfg(path=VPCFG):
    """Parse `NAME equ <integer expression>` out of the config include.

    rasm's expression syntax and Python's agree on + - * ( ) and on the
    #hex prefix once it is rewritten to 0x; `/` is integer division in
    rasm, so it is rewritten to `//`.  Anything else is a hard error --
    this parser must never silently disagree with the assembler.
    """
    env = {}
    for n, raw in enumerate(open(path), 1):
        line = raw.split(";")[0].strip()
        if not line:
            continue
        m = re.match(r"^(\w+)\s+equ\s+(.+)$", line, re.I)
        if not m:
            raise SystemExit(f"{path}:{n}: not an equ: {raw.rstrip()}")
        name, expr = m.group(1).upper(), m.group(2)
        expr = re.sub(r"#([0-9A-Fa-f]+)", r"0x\1", expr).replace("/", "//")
        if not re.fullmatch(r"[\w\s+\-*/()&|]+", expr):
            raise SystemExit(f"{path}:{n}: unsupported expression {expr!r}")
        env[name] = eval(expr, {"__builtins__": {}}, dict(env))
    return env


_VP = load_vpcfg()
VP_BX, VP_BW = _VP["VP_BX"], _VP["VP_BW"]
VP_Y, VP_H = _VP["VP_Y"], _VP["VP_H"]
VP_PW = _VP["VP_PW"]                    # 88 half-byte units (= mode-0 pixels)
CX = float(_VP["CXH"])                  # 44
CY = float(_VP["CYH"])                  # 48
MAXPUSH = _VP["MAXPUSH"]                # 22
FOV_DEG = _VP["FOV_X10"] / 10.0         # 60
FOCAL_V = float(_VP["FOCAL_V"])         # 96
COURSES = _VP["COURSES"]                # 0

# pen 14 is the weapon's slide now, not the mortar -- see pal.py.  The two
# cannot both be had, and this is the assert that says so rather than
# letting a rebuild quietly paint glowing course joints.
assert not (COURSES and pal.MORTAR == pal.GUN_SLIDE), (
    "COURSES needs a mortar pen of its own: pen %d is the weapon's slide"
    % pal.GUN_SLIDE)

# The invariants vpcfg.inc's header promises.  A viewport that broke one of
# these would still assemble, and would render subtly wrong.
assert CX == VP_BW, "CXH must equal VP_BW (= VP_PW/2 half-byte units)"
assert CY * 2 == VP_H, "CYH must be VP_H/2 -- the horizon has no pitch"
assert FOCAL_V == VP_H, "FOCAL_V must be VP_H (1 cell fills the height)"
assert MAXPUSH * 2 == VP_BW, "MAXPUSH must be VP_BW/2 (PUSH DE = 2 bytes)"
assert VP_BX + VP_BW <= 80 and VP_Y + VP_H <= 200, "viewport off screen"
assert _VP["CX_Q4"] == int(CX) * 16 and _VP["CY_Q4"] == int(CY) * 16

FOCAL_H = CX / math.tan(math.radians(FOV_DEG / 2.0))     # 76.21024
KHALF = CX / FOCAL_H                            # tan(FOV/2) = 0.5773502692

N_ANGLES = 72
DEG_STEP = 360.0 / N_ANGLES

VQ_BITS = 10                            # view-space coords: 1024 per cell
VQ_ONE = 1 << VQ_BITS
ZQ_BITS = 8                             # HTAB/PROJ index: 256 per cell
ZQ_ONE = 1 << ZQ_BITS
ZQ_SHIFT = VQ_BITS - ZQ_BITS            # zq = z_q10 >> 2
ZQ_N = 2048                             # table length -> z < 8.0 cells
ZNEAR = 0.125
ZNEAR_Q8 = int(round(ZNEAR * ZQ_ONE))   # 32
ZNEAR_Q10 = int(round(ZNEAR * VQ_ONE))  # 128

R_MAX = 6                               # march radius in cells (L1)

BANK_BASE = 0x4000
BANK_SIZE = 0x4000

# HTAB / PROJ numerators, derived once so the asm doc and the code agree.
HTAB_NUM = 16.0 * (0.5 * FOCAL_V) * ZQ_ONE      # 196608 at FOCAL_V = 96
PROJ_NUM = 16.0 * FOCAL_H * ZQ_ONE              # 312156.6 at FOCAL_H = 76.21


# --------------------------------------------------------------- tables ----

def t_qsq():
    return [t * t // 4 for t in range(512)]


def t_htab():
    out = [0xFFFF]
    for zq in range(1, ZQ_N):
        out.append(min(0xFFFF, int(round(HTAB_NUM / zq))))
    return out


def t_proj():
    out = [0xFFFF]
    for zq in range(1, ZQ_N):
        out.append(min(0xFFFF, int(round(PROJ_NUM / zq))))
    return out


def pxt_entry(p):
    """PROJ value -> (pm, sh), the pre-normalised projection factor.

    Exactly what engine2/src/project.asm used to compute at runtime with
    BITLEN plus a shift loop; doing it here costs 4 KB of table and saves
    ~80 us on every projected endpoint.
    """
    e = p.bit_length() - 8
    if e < 0:
        e = 0
    pm = (p + (1 << e >> 1)) >> e if e else p
    if pm > 255:
        pm = 255
    return pm, 10 - e


def t_pxt():
    proj = t_proj()
    out = []
    for zq in range(ZQ_N):
        pm, sh = pxt_entry(proj[max(zq, ZNEAR_Q8)])
        assert 128 <= pm <= 255 and 4 <= sh <= 10, (zq, pm, sh)
        out.append(pm | (sh << 8))
    return out


PROJN_NUM = 256.0 * FOCAL_H                     # 21283.44
HTN_NUM = 16.0 * (0.5 * FOCAL_V) * VQ_ONE       # 1048576


def t_projn():
    return [int(round(PROJN_NUM / (64 + j))) for j in range(65)]


def t_htn():
    return [int(round(HTN_NUM / (64 + j))) for j in range(65)]


def fast_proj(xv_q10, z_q10, projn, htn):
    """The normalised contract, in Python integers, exactly as the asm does."""
    s = max(0, z_q10.bit_length() - 7)
    zn = ((z_q10 >> (s - 1)) + 1) >> 1 if s else z_q10
    j = zn - 64
    a = abs(xv_q10)
    xn = ((a >> (s - 1)) + 1) >> 1 if s else a
    off = (xn * projn[j]) >> 4
    xs = int(CX) * 16 + (-off if xv_q10 < 0 else off)
    return xs, htn[j] >> s


def basis_vectors(i):
    """(rgtx, rgty, fwdx, fwdy) in Q6.10 for heading index i."""
    r = math.radians(i * DEG_STEP)
    c, s = math.cos(r), math.sin(r)
    k = float(VQ_ONE)
    return (int(round(-k * s)), int(round(k * c)),
            int(round(k * c)), int(round(k * s)))


def t_basis():
    out = []
    for i in range(N_ANGLES):
        out.extend(basis_vectors(i))
    return out


def t_rcp():
    return [0] + [int(round(32768.0 / n)) for n in range(1, 256)]


def t_linetab():
    return [0xC000 + (y & 7) * 0x800 + (y >> 3) * 80 for y in range(200)]


def t_bitlen():
    return [0] + [b.bit_length() for b in range(1, 256)]


def t_pushent():
    return [MAXPUSH - (w >> 1) for w in range(VP_BW + 1)]


def t_m0solid():
    return list(cpc.MODE0_SOLID)


def t_ramptab():
    out = []
    for door in (0, 1):
        for side in (0, 1):
            for depth in range(1, 7):
                out.append(cpc.MODE0_SOLID[pal.wall_pen(depth, side, door)])
    return out


def t_ramp():
    return pal.ramp_table()


def t_wramp():
    """The fill WORD per (kind, k): 16 entries of (E, D), low byte first.
    raster_quad loads DE from this instead of duplicating one solid byte,
    which is what puts the vertical grain on a wall for +3 us a quad --
    see pal.GRAIN."""
    return pal.wramp_table()


def t_palette():
    return pal.palette_ga()


def t_bandpen():
    return [cpc.MODE0_SOLID[p] for p in (pal.CEIL_NEAR, pal.CEIL_FAR,
                                         pal.FLOOR_FAR, pal.FLOOR_NEAR)]


def t_mortar():
    return [pal.mortar_byte()]


def t_div3():
    return [v // 3 for v in range(256)]


# ------------------------------------------------------------- the gun ----
#  gunart.py owns the picture.  Everything here is encoding.

def gun_bands():
    """-> [(rows, x0, n), ...]  consecutive scanlines that share a run.

    engine2/src/gun.asm's inner loop is per ROW but its setup is per BAND,
    so this grouping is what the blit costs turn on.  It is DERIVED, not
    declared: if the art grows a row of a new width the band list simply
    gets one entry longer."""
    gunart.check()
    rows = gunart.rows()
    assert all(r is not None for r in rows), (
        "gun.asm draws every scanline; a blank row would need a skip it "
        "does not have.  Give the row at least one pixel in gunart.py.")
    bands, i = [], 0
    while i < len(rows):
        x0, data = rows[i]
        n = len(data)
        j = i
        while j < len(rows) and rows[j][0] == x0 and len(rows[j][1]) == n:
            j += 1
        assert j - i <= 255, "a band must fit in one djnz"
        bands.append((j - i, x0, n))
        i = j
    return bands


GUN_ROWS = gunart.rows()
GUN_BANDS = gun_bands()
GUN_MAXN = max(len(r[1]) for r in GUN_ROWS)
GUN_BOBV, GUN_BOBH = gunart.bob_check()

# THE BANDS MUST ACCOUNT FOR THE WHOLE SPRITE, and nothing used to say so.
# gun_draw walks the band list and stops on a zero row count; if the bands
# covered fewer rows than the art has, the tail of the sprite -- which is
# the HAND -- would simply not be drawn, and the only thing that would
# notice is a byte-for-byte harness nobody is obliged to run.
assert sum(b[0] for b in GUN_BANDS) == gunart.H, (
    f"the {len(GUN_BANDS)} bands cover {sum(b[0] for b in GUN_BANDS)} rows "
    f"of {gunart.H}")
assert sum(b[0] * b[2] for b in GUN_BANDS) == sum(len(r[1])
                                                  for r in GUN_ROWS), (
    "the bands and GUNPIX disagree about how many bytes the sprite is")
# ...and the blitter's bottom clamp assumes the sprite always REACHES the
# bottom edge (BOB_CUT >= BOB_VA) and always has rows left to draw at the
# bottom of the swing (GUN_ROWS0 > 0).  Both are properties of the ART,
# so they belong here and not in a comment in gun.asm.
assert gunart.BOB_CUT >= gunart.BOB_VA, (
    f"BOB_CUT {gunart.BOB_CUT} < BOB_VA {gunart.BOB_VA}: at the top of the "
    f"swing the sprite would float above the bottom edge")
assert gunart.H - gunart.BOB_CUT - gunart.BOB_VA > 0, (
    f"GUN_ROWS0 = {gunart.H - gunart.BOB_CUT - gunart.BOB_VA}: the sprite "
    f"is shorter than its own anchor and nothing would be drawn")


def art_sig(rows, extra):
    """-> a 16-bit FNV-1a over a sprite's runs and its geometry.

    WHY THIS EXISTS.  The blit is verified against gunart.py by a harness
    that reads the ART out of Python and the PIXELS out of a booted disc,
    and there is nothing in that arrangement that makes the disc's tables
    and the Python art the same generation.  They came apart: the art was
    edited, `make gun` was run -- which boots build/amaze.dsk and does not
    build it -- and the comparison reported 9450 wrong bytes out of 737280
    and a weapon with no hand.  Every one of those diffs was true and none
    of them was a bug in gun.asm: the disc was simply an older drawing.
    Diffing pixels cannot tell "the blitter is broken" from "the disc is
    stale", so the generation is now STAMPED and checked first, and the
    harness says which of the two it is in one line.
    """
    h = 0x811C
    for b in (list(extra)
              + [v for r in rows for v in ((r[0], len(r[1])) + tuple(r[1]))]):
        for byte in (b & 0xFF, (b >> 8) & 0xFF):
            h = ((h ^ byte) * 0x0101) & 0xFFFF
    return h


GUN_SIG = art_sig(GUN_ROWS, (gunart.W, gunart.H, gunart.BOB_VA,
                             gunart.BOB_HA, gunart.BOB_CUT,
                             len(GUN_BOBV), len(GUN_BOBH), GUN_MAXN,
                             len(GUN_BANDS)))


def t_gunpix():
    return [b for r in GUN_ROWS for b in r[1]]


def t_gunband():
    out = []
    for i, (rows, x0, n) in enumerate(GUN_BANDS):
        nxt = GUN_BANDS[i + 1][1] if i + 1 < len(GUN_BANDS) else x0
        adj = nxt - x0
        out += [rows, 2 * (GUN_MAXN - n), (256 - n) & 0xFF,
                adj & 0xFF, (adj >> 8) & 0xFF]
    out.append(0)                       # the row count that ends the walk
    return out


def t_bobv():
    # BIASED by GUN_BOBVA: the vertical bob swings BOTH WAYS about the
    # anchor now, and biasing it lets gun.asm ease towards it with exactly
    # the same three unsigned instructions the horizontal uses.
    return [v + gunart.BOB_VA for v in GUN_BOBV]


def t_bobh():
    # BIASED by GUN_BOBHA, so the Z80 eases towards it with the same
    # unsigned compare the vertical bob uses.
    return [v + gunart.BOB_HA for v in GUN_BOBH]


# name, width (1 = byte, 2 = LE word), alignment, builder
SPEC = [
    ("QSQ",     2, 256, t_qsq),
    ("HTAB",    2, 256, t_htab),
    ("PROJ",    2, 256, t_proj),
    ("PXT",     2, 256, t_pxt),
    ("BITLEN",  1, 256, t_bitlen),
    ("PROJN",   2,   2, t_projn),
    ("HTN",     2,   2, t_htn),
    ("BASIS",   2,   2, t_basis),
    ("RCP",     2,   2, t_rcp),
    ("LINETAB", 2,   2, t_linetab),
    ("PUSHENT", 1,   1, t_pushent),
    ("M0SOLID", 1,   1, t_m0solid),
    ("RAMPTAB", 1,   1, t_ramptab),
    ("RAMP",    1,   1, t_ramp),
    ("WRAMP",   1,   1, t_wramp),
    ("PALETTE", 1,   1, t_palette),
    ("BANDPEN", 1,   1, t_bandpen),
    ("MORTAR",  1,   1, t_mortar),
    # last, and page aligned, so nothing above it moves: every address in
    # tab_equ.inc is unchanged by adding these.
    ("DIV3",    1, 256, t_div3),
    # ...and the gun goes after DIV3 for the same reason.
    ("GUNBAND", 1,   1, t_gunband),
    ("GUNPIX",  1,   1, t_gunpix),
    ("BOBV",    1,   1, t_bobv),
    ("BOBH",    1,   1, t_bobh),
]


def build():
    """-> (blob bytes, layout dict name -> (addr, width, n_entries), values)."""
    blob = bytearray()
    layout, values = {}, {}
    for name, width, align, fn in SPEC:
        pad = (-(BANK_BASE + len(blob))) % align
        blob += b"\x00" * pad
        addr = BANK_BASE + len(blob)
        vals = fn()
        for v in vals:
            if width == 1:
                assert 0 <= v <= 255, f"{name}: {v} out of byte range"
                blob.append(v)
            else:
                blob += struct.pack("<H", v & 0xFFFF)
        layout[name] = (addr, width, len(vals))
        values[name] = vals
    # THE BANK HAS AN END AND NOTHING USED TO SAY SO.  BANK_BASE+len(blob)
    # was only ever PRINTED.  TABLES.BIN is LOADed straight to #4000 by
    # disc3.bas, so one byte over #7FFF is a byte written into #8000 --
    # the back buffer on a real boot, and GAME3.BIN's own load address
    # while the loader is still running.  That is silent: the tables that
    # fit still work, the ones that spill come back as garbage runs.  The
    # gun is the table nearest the end and its size follows the ART, so
    # this is exactly the failure a taller sprite would buy.
    assert len(blob) <= BANK_SIZE, (
        f"bank 4 overflows by {len(blob) - BANK_SIZE} bytes: the tables end "
        f"at #{BANK_BASE + len(blob):04X}, past #{BANK_BASE + BANK_SIZE:04X}. "
        f"TABLES.BIN is loaded flat at #4000, so the spill lands in the "
        f"back buffer.  Take the excess out of the sprite art.")
    return bytes(blob), layout, values


# ------------------------------------------------------------- contracts ---

def self_check(values):
    """Verify every table against its documented contract.  Pure Python;
    the Z80 test then verifies the SAME contracts on the real hardware."""
    bad = list(pal.check(COURSES))

    # THE GUN'S PLACEMENT INVARIANT, and it is now three claims, not one.
    # gun.asm clips on the BOTTOM ONLY, with one comparison per band, so:
    #
    #   1. horizontally the sprite plus the full +-GUN_BOBHA bob must sit
    #      strictly inside the viewport at every phase -- there is no left
    #      or right clip and each row is a plain byte copy;
    #   2. it must never run off the TOP, at any vertical phase, for the
    #      same reason;
    #   3. and at every vertical phase its LAST row must be at or below the
    #      bottom edge, which is the anchor that makes it read as held
    #      rather than as floating.  The rows past the edge are the ones
    #      the bottom clamp drops.
    gxb = VP_BX + (VP_BW - gunart.W // 2) // 2
    for _, x0, n in GUN_BANDS:
        for dx in (-gunart.BOB_HA, gunart.BOB_HA):
            lo, hi = gxb + dx + x0, gxb + dx + x0 + n
            if lo < VP_BX or hi > VP_BX + VP_BW:
                bad.append(f"gun run [{lo},{hi}) leaves the viewport "
                           f"[{VP_BX},{VP_BX + VP_BW}) at dx = {dx}")
    y0 = VP_Y + VP_H - gunart.H + gunart.BOB_CUT + gunart.BOB_VA
    for dy in range(0, 2 * gunart.BOB_VA + 1):          # the BIASED offset
        top = y0 - dy
        if top < VP_Y:
            bad.append(f"gun row {top} is above the viewport top {VP_Y} "
                       f"at dy = {dy - gunart.BOB_VA:+d}")
        if top + gunart.H < VP_Y + VP_H:
            bad.append(f"gun bottom row {top + gunart.H - 1} floats above "
                       f"the viewport bottom {VP_Y + VP_H - 1} at dy = "
                       f"{dy - gunart.BOB_VA:+d}")
        drawn = VP_Y + VP_H - top
        if not 0 < drawn <= gunart.H:
            bad.append(f"gun draws {drawn} of {gunart.H} rows at dy = "
                       f"{dy - gunart.BOB_VA:+d}")


    qsq = values["QSQ"]
    for a in (0, 1, 7, 100, 128, 200, 255):
        for b in (0, 1, 3, 99, 127, 255):
            got = qsq[a + b] - qsq[abs(a - b)]
            if got != a * b:
                bad.append(f"QSQ mul {a}*{b} = {got}")

    htab = values["HTAB"]
    want256 = int(round(16 * 0.5 * FOCAL_V))    # z = 1 cell fills the height
    if htab[256] != want256:
        bad.append(f"HTAB[256] = {htab[256]}, want {want256} "
                   f"(= {FOCAL_V / 2:.0f}.0 scanlines)")
    for zq in (ZNEAR_Q8, 100, 256, 512, 1536, 2047):
        want = 0.5 * FOCAL_V / (zq / ZQ_ONE)
        got = htab[zq] / 16.0
        if abs(got - want) > 0.06:
            bad.append(f"HTAB[{zq}] = {got}, want {want}")

    proj = values["PROJ"]
    for zq in (ZNEAR_Q8, 256, 1536, 2047):
        want = FOCAL_H / (zq / ZQ_ONE)
        got = proj[zq] / 16.0
        if abs(got - want) > 0.06:
            bad.append(f"PROJ[{zq}] = {got}, want {want}")

    # PXT must reproduce PROJ to 8 significant bits, and the mantissa must
    # be normalised at EVERY legal depth (that is what bounds the error).
    pxt = values["PXT"]
    wrel = 0.0
    for zq in range(ZNEAR_Q8, ZQ_N):
        pm, sh = pxt[zq] & 0xFF, pxt[zq] >> 8
        if not (128 <= pm <= 255 and 4 <= sh <= 10):
            bad.append(f"PXT[{zq}] = pm {pm} sh {sh}")
            break
        wrel = max(wrel, abs((pm << (10 - sh)) - proj[zq]) / proj[zq])
    if wrel > 1.0 / 256:
        bad.append(f"PXT mantissa error {wrel*100:.3f}% > 0.39%")
    values["_pxt_rel"] = wrel

    # The full projection contract, against float ground truth, over the
    # whole legal (xv, z) domain of the frustum.  Error is reported in bands
    # of z because the near plane is structurally the worst case.
    bands = [(0.125, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 2.0),
             (2.0, 4.0), (4.0, 8.0)]
    curve = []
    worst = 0.0
    for lo, hi in bands:
        w = 0.0
        for zq10 in range(int(lo * VQ_ONE), int(hi * VQ_ONE), 3):
            z = zq10 / VQ_ONE
            zq = min(ZQ_N - 1, (zq10 + 2) >> ZQ_SHIFT)
            for k in range(-16, 17):
                xv = KHALF * z * k / 16.0
                xq = int(round(xv * VQ_ONE))
                off = ((xq * proj[zq]) >> 10 if xq >= 0
                       else -((-xq * proj[zq]) >> 10))
                got = (CX * 16 + off) / 16.0
                w = max(w, abs(got - (CX + xv * FOCAL_H / z)))
        curve.append((lo, hi, w))
        worst = max(worst, w)

    # Same sweep for the PXT route, which is what the kernel now runs, and
    # for the projected half-height (HTAB, no multiply at all).
    pcurve = []
    for lo, hi in bands:
        w = wh = 0.0
        for zq10 in range(int(lo * VQ_ONE), int(hi * VQ_ONE), 3):
            z = zq10 / VQ_ONE
            zq = min(ZQ_N - 1, (zq10 + 2) >> ZQ_SHIFT)
            pm, sh = pxt[zq] & 0xFF, pxt[zq] >> 8
            wh = max(wh, abs(htab[zq] / 16.0 - 0.5 * FOCAL_V / z))
            for k in range(-16, 17):
                xv = KHALF * z * k / 16.0
                xq = int(round(xv * VQ_ONE))
                off = ((abs(xq) * pm) >> sh) + (((abs(xq) * pm) >> (sh - 1)) & 1)
                got = (CX * 16 + (-off if xq < 0 else off)) / 16.0
                w = max(w, abs(got - (CX + xv * FOCAL_H / z)))
        pcurve.append((lo, hi, w, wh))
    values["_pcurve"] = pcurve

    # Same sweep for the normalised (one-multiply) route.
    projn, htn = values["PROJN"], values["HTN"]
    fcurve = []
    for lo, hi in bands:
        w = 0.0
        for zq10 in range(int(lo * VQ_ONE), int(hi * VQ_ONE), 3):
            z = zq10 / VQ_ONE
            for k in range(-16, 17):
                xv = KHALF * z * k / 16.0
                xq = int(round(xv * VQ_ONE))
                xs, _ = fast_proj(xq, zq10, projn, htn)
                w = max(w, abs(xs / 16.0 - (CX + xv * FOCAL_H / z)))
        fcurve.append((lo, hi, w))
    if max(w for lo, _, w in fcurve if lo >= 0.5) > 1.0:
        bad.append("PROJN far-field error above 1.0 half-byte units")
    for zq10 in range(ZNEAR_Q10, ZQ_N << ZQ_SHIFT, 37):
        _, hs = fast_proj(0, zq10, projn, htn)
        want = 0.5 * FOCAL_V / (zq10 / VQ_ONE)
        if abs(hs / 16.0 - want) > max(0.6, 0.01 * want):
            bad.append(f"HTN[{zq10}] = {hs / 16.0}, want {want}")
            break
    values["_fcurve"] = fcurve
    if curve[0][2] > 1.2:
        bad.append(f"PROJ near-plane error {curve[0][2]:.3f} half-byte units")
    if max(w for lo, _, w in curve if lo >= 0.5) > 0.30:
        bad.append("PROJ far-field error above 0.25 half-byte units")
    values["_curve"] = curve

    bas = values["BASIS"]
    for i in (0, 1, 18, 36, 54, 71):
        want = basis_vectors(i)
        got = tuple(bas[i * 4 + k] for k in range(4))
        if got != want:
            bad.append(f"BASIS[{i}] = {got}, want {want}")

    rcp = values["RCP"]
    for n in (1, 2, 3, 5, 16, 96, 255):
        for v in (1000, 12345, 32000):
            got = (v * rcp[n]) >> 15
            if abs(got - v // n) > 1:
                bad.append(f"RCP {v}/{n} = {got}, want {v // n}")

    lt = values["LINETAB"]
    for y in (0, 1, 7, 8, 63, 127, 199):
        want = 0xC000 + (y & 7) * 0x800 + (y >> 3) * 80
        if lt[y] != want:
            bad.append(f"LINETAB[{y}] = {lt[y]:04X}, want {want:04X}")

    bl = values["BITLEN"]
    for b in (0, 1, 2, 3, 127, 128, 255):
        if bl[b] != b.bit_length():
            bad.append(f"BITLEN[{b}] = {bl[b]}")

    pe = values["PUSHENT"]
    for w in range(0, VP_BW + 1):
        if pe[w] != MAXPUSH - (w >> 1):
            bad.append(f"PUSHENT[{w}] = {pe[w]}")

    return worst, bad


# ---------------------------------------------------------------- output ---

def write_inc(path, blob, layout):
    end = BANK_BASE + len(blob)
    with open(path, "w") as fh:
        fh.write("; Generated by engine2/tools/gentab.py -- do not edit.\n")
        fh.write("; See that file for the fixed-point conventions and the\n")
        fh.write("; contract of every table.\n\n")
        fh.write("; The viewport lives in ONE place and this is not it:\n")
        fh.write('    include "vpcfg.inc"\n')
        fh.write("\n; ---- projection, DERIVED from vpcfg.inc ----\n")
        fh.write(f"; viewport {VP_BW}x{VP_H} bytes at ({VP_BX},{VP_Y}),"
                 f" FOV {FOV_DEG:g} deg,"
                 f" FOCAL_H {FOCAL_H:.3f} FOCAL_V {FOCAL_V:.0f}\n")
        for name, val in (
            ("N_ANGLES", N_ANGLES),
            ("R_MAX", R_MAX),
            ("VQ_ONE", VQ_ONE), ("ZQ_ONE", ZQ_ONE),
            ("ZQ_SHIFT", ZQ_SHIFT), ("ZQ_N", ZQ_N),
            ("ZNEAR_Q10", ZNEAR_Q10), ("ZFAR_Q10", (ZQ_N << ZQ_SHIFT) - 1),
            ("ZNEAR_Q8", ZNEAR_Q8), ("ZFAR_Q8", ZQ_N - 1),
            # FOCAL_V is an equ in vpcfg.inc; FOCAL_H is a float, so only
            # its Q8 form can be handed to the assembler.
            ("FOCAL_H_Q8", int(round(FOCAL_H * 256))),   # 19510, fits 16 bits
            ("KHALF_Q10", int(round(KHALF * VQ_ONE))),
            ("KHALF_Q14", int(round(KHALF * 16384))),
        ):
            fh.write(f"{name:12s} equ {val}\n")

        fh.write("\n; ---- the weapon, DERIVED from engine2/tools/gunart.py"
                 " ----\n")
        fh.write(f"; sprite {gunart.W}x{gunart.H} px,"
                 f" {len(GUN_BANDS)} bands, {sum(len(r[1]) for r in GUN_ROWS)}"
                 f" bytes of run data\n")
        for name, val in (
            ("GUN_H", gunart.H),                    # scanlines
            ("GUN_WB", gunart.W // 2),              # sprite width, BYTES
            ("GUN_X0F", GUN_ROWS[0][0]),            # x0 of the FIRST row
            ("GUN_MAXN", GUN_MAXN),                 # longest run, bytes
            ("GUN_BOBVN", len(GUN_BOBV)),
            ("GUN_BOBHN", len(GUN_BOBH)),
            ("GUN_BOBVA", gunart.BOB_VA),           # scanlines EITHER SIDE
            ("GUN_BOBHA", gunart.BOB_HA),
            # ...and the anchor: GUN_CUT scanlines hang below the viewport
            # at the centre of the travel, and GUN_ROWS0 is how many rows
            # the blitter draws there.  Rows drawn = GUN_ROWS0 + (gun_dy),
            # the biased offset, so it runs GUN_ROWS0 .. GUN_ROWS0+2*BOBVA.
            # ...and the SHAPE of the encoded tables, so gun.asm can assert
            # that the code it was assembled against and the data it was
            # assembled with are the same sprite.  GUN_NBAND is what the
            # band walk expects to find before the terminator and
            # GUN_PIXN is how many bytes those bands consume; if either
            # drifts the assembler stops rather than the disc drawing a
            # sprite with its hand missing.
            ("GUN_NBAND", len(GUN_BANDS)),
            ("GUN_PIXN", sum(len(r[1]) for r in GUN_ROWS)),
            ("GUN_CUT", gunart.BOB_CUT),
            ("GUN_ROWS0", gunart.H - gunart.BOB_CUT - gunart.BOB_VA),
        ):
            fh.write(f"{name:12s} equ {val}\n")
        # The generation stamp.  gun.asm plants it in GAME3.BIN as
        # `gun_sig`, and emu_gun.py refuses to compare a single pixel
        # until the running machine's copy matches the one it computes
        # from gunart.py here.  See art_sig().
        fh.write(f"{'GUN_SIG':12s} equ #{GUN_SIG:04X}\n")

        fh.write("\n; ---- bank 4 table addresses ----\n")
        for name, width, align, _ in SPEC:
            addr, w, n = layout[name]
            fh.write(f"{name:12s} equ #{addr:04X}"
                     f"   ; {n} x {'word' if w == 2 else 'byte'}"
                     f"  ({n * w} bytes)\n")
        fh.write(f"\n{'TAB_BASE':12s} equ #{BANK_BASE:04X}\n")
        fh.write(f"{'TAB_END':12s} equ #{end:04X}\n")
        fh.write(f"{'TAB_SIZE':12s} equ {len(blob)}\n")
        fh.write(f"{'TAB_FREE':12s} equ {BANK_SIZE - len(blob)}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_ROOT, "engine2"))
    ap.add_argument("--check", action="store_true",
                    help="run the contract self-check and exit")
    args = ap.parse_args()

    blob, layout, values = build()
    worst, bad = self_check(values)
    for b in bad:
        print("FAIL:", b, file=sys.stderr)

    print(f"engine2 tables: viewport {VP_BW}x{VP_H} bytes "
          f"({VP_PW}x{VP_H} px) at ({VP_BX},{VP_Y}), "
          f"FOCAL_H={FOCAL_H:.3f} FOCAL_V={FOCAL_V:.0f}")
    for name, width, align, _ in SPEC:
        addr, w, n = layout[name]
        print(f"  {name:8s} #{addr:04X}  {n:5d} x {w}  = {n * w:5d} bytes")
    print(f"  {'TOTAL':8s}        {len(blob):5d} bytes of {BANK_SIZE}"
          f"  ({100.0 * len(blob) / BANK_SIZE:.1f}%),"
          f" {BANK_SIZE - len(blob)} free")
    print("  projection error vs float ground truth")
    print(f"  PXT mantissa relative error: {values['_pxt_rel']*100:.3f}% "
          f"(<= 2^-9 by construction)")
    print("    z band          xs err, half-byte units          hh err, lines")
    print("               PROJ 16x16   PXT 16x8   PROJN 8x8       HTAB")
    for (lo, hi, w), (_, _, pw, hw), (_, _, fw) in zip(
            values["_curve"], values["_pcurve"], values["_fcurve"]):
        print(f"    [{lo:5.3f}, {hi:5.3f})  {w:8.3f}   {pw:8.3f}   {fw:8.3f}"
              f"   {hw:10.3f}")

    if args.check:
        return 1 if bad else 0
    if bad:
        return 1

    os.makedirs(os.path.join(args.out, "build"), exist_ok=True)
    os.makedirs(os.path.join(args.out, "src"), exist_ok=True)
    with open(os.path.join(args.out, "build", "TABLES.BIN"), "wb") as fh:
        fh.write(blob)
    write_inc(os.path.join(args.out, "src", "tab_equ.inc"), blob, layout)
    with open(os.path.join(args.out, "build", "tables.json"), "w") as fh:
        json.dump({"base": BANK_BASE, "size": len(blob),
                   "free": BANK_SIZE - len(blob),
                   "layout": {k: list(v) for k, v in layout.items()}}, fh,
                  indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
