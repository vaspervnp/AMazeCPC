"""Verify and MEASURE the whole engine2 per-frame geometry kernel.

    python3 engine2/tools/emu_kernel.py verify [n_states]
    python3 engine2/tools/emu_kernel.py time
    python3 engine2/tools/emu_kernel.py fit [n_states]

The kernel under test is engine2/src/kernel.asm:frame_geom --
    march  ->  proj_setup  ->  proj_face per candidate face  ->  quad list
-- i.e. everything between "the player is here" and "here are the quads for
the rasteriser".  Nothing is drawn.

TIMING PROTOCOL.  A 16-bit counter is bumped once per iteration of a tight
loop with interrupts off; cpc.run_us(N) returns Z80 ticks at 4 MHz and the
gate array stretches every instruction to a whole microsecond, so
ticks/4 is exactly the CPC microsecond count.  An identical loop with the
call removed gives the loop overhead, which is subtracted.  The method is
calibrated below against a loop with 100 NOPs in it.
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
import gentab                                                # noqa: E402
import marchmodel as mm                                      # noqa: E402
import projmodel as pm                                       # noqa: E402
import world                                                 # noqa: E402
from cpc import CPC                                          # noqa: E402

BUILD = os.path.join(_E2, "build")

E_ONCE, E_ALL, E_EMPTY, E_MARCH, E_PROJ, E_SETUP, E_MSETUP = (
    0x8000, 0x8004, 0x8008, 0x800C, 0x8010, 0x8014, 0x8018)

QUADS = addrs.QUADS
QRECSZ = 8


# ------------------------------------------------------------------ build --
def build():
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "tab_test.bin"), "wb").write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_kern.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_kern", "-s", "-os", "../build/tst_kern"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_kern.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_kern")):
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

    def s(self, n):
        return self.sym[n.upper()]

    def set_state(self, px, py, a):
        self.c.write_ram(self.s("PLR_X"), struct.pack("<H", px))
        self.c.write_ram(self.s("PLR_Y"), struct.pack("<H", py))
        self.c.poke(self.s("PLR_A"), a)

    def run_once(self, px, py, a):
        self.set_state(px, py, a)
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(E_ONCE)
        for _ in range(200):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                break
        else:
            raise RuntimeError("kernel never finished")
        n = self.c.peek(self.s("FG_NQUAD"))
        raw = self.c.read_ram(QUADS, QRECSZ * n)
        out = []
        for i in range(n):
            r = raw[QRECSZ * i:QRECSZ * i + QRECSZ]
            # (blo, bhi, hlo, hhi, kind, k) -- see kernel.asm
            out.append((r[0], r[1]) + struct.unpack("<2H", r[2:6])
                       + (r[6], r[7]))
        return out, dict(visited=self.c.peek(self.s("M_VISITED")),
                         seen=self.c.peek(self.s("M_SEEN")),
                         dropped=self.c.peek(self.s("M_DROPPED")))

    def bench(self, entry, px, py, a, us=1500000):
        """-> CPC microseconds per iteration (loop overhead NOT removed)."""
        self.set_state(px, py, a)
        self.c.set_pc(entry)
        self.c.run_us(60000)                    # settle into the loop
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        if not 0 < n < 60000:
            raise RuntimeError(f"counter unusable: {n}")
        return (ticks / 4.0) / n


# ----------------------------------------------------------- the model -----
def model_frame(solid, px, py, a):
    """The bit-exact Python kernel: march + project every candidate face."""
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    quads = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        # The march already carries the endpoints in VIEW SPACE, so the
        # projector is handed them straight (v = xa, za, xb, zb); only the
        # backface test still wants endpoint A's cell offset.
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is not None:
            quads.append(q + (door, k))
    return quads, r


def states_all(grid, offsets=((137, 91),), astep=1):
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    out = []
    for x, y in floors:
        for fx, fy in offsets:
            for a in range(0, 72, astep):
                out.append(((x << 8) | fx, (y << 8) | fy, a))
    return out


# ---------------------------------------------------------------- verify ---
def verify(n):
    grid, sx, sy = world.load_maze()
    solid = mm.solid_from_grid(grid)
    rig = Rig()
    rnd = random.Random(31337)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    st = []
    for _ in range(n):
        x, y = rnd.choice(floors)
        st.append(((x << 8) | rnd.randrange(256),
                   (y << 8) | rnd.randrange(256), rnd.randrange(72)))
    for a in range(72):                     # every heading from the start
        st.append(((sx << 8) | 128, (sy << 8) | 128, a))

    bad = 0
    tot_q = 0
    for px, py, a in st:
        got, info = rig.run_once(px, py, a)
        exp, _ = model_frame(solid, px, py, a)
        tot_q += len(exp)
        # painter order: bucket key must be non-increasing
        keys = [q[5] for q in got]
        ordered = all(keys[i] >= keys[i + 1] for i in range(len(keys) - 1))
        if sorted(got) != sorted(exp) or not ordered or info["dropped"]:
            bad += 1
            if bad <= 4:
                print(f"MISMATCH px={px} py={py} a={a} "
                      f"z80={len(got)} model={len(exp)} "
                      f"dropped={info['dropped']} ordered={ordered}")
                for g, e in zip(sorted(got), sorted(exp)):
                    if g != e:
                        print("   z80", g, "\n   mdl", e)
                        break
    print(f"verified {len(st)} frames ({tot_q} quads) against the bit-exact "
          f"model: {len(st)-bad} exact, {bad} mismatched")
    return bad


# ------------------------------------------------------------ calibration --
def calibrate(rig):
    """Prove the timing method: a loop + 100 NOPs must cost 100 us more."""
    src = os.path.join(_E2, "build", "cal.asm")
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
    e = one(0x9000)
    f = one(0x9003)
    print("=== timing method calibration ===")
    print(f"  empty counter loop            : {e:8.2f} us")
    print(f"  same loop + 100 NOPs          : {f:8.2f} us")
    print(f"  difference (should be 100.00) : {f-e:8.2f} us")
    rig.c.write_ram(0x8000, rig.code)       # cal.asm sat at #9000, code safe
    return f - e


# ------------------------------------------------------------------ time ---
# The four sub-cell offsets vpsweep.py uses, in the Z80's 8.8 fixed point.
VP_OFFS = ((128, 128), (64, 128), (128, 64), (77, 179))


def cell_class(grid, x, y):
    """corridor / junction / dead end / room, by the cell's neighbourhood."""
    n = sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if grid[y + dy][x + dx] == world.FLOOR)
    open8 = sum(1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if grid[y + dy][x + dx] == world.FLOOR)
    if open8 >= 7:
        return "open room"
    if n >= 3:
        return "junction"
    if n == 2:
        return "corridor"
    return "dead end"


