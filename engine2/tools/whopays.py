"""A door-run frame charges 11.15 budgets.  WHERE does that charge go?

Not "is the charge right" -- overfit.py and emu_rcol.py's `atomic` answer
that, one-sidedly, against the machine.  This asks the other question:
which constants ADD UP to the number, so the next lever is picked by size
instead of by whichever routine I happened to be reading.

It exists because I spent a session making rc_mul8 cheaper on the
strength of "rc_slide's two multiply loops are most of what C_COLSO pays
for".  That was true and it was still the wrong place to be: the overlay
is 8% of the column renderer, the column renderer is 73% of the frame,
and the two constants holding the other 72% of it are C_COLS and C_COLR.
Run this BEFORE choosing where to cut.

    python3 engine2/tools/whopays.py [dlift ...]

Everything is read off the live constants -- change costcol.inc and the
table changes with it.
"""
import sys

sys.path.insert(0, "engine2/tools")
sys.path.insert(0, "tools")
import pacemodel as P                                   # noqa: E402
import emu_frame as ef                                  # noqa: E402
import marchmodel as mm                                 # noqa: E402
import projmodel as pm                                  # noqa: E402
import colmodel as cm                                   # noqa: E402
import rastermodel as rm                                # noqa: E402

DOORMOV = 3                     # march.asm: a door part way through its run
# The state doorperiod.py measures: the first door in the map, the player
# standing one cell west of it and looking straight at it.  A door one
# cell away is the biggest quad the engine can draw, which is the whole
# reason this frame is the worst one.
DOOR = (5, 3)
STAND = (4, 3)
HEAD = 0

# ...and the per-hook constants, by the key charge_terms uses for each.
K = dict(frame=P.C_CFRAME, face=P.C_CFACE, skip=P.C_CSKIP, pair=P.C_COLS,
         colso=P.C_COLSO, bands=P.C_CBAND, rows=P.C_COLR, edges=P.C_CEDGE,
         steps=P.C_CSTEP, far=P.C_CFAR, farp=P.C_CFARP, fars=P.C_CFARS,
         farend=P.C_CFAREND)


def project(solid, px, py, a):
    """-> (visited, faces, quads), counting the clip lerps per face.

    The same walk pacemodel._state_units does; it is repeated here rather
    than imported because that one returns only the summed units and this
    file needs the quad list to hand to colmodel.
    """
    nclip = [0]
    real = pm.lerp

    def counting(*args):
        nclip[0] += 1
        return real(*args)

    pm.lerp = counting
    try:
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        faces, quads = [], []
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
            nclip[0] = 0
            q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
            faces.append((q is not None, nclip[0]))
            if q is not None:
                quads.append(q + (door, k))
        return r["visited"], faces, quads
    finally:
        pm.lerp = real


def column_charge(quads, dlift):
    return cm.charge(quads, rm.cfg(), P.C_CFRAME, P.C_CFACE, P.C_CSKIP,
                     P.C_COLS, P.C_CBAND, P.C_COLR, P.C_CEDGE, P.C_CSTEP,
                     dlift=dlift, c_colso=P.C_COLSO, c_cfar=P.C_CFAR,
                     c_cfarp=P.C_CFARP, c_cfars=P.C_CFARS,
                     c_cfarend=P.C_CFAREND)


def table(name, rows, tot):
    print(f"--- {name}   {tot} us   = {tot / P.THRESH:.2f} budgets ---")
    for n, v in sorted(rows, key=lambda t: -t[1]):
        if v:
            print(f"   {v:7d}  {100.0 * v / tot:5.1f}%  {n}")


def main(lifts):
    _grid, base = ef.load()
    s = bytearray(base)
    s[DOOR[1] * 16 + DOOR[0]] = DOORMOV
    solid = bytes(s)
    px, py = STAND[0] * 256 + 128, STAND[1] * 256 + 128

    print(f"door {DOOR} in motion, player at {STAND} heading {HEAD}")
    print(f"budget {P.PACE_FRAMES * P.THRESH} us "
          f"({P.PACE_FRAMES} periods of {P.THRESH})\n")

    for dl in lifts:
        ncell, faces, quads = project(solid, px, py, HEAD)
        col = column_charge(quads, dl)
        nem = sum(1 for e, _ in faces if e)
        parts = [
            ("bg_fill + march_setup", P.C_BG + P.C_MSETUP),
            (f"flood, {ncell} cells", ncell * P.C_CELL),
            (f"project, {nem}/{len(faces)} faces",
             sum((P.C_FACE if e else P.C_REJ) + P.C_CLIP * n
                 for e, n in faces)),
            ("door_shrink", P.C_DANIM),
            (f"THE COLUMN RENDERER, {len(col)} hooks", sum(col)),
            ("hud_update", P.C_HUD),
            ("hud readouts + radar",
             P.C_AMMO + P.C_SCAN + P.C_HP + P.C_SWEEP
             + P.N_BLIP * P.C_BLIP + P.C_RNEEDLE),
            ("pip_draw", P.C_PIP),
        ]
        table(f"dlift {dl:3d}", parts, sum(v for _, v in parts))

        # ...and inside the column renderer, which CONSTANT is the money.
        agg = {}
        for t in cm.charge_terms(quads, rm.cfg(), dlift=dl):
            for kk, n in t.items():
                agg[kk] = agg.get(kk, 0) + n
        sub = [(f"{kk:7s} {agg[kk]:5d} x {K[kk]}", agg[kk] * K[kk])
               for kk in agg]
        table(f"...of which the column renderer, dlift {dl}",
              sub, sum(v for _, v in sub))
        print()


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [0, 42, 85, 128, 170, 213])
