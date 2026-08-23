"""Verify and MEASURE engine2/src/raster.asm on a cycle-accurate CPC 6128.

    python3 engine2/tools/emu_rast.py verify     bit-exact vs rastermodel.py
    python3 engine2/tools/emu_rast.py time       us per quad, split by path
    python3 engine2/tools/emu_rast.py frames     whole frames vs the 80 ms budget

VERIFICATION IS DONE ON THE SCREEN, NOT ON A RUN LIST.  The driver clears all
16K of the &C000 buffer, pokes ONE quad record into QUADS, runs raster_quad,
and compares the whole 16K against what rastermodel.py says should be there.
So it checks the run geometry, the screen addressing, the colour and the
absence of stray writes outside the viewport, all at once.

TIMING PROTOCOL.  A 16-bit counter is bumped once per iteration of a tight
loop with interrupts off; cpc.run_us(N) returns Z80 ticks at 4 MHz and the
gate array stretches every instruction to a whole microsecond, so ticks/4 is
exactly the CPC microsecond count.  An identical loop with the call removed
gives the loop overhead, which is subtracted.  The method is calibrated
against a loop with 100 NOPs in it, which must come out at 100.0 us.
"""

import os
import random
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import addrs                                              # noqa: E402
import gentab                                               # noqa: E402
import pal                                                  # noqa: E402
import projmodel as pm                                      # noqa: E402
import rastermodel as rm                                    # noqa: E402
from cpc import CPC                                         # noqa: E402

BUILD = os.path.join(_E2, "build")

E_ONCE, E_BENCH, E_EMPTY, E_MANY, E_FBENCH = (
    0x8000, 0x8004, 0x8008, 0x800C, 0x8010)

QUADS = addrs.QUADS
QRECSZ = 8
FRONT = 0xC000
SCRSZ = 0x4000


