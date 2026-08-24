"""Verify and time engine2/src/march.asm ALONE on the headless CPC 6128.

  python3 engine2/tools/emu_march.py verify [n_states]
  python3 engine2/tools/emu_march.py time

march.asm is deliberately self-contained -- it reads nothing from the
&4000 table bank -- so this harness needs no tables and no projector.  The
verify compares, face by face, the VIEW-SPACE record the Z80 files against
marchmodel.py: the endpoints, the normal, the door flag and the painter
bucket, plus the visited / seen counters.

Timing method: a 16-bit counter is bumped once per call, the emulator runs
N frames with interrupts off, and us/call = N*20000/iterations.  The same
loop with the call removed measures the harness overhead, which is
subtracted.
"""

import os
import addrs
import random
import struct
import subprocess
import sys


def s8(v):
    return v - 256 if v > 127 else v

sys.path.insert(0, os.path.expanduser("~/cpcemu"))
from cpc import CPC                                            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "engine2", "src")
SCRATCH = "/tmp/claude-1000/-home-vasilhs-repos-AMazeCPC/fcbeb9fc-d334-405a-8425-6e73c56fed01/scratchpad/kernel"

E_ONCE, E_BENCH, E_SETUP, E_EMPTY = 0x4000, 0x4003, 0x4006, 0x4009
E_L1, E_FRAC = 0x400C, 0x400F
# BUCKET k IS THE PAGE BUCKHI+k, AND BOTH NUMBERS COME OUT OF march.asm.
# They were written down here as 0x26 / 16, and 0x26 stopped being true
# the day the whole working-RAM block moved up four pages to make room for
# the course-joint rasteriser (see march.asm's memory map).  This harness
# went on reading pages 0x27..0x2D while the march filed into 0x2B..0x31,
# so every face record came back as the zeros that happened to be there --
# `visited` and `seen` matched, the FACES did not, and it reported the
# march broken on 516 states out of 516 with the march perfectly fine.
# That is the exact failure engine2/tools/addrs.py exists to remove: it
# parses these out of the source, so never copy one.
BUCKHI, BUCKSZ = addrs.BUCKHI, addrs.BUCKSZ


