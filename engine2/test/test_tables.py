"""Run engine2/test/tabtest.asm on a cycle-accurate CPC 6128 and check the
bank-4 tables against the Python that generated them.

Two independent levels of checking:

  LAYOUT  the Z80 copies raw slices out of bank 4 and we compare them byte
          for byte with gentab's own output -- catches wrong addresses,
          wrong alignment, wrong endianness.

  CONTRACT the Z80 *uses* the tables exactly as the docstring in gentab.py
          says the kernel must -- quarter-square multiply, 16x16 built on
          it, the PROJ/HTAB projection and the RCP divide -- and we compare
          the answers with the Python reference AND with float ground
          truth.  This is what actually proves the tables are usable.

Finally the routine is timed with the counter method (iterations per
emulated frame, empty loop subtracted), which gives a real microsecond
figure for one projected endpoint.

    python3 engine2/test/test_tables.py
"""

import math
import os
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)

sys.path.insert(0, os.path.expanduser("~/cpcemu"))
sys.path.insert(0, os.path.join(_E2, "tools"))

import ctypes                                               # noqa: E402
import cpc as cpcmod                                        # noqa: E402
from cpc import CPC                                         # noqa: E402
import gentab                                               # noqa: E402

CODE_ORG = 0x8000
PROBES, PROBERES = 0x9000, 0x9200
QSN, QSCASE, QSRES = 0x9400, 0x9401, 0x9500
PJN, PJCASE, PJRES = 0x9600, 0x9601, 0x9700
RDN, RDCASE, RDRES = 0x9800, 0x9801, 0x9900
DONE, TVEC, TXV, TZ, ITER = 0x9A00, 0x9A02, 0x9A04, 0x9A06, 0x9A08
PFRES = 0x9B00

TIME_FRAMES = 25


# --------------------------------------------------------------- build ----

def assemble():
    out = os.path.join(_E2, "build", "tabtest")
    sym = out + ".sym"
    r = subprocess.run(["rasm", "tabtest.asm", "-o", out, "-I",
                        os.path.join(_E2, "src"), "-s", "-os", sym],
                       cwd=_HERE, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr, file=sys.stderr)
        raise SystemExit("rasm failed")
    with open(out + ".bin", "rb") as fh:
        code = fh.read()
    syms = {}
    for line in open(sym):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            syms[p[0].upper()] = int(p[1][1:], 16)
    return code, syms


# ---------------------------------------------------------- test cases ----

def probe_list(layout):
    """[(name, addr, length)] -- raw slices to read back out of bank 4."""
    p = []

    def add(name, tab, first, n):
        addr, w, cnt = layout[tab]
        assert first + n <= cnt, f"{tab}[{first}..] out of range"
        p.append((f"{tab}[{first}:{first + n}]", addr + first * w, n * w))

    add("qsq_lo", "QSQ", 0, 8)
    add("qsq_hi", "QSQ", 504, 8)
    add("htab_near", "HTAB", 32, 4)
    add("htab_one", "HTAB", 256, 4)
    add("htab_far", "HTAB", 2044, 4)
    add("proj_near", "PROJ", 32, 4)
    add("proj_one", "PROJ", 256, 4)
    add("proj_far", "PROJ", 2044, 4)
    add("bitlen_lo", "BITLEN", 0, 16)
    add("bitlen_hi", "BITLEN", 240, 16)
    add("projn", "PROJN", 0, 8)
    add("projn_end", "PROJN", 57, 8)
    add("htn", "HTN", 0, 8)
    add("htn_end", "HTN", 57, 8)
    add("basis_0", "BASIS", 0, 4)
    add("basis_18", "BASIS", 72, 4)
    add("basis_71", "BASIS", 284, 4)
    add("rcp_lo", "RCP", 0, 8)
    add("rcp_hi", "RCP", 248, 8)
    add("linetab_0", "LINETAB", 0, 9)
    add("linetab_mid", "LINETAB", 96, 8)
    add("linetab_end", "LINETAB", 192, 8)
    add("pushent", "PUSHENT", 0, gentab.VP_BW + 1)
    add("m0solid", "M0SOLID", 0, 16)
    add("ramptab", "RAMPTAB", 0, 24)
    add("bandpen", "BANDPEN", 0, 4)
    return p


QS_CASES = [(0, 0), (1, 1), (1, 0), (255, 255), (255, 0), (0, 255),
            (128, 128), (127, 129), (17, 23), (200, 199), (99, 7),
            (13, 240), (255, 1), (2, 254), (64, 64), (250, 250)]


def proj_cases():
    """(xv_q10, z_q10) spread over the legal frustum domain."""
    out = []
    zs = [0.125, 0.35, 0.5, 1.0, 2.0, 3.0, 5.5, 7.0]
    ks = [-1.0, -0.6, -0.25, 0.0, 0.25, 0.6, 1.0]
    for z in zs:
        for k in ks:
            xv = gentab.KHALF * z * k
            out.append((int(round(xv * gentab.VQ_ONE)),
                        int(round(z * gentab.VQ_ONE))))
    return out


