"""WHAT DOES THE TEXTURE COST, OVER EVERY STATE A PLAYER CAN STAND IN?

Same 4055040 states pacescan.py and wallarea.py sweep, same quad list,
but scored with the coefficients emu_m1.py MEASURED on the booted 6128:

    FILL   us per painted byte  = 3.500 (ld de,nn : push de) - 2.000 (push de)
    PATCH  us per word of face width, ONCE per face (unrolled ld (nn),hl)
    FACE   us once per face      -- the ratio divide the mortar columns need
    JOINT  us per vertical mortar column (table read + interp + RMW)
    PHASE  us per wedge scanline whose run is pinned at the RIGHT, where the
           unrolled block's fixed tail no longer lines up with a fixed screen
           column and the exit has to be re-patched

    python3 m1cost.py FILL PATCH FACE JOINT PHASE NJOINT [jobs]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_W = {}
K = {}


def _init():
    import pacescan
    import rastermodel as rm
    solid, pos = pacescan.positions()
    _W["solid"], _W["pos"], _W["rm"], _W["cfg"] = solid, pos, rm, rm.cfg()


def _ini2(k):
    _init()
    K.update(k)


def _quads(px, py, a):
    import marchmodel as mm
    import projmodel as pm
    r = mm.march(_W["solid"], px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is not None:
            out.append(q + (door, k))
    return out


def _one(px, py, a):
    rm, c = _W["rm"], _W["cfg"]
    RC = c.CYH
    painted = fill = patch = face = joint = phase = 0
    nf = 0
    for q in _quads(px, py, a):
        nf += 1
        bhi, blo, hhi, hlo, bbv, bw, left_tall = rm.unpack(q, c)
        patch += K["PATCH"] * ((bw + 1) >> 1)
        face += K["FACE"]
        joint += K["JOINT"] * K["NJ"]
        jlo = RC if hlo >= RC * 16 else (hlo >> 4)
        for (row, end, npush) in rm.raster_quad(q, c):
            painted += 2 * npush
            if not (RC - jlo <= row <= RC + jlo) and not left_tall:
                phase += K["PHASE"]
    fill = K["FILL"] * painted
    return fill + patch + face + joint + phase, (painted, nf, fill, patch,
                                                 face, joint, phase)


def _chunk(args):
    lo, hi, step = args
    pos = _W["pos"]
    best = (0, None, None)
    tot = 0
    s = 0.0
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            v, d = _one(px, py, a)
            tot += 1
            s += v
            if v > best[0]:
                best = (v, (px, py, a), d)
    return best, tot, s


def main():
    import multiprocessing as mp
    K["FILL"], K["PATCH"], K["FACE"], K["JOINT"], K["PHASE"] = (
        float(x) for x in sys.argv[1:6])
    K["NJ"] = int(sys.argv[6])
    jobs = int(sys.argv[7]) if len(sys.argv) > 7 else (os.cpu_count() or 4)
    _init()
    npos = len(_W["pos"])
    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, 1)
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_ini2, initargs=(dict(K),)) as p:
        res = p.map(_chunk, bounds)
    best = (0, None, None)
    tot = 0
    s = 0.0
    for b, t, ss in res:
        tot += t
        s += ss
        if b[0] > best[0]:
            best = b
    v, st, d = best
    painted, nf, fill, patch, face, joint, phase = d
    print(f"scanned {tot} states, coefficients {K}")
    print(f"\nWORST added cost {v:9.1f} us  at {st}")
    print(f"    painted bytes        {painted}")
    print(f"    faces                {nf}")
    print(f"    fill  (+1.5/byte)    {fill:9.1f}")
    print(f"    patch (block immed)  {patch:9.1f}")
    print(f"    face  (ratio divide) {face:9.1f}")
    print(f"    joints               {joint:9.1f}")
    print(f"    wedge re-phase       {phase:9.1f}")
    print(f"\nmean added cost {s/tot:9.1f} us")


if __name__ == "__main__":
    main()
