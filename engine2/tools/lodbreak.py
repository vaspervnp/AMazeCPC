"""WHERE THE RASTERISER'S CHARGE GOES, BY DEPTH.

    python3 engine2/tools/lodbreak.py [nstates] [--open]

The question this answers is "would drawing the FAR walls with less
detail make the frame smaller, and by how much".  It is not obvious
either way: a far face covers few scanlines, so it is cheap to FILL, but
it still pays the full per-face and per-pair setup -- and on a
doors-open frame there are a lot of far faces.

So this attributes every microsecond colmodel.charge emits to the DEPTH
of the face that caused it, splits it into the part a lower level of
detail could remove (the fill, and the texture setup inside C_COLS) and
the part it could not (the march, the projector, the pair walk), and
prints what each depth is worth.

The per-byte figures it costs against are MEASURED (emu_byte.py,
engine2/src/rastcol.asm's header):

    column pair, textured           10.125 us/byte   <- what ships
    column pair, 2x magnified        7.625
    column pair, CONSTANT colour     5.125   <- the floor for a flat face
"""

import os
import sys
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "AMazeCPC", "tools"))

US_TEX = 10.125
US_MAG = 7.625
US_FLAT = 5.125


def face_charges(quads, c, P, cm):
    """-> per-face (k, us) using colmodel's own front-to-back walk.

    The charge depends on what the NEARER faces have already covered, so
    a face cannot be costed on its own -- this replays the whole list and
    tags each unit with the quad that produced it.
    """
    cover = cm.new_cover(c)
    out = []
    for q in reversed(quads):
        k = q[5]
        us = P.C_CFACE
        rows = edges = pairs = skips = 0
        for i in cm.pair_walk(q, c, cover):
            if i["closed"]:
                us += P.C_CSKIP
                skips += 1
            else:
                upc = i["up0"] + 1
                free = upc + (c.VP_H - i["dn0"])
                nb = (1 if upc > 0 else 0) + (1 if i["dn0"] < c.VP_H else 0)
                jhi = min(c.CYH, max(0, i["h"] + i["hq"] + 1) >> 4)
                jlo = min(c.CYH, max(0, i["h"] - i["hq"] - 1) >> 4)
                r = min(2 * jhi + 1, free)
                e = min(2 * (jhi - jlo), free)
                us += (P.C_COLS + P.C_CBAND * nb + P.C_COLR * r
                       + P.C_CEDGE * e)
                rows += r
                edges += e
                pairs += 1
            if 1 <= i["delta"] <= 3:
                us += P.C_CSKIP + P.C_CSTEP * i["delta"]
        out.append(dict(k=k, us=us, rows=rows, edges=edges,
                        pairs=pairs, skips=skips))
    return out


def main(nstates=200, doors=False):
    import marchmodel as mm
    import projmodel as pmod
    import pacemodel as P
    import rastermodel as rm
    import colmodel as cm
    import pacescan as ps
    import random

    c = rm.cfg()
    solid, pos = ps.positions(doors)
    rnd = random.Random(4242)
    per = collections.defaultdict(lambda: dict(us=0.0, rows=0, edges=0,
                                               pairs=0, skips=0, n=0))
    tot = 0.0
    for _ in range(nstates):
        px, py = rnd.choice(pos)
        a = rnd.randrange(72)
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        quads = []
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pmod.face_endpoints(wx, wy, fd)
            q = pmod.project_face(v[0], v[1], v[2], v[3],
                                  ax - ipx, ay - ipy, fd)
            if q is not None:
                quads.append(q + (1 if door else 0, k))
        for f in face_charges(quads, c, P, cm):
            d = per[f["k"]]
            for key in ("us", "rows", "edges", "pairs", "skips"):
                d[key] += f[key]
            d["n"] += 1
            tot += f["us"]

    print(f"{nstates} random states, doors "
          f"{'OPEN' if doors else 'shut'}; raster charge only\n")
    print("%3s %7s %9s %7s %8s %9s %9s" %
          ("k", "faces", "us", "share", "pairs", "rows", "edges"))
    for k in sorted(per):
        d = per[k]
        print("%3d %7d %9.0f %6.1f%% %8d %9d %9d"
              % (k, d["n"], d["us"], 100.0 * d["us"] / tot,
                 d["pairs"], d["rows"], d["edges"]))
    print("%3s %7s %9.0f" % ("all", sum(per[k]["n"] for k in per), tot))

    # ---- what a flat (untextured) far face would save, per depth cut
    print("\nIF EVERY FACE AT k >= CUT WERE DRAWN FLAT INSTEAD OF TEXTURED:")
    print("  (the fill falls 10.125 -> 5.125 us/byte, i.e. 5.0 us a byte,")
    print("   and a pair drawn flat needs no u division and no CTABT)")
    print("%5s %12s %12s %10s" % ("cut", "fill saved", "+setup", "of raster"))
    for cut in range(2, 8):
        rows = sum(per[k]["rows"] for k in per if k >= cut)
        pairs = sum(per[k]["pairs"] for k in per if k >= cut)
        # a row of a PAIR is two bytes
        fill = rows * 2 * (US_TEX - US_FLAT)
        setup = pairs * 250.0        # u divide + CTABT + texture walk setup
        print("%5d %12.0f %12.0f %9.1f%%"
              % (cut, fill, setup, 100.0 * (fill + setup) / tot))
    return 0


if __name__ == "__main__":
    _a = [x for x in sys.argv[1:] if not x.startswith("-")]
    raise SystemExit(main(int(_a[0]) if _a else 200,
                          "--open" in sys.argv))
