"""MEASURE THE LARGEST ATOMIC UNIT of the rasteriser -- before and after.

    python3 engine2/tools/emu_atomic.py [nstates]

WHAT AN ATOMIC UNIT IS.  main3.asm paces the frame with a cost accumulator
that can only yield to vsync where something calls cost_unit.  The longest
stretch of work between two such calls is the ATOMIC UNIT, and it -- not
the total slack -- is what decides how many 19968 us periods a frame packs
into: greedy next-fit can waste most of one atomic unit at every bin
boundary.  Until raster.asm started yielding mid-quad the smallest thing
that called cost_unit inside the rasteriser was a WHOLE QUAD.

HOW IT IS MEASURED, not modelled.  There is no clock on the machine, so
this times PREFIXES instead: engine2/test/tst_rast.asm's stub accumulator
counts hooks and bails out of the k'th one (entry #8014, e_hbench), so a
bench loop can measure "raster_quad up to hook k".  The differences
between consecutive k ARE the intervals.  Two builds of the same harness:

    -DPACED=1 -DRQ_SPLIT=1   the mid-quad yield, hooks and all (AFTER).
                Its stub accumulator YIELDS ON EVERY HOOK, which is the
                expensive path, so nothing here under-reports the cost.
    plain       the same raster.asm with the hooks compiled out, which is
                what the disc runs (BEFORE) -- its only yield point is
                main3.asm's pace_quad, in front of the quad, so its
                atomic unit is the whole quad plus that

pace_quad is what the disc still runs (raster.asm's RQ_SPLIT is 0 -- see
the note there for the measurement that decided it), and it is benched by
re-assembling a copy into the free RAM of the RUNNING GAME, against the
real cost_unit and the real mul8x8u, the same trick emu_pacefit.py uses.
That keeps this file honest whichever way RQ_SPLIT is set.

TIMING PROTOCOL is emu_rast.py's: a 16-bit counter bumped once per
iteration with interrupts off, the empty loop subtracted, calibrated on
100 NOPs.  The paced harness carries an 8 us hook-counting prologue the
disc does not have; PRO_US below is subtracted from every interval.
"""

import os
import addrs
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

import emu_rast as ER                                        # noqa: E402
import pacemodel as P                                        # noqa: E402
import rastermodel as rm                                     # noqa: E402

E_HBENCH = 0x8014
E_FBENCH = 0x8010
PRO_US = 8.0        # LD HL,hookn / LD A,(HL) / OR A / JR Z -- harness only


def split_units(q):
    """The charges the SPLIT rasteriser takes for one quad.

    pacemodel.quad_units follows the disc, and the disc ships with
    raster.asm's RQ_SPLIT at 0 -- so this file, which exists to measure
    the split one, spells the split rule out rather than asking for it.
    It is the same arithmetic; keep the two in step."""
    sh = rm.quad_shape(q)
    u = [P.C_QSET]
    n, bpl = sh["bh"], P.C_BLINE + 4 * sh["npush"]
    while n > 0:
        k = min(P.RQ_BCH, n)
        n -= k
        u.append(P.C_CHUNK + (0 if k == P.RQ_BCH else P.C_PMUL) + k * bpl)
    pre, i = sh["wpre"], 0
    while i < len(pre):
        k = min(P.RQ_WCH, len(pre) - i)
        u.append(P.C_CHUNK + (0 if k == P.RQ_WCH else P.C_PMUL)
                 + k * (P.C_WPAIR + 4 * pre[i]) + P.C_WSTEP * pre[i])
        i += k
    return u


# =====================================================================
#  pace_quad, exhumed.  This is main3.asm's deleted per-quad hook, VERBATIM,
#  assembled into the running game's free RAM at #3A00 so that "before" is
#  a measurement and not a memory.  It reads a record at HL, predicts the
#  whole quad, and falls into the real cost_unit.
# =====================================================================
PACE_QUAD = """
    org #3A40
pace_quad
    ld   a,(hl)
    inc  hl
    ld   d,a
    ld   a,(hl)
    inc  hl
    sub  d
    jr   nc,pq_bw1
    neg
pq_bw1
    add  a,a
    add  a,C_QS
    ld   e,a
    ld   c,(hl)
    inc  hl
    ld   a,(hl)
    inc  hl
    cp   CYH/16
    jr   nc,pq_locl
    add  a,a
    add  a,a
    add  a,a
    add  a,a
    ld   b,a
    ld   a,c
    rrca
    rrca
    rrca
    rrca
    and  #0F
    add  a,b
    jr   pq_look
pq_locl
    ld   a,CYH
pq_look
    ld   d,a
    ld   c,(hl)
    inc  hl
    ld   a,(hl)
    cp   CYH/16
    jr   nc,pq_hicl
    add  a,a
    add  a,a
    add  a,a
    add  a,a
    ld   b,a
    ld   a,c
    rrca
    rrca
    rrca
    rrca
    and  #0F
    add  a,b
    jr   pq_hiok
pq_hicl
    ld   a,CYH
pq_hiok
    ld   c,a
    sub  d
    ld   h,a
    ld   l,0
    srl  h
    rr   l
    push hl
    ld   a,c
    add  a,d
    ld   c,e
    call #%04X
    pop  de
    add  hl,de
    ld   de,C_QUAD
    add  hl,de
    ld   b,h
    ld   c,l
    jp   #%04X
"""

