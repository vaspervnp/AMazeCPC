"""Wall-fill microseconds (MEASURED per-byte/per-run constants, not the
pacing CHARGE) for the states the exhaustive pacing scan named as worst."""
import sys, json, os
sys.path.insert(0,'/home/vasilhs/repos/AMazeCPC/engine2/tools')
import lodscan as L

STATES = [
 (0x0140,0x0DE0,68),(0x0140,0x0DF8,67),(0x0148,0x0DF8,67),(0x0140,0x0DF0,67),
 (0x0150,0x0DF8,67),(0x0140,0x0500,15),(0x0140,0x0508,15),(0x0140,0x0510,15),
 (0x0740,0x06F8,56),(0x0758,0x06F8,56),(0x0740,0x06F0,56),(0x0C10,0x09B0,59),
 (0x0EB8,0x0140,21),(0x0EB0,0x0140,21),(0x09A8,0x0700,20),(0x0758,0x06F8,55),
 (0x02B8,0x0140,20),(0x0460,0x0140,2),(0x01D8,0x0180,36),(0x09B8,0x0180,18),
]
p = '/home/vasilhs/repos/AMazeCPC/engine2/build/pacescan_top.json'
if os.path.exists(p):
    STATES += [(px,py,a) for _c,px,py,a in json.load(open(p))]

if __name__ == "__main__":
    L._init()
    seen=set(); rows=[]
    for st in STATES:
        if st in seen: continue
        seen.add(st)
        rows.append((st, L.V(L._state(*st))))
    print(f"{len(rows)} named worst states\n")
    print(f"{'architecture':56} {'worst raster ms':>16}   at")
    print('-'*100)
    for name, fn in L.COSTS:
        best = max(rows, key=lambda r: fn(r[1]))
        print(f"{name:56} {fn(best[1])/1000:16.2f}   "
              f"(0x{best[0][0]:04X},0x{best[0][1]:04X},{best[0][2]})")
    # and the byte split at the single worst-today state
    st, v = max(rows, key=lambda r: L.cost_today(r[1]))
    print(f"\nbyte split at the worst-today state "
          f"(0x{st[0]:04X},0x{st[1]:04X},{st[2]}):")
    print(f"  {'k':>3} {'quads':>6} {'runs':>6} {'bytes':>7}")
    for k in range(1,8):
        if v.q[k]: print(f"  {k:>3} {v.q[k]:6d} {v.r[k]:6d} {v.b[k]:7d}")
    print(f"  tot {v.s('q'):6d} {v.s('r'):6d} {v.s('b'):7d}")
