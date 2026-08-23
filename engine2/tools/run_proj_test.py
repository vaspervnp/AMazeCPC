"""Build engine2/src/project.asm, run it on the headless CPC 6128, and

  1. assert the Z80 output is BIT-EXACT with engine2/tools/projmodel.py
  2. compare both against the float reference free.py:project_face()
  3. MEASURE us/face for a spread of face classes

Timing protocol: the routine under test runs in a tight loop that bumps a
16-bit counter, with interrupts off, for a known number of emulated
microseconds (cpcemu_exec_us returns the exact figure).  An identical loop
with the call removed gives the loop overhead, which is subtracted.
"""

import argparse
import math
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

import gentab                                              # noqa: E402
import projmodel as pm                                     # noqa: E402
import geom                                                # noqa: E402
import free                                                # noqa: E402
from cpc import CPC                                        # noqa: E402

# The viewport comes from engine2/src/vpcfg.inc, via gentab -- NOT from a
# copy pasted here, which would silently disagree with the tables.
geom.VP_BX, geom.VP_BW = gentab.VP_BX, gentab.VP_BW
geom.VP_Y, geom.VP_H = gentab.VP_Y, gentab.VP_H
geom.VP_PW = gentab.VP_PW
geom.CX, geom.CY = gentab.CX, gentab.CY

geom.ZNEAR = gentab.ZNEAR
free.ZNEAR = gentab.ZNEAR
free.set_focal(gentab.FOCAL_H, gentab.FOCAL_V)

BUILD = os.path.join(_E2, "build")
NDIR = {"N": 0, "E": 1, "S": 2, "W": 3}


# ------------------------------------------------------------------ build --
def build():
    blob, layout, values = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "tab_test.bin"), "wb") as fh:
        fh.write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_proj.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_proj", "-s", "-os", "../build/tst_proj"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_proj.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_proj")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0]] = int(p[1][1:], 16)
    return blob, code, sym


class Machine:
    def __init__(self, tables, code, sym):
        self.sym = sym
        self.c = CPC()
        self.c.run_frames(120)              # settle at the BASIC prompt
        self.c.write_ram(gentab.BANK_BASE, tables)
        self.c.write_ram(0x8000, code)
        self.code = code

    def reload_code(self):
        self.c.write_ram(0x8000, self.code)

    def set_player(self, fx, fy, ang):
        s = self.sym
        self.c.poke(s["PV_FX"], fx)
        self.c.poke(s["PV_FY"], fy)
        self.c.poke(s["PV_ANG"], ang)

    def set_face(self, rec):
        s = self.sym
        self.c.write_ram(s["PF_I0"], bytes(v & 0xFF for v in rec))

    def run_list(self, faces):
        s = self.sym
        buf = b"".join(bytes(v & 0xFF for v in f) for f in faces)
        self.c.write_ram(s["IN_BUF"], buf)
        self.c.poke(s["N_FACES"], len(faces))
        self.c.poke(s["DONE"], 0)
        self.c.set_pc(s["RUN_LIST"])
        for _ in range(200):
            self.c.run_frames(1)
            if self.c.peek(s["DONE"]) == 0xFF:
                break
        else:
            raise RuntimeError("run_list never finished")
        raw = self.c.read_ram(s["OUT_BUF"], 7 * len(faces))
        out = []
        for k in range(len(faces)):
            r = raw[7 * k:7 * k + 7]
            if r[0] == 0:
                out.append(None)
            else:   # (blo, bhi, hlo, hhi) -- project.asm:pf_emit
                out.append((r[1], r[2]) + struct.unpack("<2H", r[3:7]))
        return out

    def time_loop(self, entry, us=200000):
        """-> (CPC microseconds per iteration, iterations).

        cpc_exec() takes microseconds but RETURNS Z80 ticks at 4 MHz, and
        the gate array stretches every instruction to a whole microsecond,
        so ticks/4 is exactly the CPC microsecond count.  The 16-bit
        counter must not wrap, so `us` is chosen per call site.
        """
        s = self.sym
        self.c.set_pc(s[entry])
        self.c.run_us(2000)                 # get into the loop
        self.c.write_ram(s["COUNTER"], b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(s["COUNTER"], 2))[0]
        if n == 0:
            raise RuntimeError("counter did not move for " + entry)
        if n > 60000:
            raise RuntimeError(f"{entry}: counter close to wrapping ({n})")
        return (ticks / 4.0) / n, n


# ------------------------------------------------------------- face model --
def lattice(wx, wy, fd):
    (ax, ay), (bx, by), _ = pm.face_endpoints(wx, wy, fd)
    return ax, ay, bx, by