def survey(grid, solid):
    """Model every (cell, sub-offset, heading) the sweep uses.

    -> rows of (px, py, a, popped, seen, candidates, quads, ref_cells)
    where ref_cells is free.py's cells_visited (the flood that also pushes
    opaque cells), i.e. the variable fcost.py multiplies by US_MARCH_CELL.
    """
    rows = []
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    for x, y in floors:
        for fx, fy in VP_OFFS:
            px, py = (x << 8) | fx, (y << 8) | fy
            for a in range(72):
                r = mm.march(solid, px, py, a)
                ref = mm.march(solid, px, py, a, push_opaque=True)["visited"]
                rows.append((px, py, a, r["visited"], len(r["seen"]),
                             len(r["faces"]), None, ref))
    return rows


def measure_state(rig, ovh, row, us=1500000):
    px, py, a = row[0], row[1], row[2]
    # 'setup' is march_setup, the real per-frame floor.  proj_setup (E_SETUP)
    # is a dead stub -- frame_geom does not call it any more.
    return dict(total=rig.bench(E_ALL, px, py, a, us) - ovh,
                march=rig.bench(E_MARCH, px, py, a, us) - ovh,
                proj=rig.bench(E_ALL, px, py, a, us)
                - rig.bench(E_MARCH, px, py, a, us),
                setup=rig.bench(E_MSETUP, px, py, a, us) - ovh)