def build():
    os.makedirs(SCRATCH, exist_ok=True)
    binf = os.path.join(SCRATCH, "tm.bin")
    symf = os.path.join(SCRATCH, "tm.sym")
    r = subprocess.run(["rasm", "test_march.asm", "-o",
                        os.path.join(SCRATCH, "tm"), "-s", "-os", symf],
                       cwd=SRC, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    # "NAME #ADDR B0 L"
    sym = {}
    for line in open(symf):
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("#"):
            sym[parts[0].upper()] = int(parts[1][1:], 16)
    # rasm does not emit EQUs; these are the fixed memory map from march.asm
    sym.update(TAB=addrs.FTAB, SOLID=addrs.SOLID, MARK=addrs.MARK,
               MSTACK=addrs.MSTKBOT, BUCKETS=addrs.BUCKETS)
    return open(binf, "rb").read(), sym


class Rig:
    def __init__(self):
        self.blob, self.sym = build()
        self.c = CPC()
        self.c.write_ram(0x4000, self.blob)

    def s(self, name):
        return self.sym[name.upper()]

    def set_state(self, px_fx, py_fx, a):
        self.c.write_ram(self.s("plr_x"), bytes([px_fx & 255, px_fx >> 8]))
        self.c.write_ram(self.s("plr_y"), bytes([py_fx & 255, py_fx >> 8]))
        self.c.write_ram(self.s("plr_a"), bytes([a]))

    def run_once(self, px_fx, py_fx, a):
        self.set_state(px_fx, py_fx, a)
        self.c.write_ram(self.s("done_flag"), b"\x00")
        self.c.set_pc(E_ONCE)
        self.c.run_frames(1)
        assert self.c.peek(self.s("done_flag")) == 0xEE, "march did not finish"
        return self.read_result()

    def read_result(self):
        tab = self.s("TAB")
        bptr = self.c.read_ram(tab + 0xE0, 8)
        out = []
        per_bucket = {}
        for k in range(7, 0, -1):
            n = bptr[k] // BUCKSZ
            per_bucket[k] = n
            if n:
                data = self.c.read_ram((BUCKHI + k) * 256, BUCKSZ * n)
                for i in range(n):
                    r = data[BUCKSZ * i:BUCKSZ * i + BUCKSZ]
                    xa, za, xb, zb = struct.unpack("<4h", r[:8])
                    out.append((r[8], bool(r[9]), k, xa, za, xb, zb,
                                s8(r[10]), s8(r[11])))
        return {
            "faces": out,
            "visited": self.c.peek(self.s("m_visited")),
            "seen": self.c.peek(self.s("m_seen")),
            "dropped": self.c.peek(self.s("m_dropped")),
            "per_bucket": per_bucket,
        }

    def bench(self, entry, px_fx, py_fx, a, frames=25):
        self.set_state(px_fx, py_fx, a)
        self.c.write_ram(self.s("iters"), b"\x00\x00")
        self.c.set_pc(entry)
        self.c.run_frames(frames)
        lo, hi = self.c.read_ram(self.s("iters"), 2)
        it = lo | (hi << 8)
        assert 0 < it < 65000, f"iteration counter wrapped or stalled: {it}"
        return frames * 20000.0 / it


# ---------------------------------------------------------------- verify ---
def verify(nstates):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.path.insert(0, os.path.join(ROOT, "engine2", "tools"))
    import world
    import marchmodel as M
    from projmodel import face_endpoints

    grid, sx, sy = world.load_maze()
    solid = M.solid_from_grid(grid)
    rig = Rig()

    rnd = random.Random(4242)
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    states = []
    for _ in range(nstates):
        x, y = rnd.choice(floors)
        states.append((((x << 8) | rnd.randrange(0, 256)),
                       ((y << 8) | rnd.randrange(0, 256)),
                       rnd.randrange(72)))
    # plus every heading from the start cell, and cell-boundary edge cases
    for a in range(72):
        states.append(((sx << 8) | 128, (sy << 8) | 128, a))
        states.append((sx << 8, sy << 8, a))
        states.append(((sx << 8) | 255, (sy << 8) | 255, a))

    bad = 0
    for px, py, a in states:
        got = rig.run_once(px, py, a)
        exp = M.march(solid, px, py, a)
        pcx, pcy = px >> 8, py >> 8
        gf = sorted(got["faces"])
        ef = []
        for (wx, wy, fd, door, k), v in zip(exp["faces"], exp["fviews"]):
            (ax, ay), _, _ = face_endpoints(wx, wy, fd)
            ef.append((fd, door, k) + v + (ax - pcx, ay - pcy))
        ef.sort()
        ok = (gf == ef
              and got["visited"] == exp["visited"]
              and got["seen"] == len(exp["seen"])
              and got["dropped"] == 0)
        # painter order: bucket keys must be non-increasing
        keys = [f[2] for f in got["faces"]]
        ordered = all(keys[i] >= keys[i + 1] for i in range(len(keys) - 1))
        if not ok or not ordered:
            bad += 1
            if bad <= 5:
                print(f"MISMATCH px={px/256.0:.4f} py={py/256.0:.4f} a={a}")
                print("   z80  visited=%d seen=%d faces=%s" %
                      (got["visited"], got["seen"], gf))
                print("   mdl  visited=%d seen=%d faces=%s" %
                      (exp["visited"], len(exp["seen"]), ef))
                print("   ordered:", ordered, "dropped:", got["dropped"])
    print(f"verified {len(states)} states against the model: "
          f"{len(states)-bad} exact, {bad} mismatched")
    return bad


# ------------------------------------------------------------------ time ---
def timing():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.path.insert(0, os.path.join(ROOT, "engine2", "tools"))
    import world
    import marchmodel as M

    grid, sx, sy = world.load_maze()
    solid = M.solid_from_grid(grid)
    rig = Rig()

    overhead = rig.bench(E_EMPTY, sx << 8, sy << 8, 0)
    print(f"harness overhead per iteration: {overhead:.2f} us  (subtracted)")
    print("piece costs:")
    for name, addr in (("march_setup", E_SETUP), ("build_l1", E_L1),
                       ("fracmul", E_FRAC)):
        print("   %-22s %8.1f us" %
              (name, rig.bench(addr, (7 << 8) | 137, (7 << 8) | 91, 17)
               - overhead))

    # Every floor cell at a non-aligned sub-position, every 3rd heading.
    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    cand = []
    for x, y in floors:
        for a in range(0, 72, 3):
            px, py = (x << 8) | 137, (y << 8) | 91
            r = M.march(solid, px, py, a)
            rq = M.march(solid, px, py, a, push_opaque=True)
            cand.append((rq["visited"], len(r["faces"]), len(r["seen"]),
                         px, py, a))
    cand.sort()

    print()
    print("us per FRAME, by how much the reference's march has to do")
    print("%-8s %9s %6s %6s %11s %10s %11s %9s" %
          ("pct", "ref cells", "faces", "seen", "total us", "setup us",
           "flood us", "us/cell"))
    rows = []
    for label, idx in (("min", 0), ("p25", len(cand) // 4),
                       ("median", len(cand) // 2),
                       ("p90", int(len(cand) * 0.9)),
                       ("p99", int(len(cand) * 0.99)), ("max", -1)):
        vis, nf, seen, px, py, a = cand[idx]
        t_all = rig.bench(E_BENCH, px, py, a) - overhead
        t_set = rig.bench(E_SETUP, px, py, a) - overhead
        print("%-8s %9d %6d %6d %11.1f %10.1f %11.1f %9.1f" %
              (label, vis, nf, seen, t_all, t_set, t_all - t_set,
               t_all / vis))
        rows.append((label, vis, nf, seen, t_all, t_set))

    tot = tots = 0.0
    n = 0
    totcells = 0
    for vis, nf, seen, px, py, a in cand[::29]:
        tot += rig.bench(E_BENCH, px, py, a, frames=12) - overhead
        n += 1
        totcells += vis
    print(f"\nmean over {n} sampled states: {tot/n:.1f} us per frame, "
          f"{tot/totcells:.1f} us per reference-marched cell")
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "verify":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        raise SystemExit(1 if verify(n) else 0)
    else:
        timing()