def model_face(fx, fy, ang, wx, wy, fd):
    fr = pm.Frame(fx / 256.0, fy / 256.0, ang)
    assert fr.fx == fx and fr.fy == fy and fr.ipx == 0 and fr.ipy == 0
    ax, ay, bx, by = lattice(wx, wy, fd)
    return fr, pm.project_face_ij(fr, ax, ay, bx, by, fd)


def model_face_screen(fx, fy, ang, wx, wy, fd):
    """The same projection, stopped at FULL-PRECISION screen space.

    proj_face emits a byte-rounded record; the accuracy question in step
    2 below is about the PROJECTION, not about that rounding, so it is
    asked of the screen-space result -- which step 1 has already proved
    the Z80 reproduces bit for bit."""
    fr = pm.Frame(fx / 256.0, fy / 256.0, ang)
    ax, ay, bx, by = lattice(wx, wy, fd)
    s = pm.project_face_ij_screen(fr, ax, ay, bx, by, fd)
    return None if s is None else pm.screen_xy(s)


def ref_face(fx, fy, ang, wx, wy, fd):
    fwd, rgt = free.basis(ang)
    r = free.project_face(wx, wy, fd, fx / 256.0, fy / 256.0, fwd, rgt)
    if r is None:
        return None
    pts, _ = r
    return (pts[0][0], pts[0][1], pts[3][1], pts[1][0], pts[1][1], pts[2][1])


# ------------------------------------------------------------ face corpus --
def classify(fr, wx, wy, fd):
    """Which clip planes fire for this face, and its mid-depth in cells."""
    ax, ay, bx, by = lattice(wx, wy, fd)
    xa, za = fr.view(ax, ay)
    xb, zb = fr.view(bx, by)
    tags = []
    if za < pm.ZNEAR_Q10 or zb < pm.ZNEAR_Q10:
        tags.append("near")
    ka, kb = pm.khalf_z(max(za, 0)), pm.khalf_z(max(zb, 0))
    if (ka - xa < 0) != (kb - xb < 0):
        tags.append("right")
    if (xa + ka < 0) != (xb + kb < 0):
        tags.append("left")
    return tags, 0.5 * (za + zb) / 1024.0


