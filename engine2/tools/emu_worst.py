"""Directly MEASURE the true worst geometry frame: take the top states by
every ranking we have (fixed-point counters and free.py counters and the
fitted prediction) and time all of them on the emulator."""
import sys, math
sys.path.insert(0,'engine2/tools'); sys.path.insert(0,'tools'); sys.path.insert(0,'prototype/free-angle')
import emu_kernel as EK, marchmodel as mm, world, free, geom, gentab, fcost_measured as F
# The viewport comes from engine2/src/vpcfg.inc, via gentab -- NOT from a
# copy pasted here, which would silently disagree with the tables.
geom.VP_BX, geom.VP_BW = gentab.VP_BX, gentab.VP_BW
geom.VP_Y, geom.VP_H = gentab.VP_Y, gentab.VP_H
geom.VP_PW = gentab.VP_PW
geom.CX, geom.CY = gentab.CX, gentab.CY

geom.ZNEAR = gentab.ZNEAR; free.ZNEAR = gentab.ZNEAR
free.set_focal(gentab.FOCAL_H, gentab.FOCAL_V); free.R_MAX=6

grid,_,_=world.load_maze(); solid=mm.solid_from_grid(grid)
OFFS=[(128,128),(64,128),(128,64),(77,179),(26,26),(230,230),(128,230),(230,128)]
rows=[]
for y in range(16):
    for x in range(16):
        if grid[y][x]!=world.FLOOR: continue
        for fx,fy in OFFS:
            px,py=(x<<8)|fx,(y<<8)|fy
            for a in range(72):
                r=mm.march(solid,px,py,a)
                ref=mm.march(solid,px,py,a,push_opaque=True)["visited"]
                f=free.build_frame(grid,px/256.0,py/256.0,a)
                pred=7672+543.5*f["cells_visited"]+1233.5*f["n_faces"]
                rows.append((pred, ref, len(r["faces"]), px,py,a,
                             f["cells_visited"], f["n_faces"]))
print("surveyed",len(rows),"states (8 offsets x 72 headings)",flush=True)
cand={}
for key,idx in (("pred",0),("z80cells",1),("z80faces",2)):
    for r in sorted(rows,key=lambda t:-t[idx])[:12]:
        cand[(r[3],r[4],r[5])]=r
print("measuring",len(cand),"extreme states on the emulator",flush=True)
rig=EK.Rig(); ovh=rig.bench(EK.E_EMPTY,0x0A80,0x0D80,0)
res=[]
for (px,py,a),r in cand.items():
    t=rig.bench(EK.E_ALL,px,py,a,us=2000000)-ovh
    res.append((t,r))
res.sort(reverse=True)
print("%9s %9s %8s %8s %9s %9s  state"%("meas us","pred us","z80cell","z80face","freecell","freeface"))
for t,r in res[:14]:
    print("%9.0f %9.0f %8d %8d %9d %9d  (%d,%d.%02x)a%d"%(t,r[0],r[1],r[2],r[6],r[7],r[3]>>8,r[4]>>8,r[3]&255,r[5]))
print("\nTRUE MEASURED WORST GEOMETRY FRAME: %.0f us = %.2f ms"%(res[0][0],res[0][0]/1000.0))
