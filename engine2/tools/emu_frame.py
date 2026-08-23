"""MEASURE a COMPLETE engine2 frame on a cycle-accurate CPC 6128.

    python3 engine2/tools/emu_frame.py verify [n]   frame == model, byte for byte
    python3 engine2/tools/emu_frame.py time         5 named scenarios, broken down
    python3 engine2/tools/emu_frame.py sweep [n]    the reachable state space

THE FRAME UNDER TEST is engine2/test/tst_frame.asm:frame_all --

    bg_fill        ceiling + floor bands (this IS the buffer clear)
    frame_geom     march + project -> QUADS, painter order back to front
    raster_frame   every quad -> horizontal PUSH DE runs

-- i.e. everything between "the player is here" and "the buffer is finished".
Only the CRTC flip is missing, and that is 2 OUTs.

TIMING PROTOCOL.  A 16-bit counter is bumped once per iteration of a tight
loop with interrupts off; cpc.run_us(N) returns Z80 ticks at 4 MHz and the
gate array stretches every instruction to a whole microsecond, so ticks/4 is
exactly the CPC microsecond count.  An identical loop with the CALL removed
gives the loop overhead, which is subtracted.  The method is calibrated
against a loop with 100 NOPs in it, which must come out at 100.0 us.

The window is sized ADAPTIVELY so that at least ~200 whole iterations
complete: the counter counts iterations STARTED, so the partial iteration at
the end of the window is worth up to one period, i.e. ~0.5% at n = 200.  (It
also must not exceed 65535 -- that wrap is the bug that made emu_kernel.py's
empty-loop baseline read 43.5 us instead of 14.9.)
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
sys.path.insert(0, os.path.join(_ROOT, "prototype", "free-angle"))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import addrs                                              # noqa: E402
import cpchw as cpc                                          # noqa: E402
import gentab                                                # noqa: E402
import marchmodel as mm                                      # noqa: E402
import pal                                                   # noqa: E402
import projmodel as pm                                       # noqa: E402
import rastermodel as rm                                     # noqa: E402
import world                                                 # noqa: E402
from cpc import CPC                                          # noqa: E402

BUILD = os.path.join(_E2, "build")

E_ONCE, E_FRAME, E_EMPTY, E_GEOM, E_BG, E_RAST, E_BGEOM = (
    0x8000, 0x8004, 0x8008, 0x800C, 0x8010, 0x8014, 0x8018)

QUADS = addrs.QUADS
QRECSZ = 8
FRONT = 0xC000
SCRSZ = 0x4000
BUDGET_US = 100000.0                    # 5 vsync frames = 10 fps.
# main3.asm paces the loop with a cost accumulator and spends exactly
# PACE_FRAMES = 5 vsync waits a frame; see the PACING note there for why
# 4 was not reachable.  NOTE that the figures this file measures are the
# DRAW only, and with `PACED` undefined -- tst_frame.asm has no main3.asm,
# so the accumulator hooks are compiled out.  For what the shipped frame
# costs WITH them, use engine2/tools/emu_pacefit.py.


# ------------------------------------------------------------------ build --
def build():
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "tab_test.bin"), "wb").write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_frame.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_frame", "-s", "-os", "../build/tst_frame"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_frame.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_frame")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return blob, code, sym


class Rig:
    def __init__(self):
        self.tables, self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(gentab.BANK_BASE, self.tables)
        self.c.write_ram(0x8000, self.code)
        self.cfg = rm.cfg()
        self.ramp = pal.ramp_table()
        self.ovh = 0.0

    def s(self, n):
        return self.sym[n.upper()]

    def set_state(self, px, py, a):
        self.c.write_ram(self.s("PLR_X"), struct.pack("<H", px))
        self.c.write_ram(self.s("PLR_Y"), struct.pack("<H", py))
        self.c.poke(self.s("PLR_A"), a)

    # -- one frame, for verification -----------------------------------
    def run_once(self, px, py, a, poison=0x5A):
        self.set_state(px, py, a)
        self.c.write_ram(FRONT, bytes([poison]) * SCRSZ)
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(E_ONCE)
        for _ in range(400):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                break
        else:
            raise RuntimeError("frame never finished")
        n = self.c.peek(self.s("FG_NQUAD"))
        raw = self.c.read_ram(QUADS, QRECSZ * n)
        # (blo, bhi, hlo, hhi, kind, k) -- see kernel.asm
        quads = [(raw[QRECSZ * i], raw[QRECSZ * i + 1])
                 + struct.unpack("<2H", raw[QRECSZ * i + 2:QRECSZ * i + 6])
                 + (raw[QRECSZ * i + 6], raw[QRECSZ * i + 7])
                 for i in range(n)]
        return self.c.read_ram(FRONT, SCRSZ), quads

    # -- timing ---------------------------------------------------------
    def _bench_raw(self, entry, us):
        self.c.set_pc(entry)
        self.c.run_us(60000)                    # settle into the loop
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        if not 0 < n < 60000:
            raise RuntimeError(f"counter unusable: {n} (window {us} us)")
        return (ticks / 4.0) / n, n

    def bench(self, entry, px, py, a, target_n=200, maxus=20000000):
        """-> CPC us per iteration, loop overhead REMOVED, window adaptive."""
        self.set_state(px, py, a)
        p, _ = self._bench_raw(entry, 600000)
        us = min(maxus, max(600000, int(p * target_n)))
        p, n = self._bench_raw(entry, us)
        return p - self.ovh

    def measure_overhead(self):
        # short window: the empty loop is ~15 us, so 500 ms is 33000 counts
        # and 1.5 s would WRAP the 16-bit counter.
        self.ovh = 0.0
        self.ovh, _ = self._bench_raw(E_EMPTY, 500000)
        return self.ovh


# ------------------------------------------------------------ calibration --
def calibrate(rig):
    src = os.path.join(BUILD, "cal.asm")
    open(src, "w").write(
        "    org #9E00\n    jp cal_e\n    jp cal_n\n"
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
    save = rig.c.read_ram(0x9E00, len(blob))
    rig.c.write_ram(0x9E00, blob)

    def one(pc, us=400000):
        rig.c.set_pc(pc)
        rig.c.run_us(2000)
        rig.c.write_ram(sym["CNT"], b"\x00\x00")
        t = rig.c.run_us(us)
        n = struct.unpack("<H", rig.c.read_ram(sym["CNT"], 2))[0]
        return (t / 4.0) / n
    e, f = one(0x9E00), one(0x9E03)
    print("=== timing method calibration ===")
    print(f"  empty counter loop            : {e:8.2f} us")
    print(f"  same loop + 100 NOPs          : {f:8.2f} us")
    print(f"  difference (should be 100.00) : {f - e:8.2f} us")
    rig.c.write_ram(0x9E00, save)
    rig.c.write_ram(0x8000, rig.code)
    return f - e


# ------------------------------------------------------------- the model ---
def bands():
    """-> [(first_y, n_lines, pen_byte)], the 4-band background."""
    solid = cpc.MODE0_SOLID
    c = rm.cfg()
    q = (c.CYH // 16) * 8
    segs = [(q, solid[pal.CEIL_NEAR]), (c.CYH - q, solid[pal.CEIL_FAR]),
            (c.CYH - q, solid[pal.FLOOR_FAR]), (q, solid[pal.FLOOR_NEAR])]
    out, y = [], c.VP_Y
    for nl, pen in segs:
        out.append((y, nl, pen))
        y += nl
    return out


def expect_screen(quads, c, ramp, poison=0x5A):
    """The 16K buffer the model says a whole frame must leave behind."""
    scr = bytearray([poison]) * SCRSZ
    for y0, nl, pen in bands():
        for y in range(y0, y0 + nl):
            base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
            for x in range(c.VP_BW):
                scr[base + x] = pen
    mc = rm.joint_colour()
    for q in quads:
        col = rm.colour(q, ramp)
        # the face, and then its two course joints ON TOP of it -- the
        # order raster_frame draws them in
        for runs, cl in ((rm.raster_quad(q, c), col),
                         (rm.joint_runs(q, c), mc)):
            for (r, e, n) in runs:
                y = c.VP_Y + r
                base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
                for x in range(e - 2 * n, e):
                    scr[base + x] = cl
    return bytes(scr)


def model_quads(solid, px, py, a):
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is not None:
            out.append(q + (1 if door else 0, k))
    return out, r


def counters(solid, px, py, a):
    """-> (quads, ref_cells, cand_faces, body_l, body_b, wedge_l, wedge_b)."""
    c = rm.cfg()
    quads, r = model_quads(solid, px, py, a)
    ref = mm.march(solid, px, py, a, push_opaque=True)["visited"]
    bl = bb = wl = wb = 0
    for q in quads:
        a1, a2, a3, a4 = rm.counts(q, c)
        bl += a1
        bb += a2
        wl += a3
        wb += a4
    return quads, ref, len(r["faces"]), bl, bb, wl, wb


# ----------------------------------------------------------------- maze ----
def load():
    grid, _, _ = world.load_maze()
    return grid, mm.solid_from_grid(grid)


def floors(grid):
    return [(x, y) for y in range(16) for x in range(16)
            if grid[y][x] == world.FLOOR]


# ----------------------------------------------------------------- lstsq ---
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


# ---------------------------------------------------------------- verify ---
def verify(n=12):
    rig = Rig()
    c = rig.cfg
    grid, solid = load()
    fl = floors(grid)
    rnd = random.Random(24601)
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes at ({c.VP_BX},{c.VP_Y}), "
          f"horizon row {c.CYH}")
    bad = 0
    for i in range(n):
        x, y = rnd.choice(fl)
        px, py = (x << 8) | rnd.randrange(256), (y << 8) | rnd.randrange(256)
        a = rnd.randrange(72)
        got, zq = rig.run_once(px, py, a)
        mq, _ = model_quads(solid, px, py, a)
        if list(zq) != [tuple(q) for q in mq]:
            print(f"  QUAD LIST MISMATCH at ({px:04X},{py:04X},{a})")
            print(f"    z80   {zq}")
            print(f"    model {mq}")
            bad += 1
            continue
        want = expect_screen(zq, c, rig.ramp)
        if got != want:
            nb = sum(1 for j in range(SCRSZ) if got[j] != want[j])
            print(f"  SCREEN MISMATCH at ({px:04X},{py:04X},{a}): {nb} bytes")
            bad += 1
        else:
            print(f"  ok  ({px:04X},{py:04X}) a={a:2d}  {len(zq):2d} quads, "
                  f"16384 bytes exact")
    print(f"\nVERIFY: {n} whole frames, {n - bad} exact, {bad} bad")
    return bad


# ------------------------------------------------------------- scenarios ---
def scenarios(grid, solid):
    """Five named player states: corridor, junction, corner, open, nose."""
    def openp(x, y):
        return 0 <= x < 16 and 0 <= y < 16 and grid[y][x] == world.FLOOR

    def nb(x, y):
        return [d for d, (dx, dy) in enumerate(((1, 0), (0, 1), (-1, 0),
                                                (0, -1)))
                if openp(x + dx, y + dy)]
    # heading 0..71 is 5 deg steps; +x is 0, +y is 18, -x is 36, -y is 54
    HDG = {0: 0, 1: 18, 2: 36, 3: 54}
    out = {}
    for x, y in floors(grid):
        d = nb(x, y)
        if len(d) == 2 and (d[1] - d[0]) == 2:
            out.setdefault("corridor, looking along it",
                           ((x << 8) | 128, (y << 8) | 128, HDG[d[0]]))
        if len(d) >= 3:
            out.setdefault("junction (3+ ways)",
                           ((x << 8) | 128, (y << 8) | 128, HDG[d[0]] + 2))
        if len(d) == 2 and (d[1] - d[0]) % 2 == 1:
            out.setdefault("tight corner, into the bend",
                           ((x << 8) | 128, (y << 8) | 128,
                            (HDG[d[0]] + HDG[d[1]]) // 2))
        if len(d) == 4 and all(openp(x + dx, y + dy)
                               for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            out.setdefault("open area (3x3 clear), off-axis",
                           ((x << 8) | 128, (y << 8) | 128, 9))
        if len(d) == 3:
            # 64/256 = 0.25 cells from the wall plane.  Do NOT push this
            # past 0.375: project.asm's near plane is ZNEAR = 0.125 cells,
            # and a face closer than that is rejected outright, so the
            # movement code's collision radius must be > 0.125.
            wall = [dd for dd in range(4) if dd not in d][0]
            dx, dy = ((1, 0), (0, 1), (-1, 0), (0, -1))[wall]
            out.setdefault("nose against a wall (0.25 cells)",
                           ((x << 8) | (128 + 64 * dx),
                            (y << 8) | (128 + 64 * dy), HDG[wall]))
    if not any(k.startswith("open") for k in out):
        # no 3x3 clear cell in this maze: take the cell with the most open
        # neighbours in its 5x5 and look off-axis from it
        best = max(floors(grid),
                   key=lambda p: sum(openp(p[0] + dx, p[1] + dy)
                                     for dx in range(-2, 3)
                                     for dy in range(-2, 3)))
        out["most open cell here, off-axis"] = ((best[0] << 8) | 128,
                                                (best[1] << 8) | 128, 9)
    return [(k,) + v for k, v in out.items()]


def time_it():
    rig = Rig()
    c = rig.cfg
    cal = calibrate(rig)
    ovh = rig.measure_overhead()
    grid, solid = load()
    print(f"\nloop overhead per iteration: {ovh:.2f} us  (subtracted below)")
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes = {c.VP_BW*2}x{c.VP_H} pixels,"
          f" budget {BUDGET_US/1000:.0f} ms\n")

    rows = []
    print("%-30s %5s %4s %4s %8s %8s %8s %9s %7s" %
          ("scenario", "quads", "ref", "cnd", "bg us", "geom us",
           "rast us", "FRAME us", "ms"))
    for name, px, py, a in scenarios(grid, solid):
        q, ref, cand, bl, bb, wl, wb = counters(solid, px, py, a)
        bg = rig.bench(E_BG, px, py, a, target_n=400)
        gm = rig.bench(E_GEOM, px, py, a)
        rs = rig.bench(E_RAST, px, py, a)
        fr = rig.bench(E_FRAME, px, py, a)
        rows.append((name, fr))
        print("%-30s %5d %4d %4d %8.0f %8.0f %8.0f %9.0f %7.2f" %
              (name, len(q), ref, cand, bg, gm, rs, fr, fr / 1000.0))
        print("%-30s %5s %4s %4s   sum of the three parts = %8.0f us "
              "(call overhead %+.0f)" % ("", "", "", "", bg + gm + rs,
                                         fr - (bg + gm + rs)))
    return rig, cal


# ---------------------------------------------------------------- sweep ----
def reachable(solid, px, py, rad_q8):
    """Can the player centre stand here with a collision radius of rad_q8
    (in 1/256 cells)?  Circle vs the solid cells around it: a face is too
    close if the perpendicular distance is under the radius, a corner if
    the diagonal distance is.  rad_q8 = 0 accepts everything.

    This matters because project.asm's near plane is ZNEAR = 0.125 cells:
    a wall face closer than that is REJECTED, so the movement code has to
    keep the player further out than 32/256 anyway, and sub-cell offsets
    inside that band are not states the game can actually be in."""
    if rad_q8 <= 0:
        return True
    cx, cy, fx, fy = px >> 8, py >> 8, px & 255, py & 255
    r = rad_q8

    def blocked(i, j):
        return not (0 <= i < 16 and 0 <= j < 16) or solid[j * 16 + i]
    if blocked(cx, cy):
        return False
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (dx or dy) and blocked(cx + dx, cy + dy):
                # signed distance from the player to that cell, per axis
                ex = 0 if dx == 0 else (fx if dx < 0 else 256 - fx)
                ey = 0 if dy == 0 else (fy if dy < 0 else 256 - fy)
                if ex * ex + ey * ey < r * r:
                    return False
    return True


def sweep(nmeas=120, nworst=64, sub=4, seed=20260819, rad_q8=0):
    """Sweep the reachable state space and MEASURE whole frames.

      1. enumerate every reachable state (floor cells x sub-cell grid x 72)
         and count what drives the cost, with the bit-exact Python models;
      2. MEASURE `nmeas` of them drawn UNIFORMLY from that pool, and fit
         whole-frame us to those counters;
      3. rank the whole pool with the fit and MEASURE the `nworst` worst,
         plus a percentile ladder.

    Step 2 gives the MEASURED typical figures; step 3 gives the MEASURED
    worst.  The fit is only used to decide WHICH states are worth measuring
    -- every number reported as measured is a real emulator run.
    """
    rig = Rig()
    c = rig.cfg
    calibrate(rig)
    ovh = rig.measure_overhead()
    grid, solid = load()
    fl = floors(grid)
    rnd = random.Random(seed)
    print(f"\nloop overhead {ovh:.2f} us subtracted from every figure below")
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes at ({c.VP_BX},{c.VP_Y}) "
          f"= {c.VP_BW*2}x{c.VP_H} pixels\n")

    # ---- 1. the reachable state space ---------------------------------
    offs = [(i * 256 // sub) + (256 // (2 * sub)) for i in range(sub)]
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for (cx, cy) in fl for ox in offs for oy in offs
            for a in range(72)
            if reachable(solid, (cx << 8) | ox, (cy << 8) | oy, rad_q8)]
    print(f"=== 1. {len(fl)} floor cells x {sub*sub} sub-cell offsets "
          f"x 72 headings = {len(pool)} states")
    if rad_q8:
        print(f"    filtered to a collision radius of {rad_q8}/256 = "
              f"{rad_q8/256.0:.3f} cells (ZNEAR is 0.125)")
    cnt = [counters(solid, *st) for st in pool]
    print(f"    counted (quads {min(len(k[0]) for k in cnt)}.."
          f"{max(len(k[0]) for k in cnt)}, "
          f"marched cells {min(k[1] for k in cnt)}..{max(k[1] for k in cnt)})")

    def vec(k):
        q, ref, cand, bl, bb, wl, wb = k
        return [1.0, float(ref), float(cand), float(len(q)), float(bl),
                float(bb), float(wl), float(wb)]

    # ---- 2. MEASURE a uniform sample, and fit -------------------------
    print(f"\n=== 2. MEASURING {nmeas} states drawn uniformly from the pool")
    idx = rnd.sample(range(len(pool)), nmeas)
    X, Y = [], []
    for n, i in enumerate(idx):
        us = rig.bench(E_FRAME, *pool[i], target_n=150)
        X.append(vec(cnt[i]))
        Y.append(us)
        if n % 20 == 0:
            print(f"    {n:4d}/{nmeas}  {us/1000:6.2f} ms")
    Ys = sorted(Y)

    def q_(p):
        return Ys[min(len(Ys) - 1, int(p * len(Ys)))] / 1000.0
    print(f"  MEASURED, uniform sample of {nmeas}:  median {q_(0.5):.2f}  "
          f"mean {sum(Y)/len(Y)/1000:.2f}  p90 {q_(0.9):.2f}  "
          f"max {Ys[-1]/1000:.2f} ms")
    over = sum(1 for v in Y if v > BUDGET_US)
    print(f"  {over}/{nmeas} of the uniform sample are over {BUDGET_US/1000:.0f} ms "
          f"({100.0*over/nmeas:.1f}%)")
    co, rms, r2, wr = lstsq(X, Y)
    print("  fit: us = %.0f + %.1f*ref + %.1f*cand + %.0f*nquad + %.2f*bodyL"
          " + %.3f*bodyB + %.2f*wedgeL + %.3f*wedgeB" % tuple(co))
    print(f"       R^2 {r2:.5f}, RMS residual {rms:.0f} us, worst {wr:.0f} us")

    # ---- 3. rank the pool, MEASURE the top of it ----------------------
    pred = sorted(range(len(pool)),
                  key=lambda i: sum(a * b for a, b in zip(co, vec(cnt[i]))))
    pv = [sum(a * b for a, b in zip(co, vec(cnt[i]))) for i in pred]
    print("  PREDICTED over the whole pool: median %.2f  p90 %.2f  p99 %.2f "
          " worst %.2f ms" % (pv[len(pv)//2]/1000, pv[int(.9*len(pv))]/1000,
                              pv[int(.99*len(pv))]/1000, pv[-1]/1000))

    print(f"\n=== 3. MEASURING the {nworst} worst states the fit ranks, plus "
          f"a percentile ladder")
    picks = [("worst-%d" % n, i) for n, i in enumerate(pred[::-1][:nworst])]
    picks += [("p%.1f" % (p*100), pred[int(p * (len(pred) - 1))])
              for p in (0.5, 0.75, 0.9, 0.99, 0.999)]
    print("%-9s %-19s %5s %4s %4s %8s %8s %7s" %
          ("pick", "state", "quads", "ref", "cnd", "pred ms", "MEAS ms",
           "budget"))
    meas = []
    for tag, i in picks:
        px, py, a = pool[i]
        k = cnt[i]
        us = rig.bench(E_FRAME, px, py, a, target_n=300)
        p = sum(x * y for x, y in zip(co, vec(k)))
        meas.append((tag, us, p, px, py, a))
        if tag.startswith("p") or us > BUDGET_US - 4000 or len(meas) < 12:
            print("%-9s (%04X,%04X) a=%2d  %5d %4d %4d %8.2f %8.2f %7s" %
                  (tag, px, py, a, len(k[0]), k[1], k[2], p/1000, us/1000,
                   "OK" if us <= BUDGET_US else "OVER"))
    err = [m[1] - m[2] for m in meas]
    print("  fit error on the measured picks: mean %+.0f us, worst %+.0f us"
          % (sum(err) / len(err), max(err, key=abs)))
    nover = sum(1 for m in meas if m[1] > BUDGET_US)
    frac = sum(1 for v in pv if v > BUDGET_US) / float(len(pv))

    # ---- 4. the verdict ----------------------------------------------
    wm = max(meas, key=lambda m: m[1])
    print("\n=== VERDICT, viewport %dx%d bytes " % (c.VP_BW, c.VP_H)
          + "=" * 42)
    print(f"  typical (uniform sample) median   {q_(0.5):8.2f} ms")
    print(f"  p90 of that sample                {q_(0.9):8.2f} ms")
    print(f"  worst frame MEASURED              {wm[1]/1000:8.2f} ms   at "
          f"({wm[3]:04X},{wm[4]:04X}) a={wm[5]}")
    print(f"  budget (5 vsync frames, 10.0 fps) {BUDGET_US/1000:8.2f} ms")
    if wm[1] <= BUDGET_US:
        print(f"  FITS, with {(BUDGET_US-wm[1])/1000:.2f} ms "
              f"({100*(BUDGET_US-wm[1])/BUDGET_US:.1f}%) to spare")
    else:
        print(f"  MISSES by {(wm[1]-BUDGET_US)/1000:.2f} ms "
              f"= {100*wm[1]/BUDGET_US:.1f}% of budget")
    print(f"  {nover} of the {len(meas)} measured picks are over budget; the "
          f"fit puts {100*frac:.3f}% of all {len(pool)} states over")
    return co, pool, cnt, meas


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "time"
    if mode == "verify":
        raise SystemExit(1 if verify(int(sys.argv[2]) if len(sys.argv) > 2
                                     else 12) else 0)
    elif mode == "time":
        time_it()
    elif mode == "sweep":
        sweep(*[int(v) for v in sys.argv[2:]])
    else:
        raise SystemExit(__doc__)