def build_pace_quad(rig, cyh):
    """Assemble the exhumed pace_quad into the booted game and hand back
    its address.

    C_QUAD and C_QS come from main3.asm through pacemodel, NOT from a copy
    kept here.  They were copied once -- `C_QUAD_OLD, C_QS_OLD = 740, 22`
    -- and the moment the shipped values moved to 820/22 this file was
    benching a pace_quad the disc does not contain, while calling its
    column "BEFORE".  RQ_SPLIT is 0, so "BEFORE" IS the shipping path."""
    src = PACE_QUAD % (rig.s["MUL8X8U"], rig.s["COST_UNIT"])
    src = ("C_QS equ %d\nC_QUAD equ %d\nCYH equ %d\n" % (P.C_QS, P.C_QUAD,
                                                         cyh)) + src
    d = os.path.join(_E2, "build")
    open(os.path.join(d, "pq.asm"), "w").write(src)
    subprocess.run(["rasm", "pq.asm", "-o", "pq"], cwd=d,
                   capture_output=True, check=True)
    blob = open(os.path.join(d, "pq.bin"), "rb").read()
    rig.c.write_ram(0x3A40, blob)
    return 0x3A40


# ----------------------------------------------------------------- probes --
def probes(c):
    """The shapes that bound the atomic unit, plus real ones."""
    X, CY = c.XMAX_Q4, c.CY_Q4
    out = [
        ("full-viewport body", ER.q(0, CY, X, CY, 0, 1, c)),
        ("body, 8x overheight", ER.q(0, 8 * CY, X, 8 * CY, 0, 1, c)),
        ("wedge 0 -> full", ER.q(0, 0, X, CY, 0, 1, c)),
        ("wedge full -> 0", ER.q(0, CY, X, 0, 0, 1, c)),
        ("wedge 2x overheight", ER.q(0, CY // 4, X, 2 * CY, 0, 1, c)),
        ("wedge 4x overheight", ER.q(0, CY // 4, X, 4 * CY, 0, 1, c)),
        ("wedge 8x overheight", ER.q(0, CY // 4, X, 8 * CY, 0, 1, c)),
        ("near wall, one end 8x over", ER.q(0, 8 * CY, X, CY // 2, 0, 1, c)),
        ("both ends over, different", ER.q(0, 6 * CY, X, 2 * CY, 0, 1, c)),
        ("h at the near-plane limit", ER.q(0, 6144, X, 6144, 0, 1, c)),
        ("one-row wedge, full width", ER.q(0, 0, X, 16, 0, 1, c)),
        ("two-row wedge, full width", ER.q(0, 0, X, 32, 0, 1, c)),
        ("8-pair wedge, full width", ER.q(0, 0, X, 8 * 16, 0, 1, c)),
        ("9-pair wedge, full width", ER.q(0, 0, X, 9 * 16, 0, 1, c)),
        ("15-line body, full width", ER.q(0, 7 * 16, X, 7 * 16, 0, 1, c)),
        ("17-line body, full width", ER.q(0, 8 * 16, X, 8 * 16, 0, 1, c)),
        ("degenerate xa == xb", ER.q(700, 400, 700, 400, 0, 1, c)),
        ("pinned at column 0 (words)", ER.q(0, 310, 300, 290, 0, 4, c)),
    ]
    return out


def plain(rig, entry, qq, ovh):
    """A bench with the hook trap DISARMED -- it is a countdown in RAM and
    a run that stops early leaves it part-way down, which would then abort
    somebody else's loop."""
    rig.c.poke(rig.s("HOOKN"), 0)
    rig.c.poke(rig.s("HOOKK"), 0)
    return rig.bench(entry, [qq]) - ovh


def intervals(rig, qq, nhook, ovh):
    """-> the measured length of every stretch of work BETWEEN two hooks,
    in us, with the harness's own 8 us prologue taken back off.

    iv[0] is the run-up to the first hook (raster_quad's two-instruction
    entry) and iv[i+1] is what the charge taken at hook i has to cover.
    """
    t, charged = [], []
    for k in range(1, nhook + 2):
        rig.c.poke(rig.s("HOOKK"), min(k, 255))
        t.append(rig.bench(E_HBENCH, [qq]) - ovh)
        charged.append(struct.unpack("<H",
                       rig.c.read_ram(rig.s("HOOKBC"), 2))[0])
    t.append(plain(rig, ER.E_BENCH, qq, ovh))   # the whole quad
    out = [t[0]]
    for i in range(1, len(t)):
        out.append(t[i] - t[i - 1])
    return [max(0.0, x - PRO_US) for x in out], charged[:nhook]


def main(nstates=8):
    c = rm.cfg()
    print("viewport %dx%d bytes, horizon row %d, MAXPUSH %d"
          % (c.VP_BW, c.VP_H, c.CYH, c.MAXPUSH))
    print("chunking: RQ_BCH %d body scanlines, RQ_WCH %d wedge pairs"
          % (P.RQ_BCH, P.RQ_WCH))

    up = ER.Rig(False)
    cal = ER.calibrate(up)
    assert abs(cal - 100.0) < 0.5, cal
    up_ovh = up.bench(ER.E_EMPTY, [ER.q(0, 0, 16, 0, 0, 1, c)])
    pa = ER.Rig(True)
    pa_ovh = pa.bench(ER.E_EMPTY, [ER.q(0, 0, 16, 0, 0, 1, c)])
    print("empty loop: unpaced %.2f us, paced %.2f us (both subtracted)"
          % (up_ovh, pa_ovh))

    # ---- pace_quad, on the booted disc -------------------------------
    import emu_pacefit as PF
    disc = PF.Rig()
    disc.ovh = disc.bench(None)
    dcal = disc.bench(None, nops=100)
    pq = build_pace_quad(disc, c.CYH)
    print("100 NOPs on the disc calibrate to %.2f us" % dcal)

    cases = probes(c) + [("real quad #%d" % i, qq)
                         for i, qq in enumerate(ER.from_kernel(nstates))]

    mismatch = [0]
    print("\n%-28s %5s %8s %8s %8s %8s %8s %7s"
          % ("quad", "hooks", "BEFORE", "AFTER", "overhd", "atom-b",
             "atom-a", "charge"))
    rows = []
    for label, qq in cases:
        u = split_units(qq)
        # BEFORE: pace_quad + the whole unpaced quad, one atomic unit
        disc.c.write_ram(addrs.QUADS, struct.pack("<BBHHBB", *qq))
        pqus = disc.bench(pq)
        before = up.bench(ER.E_BENCH, [qq]) - up_ovh
        pa.poke_quads([qq])
        after = plain(pa, ER.E_BENCH, qq, pa_ovh)
        iv, z80 = intervals(pa, qq, len(u), pa_ovh)
        if z80 != u:
            print("  CHARGE MISMATCH %s\n    Z80    %s\n    model  %s"
                  % (label, z80, u))
            mismatch[0] += 1
        rows.append(dict(label=label, q=qq, nhook=len(u), pq=pqus,
                         before=before, after=after, iv=iv,
                         charge=sum(u), units=u))
        print("%-28s %5d %8.0f %8.0f %+8.0f %8.0f %8.0f %7.0f"
              % (label, len(u), before + pqus, after, after - before - pqus,
                 before + pqus, max(iv), sum(u)))

    wb = max(rows, key=lambda r: r["before"] + r["pq"])
    wa = max(rows, key=lambda r: max(r["iv"]))
    print("\n=== THE LARGEST ATOMIC UNIT")
    print("  BEFORE  %8.1f us  (%.1f%% of a 19968 us period)   %s"
          % (wb["before"] + wb["pq"],
             100 * (wb["before"] + wb["pq"]) / 19968.0, wb["label"]))
    print("  AFTER   %8.1f us  (%.1f%% of a 19968 us period)   %s"
          % (max(wa["iv"]), 100 * max(wa["iv"]) / 19968.0, wa["label"]))
    print("  pace_quad, the old per-quad hook: %.1f us, MEASURED on the"
          " booted disc" % (sum(r["pq"] for r in rows) / len(rows)))

    # ---- the overhead, as a straight line in the chunk count ---------
    co, rms, r2, worst = ER.lstsq(
        [[1.0, float(r["nhook"])] for r in rows],
        [r["after"] - r["before"] - r["pq"] for r in rows])
    print("\n=== WHAT THE YIELD MACHINERY COSTS (paced - unpaced - pace_quad)")
    print("  us = %+.1f %+.1f per hook      R^2 %.4f rms %.1f worst %.1f"
          % (co[0], co[1], r2, rms, worst))
    d = [r["after"] - r["before"] - r["pq"] for r in rows]
    print("  per quad: min %+.0f  median %+.0f  max %+.0f us"
          % (min(d), sorted(d)[len(d) // 2], max(d)))

    # ---- and the thing the charge has to be: one-sided ---------------
    print("\n=== IS THE CHARGE STILL AN UPPER BOUND ON THE WORK?")
    m = [r["charge"] - r["after"] for r in rows]
    bad = [r for r in rows if r["charge"] < r["after"]]
    print("  charge - measured:  min %+.0f  median %+.0f  max %+.0f us"
          % (min(m), sorted(m)[len(m) // 2], max(m)))
    print("  ratio charged/measured %.4f over %d quads"
          % (sum(r["charge"] for r in rows) / sum(r["after"] for r in rows),
             len(rows)))
    for r in bad:
        print("  UNDER  %-28s charged %d, measured %.0f"
              % (r["label"], r["charge"], r["after"]))
    # ...and per INTERVAL, which is the property the pacing really needs
    ubad = 0
    umin = 1e9
    uworst = None
    for r in rows:
        # unit i is charged AT hook i and pays for the work UNTIL hook
        # i+1, which is iv[i+1] -- iv[0] is the run-up to the first hook
        # and belongs to whoever charged before raster_quad was called.
        for i, (ch, us) in enumerate(zip(r["units"], r["iv"][1:])):
            if ch - us < umin:
                umin, uworst = ch - us, (r["label"], i, len(r["units"]),
                                         ch, us)
            ubad += ch < us
    print("  per INTERVAL, charge - measured: min %+.0f us, %d of %d under"
          % (umin, ubad, sum(len(r["units"]) for r in rows)))
    if uworst:
        print("  worst interval: %s, unit %d of %d, charged %d, measured %.0f"
              % (uworst[0], uworst[1], uworst[2], uworst[3], uworst[4]))
    # ---- the per-unit view, so a constant that is under shows up as
    #      itself rather than as a quad that happens to contain it
    kinds = {}
    need = {}
    for r in rows:
        sh = rm.quad_shape(r["q"])
        nb = (sh["bh"] + P.RQ_BCH - 1) // P.RQ_BCH
        bpl = P.C_BLINE + 4 * sh["npush"]
        for i, (ch, us) in enumerate(zip(r["units"], r["iv"][1:])):
            # `var` is the part of the charge that scales with the work;
            # measured - var is what the per-chunk CONSTANT has to be, and
            # reporting it directly is how C_CHUNK gets fitted instead of
            # guessed.
            if i == 0:
                k, var, full = "C_QSET (setup)", 0, True
            elif i <= nb:
                n = min(P.RQ_BCH, sh["bh"] - (i - 1) * P.RQ_BCH)
                full = n == P.RQ_BCH
                k, var = "body chunk", n * bpl + (0 if full else P.C_PMUL)
            else:
                j = (i - nb - 1) * P.RQ_WCH
                m = min(P.RQ_WCH, len(sh["wpre"]) - j)
                w = sh["wpre"][j]
                k = "wedge chunk"
                full = m == P.RQ_WCH
                var = (m * (P.C_WPAIR + 4 * w) + P.C_WSTEP * w
                       + (0 if full else P.C_PMUL))
            kinds.setdefault(k, []).append(ch - us)
            key = k + (" (full)" if full else " (short)")
            need.setdefault(key, []).append(us - var)
    print("\n=== MARGIN BY UNIT (charge - measured)")
    for k in ("C_QSET (setup)", "body chunk", "wedge chunk"):
        v = kinds.get(k)
        if v:
            print("  %-20s n=%4d   min %+7.0f   median %+7.0f   max %+7.0f"
                  % (k, len(v), min(v), sorted(v)[len(v) // 2], max(v)))
    print("\n=== WHAT THE PER-CHUNK CONSTANT HAS TO BE (measured - work)")
    for k in sorted(need):
        v = need[k]
        print("  %-22s n=%4d   median %+7.0f   WORST %+7.0f"
              % (k, len(v), sorted(v)[len(v) // 2], max(v)))
    print("    charged: C_QSET %d, C_CHUNK %d (+ C_PMUL on a short chunk)"
          % (P.C_QSET, P.C_CHUNK))
    print("\n  THE Z80 CHARGES WHAT pacemodel.py SAYS IT DOES: %s"
          % (mismatch[0] == 0))
    print("  EVERY QUAD BOUNDED: %s   EVERY INTERVAL BOUNDED: %s"
          % (not bad, ubad == 0))
    frames(disc, up, up_ovh, pa, pa_ovh, c, nstates)
    return 1 if (bad or ubad or mismatch[0]) else 0


# =====================================================================
#  WHOLE FRAMES.  Only the rasteriser changed, so the frame's before/after
#  is its before/after: raster_paced on the booted disc against the same
#  quad list drawn by the UNPACED harness plus the exhumed pace_quad.
# =====================================================================
def frames(disc, up, up_ovh, pa, pa_ovh, c, nstates):
    import emu_frame as ef
    import emu_pace as ep
    _grid, _msolid = ef.load()
    rnd = random.Random(4242)
    offs = ep.lattice_offsets()
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for cy in range(16) for cx in range(16) for ox in offs
            for oy in offs for a in range(72)
            if ep.reachable(disc.solid, (cx << 8) | ox, (cy << 8) | oy)]
    # the worst state in the maze by name, plus a lattice sample
    states = [(0x0150, 0x0DF0, 67)] + rnd.sample(pool, nstates)
    pq = 0x3A40
    print("\n=== WHOLE FRAMES: the rasteriser, before and after")
    print("%-20s %4s %6s %9s %9s %9s %8s"
          % ("state", "quad", "chunks", "BEFORE", "AFTER", "delta", "charge"))
    rows = []
    for (px, py, a) in states:
        disc.place(px, py, a)
        disc.once(disc.s["MARCH"], disc.s["PROJECT_ALL"])
        nq = disc.c.peek(disc.s["FG_NQUAD"])
        raw = disc.c.read_ram(addrs.QUADS, 8 * nq)
        quads = [(raw[8 * i], raw[8 * i + 1])
                 + struct.unpack("<2H", raw[8 * i + 2:8 * i + 6])
                 + (raw[8 * i + 6], raw[8 * i + 7]) for i in range(nq)]
        # Both columns come from the SAME harness, so they are the same
        # measurement with and without the hooks: BEFORE is the hookless
        # rasteriser plus one pace_quad a quad (benched on the booted
        # disc, which is what main3.asm really runs), AFTER is the split
        # one with its stub accumulator yielding on EVERY hook -- the
        # worst path, so the overhead is not under-reported.
        up.poke_quads(quads)
        raw_before = up.bench(ER.E_FBENCH, quads) - up_ovh
        pa.poke_quads(quads)
        pa.c.poke(pa.s("HOOKN"), 0)
        pa.c.poke(pa.s("HOOKK"), 0)
        after = pa.bench(E_FBENCH, quads) - pa_ovh
        pqs = 0.0
        for qq in quads:
            disc.c.write_ram(addrs.QUADS, struct.pack("<BBHHBB", *qq))
            pqs += disc.bench(pq)
        disc.c.write_ram(addrs.QUADS, raw)
        before = raw_before + pqs
        nch = sum(len(split_units(q)) for q in quads)
        charge = sum(sum(split_units(q)) for q in quads)
        rows.append((before, after, charge, nq, nch, (px, py, a)))
        print("(%04X,%04X)a%2d %6d %6d %9.0f %9.0f %+9.0f %8.0f"
              % (px, py, a, nq, nch, before, after, after - before, charge))
    w = max(rows, key=lambda r: r[1])
    b = max(rows, key=lambda r: r[0])
    print("  worst rasteriser BEFORE %.2f ms, AFTER %.2f ms, delta %+.2f ms"
          % (b[0] / 1000, w[1] / 1000, (w[1] - b[0]) / 1000))
    d = [r[1] - r[0] for r in rows]
    print("  per frame the yield machinery costs: min %+.0f  median %+.0f"
          "  max %+.0f us" % (min(d), sorted(d)[len(d) // 2], max(d)))
    print("  charged / measured: %.4f"
          % (sum(r[2] for r in rows) / sum(r[1] for r in rows)))


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8))
