"""Verify and MEASURE engine2/src/rastcol.asm on a cycle-accurate CPC 6128.

    python3 engine2/tools/emu_rcol.py verify    bit-exact vs colmodel.py
    python3 engine2/tools/emu_rcol.py time      us per frame's worth of quads

VERIFICATION IS DONE ON THE SCREEN, NOT ON A COLUMN LIST, which is the
same rule engine2/tools/emu_rast.py holds the span renderer to: the driver
clears all 16K of the &C000 buffer, pokes quad records into QUADS, runs
raster_colframe, and compares the whole 16K against what colmodel.py says
should be there.  So it checks the perspective u, the vertical step, the
texture bytes, the screen addressing, the front-to-back occlusion and the
absence of stray writes outside the viewport, all at once.

TWO BANKS, AND cpc.write_ram CANNOT REACH THE SECOND ONE.  It writes the
BASE 64K -- banks 0 to 3 -- "ignoring ROM paging", and ignoring RAM paging
with it; that is why every other harness here can write "bank 4" at &4000
without ever selecting it, because what it is really writing is bank 1.
rastcol.asm's textures have to land in PHYSICAL bank 5, so this driver
goes through cpcemu_ram_ptr(5) instead.

Getting that wrong does not fail loudly, it fails PLAUSIBLY: the first
attempt here paged bank 5 from the Z80 and then called write_ram, which
put the textures in bank 1 on top of the tables, and rastcol.asm read a
zero out of RTHRESH and hung in its normalise loop.  A harness that
addresses the wrong memory reports a defect in the code it is testing --
which is the same failure engine2/tools/addrs.py exists to prevent, one
bank further out.
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

import addrs                                                # noqa: E402
import colmodel                                             # noqa: E402
import emu_rast                                             # noqa: E402
import gentab                                               # noqa: E402
import gentex                                               # noqa: E402
import rastermodel as rm                                    # noqa: E402
import ctypes                                               # noqa: E402
import cpc as _cpc                                          # noqa: E402
from cpc import CPC                                         # noqa: E402


def write_bank(c, bank, data):
    """Write a PHYSICAL 16K RAM bank, whatever is currently paged.

    cpc.write_ram is address-space based and only reaches banks 0-3; the
    library exposes a pointer to each bank, which is the only way to put
    anything in bank 5 from outside the machine.  The disc does it the
    ordinary way, with OUT (&7Fxx),&C5 and a LOAD (engine2/src/disc3.bas).
    """
    p = _cpc._lib.cpcemu_ram_ptr(c._h, bank)
    if not p:
        raise RuntimeError(f"no ram_ptr for bank {bank}")
    ctypes.memmove(p, bytes(data), len(data))

BUILD = os.path.join(_E2, "build")

E_MANY, E_BENCH, E_EMPTY, E_HBENCH = 0x8000, 0x8004, 0x8008, 0x800C
PRO_US = 8.0        # the hookn countdown, harness only

QUADS = addrs.QUADS
QRECSZ = 8
FRONT = 0xC000
SCRSZ = 0x4000


def build(paced=False):
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "tab_test.bin"), "wb").write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    tex, _c = gentex.build()
    out = "tst_rcolp" if paced else "tst_rcol"
    r = subprocess.run(
        ["rasm", "tst_rcol.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/" + out, "-s", "-os", "../build/" + out]
        + (["-DPACED=1"] if paced else []),
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
    return blob, tex, code, sym


class Rig:
    def __init__(self, paced=False):
        self.tables, self.tex, self.code, self.sym = build(paced)
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(0x8000, self.code)
        # BOTH banks go through ram_ptr, and bank 4 has to as well: the
        # harness runs in RAM config 4 (which is what main3.asm:start
        # leaves the machine in and what raster_colframe restores), so
        # &4000 is PHYSICAL bank 4 and write_ram would put the tables in
        # bank 1 where nothing would ever read them.
        write_bank(self.c, 4, self.tables)
        write_bank(self.c, 5, self.tex)
        self.cfg = rm.cfg()
        self.blank = bytes(SCRSZ)
        self.pw = colmodel.wall_pages()
        self.pd = colmodel.door_pages()

    def s(self, n):
        return self.sym[n.upper()]

    def poke_quads(self, quads):
        raw = b"".join(struct.pack("<BBHHBB", *q) for q in quads)
        self.c.write_ram(QUADS, raw)
        self.c.poke(self.s("FG_NQUAD"), len(quads))

    def run_once(self, quads):
        self.c.write_ram(FRONT, self.blank)
        self.poke_quads(quads)
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(E_MANY)
        for _ in range(400):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                break
        else:
            raise RuntimeError("raster_colframe never finished")
        return self.c.read_ram(FRONT, SCRSZ)

    def expect(self, quads):
        scr, st = colmodel.render(quads, self.cfg, self.pw, self.pd)
        return scr, st

    def bench(self, entry, quads, us=800000):
        self.poke_quads(quads)
        self.c.set_pc(entry)
        self.c.run_us(60000)
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        if not 0 < n < 60000:
            raise RuntimeError(f"counter unusable: {n}")
        return (ticks / 4.0) / n


def diff_report(got, want, c, n=8):
    out = []
    for i in range(SCRSZ):
        if got[i] != want[i]:
            row = (i // 0x800) & 7
            rest = i & 0x7FF
            y = row + (rest // 80) * 8
            x = rest % 80
            out.append(f"    &{0xC000 + i:04X}  y={y:3d} byte={x:2d} "
                       f"(vp x={x - c.VP_BX:3d})  z80={got[i]:02X} "
                       f"model={want[i]:02X}")
            if len(out) >= n:
                break
    return out


def verify():
    rig = Rig()
    c = rig.cfg
    cases = emu_rast.synthetic(c)
    real = emu_rast.from_kernel()
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes at ({c.VP_BX},{c.VP_Y}), "
          f"horizon row {c.CYH}, {c.VP_BW // 2} column pairs")
    print(f"texture {colmodel.TEX_BW} byte columns x {colmodel.TEX_H} rows, "
          f"replicated x{colmodel.IDX_REP} into {colmodel.IDX_N}-byte pages")
    print(f"{len(cases)} hand-built quads + {len(real)} quads from real "
          f"march/project frames")

    bad = tested = 0
    for label, qq in cases:
        got = rig.run_once([qq])
        want, st = rig.expect([qq])
        tested += 1
        if got != want:
            bad += 1
            print(f"MISMATCH  {label}\n    quad {qq}")
            for line in diff_report(got, want, c):
                print(line)
        else:
            print(f"  ok  {label:46s} {st['pairs']:3d} bands / "
                  f"{st['painted']:4d} bytes")

    nb = 0
    for i, qq in enumerate(real):
        got = rig.run_once([qq])
        want, _ = rig.expect([qq])
        tested += 1
        if got != want:
            bad += 1
            nb += 1
            if nb < 6:
                print(f"MISMATCH  real quad #{i}: {qq}")
                for line in diff_report(got, want, c):
                    print(line)
    print(f"  {len(real)} real quads, one at a time: {len(real) - nb} exact")

    # WHOLE FRAMES ARE THE POINT HERE, not single quads: the occlusion
    # interval only does anything when faces overlap, so a renderer that
    # got it wrong would still pass every single-quad screen above.
    rnd = random.Random(4242)
    nbat = 0
    for _t in range(24):
        batch = [real[rnd.randrange(len(real))]
                 for _ in range(rnd.randrange(2, 9))]
        got = rig.run_once(batch)
        want, _ = rig.expect(batch)
        tested += 1
        if got != want:
            bad += 1
            nbat += 1
            if nbat < 3:
                print(f"MISMATCH  batch of {len(batch)}")
                for line in diff_report(got, want, c):
                    print(line)
    print(f"  24 painter batches of 2..8 quads: {24 - nbat} exact")

    print(f"\nVERIFY: {tested} screens compared byte for byte over all "
          f"{SCRSZ} bytes of the buffer, {tested - bad} exact, {bad} bad")
    return bad


def time_it(nstates=24):
    rig = Rig()
    c = rig.cfg
    ovh = rig.bench(E_EMPTY, [emu_rast.q(0, 0, 16, 0, 0, 1, c)])
    print(f"loop overhead per iteration: {ovh:.2f} us  (subtracted below)")
    import marchmodel as mm
    import projmodel as pmod
    import world
    grid, _, _ = world.load_maze()
    solid = mm.solid_from_grid(grid)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    rnd = random.Random(1337)
    rows = []
    for _ in range(nstates):
        x, y = rnd.choice(floors)
        px, py = (x << 8) | rnd.randrange(256), (y << 8) | rnd.randrange(256)
        a = rnd.randrange(72)
        r = mm.march(solid, px, py, a)
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
        _scr, st = rig.expect(qs)
        us = rig.bench(E_BENCH, qs, us=4000000) - ovh
        rows.append((len(qs), st["pairs"], st["painted"], us))
    rows.sort(key=lambda r: r[3])
    print("\n%-8s %6s %7s %7s %10s %10s" %
          ("pctile", "quads", "bands", "bytes", "us", "us/byte"))
    for p, lbl in ((0.0, "min"), (0.5, "median"), (0.9, "p90"), (1.0, "max")):
        r = rows[min(len(rows) - 1, int(p * len(rows)))]
        print("%-8s %6d %7d %7d %10.1f %10.3f" %
              (lbl, r[0], r[1], r[2], r[3], r[3] / max(1, r[2])))
    # the per-band and per-byte split, least squares, so main3.asm's
    # C_COLS and C_COLR can be checked against a measurement
    X = [[1.0, float(r[1]), float(r[2])] for r in rows]
    co, rms, r2, worst = emu_rast.lstsq(X, [r[3] for r in rows])
    print("\n  us = %.1f + %.2f*bands + %.4f*bytes   R^2 %.5f, RMS %.0f us"
          % (co[0], co[1], co[2], r2, rms))
    print("  -> per BAND %.1f us, per SCANLINE of a pair %.2f us"
          % (co[1], 2 * co[2]))
    return rows


# ---------------------------------------------------------------- atomic --
def charges_for(quads, c):
    import pacemodel as P
    return colmodel.charge(quads, c, P.C_CFRAME, P.C_CFACE, P.C_CSKIP,
                           P.C_COLS, P.C_CBAND, P.C_COLR, P.C_CEDGE)


def atomic(nstates=3, seed=1337):
    """EVERY INTERVAL, MEASURED -- not every frame.

    A charge can bound a whole frame and still under-charge one stretch of
    work inside it; that interval then runs past the vsync edge, the yield
    lands on the wrong side of it and the frame silently takes another
    period.  A per-frame check cannot see it BY CONSTRUCTION, which is why
    the 40-state one-sided check passed while the booted disc read
    [10, 11, 13] vsyncs against a budget of 10.

    So: cost_unit aborts on the k'th call, k is swept, and the DIFFERENCES
    between consecutive k are the intervals.  Each is compared with the
    charge the Z80 itself was about to take there, which also cross-checks
    colmodel.charge against the asm hook for hook.
    """
    import marchmodel as mm
    import projmodel as pmod
    import random
    import world
    rig = Rig(paced=True)
    c = rig.cfg
    ovh = rig.bench(E_EMPTY, [emu_rast.q(0, 0, 16, 0, 0, 1, c)])
    grid, _sx, _sy = world.load_maze()
    solid = mm.solid_from_grid(grid)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    rnd = random.Random(seed)
    worst = []
    for _s in range(nstates):
        x, y = rnd.choice(floors)
        px, py = (x << 8) | rnd.randrange(256), (y << 8) | rnd.randrange(256)
        a = rnd.randrange(72)
        r = mm.march(solid, px, py, a)
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
        ch = charges_for(qs, c)
        rig.poke_quads(qs)
        t, z80 = [], []
        for k in range(1, len(ch) + 2):
            rig.c.poke(rig.s("HOOKK"), min(k, 255))
            t.append(rig.bench(E_HBENCH, qs, us=2000000) - ovh)
            z80.append(struct.unpack(
                "<H", rig.c.read_ram(rig.s("HOOKBC"), 2))[0])
        iv = [t[0]] + [t[i] - t[i - 1] for i in range(1, len(t))]
        iv = [max(0.0, v - PRO_US) for v in iv]
        print(f"\nstate ({px:04X},{py:04X},{a})  {len(qs)} quads, "
              f"{len(ch)} hooks, whole render {t[-1]:.0f} us")
        bad, dis = [], 0
        for i, cc in enumerate(ch):
            meas = iv[i + 1] if i + 1 < len(iv) else 0.0
            if z80[i] != cc:
                dis += 1
                if dis < 4:
                    print(f"  hook {i:3d}: MODEL/ASM DISAGREE  "
                          f"model {cc} vs z80 {z80[i]}")
            if meas - cc > 0:
                bad.append((meas - cc, i, cc, meas))
        bad.sort(reverse=True)
        for d, i, cc, meas in bad[:4]:
            print(f"  hook {i:3d}: charged {cc:6d}  MEASURED {meas:8.0f}"
                  f"   UNDER by {d:7.0f} us")
        if not bad:
            print("  every interval inside its charge")
        worst += bad
    worst.sort(reverse=True)
    print(f"\n=== worst under-charge over {nstates} states ===")
    for d, i, cc, meas in worst[:6]:
        print(f"  charged {cc:6d}  measured {meas:8.0f}  under by {d:7.0f}")
    return worst


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        raise SystemExit(1 if verify() else 0)
    if cmd == "atomic":
        atomic(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
        raise SystemExit(0)
    time_it(int(sys.argv[2]) if len(sys.argv) > 2 else 24)