RD_CASES = [(1000, 1), (1000, 2), (1000, 3), (1000, 7), (12345, 5),
            (32000, 96), (65535, 255), (65535, 1), (0, 3), (777, 13),
            (4096, 16), (60000, 200)]


# ------------------------------------------------------------ reference ---

def ref_proj(xv_q10, z_q10, htab, proj):
    """The contract, evaluated in Python integers exactly as the asm does."""
    zq = (z_q10 + 2) >> 2
    zq = max(gentab.ZNEAR_Q8, min(gentab.ZQ_N - 1, zq))
    hs = htab[zq]
    p = proj[zq]
    if xv_q10 >= 0:
        off = (xv_q10 * p) >> 10
    else:
        off = -(((-xv_q10) * p) >> 10)
    return (int(gentab.CX) * 16 + off) & 0xFFFF, hs


def s16(v):
    return v - 0x10000 if v >= 0x8000 else v


# ----------------------------------------------------------------- run ----

def poke_bank4(c, blob):
    p = cpcmod._lib.cpcemu_ram_ptr(c._h, 4)
    if not p:
        raise SystemExit("emulator has no bank 4")
    ctypes.memmove(p, blob, len(blob))


def load(c, code, probes, tvec, txv, tz):
    plist = b"".join(struct.pack("<HB", a, n) for _, a, n in probes) + b"\0\0"
    c.write_ram(CODE_ORG, code)
    c.write_ram(PROBES, plist)
    c.write_ram(QSN, bytes([len(QS_CASES)]))
    c.write_ram(QSCASE, bytes(v for ab in QS_CASES for v in ab))
    pj = proj_cases()
    c.write_ram(PJN, bytes([len(pj)]))
    c.write_ram(PJCASE, b"".join(struct.pack("<hH", x, z) for x, z in pj))
    c.write_ram(RDN, bytes([len(RD_CASES)]))
    c.write_ram(RDCASE, b"".join(struct.pack("<HB", v, n)
                                 for v, n in RD_CASES))
    c.write_ram(DONE, bytes([0]))
    c.write_ram(TVEC, struct.pack("<H", tvec))
    c.write_ram(TXV, struct.pack("<h", txv))
    c.write_ram(TZ, struct.pack("<H", tz))
    c.set_pc(CODE_ORG)
    return pj


