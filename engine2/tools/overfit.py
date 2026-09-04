"""FIT the overlay pair's extra fixed cost.

The slope is C_COLR and it is right.  What is short is the per-pair
INTERCEPT: an overlay pair does work a pass-1 pair does not -- it resets
the cover bytes and rc_column takes the ignore-the-cover path -- and
C_COLS covers only the pass-1 setup.

So: collect every OVERLAY hook over several states and both ends of the
lift, and report measured - charge.  The constant wanted is the largest
of those, rounded up: a one-sided bound, like every other C_* here.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.getcwd(), "engine2/tools"))
import emu_rcol as er
import pacemodel as P

rig = er.Rig(paced=True)
c = rig.cfg
print(f"C_COLS {P.C_COLS}  C_COLR {P.C_COLR}  C_CBAND {P.C_CBAND}\n")

short = []
for DL in (0, 42, 85, 128, 170, 213):
    for px, py, a, qs in er._atomic_states(6, 20260903, c):
        if not qs:
            continue
        qs = [tuple(q) for q in qs]
        i = max(range(len(qs)), key=lambda k: qs[k][3])
        q = list(qs[i]); q[4] = 3; qs[i] = tuple(q)
        terms, iv = er.measure(rig, qs, DL)
        ch = er.charges_for(qs, c, DL)
        # the OVERLAY hooks are the pair hooks that come after the far
        # pass, i.e. the ones belonging to the moving face.  colmodel
        # emits them last, so take the pair hooks from the tail.
        pairs = [k for k, t in enumerate(terms) if t.get("pair")]
        # the moving face is drawn LAST, so its pairs are the final run
        for k in pairs:
            meas = iv[k + 1] if k + 1 < len(iv) else 0.0
            # what C_COLSO would have to be: the measurement less the
            # charge WITHOUT it.
            base = ch[k] - (P.C_COLSO if terms[k].get("colso") else 0)
            d = meas - base
            if terms[k].get("colso"):
                short.append((d, DL, k, terms[k]["rows"], base, meas))

short.sort(reverse=True)
print(f"{len(short)} OVERLAY pair hooks; the number is what C_COLSO must cover\n")
print(f"{'short':>7} {'dlift':>6} {'hook':>5} {'rows':>5} {'charge':>7} "
      f"{'meas':>7}")
for d, dl, k, rows, cc, meas in short[:14]:
    print(f"{d:7.0f} {dl:6d} {k:5d} {rows:5d} {cc:7d} {meas:7.0f}")
if short:
    print(f"\nC_COLSO must be at least {short[0][0]:.0f} "
          f"(it is {P.C_COLSO}).")
