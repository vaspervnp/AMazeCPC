"""COUNT the background slivers in a rendered engine2 viewport.

    python3 engine2/tools/emu_sliver.py states [n]   named states + a random sweep
    python3 engine2/tools/emu_sliver.py disc         the BOOTED build/amaze.dsk

WHAT A SLIVER IS (the defect report's definition)
    a run of background-coloured pixels bounded on both sides by wall pixels
    on the SAME scanline.  Runs are byte granular, so the artefact the odd
    width rounding produces is exactly ONE byte = 2 mode-0 pixels wide.
    A left EDGE LEAK is the same thing against the viewport's left border:
    background at byte column 0 with wall immediately to its right.

    Wider background runs between walls are legitimate -- a doorway, or the
    ceiling seen over a distant wall -- so they are tallied separately, by
    width, and never counted as slivers.

HOLES is the second, geometry-derived metric and does not depend on the
definition above: a byte is a hole when it is background on the screen but
some quad's EXACT Q12.4 x-interval at that scanline overlaps it, even
partly.  It is the stricter measure -- it counts a byte the runs should
arguably have painted even where nothing bounds it on both sides -- and it
is also what separates a REAL 2-pixel gap between two walls from an
artefact, which is why each sliver is reported with it.  It does not go to
zero.  The wedge's moving edge used to be interpolated in whole ROWS between
jlo and jhiu rather than in half heights, so it arrived at the pinned column
up to a row early -- 12 slivers, 774 holes; raster.asm now interpolates in u
and floors, which leaves 2 and 82.  What is left is upstream of the
rasteriser: project.asm rounds the two endpoint COLUMNS outward, so the line
between them is not the exact top edge and leans inward near the tall end by
up to a byte.  See the RUNS note in raster.asm.

The frames come from engine2/test/tst_frame.asm on a cycle-accurate CPC
6128 (bg_fill + march + project + raster_frame), i.e. the real Z80 output,
or -- with `disc` -- straight off the booted disc image.
"""

import os
import random
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpchw as cpchw                                        # noqa: E402
import emu_frame as ef                                       # noqa: E402
import marchmodel as mm                                      # noqa: E402
import pal                                                   # noqa: E402
import projmodel as pm                                       # noqa: E402
import rastermodel as rm                                     # noqa: E402

# the state vpcfg.inc names as the worst frame in the maze, and the
# corridor shot_amaze3.py photographs
WORST = (0x0770, 0x06F0, 55)
CORRIDOR = (10 * 256 + 128, 13 * 256 + 128, 0)


def palette_sets():
    ramp = pal.ramp_table()
    # entries 0 and 8 are the unused k = 0 slot (quads carry k = 1..7) and
    # hold 0, which is also the far ceiling: leave them out.
    wall = {ramp[i] for i in list(range(1, 8)) + list(range(9, 16))}
    bg = {cpchw.MODE0_SOLID[p]
          for p in (pal.CEIL_NEAR, pal.CEIL_FAR, pal.FLOOR_NEAR,
                    pal.FLOOR_FAR)}
    assert not (wall & bg)
    return wall, bg


def viewport(screen, c):
    """-> VP_H rows of VP_BW bytes out of a 16K buffer."""
    rows = []
    for r in range(c.VP_H):
        y = c.VP_Y + r
        base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
        rows.append(screen[base:base + c.VP_BW])
    return rows


def model_screen(solid, px, py, a):
    """The frame's faces in FULL-PRECISION screen space (sxa, hha, sxb, hhb),
    i.e. what projmodel.pack_quad rounds to byte columns."""
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        s = pm.project_face_screen(v[0], v[1], v[2], v[3],
                                   ax - ipx, ay - ipy, fd)
        if s is not None:
            out.append(s)
    return out