# ------------------------------------------------------------------ build --
def build(paced=False):
    """Assemble tst_rast.asm.  `paced` compiles raster.asm's mid-quad yield
    (rq_bchunk / rq_wchunk) against the stub accumulator at the foot of the
    harness -- the same code main3.asm gets, and the reason this is built
    twice: the hooks must not change a pixel."""
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "tab_test.bin"), "wb").write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    out = "tst_rastp" if paced else "tst_rast"
    r = subprocess.run(
        ["rasm", "tst_rast.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/" + out, "-s", "-os", "../build/" + out]
        + (["-DPACED=1", "-DRQ_SPLIT=1"] if paced else []),
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, out + ".bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, out)):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return blob, code, sym


class Rig:
    def __init__(self, paced=False):
        self.tables, self.code, self.sym = build(paced)
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(gentab.BANK_BASE, self.tables)
        self.c.write_ram(0x8000, self.code)
        self.cfg = rm.cfg()
        self.ramp = pal.ramp_table()
        self.blank = bytes(SCRSZ)

    def s(self, n):
        return self.sym[n.upper()]

    def poke_quads(self, quads):
        # (blo, bhi, hlo, hhi, kind, k) -- kernel.asm owns the layout
        raw = b"".join(struct.pack("<BBHHBB", *q) for q in quads)
        self.c.write_ram(QUADS, raw)
        self.c.poke(self.s("FG_NQUAD"), len(quads))

    def run_once(self, quads, entry=None):
        """-> the whole 16K front buffer after painting `quads`."""
        self.c.write_ram(FRONT, self.blank)
        self.poke_quads(quads)
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(entry or (E_ONCE if len(quads) == 1 else E_MANY))
        for _ in range(400):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                break
        else:
            raise RuntimeError("raster never finished")
        return self.c.read_ram(FRONT, SCRSZ)

    def bench(self, entry, quads, us=800000):
        """-> CPC microseconds per iteration (loop overhead NOT removed)."""
        self.poke_quads(quads)
        self.c.set_pc(entry)
        self.c.run_us(60000)
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        if not 0 < n < 60000:
            raise RuntimeError(f"counter unusable: {n}")
        return (ticks / 4.0) / n


# ------------------------------------------------------------ the model ----
def expect_screen(quads, c, ramp, joints=None):
    """The 16K buffer rastermodel.py says the Z80 must produce.

    A face is its quad and THEN, on top of it, its two course joints --
    the order raster_frame draws them in.  Whether the joints are there
    at all depends on TWO things and both matter: vpcfg.inc's COURSES,
    and WHICH ENTRY POINT the harness used.  #8000 calls raster_quad and
    draws a bare face; #800C calls raster_frame, which is the one that
    calls raster_joint.  run_once picks between them on the quad count,
    so the default here has to pick the same way -- modelling joints on
    the single-quad screens reported 180 bad screens and no defect.
    """
    if joints is None:
        joints = c.COURSES and len(quads) > 1
    scr = bytearray(SCRSZ)
    mortar = rm.joint_colour()
    for q in quads:
        # A FACE IS FILLED WITH A WORD, NOT A BYTE.  PUSH DE writes E at the
        # lower address, so the left byte of every pair carries pal.GRAIN --
        # see rastermodel.fill_word.  The joints stay solid: raster_joint
        # still copies one mortar byte into both halves of DE.
        we, wd = rm.fill_word(q)
        work = [(rm.raster_quad(q, c), (we, wd))]
        if joints:
            work.append((rm.joint_runs(q, c), (mortar, mortar)))
        for runs, (ce, cd) in work:
            for (r, e, n) in runs:
                y = c.VP_Y + r
                base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
                start = e - 2 * n
                for x in range(start, e):
                    scr[base + x] = ce if (x - start) % 2 == 0 else cd
    return bytes(scr)


def diff_report(got, want, c):
    """-> a short human description of the first few differing bytes."""
    out = []
    for i in range(SCRSZ):
        if got[i] != want[i]:
            # decode the address back to (y, byte column)
            row = (i // 0x800) & 7
            rest = i & 0x7FF
            y = row + (rest // 80) * 8
            x = rest % 80
            out.append(f"    &{0xC000 + i:04X}  y={y:3d} byte={x:2d} "
                       f"(vp x={x - c.VP_BX:3d})  z80={got[i]:02X} "
                       f"model={want[i]:02X}")
            if len(out) >= 6:
                break
    return out


# ------------------------------------------------------------- test quads --
def q(xa_q4, ha, xb_q4, hb, kind=0, k=1, c=None):
    """Build a quad RECORD from (x, half-height) pairs -- exactly the pack
    project.asm:pf_emit does, so a probe written in screen space still says
    what it used to say."""
    return pm.pack_quad((xa_q4, ha, xb_q4, hb)) + (kind, k)


def synthetic(c):
    """Hand-built cases: degenerate, clipped, and the awkward boundaries."""
    X = c.XMAX_Q4
    CY = c.CY_Q4
    out = [
        # -- pure body (front-facing wall: both endpoints the same depth) --
        ("front wall, 1 cell (fills the viewport)", q(0, CY, X, CY, 0, 1, c)),
        ("front wall, half height", q(200, CY // 2, 1000, CY // 2, 0, 3, c)),
        ("front wall, 2 rows tall", q(300, 16, 900, 16, 0, 6, c)),
        ("front wall, ZERO height (one row)", q(300, 0, 900, 0, 0, 7, c)),
        ("front wall, door ramp", q(64, 300, 1200, 300, 1, 2, c)),
        # -- degenerate widths --
        ("degenerate xa == xb", q(700, 400, 700, 400, 0, 1, c)),
        ("one half-byte wide", q(700, 400, 701, 400, 0, 1, c)),
        ("exactly one byte wide", q(704, 400, 736, 400, 0, 1, c)),
        ("exactly two bytes wide", q(704, 400, 768, 400, 0, 1, c)),
        ("three bytes wide (odd: loses the left byte)",
         q(704, 400, 800, 400, 0, 1, c)),
        # -- wedges --
        ("shallow wedge, right taller", q(0, 100, X, 300, 0, 2, c)),
        ("shallow wedge, left taller", q(0, 300, X, 100, 0, 2, c)),
        ("steep wedge, right taller", q(0, 16, X, CY, 0, 1, c)),
        ("steep wedge, left taller", q(0, CY, X, 16, 0, 1, c)),
        # (X, not a literal 1300: this probe was written at 44 bytes wide,
        #  where XMAX_Q4 was 1408, and at 40 it asks the packer for column
        #  41 of a 40-byte viewport)
        ("wedge with zero at one end", q(100, 0, X, CY, 0, 4, c)),
        # -- SHORT wedges, where interpolating in whole rows used to lose
        #    the span entirely: jlo and jhiu are truncations, so a one-row
        #    wedge stepped the edge all the way onto the pinned column.
        #    The first of these IS the quad from the junction state
        #    (0780,0380, heading 2), rows 35 and 61 -- see raster.asm.
        ("one-row wedge, left taller (was a sliver)", q(660, 217, 980, 207,
                                                        0, 4, c)),
        ("one-row wedge, right taller", q(300, 207, 1000, 217, 0, 4, c)),
        ("one-row wedge, pinned at column 0 (words)", q(0, 310, 300, 290,
                                                        0, 4, c)),
        ("wedge over the WHOLE height range", q(0, 0, X, 6144, 0, 1, c)),
        # -- vertically clipped: a wall closer than one cell --
        ("near wall, 4x overheight, flat", q(0, 4 * CY, X, 4 * CY, 0, 1, c)),
        ("near wall, one end 8x over", q(0, 8 * CY, X, CY // 2, 0, 1, c)),
        ("near wall, other end 8x over", q(0, CY // 2, X, 8 * CY, 0, 1, c)),
        ("both ends over, different", q(0, 6 * CY, X, 2 * CY, 0, 1, c)),
        ("extreme: h at the near-plane limit",
         q(0, 6144, X, 6144, 0, 1, c)),
        # -- side clipped: hard against the viewport edges --
        ("hard against the left edge", q(0, 500, 200, 900, 0, 2, c)),
        ("hard against the right edge", q(X - 200, 900, X, 500, 0, 2, c)),
        ("spans the full width, both clipped", q(0, 700, X, 200, 0, 1, c)),
        # -- k / kind sweep, so every ramp entry gets pushed once --
    ]
    for kk in range(1, 8):
        out.append((f"wall ramp k={kk}", q(300, 200 + 40 * kk, 900,
                                           120 + 40 * kk, 0, kk, c)))
        out.append((f"door ramp k={kk}", q(300, 200 + 40 * kk, 900,
                                           120 + 40 * kk, 1, kk, c)))
    return out


def from_kernel(nstates=24, seed=90210):
    """Real quads: march + project over random player states on the maze."""
    sys.path.insert(0, _HERE)
    import marchmodel as mm
    import projmodel as pmod
    import world
    grid, _, _ = world.load_maze()
    solid = mm.solid_from_grid(grid)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    rnd = random.Random(seed)
    out = []
    for _ in range(nstates):
        x, y = rnd.choice(floors)
        px, py = (x << 8) | rnd.randrange(256), (y << 8) | rnd.randrange(256)
        a = rnd.randrange(72)
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pmod.face_endpoints(wx, wy, fd)
            qq = pmod.project_face(v[0], v[1], v[2], v[3],
                                   ax - ipx, ay - ipy, fd)
            if qq is not None:
                out.append(qq + (1 if door else 0, k))
    return out


# ---------------------------------------------------------------- verify ---
def verify(paced=False):
    rig = Rig(paced)
    c = rig.cfg
    cases = synthetic(c)
    real = from_kernel()
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes at ({c.VP_BX},{c.VP_Y}), "
          f"horizon row {c.CYH}, MAXPUSH {c.MAXPUSH}")
    print("PACED -- the mid-quad yield is compiled IN and fires on every"
          " hook" if paced else "UNPACED -- raster.asm on its own")
    print(f"{len(cases)} hand-built quads + {len(real)} quads from real "
          f"march/project frames")

    bad = 0
    tested = 0
    for label, qq in cases:
        got = rig.run_once([qq])
        want = expect_screen([qq], c, rig.ramp)
        tested += 1
        if got != want:
            bad += 1
            print(f"MISMATCH  {label}\n    quad {qq}")
            for line in diff_report(got, want, c):
                print(line)
        else:
            bl, bb, wl, wb = rm.counts(qq, c)
            print(f"  ok  {label:46s} body {bl:3d} lines/{bb:4d} B   "
                  f"wedge {wl:3d} lines/{wb:4d} B")

    # real quads, in batches -- one at a time first, then a whole frame's
    # worth at once so the painter overdraw path is exercised too
    for i, qq in enumerate(real):
        got = rig.run_once([qq])
        want = expect_screen([qq], c, rig.ramp)
        tested += 1
        if got != want:
            bad += 1
            if bad < 8:
                print(f"MISMATCH  real quad #{i}: {qq}")
                for line in diff_report(got, want, c):
                    print(line)
    print(f"  {len(real)} real quads, one at a time: "
          f"{len(real) - bad} exact")

    rnd = random.Random(4242)
    nb = 0
    for t in range(12):
        batch = [real[rnd.randrange(len(real))]
                 for _ in range(rnd.randrange(2, 9))]
        got = rig.run_once(batch)
        want = expect_screen(batch, c, rig.ramp)
        tested += 1
        if got != want:
            bad += 1
            nb += 1
            if nb < 3:
                print(f"MISMATCH  batch of {len(batch)}")
                for line in diff_report(got, want, c):
                    print(line)
    print(f"  12 painter batches of 2..8 quads: {12 - nb} exact")

    print(f"\nVERIFY: {tested} screens compared byte for byte over all "
          f"{SCRSZ} bytes of the buffer, {tested - bad} exact, {bad} bad")
    return bad


# ------------------------------------------------------------ calibration --
def calibrate(rig):
    src = os.path.join(BUILD, "cal.asm")
    open(src, "w").write(
        "    org #9000\n    jp cal_e\n    jp cal_n\n"
        "cal_e\n    di\n    ld sp,#7FF0\n    ld hl,0\n    ld (cnt),hl\n"
        "ce\n    ld hl,(cnt)\n    inc hl\n    ld (cnt),hl\n    jr ce\n"
        "cal_n\n    di\n    ld sp,#7FF0\n    ld hl,0\n    ld (cnt),hl\n"
        "cn\n    ld hl,(cnt)\n    inc hl\n    ld (cnt),hl\n"
        + "    nop\n" * 100 + "    jr cn\ncnt dw 0\n")
    subprocess.run(["rasm", "cal.asm", "-o", "cal", "-s", "-os", "cal"],
                   cwd=BUILD, capture_output=True, text=True, check=True)
    blob = open(os.path.join(BUILD, "cal.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "cal")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    rig.c.write_ram(0x9000, blob)

    def one(pc, us=400000):
        rig.c.set_pc(pc)
        rig.c.run_us(2000)
        rig.c.write_ram(sym["CNT"], b"\x00\x00")
        t = rig.c.run_us(us)
        n = struct.unpack("<H", rig.c.read_ram(sym["CNT"], 2))[0]
        return (t / 4.0) / n
    e, f = one(0x9000), one(0x9003)
    print("=== timing method calibration ===")
    print(f"  empty counter loop            : {e:8.2f} us")
    print(f"  same loop + 100 NOPs          : {f:8.2f} us")
    print(f"  difference (should be 100.00) : {f - e:8.2f} us")
    rig.c.write_ram(0x8000, rig.code)
    return f - e


# ------------------------------------------------------------------ time ---
def lstsq(X, y):
    n, m = len(X), len(X[0])
    A = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(m)]
         for i in range(m)]
    b = [sum(X[k][i] * y[k] for k in range(n)) for i in range(m)]
    for i in range(m):
        p = max(range(i, m), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        b[i], b[p] = b[p], b[i]
        for r in range(i + 1, m):
            f = A[r][i] / A[i][i]
            for cc in range(i, m):
                A[r][cc] -= f * A[i][cc]
            b[r] -= f * b[i]
    co = [0.0] * m
    for i in range(m - 1, -1, -1):
        co[i] = (b[i] - sum(A[i][j] * co[j] for j in range(i + 1, m))) / A[i][i]
    res = [y[k] - sum(X[k][i] * co[i] for i in range(m)) for k in range(n)]
    ybar = sum(y) / n
    ss = sum((v - ybar) ** 2 for v in y)
    r2 = 1 - sum(r * r for r in res) / ss if ss else 1.0
    rms = (sum(r * r for r in res) / n) ** 0.5
    return co, rms, r2, max(abs(r) for r in res)


def time_it():
    rig = Rig()
    c = rig.cfg
    calibrate(rig)
    ovh = rig.bench(E_EMPTY, [q(0, 0, 16, 0, 0, 1, c)])
    print(f"\nloop overhead per iteration: {ovh:.2f} us  (subtracted below)")

    # ---- a designed sweep, so the four costs are separable.  Body lines
    #      and body bytes are varied independently; so are wedge lines
    #      (set by the height difference) and wedge bytes (set by the
    #      width) -- otherwise the two are perfectly collinear and the fit
    #      hands back a per-byte cost below the 2 us PUSH DE floor.
    X = c.XMAX_Q4
    CY = c.CY_Q4
    probes = [("nothing drawn at all (pure setup)", q(700, 400, 700, 400,
                                                      0, 1, c))]
    for hh in (0, 16, 64, 128, 256, 384, 512, 640, 768, 4 * CY):
        probes.append(("body, full width", q(0, hh, X, hh, 0, 1, c)))
    for w in (2, 6, 12, 22, 32, 44):
        for hh in (32, 256, 768):
            probes.append((f"body {w:2d} B wide",
                           q(0, hh, w * 32, hh, 0, 1, c)))
    for hh in (32, 96, 192, 384, 576, 768):
        for w in (6, 22, 44):
            probes.append((f"wedge to h={hh:4d}, {w:2d} B wide",
                           q(0, 0, w * 32, hh, 0, 1, c)))
            probes.append((f"wedge from h={hh:4d}, {w:2d} B wide",
                           q(0, hh, w * 32, 0, 0, 1, c)))
    for m in (2, 4, 8):
        probes.append((f"wedge {m}x overheight", q(0, CY // 4, X, m * CY,
                                                   0, 1, c)))

    rows = []
    print("\n=== designed sweep ===")
    print("%-34s %6s %6s %6s %6s %10s" %
          ("probe", "bodyL", "bodyB", "wedgL", "wedgB", "us/quad"))
    for label, qq in probes:
        bl, bb, wl, wb = rm.counts(qq, c)
        us = rig.bench(E_BENCH, [qq]) - ovh
        rows.append((bl, bb, wl, wb, us))
        print("%-34s %6d %6d %6d %6d %10.1f" % (label, bl, bb, wl, wb, us))

    co, rms, r2, worst = lstsq(
        [[1.0, float(r[0]), float(r[1]), float(r[2]), float(r[3])]
         for r in rows], [r[4] for r in rows])
    print("\n=== least squares over the sweep ===")
    print("  us = %.1f  +  %.2f*body_lines  +  %.3f*body_bytes"
          "  +  %.2f*wedge_lines  +  %.3f*wedge_bytes" % tuple(co))
    print(f"  R^2 {r2:.5f}, RMS residual {rms:.1f} us, worst {worst:.1f} us")
    print("  -> per BODY  scanline: %.1f us fixed + %.3f us/byte"
          % (co[1], co[2]))
    print("     per WEDGE scanline: %.1f us fixed + %.3f us/byte"
          % (co[3], co[4]))
    print("     PUSH DE floor is 2.000 us/byte; per-quad setup %.0f us"
          % co[0])

    # ---- real quads ---------------------------------------------------
    real = from_kernel(16)
    rrows = []
    for qq in real:
        bl, bb, wl, wb = rm.counts(qq, c)
        rrows.append((bl, bb, wl, wb, rig.bench(E_BENCH, [qq]) - ovh))
    tot = sum(r[4] for r in rrows)
    pred = [co[0] + co[1] * r[0] + co[2] * r[1] + co[3] * r[2] + co[4] * r[3]
            for r in rrows]
    err = max(abs(p - r[4]) for p, r in zip(pred, rrows))
    rrows.sort(key=lambda r: r[4])
    print(f"\n=== {len(rrows)} REAL quads from march/project frames ===")
    print("  mean %.0f us, median %.0f us, worst %.0f us"
          % (tot / len(rrows), rrows[len(rrows) // 2][4], rrows[-1][4]))
    print("  the fit above predicts every one of them to within %.0f us" % err)
    print("  bytes pushed: mean %.0f, worst %d"
          % (sum(r[1] + r[3] for r in rrows) / len(rrows),
             max(r[1] + r[3] for r in rrows)))
    return co


# ----------------------------------------------------------- whole frames --
# The geometry kernel's own MEASURED fit (engine2/src/kernel.asm header,
# emu_kernel.py time, 127 sampled states).  It does not depend on the
# viewport: at a fixed FOV and march radius the frustum is the same shape
# whatever the window is, so the marched-cell and candidate-face counts are
# unchanged and only the FILL scales.
KERNEL_US = (3281.0, 544.7, 506.3)      # const, per ref cell, per cand face
BG_US = 9036.0                          # engine2/src/bg.asm, 44x96, 4 bands
BUDGET_US = 80000.0                     # 4 vsync frames = 12.5 fps


# The rasteriser's own MEASURED fit (this file, `time`, R^2 0.9968).  The
# wedge's line and byte costs are collinear over any one quad, so the split
# between them moves when the runs get wider; the SUM is what predicts.
RAST_US = (622.4, 16.01, 1.989, 56.07, 2.136)


def rast_predict(quads, c):
    us = 0.0
    for qq in quads:
        bl, bb, wl, wb = rm.counts(qq, c)
        us += (RAST_US[0] + RAST_US[1] * bl + RAST_US[2] * bb
               + RAST_US[3] * wl + RAST_US[4] * wb)
    return us


def frames(nstates=60, seed=1337):
    """MEASURE the rasteriser on whole frames' worth of quads, then add the
    already-measured geometry and background costs and see what is left."""
    import marchmodel as mm
    import projmodel as pmod
    import world
    rig = Rig()
    c = rig.cfg
    calibrate(rig)
    ovh = rig.bench(E_EMPTY, [q(0, 0, 16, 0, 0, 1, c)])

    grid, _, _ = world.load_maze()
    solid = mm.solid_from_grid(grid)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    rnd = random.Random(seed)

    # Random sampling never finds the worst frame, so survey a large pool
    # with the MODEL, rank it by (measured geometry fit + measured raster
    # fit), and then MEASURE the worst of the pool as well as a random
    # spread of it.
    pool = []
    for _ in range(nstates * 12):
        x, y = rnd.choice(floors)
        pool.append(((x << 8) | rnd.randrange(256),
                     (y << 8) | rnd.randrange(256), rnd.randrange(72)))
    scored = []
    for px, py, a in pool:
        r = mm.march(solid, px, py, a)
        ref = mm.march(solid, px, py, a, push_opaque=True)["visited"]
        ipx, ipy = px >> 8, py >> 8
        qs = []
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pmod.face_endpoints(wx, wy, fd)
            qq = pmod.project_face(v[0], v[1], v[2], v[3],
                                   ax - ipx, ay - ipy, fd)
            if qq is not None:
                qs.append(qq + (1 if door else 0, k))
        if not qs:
            continue
        geom = KERNEL_US[0] + KERNEL_US[1] * ref + KERNEL_US[2] * len(r["faces"])
        scored.append((geom + rast_predict(qs, c) + BG_US, px, py, a, ref,
                       len(r["faces"]), qs))
    scored.sort(key=lambda t: t[0])
    print(f"  surveyed {len(scored)} states with the model; measuring the "
          f"{nstates//3} worst and {nstates - nstates//3} sampled")
    picks = scored[-(nstates // 3):]
    picks += [scored[i] for i in
              range(0, len(scored), max(1, len(scored) // (nstates - nstates // 3)))]

    rows = []
    for _pred, px, py, a, ref, cand, quads in picks:
        r = dict(faces=[])
        # SIZE THE WINDOW to the frame, as emu_frame.py does.  The counter
        # counts iterations STARTED, so a fixed 1.2 s window is only ~34
        # iterations on a 35 ms frame and quantises it to ~3% -- a whole
        # millisecond, which is the size of the effects being measured.
        p = rig.bench(E_FBENCH, quads, us=600000)
        rast = rig.bench(E_FBENCH, quads,
                         us=min(20000000, max(600000, int(p * 200)))) - ovh
        geom = KERNEL_US[0] + KERNEL_US[1] * ref + KERNEL_US[2] * cand
        px_ = sum(sum(2 * n for (_r, _e, n) in rm.raster_quad(qq, c))
                  for qq in quads)
        rows.append(dict(nq=len(quads), ref=ref, cand=cand,
                         bytes=px_, rast=rast, geom=geom,
                         total=rast + geom + BG_US))

    rows.sort(key=lambda r: r["total"])
    print(f"\n=== {len(rows)} whole frames, rasteriser MEASURED, geometry "
          f"and background from their own measured fits ===")
    print("%-8s %5s %6s %8s %9s %9s %9s %9s" %
          ("pctile", "quads", "bytes", "overdraw", "geom ms", "bg ms",
           "rast ms", "TOTAL ms"))
    vp = c.VP_BW * c.VP_H
    for p, lbl in ((0.0, "min"), (0.5, "median"), (0.9, "p90"),
                   (0.99, "p99"), (1.0, "max")):
        r = rows[min(len(rows) - 1, int(p * len(rows)))]
        print("%-8s %5d %6d %8.2fx %9.2f %9.2f %9.2f %9.2f" %
              (lbl, r["nq"], r["bytes"], r["bytes"] / vp, r["geom"] / 1000,
               BG_US / 1000, r["rast"] / 1000, r["total"] / 1000))
    over = [r for r in rows if r["total"] > BUDGET_US]
    print(f"\n  budget {BUDGET_US/1000:.0f} ms (4 vsync frames, 12.5 fps): "
          f"{len(rows)-len(over)}/{len(rows)} frames fit, {len(over)} over")
    print("  rasteriser share of the total: %.0f%% median"
          % (100.0 * rows[len(rows) // 2]["rast"] / rows[len(rows) // 2]["total"]))
    tot = sum(r["rast"] for r in rows)
    nq = sum(r["nq"] for r in rows)
    print("  %.0f us per quad on average over %d quads in %d frames"
          % (tot / nq, nq, len(rows)))
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        # BOTH BUILDS.  The disc runs the PACED one; the mid-quad yield is
        # only allowed to move the schedule, so the two must paint the
        # same 180 screens as each other and as rastermodel.py.
        bad = verify(False)
        print()
        bad += verify(True)
        raise SystemExit(1 if bad else 0)
    if cmd == "frames":
        frames(int(sys.argv[2]) if len(sys.argv) > 2 else 60)
    else:
        time_it()