def main():
    blob, layout, values = gentab.build()
    worst, bad = gentab.self_check(values)
    if bad:
        for b in bad:
            print("python self-check FAIL:", b)
        return 1

    code, syms = assemble()
    probes = probe_list(layout)
    pj = proj_cases()
    TXV_V = int(round(0.4 * gentab.VQ_ONE))
    TZ_V = int(round(2.5 * gentab.VQ_ONE))

    c = CPC()
    c.run_frames(120)                   # let the firmware finish booting
    poke_bank4(c, blob)
    load(c, code, probes, syms["T_PROJ"], TXV_V, TZ_V)
    c.run_frames(10)

    fails = []
    if c.read_ram(DONE, 1)[0] != 0xA5:
        print("Z80 test did not reach the done flag -- aborting")
        return 1

    # ---- LAYOUT ------------------------------------------------------
    got = c.read_ram(PROBERES, sum(n for _, _, n in probes))
    off = 0
    nprobe = 0
    for name, addr, n in probes:
        want = blob[addr - gentab.BANK_BASE: addr - gentab.BANK_BASE + n]
        if got[off:off + n] != want:
            fails.append(f"LAYOUT {name} @#{addr:04X}: "
                         f"z80 {got[off:off + n].hex()} != {want.hex()}")
        off += n
        nprobe += 1
    print(f"LAYOUT   {nprobe} raw slices, {off} bytes read back from bank 4"
          f" -> {'OK' if not fails else 'FAIL'}")

    # ---- QSQ multiply ------------------------------------------------
    raw = c.read_ram(QSRES, 2 * len(QS_CASES))
    qbad = 0
    for i, (a, b) in enumerate(QS_CASES):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)
        if v != a * b:
            qbad += 1
            fails.append(f"QSQ {a}*{b}: z80 {v} != {a * b}")
    print(f"QSQ      {len(QS_CASES)} products via QSQ[a+b]-QSQ[|a-b|]"
          f" -> {'all exact' if not qbad else f'{qbad} WRONG'}")

    # ---- projection --------------------------------------------------
    raw = c.read_ram(PJRES, 4 * len(pj))
    err_hbu, err_lines = 0.0, 0.0
    pbad = 0
    for i, (xv, z) in enumerate(pj):
        xs = raw[4 * i] | (raw[4 * i + 1] << 8)
        hs = raw[4 * i + 2] | (raw[4 * i + 3] << 8)
        wxs, whs = ref_proj(xv, z, values["HTAB"], values["PROJ"])
        if (xs, hs) != (wxs, whs):
            pbad += 1
            if pbad <= 6:
                fails.append(f"PROJ xv={xv} z={z}: z80 ({s16(xs)},{hs}) "
                             f"!= py ({s16(wxs)},{whs})")
        # float ground truth
        zc, xvc = z / gentab.VQ_ONE, xv / gentab.VQ_ONE
        fxs = gentab.CX + xvc * gentab.FOCAL_H / zc
        fhs = 0.5 * gentab.FOCAL_V / zc
        err_hbu = max(err_hbu, abs(s16(xs) / 16.0 - fxs))
        err_lines = max(err_lines, abs(min(hs, 40000) / 16.0 - fhs))
    print(f"PROJ     {len(pj)} endpoints projected on the Z80"
          f" -> {'bit-exact vs Python' if not pbad else f'{pbad} MISMATCH'}")
    print(f"         worst error vs float truth: {err_hbu:.3f} half-byte"
          f" units ({err_hbu / 2:.3f} byte), {err_lines:.3f} scanline")

    # ---- projection, normalised (PROJN/HTN) route --------------------
    raw = c.read_ram(PFRES, 4 * len(pj))
    ferr_hbu, ferr_lines, fbad = 0.0, 0.0, 0
    for i, (xv, z) in enumerate(pj):
        xs = raw[4 * i] | (raw[4 * i + 1] << 8)
        hs = raw[4 * i + 2] | (raw[4 * i + 3] << 8)
        wxs, whs = gentab.fast_proj(xv, z, values["PROJN"], values["HTN"])
        if (xs, hs) != (wxs & 0xFFFF, whs):
            fbad += 1
            if fbad <= 6:
                fails.append(f"PROJN xv={xv} z={z}: z80 ({s16(xs)},{hs}) "
                             f"!= py ({wxs},{whs})")
        zc, xvc = z / gentab.VQ_ONE, xv / gentab.VQ_ONE
        ferr_hbu = max(ferr_hbu,
                       abs(s16(xs) / 16.0
                           - (gentab.CX + xvc * gentab.FOCAL_H / zc)))
        ferr_lines = max(ferr_lines,
                         abs(hs / 16.0 - 0.5 * gentab.FOCAL_V / zc))
    print(f"PROJN    {len(pj)} endpoints via the one-multiply route"
          f" -> {'bit-exact vs Python' if not fbad else f'{fbad} MISMATCH'}")
    print(f"         worst error vs float truth: {ferr_hbu:.3f} half-byte"
          f" units ({ferr_hbu / 2:.3f} byte), {ferr_lines:.3f} scanline")

    # ---- reciprocal divide -------------------------------------------
    raw = c.read_ram(RDRES, 2 * len(RD_CASES))
    rbad, rworst = 0, 0
    for i, (v, n) in enumerate(RD_CASES):
        q = raw[2 * i] | (raw[2 * i + 1] << 8)
        want = (v * values["RCP"][n]) >> 15
        if q != want:
            rbad += 1
            fails.append(f"RCP {v}/{n}: z80 {q} != py {want}")
        rworst = max(rworst, abs(q - v // n))
    print(f"RCP      {len(RD_CASES)} divides"
          f" -> {'bit-exact vs Python' if not rbad else f'{rbad} MISMATCH'},"
          f" worst off-by {rworst} from exact integer division")

    # ---- timing ------------------------------------------------------
    # Counter method: N emulated frames with interrupts off, iterations
    # read out of RAM, empty loop subtracted.
    print()
    routines = [("empty loop (baseline)", "T_NOP"),
                ("qsmul   8x8 -> 16 via QSQ", "T_QSMUL"),
                ("mul16  16x16 -> 32 (4 x qsmul)", "T_MUL16"),
                ("rcpdiv 16/8 via RCP + mul16", "T_RCPDIV"),
                ("project  endpoint via PROJ/HTAB", "T_PROJ"),
                ("project_fast    via PROJN/HTN", "T_PROJFAST")]
    us = {}
    for label, name in routines:
        c2 = CPC()
        c2.run_frames(120)
        poke_bank4(c2, blob)
        load(c2, code, probes, syms[name], TXV_V, TZ_V)
        c2.run_frames(10)
        a = struct.unpack("<H", c2.read_ram(ITER, 2))[0]
        c2.run_frames(TIME_FRAMES)
        b = struct.unpack("<H", c2.read_ram(ITER, 2))[0]
        n = (b - a) & 0xFFFF
        t = TIME_FRAMES * 20000.0 / n if n else float("nan")
        us[name] = t
        net = "" if name == "T_NOP" else f"   net {t - us['T_NOP']:6.1f} us"
        print(f"TIMING   {label:32s} {t:6.1f} us/pass"
              f"  ({n:6d} iters){net}")
    proj_us = us["T_PROJ"] - us["T_NOP"]
    fast_us = us["T_PROJFAST"] - us["T_NOP"]
    print()
    print(f"         PROJ/HTAB  {proj_us:5.0f} us/endpoint"
          f"  ->  {2 * proj_us:5.0f} us/face in projection alone")
    print(f"         PROJN/HTN  {fast_us:5.0f} us/endpoint"
          f"  ->  {2 * fast_us:5.0f} us/face in projection alone")

    print()
    print(f"BANK 4   {len(blob)} bytes used of 16384,"
          f" {16384 - len(blob)} free ({100.0 * len(blob) / 16384:.1f}% full)")

    if fails:
        print(f"\n{len(fails)} FAILURES:")
        for f in fails[:40]:
            print("  ", f)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