def ideal_cover(screenq, c):
    """-> set of (row, byte) a face's EXACT geometry overlaps, even partly."""
    cov = set()
    for xa, ha, xb, hb in screenq:
        for j in range(0, c.CYH + 1):
            u = 16 * j
            if u > max(ha, hb):
                continue
            if ha == hb:
                xl, xr = xa, xb
            else:                       # the moving edge, exactly
                xe = xa + (u - ha) * (xb - xa) / float(hb - ha)
                xl, xr = (xa, xe) if hb < ha else (xe, xb)
                xl, xr = max(xa, min(xb, xl)), max(xa, min(xb, xr))
            if xr <= xl:
                continue
            b0 = int(xl // 32)
            b1 = int(-((-xr) // 32))    # ceil
            b0, b1 = max(0, b0), min(c.VP_BW, b1)
            for r in (c.CYH - j, c.CYH + j):
                if 0 <= r < c.VP_H:
                    for b in range(b0, b1):
                        cov.add((r, b))
    return cov


def count(screen, screenq, c, wall, bg):
    """-> dict of sliver / edge / hole counts for one rendered frame."""
    rows = viewport(screen, c)
    cov = ideal_cover(screenq, c)
    res = {"sliver": 0, "art": 0, "left": 0, "lart": 0, "right": 0,
           "hole": 0, "widths": {}}
    for r, row in enumerate(rows):
        x = 0
        while x < c.VP_BW:
            if row[x] in bg:
                s = x
                while x < c.VP_BW and row[x] in bg:
                    x += 1
                w = x - s
                lw = s > 0 and row[s - 1] in wall
                rw = x < c.VP_BW and row[x] in wall
                if lw and rw:
                    res["widths"][w] = res["widths"].get(w, 0) + 1
                    if w == 1:
                        res["sliver"] += 1
                        # ...and is it a HOLE, i.e. does some face's exact
                        # geometry cover it?  A 1-byte gap that no face
                        # covers is real: two walls 2 px apart on screen.
                        res["art"] += (r, s) in cov
                elif rw and s == 0 and w == 1:
                    res["left"] += 1
                    res["lart"] += (r, 0) in cov
                elif lw and x == c.VP_BW and w == 1:
                    res["right"] += 1
                for b in range(s, x):
                    if (r, b) in cov:
                        res["hole"] += 1
            else:
                x += 1
    return res


def report(tag, res):
    w = ",".join(f"{k}:{v}" for k, v in sorted(res["widths"].items()))
    print(f"  {tag:44s} slivers {res['sliver']:4d} (real gaps in the "
          f"geometry: {res['art']:4d})  left-edge {res['left']:3d} "
          f"({res['lart']:3d})  right-edge {res['right']:3d}  holes "
          f"{res['hole']:4d}")


def states(n=0):
    rig = ef.Rig()
    c = rig.cfg
    wall, bg = palette_sets()
    grid, solid = ef.load()
    named = [("worst frame in the maze",) + WORST,
             ("corridor (10.5,13.5) heading 0",) + CORRIDOR]
    named += ef.scenarios(grid, solid)
    tot = {"sliver": 0, "art": 0, "left": 0, "lart": 0, "right": 0,
           "hole": 0}
    print(f"viewport {c.VP_BW}x{c.VP_H} bytes at ({c.VP_BX},{c.VP_Y})")
    for tag, px, py, a in named:
        scr, q = rig.run_once(px, py, a)
        res = count(scr, model_screen(solid, px, py, a), c, wall, bg)
        report(f"{tag}  ({px:04X},{py:04X},{a})", res)
        for k in tot:
            tot[k] += res[k]
    if n:
        rnd = random.Random(1234)
        fl = ef.floors(grid)
        sw = {"sliver": 0, "art": 0, "left": 0, "lart": 0, "right": 0,
              "hole": 0}
        worst = (0, None)
        for i in range(n):
            x, y = rnd.choice(fl)
            px = (x << 8) | rnd.randrange(64, 192)
            py = (y << 8) | rnd.randrange(64, 192)
            a = rnd.randrange(72)
            scr, q = rig.run_once(px, py, a)
            res = count(scr, model_screen(solid, px, py, a), c, wall, bg)
            for k in sw:
                sw[k] += res[k]
            if res["sliver"] + res["left"] > worst[0]:
                worst = (res["sliver"] + res["left"], (px, py, a, res))
        print(f"\n  {n} random reachable states: slivers {sw['sliver']} "
              f"({sw['art']} of them real gaps), left-edge {sw['left']} "
              f"({sw['lart']}), right-edge {sw['right']}, "
              f"holes {sw['hole']}")
        if worst[1]:
            px, py, a, res = worst[1]
            report(f"worst of the sweep ({px:04X},{py:04X},{a})", res)
        for k in tot:
            tot[k] += sw[k]
    print(f"\nTOTAL over all states: slivers {tot['sliver']} of which "
          f"{tot['art']} are ARTEFACTS (the rest are 2-pixel gaps the "
          f"geometry really has), left-edge {tot['left']} ({tot['lart']} "
          f"artefacts), right-edge {tot['right']}, holes {tot['hole']}")
    return tot


# ---------------------------------------------------------------- disc ----
def disc():
    """The same count, on the front buffer of the BOOTED amaze.dsk."""
    from cpc import CPC
    dsk = os.path.join(_ROOT, "build", "amaze.dsk")
    sym = {}
    for line in open(os.path.join(_ROOT, "build", "e3", "game3.sym")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    c = rm.cfg()
    wall, bg = palette_sets()
    m = CPC()
    m.insert_disc(dsk)
    m.run_frames(150)
    m.type_text('RUN"AMAZE\n')
    m.run_frames(bootdisc.LOAD_FRAMES)
    bootdisc.start(m)   # past the title screen -- see bootdisc.py
    assert m.mode == 0
    tot = {"sliver": 0, "left": 0, "right": 0}
    for tag, px, py, a in [("worst frame in the maze",) + WORST,
                           ("corridor",) + CORRIDOR,
                           ("corridor +5 deg", CORRIDOR[0], CORRIDOR[1], 1),
                           ("corridor +45 deg", CORRIDOR[0], CORRIDOR[1], 9)]:
        m.write_ram(sym["PLR_X"], struct.pack("<H", px))
        m.write_ram(sym["PLR_Y"], struct.pack("<H", py))
        m.poke(sym["PLR_A"], a)
        m.run_frames(30)
        # R12/R13 is the CRTC's own start address; the RAM base of the
        # displayed 16K buffer is bits 13..12 of it, shifted up by two.
        base = (m.crtc_screen_addr & 0x3000) << 2
        scr = m.read_ram(base, 0x4000)
        res = count(scr, [], c, wall, bg)      # no quad list off the disc
        report(f"{tag}  ({px:04X},{py:04X},{a})", res)
        for k in tot:
            tot[k] += res[k]
    print(f"\nTOTAL on the booted disc: slivers {tot['sliver']}, left-edge "
          f"{tot['left']}, right-edge {tot['right']}")
    return tot


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "states"
    if cmd == "disc":
        disc()
    else:
        states(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