def report(rig, grid, solid, rows, ovh, tag=""):
    print(f"\n=== named views {tag} ===")
    print("%-30s %6s %5s %5s %6s %9s %9s %9s %9s" %
          ("state", "refcel", "pop", "cand", "quads", "march us",
           "msetup us", "faces us", "TOTAL us"))
    named = []
    for want in ("corridor", "junction", "open room", "dead end"):
        sel = [r for r in rows if cell_class(grid, r[0] >> 8, r[1] >> 8) == want]
        if not sel:
            print("%-30s  (this maze has no cell of that class)" % want)
            continue
        sel.sort(key=lambda r: r[5])
        named.append((want + " (median)", sel[len(sel) // 2]))
        named.append((want + " (worst)", sel[-1]))
    byc = sorted(rows, key=lambda r: r[5])
    named.append(("MOST FACES in the maze", byc[-1]))
    byr = sorted(rows, key=lambda r: r[7])
    named.append(("MOST MARCHED CELLS", byr[-1]))
    named.append(("median over all states", byc[len(byc) // 2]))

    out = []
    for label, r in named:
        m = measure_state(rig, ovh, r)
        px, py, a = r[0], r[1], r[2]
        print("%-30s %6d %5d %5d %6d %9.0f %9.0f %9.0f %9.0f" %
              (f"{label} ({px>>8},{py>>8})a{a}", r[7], r[3], r[5], r[6] or 0,
               m["march"], m["setup"], m["proj"], m["total"]))
        out.append(dict(label=label, px=px, py=py, a=a, ref_cells=r[7],
                        popped=r[3], cand=r[5], quads=r[6], **m))
    return out


def regress(data):
    """total_us ~ A + B*ref_cells + C*candidate_faces, least squares."""
    import statistics
    n = len(data)
    X = [[1.0, float(d["ref_cells"]), float(d["cand"])] for d in data]
    y = [d["total"] for d in data]
    A = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(3)]
         for i in range(3)]
    b = [sum(X[k][i] * y[k] for k in range(n)) for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        b[i], b[p] = b[p], b[i]
        for r in range(i + 1, 3):
            f = A[r][i] / A[i][i]
            for c in range(i, 3):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    co = [0.0] * 3
    for i in (2, 1, 0):
        co[i] = (b[i] - sum(A[i][j] * co[j] for j in range(i + 1, 3))) / A[i][i]
    res = [y[k] - sum(X[k][i] * co[i] for i in range(3)) for k in range(n)]
    ybar = statistics.mean(y)
    r2 = 1 - sum(r * r for r in res) / sum((v - ybar) ** 2 for v in y)
    rms = (sum(r * r for r in res) / n) ** 0.5
    return co, rms, r2, ybar


def run(nsample=120, seed=2718):
    import json
    grid, _, _ = world.load_maze()
    solid = mm.solid_from_grid(grid)
    rig = Rig()
    calib = calibrate(rig)

    # NB the window: (counter) is SIXTEEN BITS and the empty control loop
    # is 15 us, so it wraps after 0.98 s.  Benched at the 1.5 s default it
    # reports 43.5 us instead of 14.9 us and that inflated overhead is then
    # subtracted from every measurement below.  (The figures quoted in
    # kernel.asm were taken with the bug present, so they are each ~29 us
    # LOW -- 2% of the 1401 us frame floor, well inside the 1164 us RMS of
    # the fit, but the sign is worth knowing.)
    ovh = rig.bench(E_EMPTY, 0x0A80, 0x0D80, 0, us=500000)
    print(f"\nloop overhead per iteration: {ovh:.2f} us  (subtracted "
          f"everywhere below)")

    rows = survey(grid, solid)
    print(f"surveyed {len(rows)} player states "
          f"({len(rows)//(72*len(VP_OFFS))} floor cells x "
          f"{len(VP_OFFS)} sub-offsets x 72 headings) with the model")

    # fill in the projected-quad counts only where we need them
    def with_quads(r):
        if r[6] is None:
            q, _ = model_frame(solid, r[0], r[1], r[2])
            r = r[:6] + (len(q),) + r[7:]
        return r

    rnd = random.Random(seed)
    byc = sorted(rows, key=lambda r: r[5])
    byr = sorted(rows, key=lambda r: r[7])
    named_rows = set()
    pick = [with_quads(r) for r in rnd.sample(rows, nsample)]
    pick += [with_quads(r) for r in (byc[-1], byc[-2], byc[-3], byc[0],
                                     byr[-1], byr[-2], byc[len(byc) // 2])]
    rows2 = [with_quads(r) for r in rows]

    named = report(rig, grid, solid, rows2, ovh)

    print(f"\n=== regression over {len(pick)} sampled states ===")
    data = []
    for r in pick:
        m = rig.bench(E_ALL, r[0], r[1], r[2], us=1200000) - ovh
        data.append(dict(px=r[0], py=r[1], a=r[2], popped=r[3], seen=r[4],
                         cand=r[5], quads=r[6], ref_cells=r[7], total=m))
    co, rms, r2, ybar = regress(data)
    print("  total_us = %.0f  +  %.1f * ref_cells  +  %.1f * cand_faces"
          % tuple(co))
    print("  R^2 %.4f, RMS residual %.0f us, mean total %.0f us"
          % (r2, rms, ybar))

    tot = sum(d["total"] for d in data)
    print("  crude ratios: %.0f us per ref-marched cell, %.0f us per "
          "candidate face, %.0f us per drawn quad"
          % (tot / sum(d["ref_cells"] for d in data),
             tot / sum(d["cand"] for d in data),
             tot / max(1, sum(d["quads"] for d in data))))
    print("  candidate faces per drawn quad: %.3f"
          % (sum(d["cand"] for d in data) / max(1, sum(d["quads"] for d in data))))

    # distribution over the WHOLE reachable state space, predicted by the fit
    pred = sorted(co[0] + co[1] * r[7] + co[2] * r[5] for r in rows2)
    def pc(p):
        return pred[min(len(pred) - 1, int(p * len(pred)))]
    print("\n=== predicted geometry-only cost over all %d states ===" % len(pred))
    for p, lbl in ((0.5, "median"), (0.9, "p90"), (0.99, "p99"), (1.0, "max")):
        print("  %-8s %8.0f us = %5.2f ms" % (lbl, pc(p), pc(p) / 1000.0))

    out = dict(calibration_100nop=calib, overhead=ovh, coef=co, rms=rms,
               r2=r2, named=named, sample=data,
               all_states=[dict(px=r[0], py=r[1], a=r[2], popped=r[3],
                                seen=r[4], cand=r[5], quads=r[6],
                                ref_cells=r[7]) for r in rows2])
    open(os.path.join(BUILD, "kernel_timing.json"), "w").write(
        json.dumps(out, indent=1))
    print("\n-> engine2/build/kernel_timing.json")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        raise SystemExit(
            1 if verify(int(sys.argv[2]) if len(sys.argv) > 2 else 200) else 0)
    else:
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 120)
