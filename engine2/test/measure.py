#!/usr/bin/env python3
"""Unit-test AND time engine2's math primitives on the cycle-accurate emulator.

Correctness: batch drivers in tst_math.asm run N records through a routine
and the results are compared against Python (exact integer arithmetic for the
multiplies, exact floats for the reciprocal and the rotation).

Timing: each routine has a loop that sets up its arguments, does
"call TRAMP", and bumps a 24-bit counter.  TRAMP is a 3-byte JP the driver
points either at the routine or at a bare RET, so the loop, the argument
setup and the counter all cancel and the difference is the routine body.
Reported us/call = body + 8 (the CALL and RET the real caller pays).
"""

import math
import os
import random
import struct
import subprocess
import sys

sys.path.insert(0, os.path.expanduser("~/cpcemu"))
from cpc import CPC                                            # noqa: E402

# The Python reference IS the ground truth: pull to_view/basis straight out
# of prototype/free-angle/free.py rather than re-deriving them here.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "tools"))
sys.path.insert(0, os.path.join(_REPO, "prototype", "free-angle"))
import free                                                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "..", "build", "e2")

BASE = 0x4000
BT_IN, BT_OUT, BT_N, BT_DONE = 0x7000, 0x7800, 0x7E00, 0x7E01
CTR, ARGS, TRAMP = 0x7E02, 0x7E08, 0x7E10

N_ANGLES = 72
TIME_FRAMES = 60


