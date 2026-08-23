"""Compare the fixed-point march model against the float reference.

Run: PYTHONPATH=tools:prototype/free-angle:engine2/tools python3 engine2/tools/check_model.py
"""

import math
import sys
import random
import collections

import geom
import world
import free
import marchmodel as M

# engine2 target viewport: 48x128 bytes at (16,0), 60 degree FOV.
geom.VP_BX, geom.VP_BW, geom.VP_Y, geom.VP_H = 16, 48, 0, 128
geom.VP_PW = geom.VP_BW * 2
geom.CX = geom.VP_PW / 2.0
geom.CY = geom.VP_H / 2.0
free.set_focal(geom.CX / math.tan(math.radians(30.0)), 128.0)

grid, sx, sy = world.load_maze()
solid = M.solid_from_grid(grid)


def ref_faces(px, py, a):
    """Reference face set AFTER project_face's backface cull (= march output),
    plus the subset that actually rasterises to something on screen."""
    fwd, rgt = free.basis(a)
    seen, cand, visited = free.march(grid, px, py, a, {})
    out = set()
    drawn = set()
    for wx, wy, fd, isd in cand:
        (ax, ay), (bx, by), n = free.face_endpoints(wx, wy, fd)
        if (px - ax) * n[0] + (py - ay) * n[1] <= 0.0:
            continue
        out.add((wx, wy, fd, isd))
        r = free.project_face(wx, wy, fd, px, py, fwd, rgt)
        if r is not None and free.rasterise(r[0]) is not None:
            drawn.add((wx, wy, fd, isd))
    return visited, set(seen), out, drawn


def gen_states(mode, nsub, seed=12345):
    rnd = random.Random(seed)
    st = []
    for y in range(16):
        for x in range(16):
            if grid[y][x] != world.FLOOR:
                continue
            for _ in range(nsub * nsub):
                if mode == "grid":
                    pass
                fx = rnd.randrange(8, 249)
                fy = rnd.randrange(8, 249)
                for a in range(72):
                    st.append(((x << 8) | fx, (y << 8) | fy, a))
    if mode == "grid":
        st = []
        for y in range(16):
            for x in range(16):
                if grid[y][x] != world.FLOOR:
                    continue
                for i in range(nsub):
                    for j in range(nsub):
                        fx = int((i + 0.5) / nsub * 256)
                        fy = int((j + 0.5) / nsub * 256)
                        for a in range(72):
                            st.append(((x << 8) | fx, (y << 8) | fy, a))
    return st


def run(states, label):
    bad_seen = bad_face = bad_drawn = 0
    agg = collections.Counter()
    mx = collections.Counter()
    bmax = collections.Counter()
    for px_fx, py_fx, a in states:
        px, py = px_fx / 256.0, py_fx / 256.0
        r = M.march(solid, px_fx, py_fx, a)
        rq = M.march(solid, px_fx, py_fx, a, push_opaque=True)
        assert set(r["seen"]) == set(rq["seen"]), "flood variants disagree"
        assert sorted(r["faces"]) == sorted(rq["faces"]), \
            "flood variants disagree on faces"
        rv, rs, rf, rd = ref_faces(px, py, a)
        ms = set(r["seen"])
        mf = set(f[:4] for f in r["faces"])
        if ms != rs or rq["visited"] != rv:
            bad_seen += 1
        if mf != rf:
            bad_face += 1
            # does the disagreement survive the reference's clip+raster?
            if (mf ^ rf) & rd:
                bad_drawn += 1
        agg["visited"] += r["visited"]
        agg["seen"] += len(ms)
        agg["faces"] += len(mf)
        agg["drawn"] += len(rd)
        mx["visited"] = max(mx["visited"], r["visited"])
        mx["seen"] = max(mx["seen"], len(ms))
        mx["faces"] = max(mx["faces"], len(mf))
        mx["drawn"] = max(mx["drawn"], len(rd))
        for k, b in enumerate(r["buckets"]):
            bmax[k] = max(bmax[k], len(b))
    n = len(states)
    print(f"[{label}] FBITS={M.FBITS} states={n}")
    print(f"   seen/visited mismatch : {bad_seen:6d}  {100.0*bad_seen/n:7.4f}%")
    print(f"   face-set mismatch     : {bad_face:6d}  {100.0*bad_face/n:7.4f}%")
    print(f"   ... of which VISIBLE  : {bad_drawn:6d}  {100.0*bad_drawn/n:7.4f}%")
    print("   mean:", {k: round(v / n, 2) for k, v in agg.items()},
          " max:", dict(mx))
    print("   max bucket occupancy  :", dict(sorted(bmax.items())))


if __name__ == "__main__":
    nsub = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    sweep = len(sys.argv) > 2 and sys.argv[2] == "sweep"
    for fb in ((10,) if sweep else (10,)):
        M.set_fbits(fb)
        run(gen_states("grid", nsub), "grid-aligned")
        run(gen_states("rand", nsub), "random-pos")
