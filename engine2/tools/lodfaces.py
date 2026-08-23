"""How big is a face at each k, in PIXELS, and how wide would a 1/4-cell
block be?  Sampled off the real march+project."""
import sys, random, statistics, collections
sys.path.insert(0,'/home/vasilhs/repos/AMazeCPC/engine2/tools')
import pacescan, marchmodel as mm, projmodel as pm, rastermodel as rm

solid, pos = pacescan.positions()
c = rm.cfg()
rnd = random.Random(4242)
st = [(p[0],p[1],a) for p in rnd.sample(pos, 3000) for a in (rnd.randrange(72),)]
W = collections.defaultdict(list)   # k -> (width px, height px)
for px,py,a in st:
    r = mm.march(solid, px, py, a)
    ipx,ipy = px>>8, py>>8
    for (wx,wy,fd,door,k), v in zip(r["faces"], r["fviews"]):
        (ax,ay),_b,_n = pm.face_endpoints(wx,wy,fd)
        q = pm.project_face(v[0],v[1],v[2],v[3], ax-ipx, ay-ipy, fd)
        if q is None: continue
        blo,bhi,hlo,hhi = q[0],q[1],q[2],q[3]
        wpx = abs(bhi-blo)*2                 # bytes -> mode-0 pixels
        hpx = min(c.VP_H, 2*(hhi>>4))        # tall end, clipped
        W[k].append((wpx,hpx))
print(f"{'k':>3} {'faces':>7} {'width px':>22} {'height px (tall end)':>24} "
      f"{'1/4-cell block px':>18}")
print(f"{'':>3} {'':>7} {'p10   med   p90   max':>22} "
      f"{'p10   med   p90   max':>24}")
for k in sorted(W):
    ws = sorted(x[0] for x in W[k]); hs = sorted(x[1] for x in W[k])
    def q(v,f): return v[min(len(v)-1,int(f*len(v)))]
    med = q(ws,.5)
    print(f"{k:>3} {len(ws):>7}  {q(ws,.1):4d} {med:5d} {q(ws,.9):5d} {ws[-1]:5d}"
          f"   {q(hs,.1):5d} {q(hs,.5):5d} {q(hs,.9):5d} {hs[-1]:5d}"
          f"      {med/4.0:8.1f}")