def build():
    os.makedirs(BUILD, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "tools",
                                                 "gen_math_tables.py"),
                    os.path.join(ROOT, "src", "mathdata.inc")],
                   check=True, capture_output=True)
    r = subprocess.run(["rasm", "test/tst_math.asm",
                        "-o", os.path.join(BUILD, "tstmath"),
                        "-s", "-os", os.path.join(BUILD, "tstmath.sym"),
                        "-I", "src", "-I", "test"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("assembly failed")
    sym = {}
    for line in open(os.path.join(BUILD, "tstmath.sym")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0]] = int(p[1][1:], 16)
    blob = open(os.path.join(BUILD, "tstmath.bin"), "rb").read()
    return blob, sym


class Rig:
    def __init__(self, blob):
        self.blob = blob
        self.c = CPC()
        self.c.run_frames(60)               # let the firmware settle

    def reload(self):
        self.c.write_ram(BASE, self.blob)

    def batch(self, entry, records, rec_len, out_len, frames=40):
        self.reload()
        assert len(records) <= 250
        buf = b"".join(records)
        self.c.write_ram(BT_IN, buf)
        self.c.write_ram(BT_N, bytes([len(records)]))
        self.c.write_ram(BT_DONE, b"\x00")
        self.c.set_pc(entry)
        self.c.run_frames(frames)
        if self.c.read_ram(BT_DONE, 1)[0] != 0xAA:
            raise RuntimeError("batch at #%04X did not finish (pc=#%04X)"
                               % (entry, self.c.pc))
        raw = self.c.read_ram(BT_OUT, out_len * len(records))
        return [raw[i * out_len:(i + 1) * out_len] for i in range(len(records))]

    def time(self, entry, target, args, frames=TIME_FRAMES):
        self.reload()
        self.c.write_ram(ARGS, bytes(args) + b"\x00" * (8 - len(args)))
        self.c.write_ram(TRAMP, bytes([0xC3, target & 0xFF, target >> 8]))
        self.c.set_pc(entry)
        self.c.run_frames(frames)
        b = self.c.read_ram(CTR, 3)
        n = b[0] | (b[1] << 8) | (b[2] << 16)
        if n == 0:
            raise RuntimeError("counter 0 at #%04X" % entry)
        return frames * 20000.0 / n, n


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s24(v):
    return v - 0x1000000 if v & 0x800000 else v


def u16(v):
    return v & 0xFFFF


# --------------------------------------------------------------- tests ----

def test_mul8x8(rig, sym, entry="T_MUL8X8"):
    recs, exp = [], []
    vals = [0, 1, 2, 3, 127, 128, 129, 200, 254, 255]
    pairs = [(a, b) for a in vals for b in vals][:120]
    random.seed(1)
    while len(pairs) < 200:
        pairs.append((random.randrange(256), random.randrange(256)))
    for a, b in pairs:
        recs.append(bytes([a, b]))
        exp.append(a * b)
    out = rig.batch(sym[entry], recs, 2, 2, frames=10)
    bad = 0
    for (a, b), o, e in zip(pairs, out, exp):
        got = o[0] | (o[1] << 8)
        if got != e:
            bad += 1
            if bad < 6:
                print("   mul8x8 %d*%d -> %d expected %d" % (a, b, got, e))
    return bad, len(pairs)


def test_mul16x8u(rig, sym):
    vals16 = [0, 1, 255, 256, 257, 2048, 4096, 20000, 32767, 32768, 65535]
    vals8 = [0, 1, 127, 128, 129, 255]
    pairs = [(a, b) for a in vals16 for b in vals8]
    random.seed(2)
    while len(pairs) < 150:
        pairs.append((random.randrange(65536), random.randrange(256)))
    pairs = pairs[:200]
    recs = [struct.pack("<HB", a, b) for a, b in pairs]
    out = rig.batch(sym["T_MUL16X8U"], recs, 3, 3, frames=20)
    bad = 0
    for (a, b), o in zip(pairs, out):
        got = o[0] | (o[1] << 8) | (o[2] << 16)
        if got != a * b:
            bad += 1
            if bad < 6:
                print("   mul16x8u %d*%d -> %d expected %d" % (a, b, got, a * b))
    return bad, len(pairs)


def test_mul16x8s(rig, sym):
    vals16 = [0, 1, -1, 255, -255, 256, -256, 2048, -2048, 8191, -8192,
              32767, -32768]
    vals8 = [0, 1, -1, 64, -64, 127, -128]
    pairs = [(a, b) for a in vals16 for b in vals8]
    random.seed(3)
    while len(pairs) < 150:
        pairs.append((random.randrange(-32768, 32768),
                      random.randrange(-128, 128)))
    pairs = pairs[:200]
    recs = [struct.pack("<hb", a, b) for a, b in pairs]
    out = rig.batch(sym["T_MUL16X8S"], recs, 3, 3, frames=20)
    bad = 0
    for (a, b), o in zip(pairs, out):
        got = s24(o[0] | (o[1] << 8) | (o[2] << 16))
        if got != a * b:
            bad += 1
            if bad < 6:
                print("   mul16x8s %d*%d -> %d expected %d" % (a, b, got, a * b))
    return bad, len(pairs)


def test_recip(rig, sym):
    """recip_zv(v) must equal 2^20/v, i.e. Q4.12 of 1/(v/256).

    EXHAUSTIVE over the whole legal input range: zv from the near plane
    (0.078 cells, v = 20) out to 32 cells (v = 8192), every single value.
    """
    lo, hi = 20, 8192
    # (worst rel error, offending case) for the design range and for all of it
    res = {"design": [0.0, None], "all": [0.0, None]}
    extra = [32767, 65535, 16384]
    vs_all = list(range(lo, hi + 1)) + extra
    for i in range(0, len(vs_all), 250):
        vs = vs_all[i:i + 250]
        recs = [struct.pack("<H", v) for v in vs]
        out = rig.batch(sym["T_RECIP"], recs, 2, 2, frames=10)
        for v, o in zip(vs, out):
            got = o[0] | (o[1] << 8)
            exact = 1048576.0 / v                   # 4096 / (v/256)
            rel = abs(got - exact) / exact
            keys = ["all"] + (["design"] if 20 <= v <= 2048 else [])
            for k in keys:
                if rel > res[k][0]:
                    res[k] = [rel, (v, got, exact)]
    return res, len(vs_all)


def to_view_float(dx, dy, ang):
    """free.to_view() of a point at offset (dx,dy) from the player."""
    fwd, rgt = free.basis(ang)
    return free.to_view(dx, dy, 0.0, 0.0, fwd, rgt)


def to_view_quant(dx, dy, ang):
    """Same, but with cos/sin already snapped to the k/128 table grid."""
    r = math.radians(ang * 5.0)
    c = round(math.cos(r) * 128.0) / 128.0
    s = round(math.sin(r) * 128.0) / 128.0
    return (dy * c - dx * s, dx * c + dy * s)


def test_rotate(rig, sym):
    cases = []
    edge = [0, 1, -1, 256, -256, 20, -20, 2048, -2048, 1792, -1792,
            8191, -8192]
    for dx in edge:
        for dy in (0, 256, -256, 2048, -2048):
            for ang in (0, 5, 18, 27, 36, 53, 71):
                cases.append((dx, dy, ang))
    random.seed(5)
    while len(cases) < 240:
        cases.append((random.randrange(-2048, 2049),
                      random.randrange(-2048, 2049),
                      random.randrange(72)))
    random.seed(15)
    while len(cases) < 1000:
        cases.append((random.randrange(-2048, 2049),
                      random.randrange(-2048, 2049),
                      random.randrange(72)))
    worst_f = worst_q = 0.0
    wf = wq = None
    out = []
    for i in range(0, len(cases), 250):
        recs = [struct.pack("<hhB", dx, dy, a) for dx, dy, a in cases[i:i + 250]]
        out += rig.batch(sym["T_ROTATE"], recs, 5, 4, frames=60)
    worst_d, wd = 0.0, None
    for (dx, dy, ang), o in zip(cases, out):
        xv = s16(o[0] | (o[1] << 8))
        zv = s16(o[2] | (o[3] << 8))
        fx, fz = to_view_float(dx, dy, ang)
        qx, qz = to_view_quant(dx, dy, ang)
        indesign = max(abs(dx), abs(dy)) <= 2048
        for got, ex, exq in ((xv, fx, qx), (zv, fz, qz)):
            if abs(got - ex) > worst_f:
                worst_f, wf = abs(got - ex), (dx, dy, ang, got, ex)
            if indesign and abs(got - ex) > worst_d:
                worst_d, wd = abs(got - ex), (dx, dy, ang, got, ex)
            if abs(got - exq) > worst_q:
                worst_q, wq = abs(got - exq), (dx, dy, ang, got, exq)
    return worst_f, wf, worst_q, wq, worst_d, wd, len(cases)


def test_lattice(rig, sym):
    cases = []
    for ang in (0, 5, 13, 18, 27, 36, 44, 53, 62, 71):
        for fx in (0, 1, 128, 255):
            for jx in (-8, -3, 0, 3, 8):
                cases.append((ang, fx, (fx * 7) & 255, jx, -jx))
    random.seed(6)
    while len(cases) < 200:
        cases.append((random.randrange(72), random.randrange(256),
                      random.randrange(256), random.randrange(-8, 9),
                      random.randrange(-8, 9)))
    for ang in range(72):
        for fx, fy in ((0, 0), (255, 255), (128, 64), (37, 211)):
            for jx, jy in ((-8, -8), (8, 8), (-8, 8), (8, -8), (7, 3),
                           (0, 8), (8, 0), (-3, 6)):
                cases.append((ang, fx, fy, jx, jy))
    out = []
    for i in range(0, len(cases), 250):
        recs = [bytes([a, fx, fy, jx + 8, jy + 8])
                for a, fx, fy, jx, jy in cases[i:i + 250]]
        out += rig.batch(sym["T_LATTICE"], recs, 5, 4, frames=60)
    worst = 0.0
    w = None
    worst_m, wm = 0.0, None
    for (ang, fx, fy, jx, jy), o in zip(cases, out):
        xv = s16(o[0] | (o[1] << 8))
        zv = s16(o[2] | (o[3] << 8))
        dx = jx * 256.0 - fx
        dy = jy * 256.0 - fy
        ex, ez = to_view_float(dx, dy, ang)
        inmarch = abs(jx) + abs(jy) <= 7          # the R_MAX = 6 L1 bound
        for got, e in ((xv, ex), (zv, ez)):
            if abs(got - e) > worst:
                worst, w = abs(got - e), (ang, fx, fy, jx, jy, got, e)
            if inmarch and abs(got - e) > worst_m:
                worst_m, wm = abs(got - e), (ang, fx, fy, jx, jy, got, e)
    return worst, w, worst_m, wm, len(cases)


# ------------------------------------------------------------- timing ----

def timings(rig, sym):
    rows = []

    def t(name, loop, target, args):
        full, nf = rig.time(sym[loop], sym[target], args)
        null, nn = rig.time(sym[loop], sym["RET_ONLY"], args)
        body = full - null
        rows.append((name, body + 8, full, null, nf))
        return body + 8

    t("[self-check] 10 NOPs, must be 18.00", "M_RECIP", "TEN_NOPS", [0, 1])
    t("mul8x8u        (A=200 C=173)", "M_MUL8X8", "MUL8X8U", [200, 173])
    t("mul8x8u        (A=50  C=200, a<b branch)", "M_MUL8X8", "MUL8X8U", [50, 200])
    t("mul8x8i        interleaved-word QS table", "M_MUL8X8", "MUL8X8I",
      [200, 173])
    t("mul16x8u       (DE=2000 C=128)", "M_MUL16X8", "MUL16X8U",
      [0xD0, 0x07, 128])
    t("mul16x8s       (DE=-2000 C=-99)", "M_MUL16X8", "MUL16X8S",
      [0x30, 0xF8, 0x9D])
    t("recip_zv       (zv=1.0, v=256)", "M_RECIP", "RECIP_ZV", [0x00, 0x01])
    t("recip_zv       (zv=0.08, v=20)", "M_RECIP", "RECIP_ZV", [20, 0])
    t("recip_zv       (zv=6.0, v=1536)", "M_RECIP", "RECIP_ZV", [0x00, 0x06])
    t("recip_zv       (zv=2.03, v=520)", "M_RECIP", "RECIP_ZV", [0x08, 0x02])
    t("rotate_point   (dx=1000 dy=-700 a=13)", "M_ROTATE", "ROTATE_POINT",
      [0xE8, 0x03, 0x44, 0xFD, 13])
    t("rotate_point   (dx=+2048 dy=+2048 a=0)", "M_ROTATE", "ROTATE_POINT",
      [0x00, 0x08, 0x00, 0x08, 0])
    t("rotate_point   (dx=-2048 dy=-2048 a=54)", "M_ROTATE", "ROTATE_POINT",
      [0x00, 0xF8, 0x00, 0xF8, 54])
    t("rot_setup      (per frame)", "M_ROTSETUP", "ROT_SETUP",
      [0x40, 0xC0, 0, 0, 13])
    t("rot_lattice    (per endpoint)", "M_LATTICE", "ROT_LATTICE",
      [0x40, 0xC0, 3, 12, 13])
    return rows


def main():
    blob, sym = build()
    rig = Rig(blob)
    print("=== correctness (emulator vs Python) ===")
    bad, n = test_mul8x8(rig, sym)
    print("mul8x8u      : %d/%d exact" % (n - bad, n))
    bad, n = test_mul8x8(rig, sym, "T_MUL8X8I")
    print("mul8x8i      : %d/%d exact  (interleaved-table variant)" % (n - bad, n))
    bad, n = test_mul16x8u(rig, sym)
    print("mul16x8u     : %d/%d exact" % (n - bad, n))
    bad, n = test_mul16x8s(rig, sym)
    print("mul16x8s     : %d/%d exact" % (n - bad, n))
    res, n = test_recip(rig, sym)
    for k, lab in (("design", "zv 0.078..8 cells"), ("all", "zv 0.078..32")):
        rel, w = res[k]
        v, got, ex = w
        print("recip_zv     : %-18s worst rel err %.4f%%  (v=%d -> %d, "
              "exact %.2f)" % (lab, rel * 100, v, got, ex))
    print("               %d inputs tested, EVERY integer v in 20..8192" % n)
    wf, f, wq, q, wd, d, n = test_rotate(rig, sym)
    print("rotate_point : %d cases" % n)
    print("               |dx|,|dy| <= 8 cells : worst err vs exact float "
          "%.2f LSB = %.4f cells  %s" % (wd, wd / 256.0, d))
    print("               incl. 32-cell inputs : worst err vs exact float "
          "%.2f LSB = %.4f cells  %s" % (wf, wf / 256.0, f))
    print("               vs 1/128-quantised trig (pure asm error) "
          "%.2f LSB  %s" % (wq, q))
    wl, w, wm, m, n = test_lattice(rig, sym)
    print("rot_lattice  : %d cases (all 72 headings)" % n)
    print("               |jx|+|jy| <= 7 (the march bound) : worst "
          "%.2f LSB = %.4f cells  %s" % (wm, wm / 256.0, m))
    print("               full |jx|,|jy| <= 8 corner       : worst "
          "%.2f LSB = %.4f cells  %s" % (wl, wl / 256.0, w))

    print()
    print("=== timing (CPC us, gate-array stretched) ===")
    print("%-40s %9s %9s %9s %10s" % ("routine", "us/call", "loop+rt",
                                      "loop", "iters"))
    for name, us, full, null, it in timings(rig, sym):
        print("%-40s %9.2f %9.2f %9.2f %10d" % (name, us, full, null, it))


if __name__ == "__main__":
    main()