def corpus(n, seed=4242):
    """A spread of faces the MARCH could really hand us.

    Half are faces the model accepts (so the reference comparison has
    something to compare) and half are whatever falls out, so the
    exactness test also covers every rejection path.
    """
    rnd = random.Random(seed)
    acc, rej = [], []
    tries = 0
    while (len(acc) < n // 2 or len(rej) < n - n // 2) and tries < 200000:
        tries += 1
        wx, wy = rnd.randint(-7, 7), rnd.randint(-7, 7)
        if abs(wx) + abs(wy) > 7:
            continue
        c = (rnd.randrange(1, 256), rnd.randrange(1, 256),
             rnd.randrange(72), wx, wy, rnd.randint(0, 3))
        _, e = model_face(*c)
        if e is None:
            if len(rej) < n - n // 2:
                rej.append(c)
        elif len(acc) < n // 2:
            acc.append(c)
    return acc + rej


# Named faces for the timing breakdown, as (label, fx, fy, ang, wx, wy, fd).
# Heading 0 looks along +x, so a wall cell at (+f, 0) shows its WEST face
# and a wall row at y = -1 shows its SOUTH face (a side wall).
SCENES = [
    ("front wall, 1 cell",      128, 128,  0,  1,  0, pm.WEST),
    ("front wall, 6 cells",     128, 128,  0,  6,  0, pm.WEST),
    ("front wall, oblique",     128, 128,  5,  2,  0, pm.WEST),
    ("side wall, no clip",      128, 128,  0,  1, -1, pm.SOUTH),
    ("side wall, 1 edge clip",  128, 128,  0,  3, -1, pm.SOUTH),
    ("side wall, 2 edge clips", 128, 128,  0, -4, -1, pm.SOUTH),
    ("crosses the near plane",  128, 128,  0,  0, -1, pm.SOUTH),
    ("backfacing (early out)",  128, 128,  0,  1,  0, pm.EAST),
    ("behind the player",       128, 128,  0, -3,  0, pm.EAST),
]


# ------------------------------------------------------------------ main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--faces", type=int, default=400)
    args = ap.parse_args()

    tables, code, sym = build()
    m = Machine(tables, code, sym)
    print(f"code {len(code)} bytes at #8000, tables {len(tables)} bytes "
          f"at #{gentab.BANK_BASE:04X}")

    # ---- 0. prove the timing method ---------------------------------
    t_empty, _ = m.time_loop("TM_EMPTY", 200000)
    t_cal, _ = m.time_loop("TM_CALIB", 200000)
    print()
    print("=== 0. timing method calibration ===")
    print(f"  empty counter loop            : {t_empty:8.2f} us")
    print(f"  same loop + 100 NOPs          : {t_cal:8.2f} us")
    print(f"  difference (should be 100.00) : {t_cal - t_empty:8.2f} us")

    # ---- 1/2. correctness -------------------------------------------
    cases = corpus(args.faces)
    groups = {}
    for fx, fy, ang, wx, wy, fd in cases:
        groups.setdefault((fx, fy, ang), []).append((wx, wy, fd))

    nexact = nmismatch = accdis = 0
    mism = []
    ex, ey, exc, eyc = [], [], [], []
    for (fx, fy, ang), faces in groups.items():
        m.set_player(fx, fy, ang)
        recs = [lattice(wx, wy, fd) + (fd,) for wx, wy, fd in faces]
        got = m.run_list(recs)
        for (wx, wy, fd), g in zip(faces, got):
            fr, exp = model_face(fx, fy, ang, wx, wy, fd)
            if g != exp:
                nmismatch += 1
                if len(mism) < 8:
                    mism.append((fx, fy, ang, wx, wy, fd, exp, g))
                continue
            nexact += 1
            r = ref_face(fx, fy, ang, wx, wy, fd)
            if (r is None) != (g is None):
                accdis += 1
                continue
            if g is None:
                continue
            gg = tuple(v / 16.0 for v in
                       model_face_screen(fx, fy, ang, wx, wy, fd))
            cl = lambda v, h: min(max(v, 0.0), h)
            for i in (0, 3):
                ex.append(abs(r[i] - gg[i]))
                exc.append(abs(cl(r[i], 96.0) - cl(gg[i], 96.0)))
            for i in (1, 2, 4, 5):
                ey.append(abs(r[i] - gg[i]))
                eyc.append(abs(cl(r[i], 128.0) - cl(gg[i], 128.0)))

    print()
    print("=== 1. Z80 vs the bit-exact model (projmodel.py) ===")
    print(f"  faces run on the emulator : {nexact + nmismatch}")
    print(f"  bit-exact                 : {nexact}")
    print(f"  MISMATCHES                : {nmismatch}")
    for t in mism:
        print("   ", t)

    def pct(a, q):
        a = sorted(a)
        return a[int(q * (len(a) - 1))] if a else 0.0

    print()
    print("=== 2. Z80 vs float reference (free.py project_face) ===")
    print(f"  faces where both accepted   : {len(ex)//2}")
    print(f"  accept/reject disagreements : {accdis}")
    print(f"  screen x error, px        median {pct(ex,.5):6.3f}"
          f"  p99 {pct(ex,.99):6.3f}  MAX {max(ex) if ex else 0:6.3f}")
    print(f"  screen y error, scanlines median {pct(ey,.5):6.3f}"
          f"  p99 {pct(ey,.99):6.3f}  MAX {max(ey) if ey else 0:6.3f}")
    print("  clamped to the 96x128 viewport (all that is ever drawn):")
    print(f"    x MAX {max(exc) if exc else 0:.3f} px      "
          f"y MAX {max(eyc) if eyc else 0:.3f} scanlines")
    if nmismatch:
        return 1

    # ---- 3. timing ---------------------------------------------------
    print()
    print("=== 3. MEASURED COST, CPC microseconds ===")
    print("  (call + body + ret; the empty counter loop is subtracted)")
    print(f"  {'face class':28s} {'us':>8s} {'march-fed':>10s}"
          f"  {'z':>5s}  clips")
    print("  (march-fed = proj_face handed VIEW-SPACE endpoints, i.e. with"
          " lat_view gone)")
    tot = {}
    fed = {}
    tv0, _ = m.time_loop("TM_FACEV0", 200000)
    for label, fx, fy, ang, wx, wy, fd in SCENES:
        rec = lattice(wx, wy, fd) + (fd,)
        m.set_player(fx, fy, ang)
        m.set_face(rec)
        fr = pm.Frame(fx / 256.0, fy / 256.0, ang)
        e = pm.project_face_ij(fr, *rec)
        tags, zmid = classify(fr, wx, wy, fd)
        t, n = m.time_loop("TM_FACE", 200000)
        tot[label] = t - t_empty
        tv0, _ = m.time_loop("TM_FACEV0", 200000)
        tv, _ = m.time_loop("TM_FACEV", 200000)
        fed[label] = tv - tv0
        note = ",".join(tags) if tags else "-"
        if e is None:
            note += "  REJECTED"
        print(f"  {label:28s} {t-t_empty:8.1f} {tv-tv0:10.1f}"
              f"  {zmid:5.2f}  {note}")

    print()
    print("  --- component costs ---")
    m.set_player(128, 128, 5)
    m.set_face(lattice(2, 0, pm.WEST) + (pm.WEST,))
    for entry, label, us in (("TM_SETUP", "proj_setup (ONCE PER FRAME)", 400000),
                             ("TM_LATVIEW", "lat_view   (per endpoint)", 200000),
                             ("TM_PROJPT", "proj_pt    (per endpoint)", 200000),
                             ("TM_MUL168", "mul16x8u", 100000)):
        t, n = m.time_loop(entry, us)
        print(f"  {label:28s} {t-t_empty:8.1f}")
    m.c.write_ram(sym["L_A"], struct.pack("<4h", 1000, 3000, 700, 300))
    t, n = m.time_loop("TM_LERP", 200000)
    print(f"  {'lerp       (per clipped pt)':28s} {t-t_empty:8.1f}")
    m.set_player(128, 128, 5)
    m.set_face(lattice(2, 0, pm.WEST) + (pm.WEST,))
    tv0, _ = m.time_loop("TM_FACEV0", 200000)
    ts, _ = m.time_loop("TM_SIDE", 200000)
    print(f"  {'pf_side (dies with march)':28s} {ts-tv0:8.1f}")

    # ---- 3b. average over REAL frames --------------------------------
    print()
    print("=== 3b. average over REAL marched frames (world.py maze) ===")
    import world
    grid, _sx, _sy = world.load_maze()
    tb0, _ = m.time_loop("TM_BATCH0", 200000)
    harness = tb0 - t_empty
    print(f"  batch harness overhead per face: {harness:.1f} us (subtracted)")
    print(f"  {'player':22s} {'cand':>5s} {'kept':>5s} {'us/face':>9s} "
          f"{'geom ms':>8s}")
    rows = []
    rnd = random.Random(99)
    for _ in range(8):
        while True:
            px = rnd.uniform(1.2, world.MAZE_W - 2.2)
            py = rnd.uniform(1.2, world.MAZE_H - 2.2)
            if world.cell_at(grid, int(px), int(py)) == world.FLOOR:
                break
        ang = rnd.randrange(72)
        _, cand, _ = free.march(grid, px, py, ang, {})
        ipx, ipy = int(math.floor(px)), int(math.floor(py))
        recs, kept = [], 0
        fx = int(round((px - ipx) * 256)) & 0xFF
        fy = int(round((py - ipy) * 256)) & 0xFF
        fr = pm.Frame(ipx + fx / 256.0, ipy + fy / 256.0, ang)
        for wx, wy, fd, _door in cand:
            ax, ay, bx, by = lattice(wx - ipx, wy - ipy, fd)
            if max(abs(ax), abs(ay), abs(bx), abs(by)) > 8:
                continue
            recs.append((ax, ay, bx, by, fd))
            if pm.project_face_ij(fr, ax, ay, bx, by, fd) is not None:
                kept += 1
        if not recs or len(recs) > 255:
            continue
        m.set_player(fx, fy, ang)
        m.c.write_ram(sym["IN_BUF"],
                      b"".join(bytes(v & 0xFF for v in r) for r in recs))
        m.c.poke(sym["N_FACES"], len(recs))
        t, n = m.time_loop("TM_BATCH", 200000)
        per = t - t_empty - harness
        rows.append((len(recs), kept, per))
        print(f"  ({px:5.2f},{py:5.2f}) a={ang:2d}  {len(recs):5d} {kept:5d} "
              f"{per:9.1f} {(per*len(recs))/1000:8.2f}")
    if rows:
        tot_us = sum(c * p for c, k, p in rows) / len(rows)
        print(f"  MEAN over these frames: {sum(c for c,k,p in rows)/len(rows):.1f}"
              f" candidate faces, {sum(k for c,k,p in rows)/len(rows):.1f} drawn,"
              f" {tot_us/1000:.2f} ms of proj_face per frame")

    # ---- 4. what it means for the frame ------------------------------
    print()
    print("=== 4. frame budget ===")
    typ = tot["front wall, oblique"]
    worst = max(tot[k] for k in tot)
    setup, _ = m.time_loop("TM_SETUP", 400000)
    setup -= t_empty
    for nf in (20, 30, 40):
        print(f"  {nf} faces x {typ:.0f} us + {setup:.0f} us setup = "
              f"{(nf*typ+setup)/1000:.1f} ms"
              f"   (worst-case face {worst:.0f} us -> "
              f"{(nf*worst+setup)/1000:.1f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
