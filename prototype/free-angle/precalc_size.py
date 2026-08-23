"""How big would the PRECALCULATED table be if we kept the current
architecture and merely added angles and 2-D sub-positions?

Same record encoding as tools/gen.py:
    RECT   8 bytes
    SPANS  4 + 3 * nlines bytes
plus a per-state index of the faces that fall inside the frustum.

Symmetry that is genuinely free (the shipped engine already uses it):
    * 4-fold rotation -- a 90 deg turn is a relabelling of the maze axes
      (FDELTA / RDELTA), so only headings 0..85 deg need tables: 18 of 72.
Symmetry that is NOT free:
    * left/right mirror would halve it again, but a Mode 0 span record bakes
      absolute screen addresses, so mirroring costs an address recomputation
      per scanline at runtime (~10 us/line).  Reported separately.
"""

import math
import sys

import geom
import world
import free

REC_RECT = 8                    # DB kind, DB colour, DW end, DB h, npush, crow, yield
REC_SPAN_HDR = 4                # DB kind, DB colour + DW 0 terminator
REC_SPAN_LINE = 3               # DB lo, hi, jmp

IDX_ENTRY = 5                   # DB dx, DB dy, DB side, DW record pointer

RANGE = 6                       # dx, dy in -RANGE..RANGE


def rec_bytes(g):
    if hasattr(g, "lines"):
        return REC_SPAN_HDR + REC_SPAN_LINE * len(g.lines)
    return REC_RECT


def state_faces(ox, oy, a_idx):
    """Every face slot that lands inside the frustum for this player state,
    with NO maze knowledge (precalc cannot know what is solid)."""
    px, py = ox, oy
    fwd, rgt = free.basis(a_idx)
    out = []
    for dy in range(-RANGE, RANGE + 1):
        for dx in range(-RANGE, RANGE + 1):
            for side in range(4):
                r = free.project_face(dx, dy, side, px, py, fwd, rgt)
                if r is None:
                    continue
                g = free.rasterise(r[0])
                if g is None:
                    continue
                out.append(((dx, dy, side), g))
    return out


def survey(n_sub, n_ang=18):
    """n_sub x n_sub sub-positions per cell, n_ang headings over 90 deg."""
    pool = {}
    total_rec = 0
    total_idx = 0
    n_faces = 0
    step = 72 // (4 * n_ang) if n_ang <= 18 else 1
    for iy in range(n_sub):
        for ix in range(n_sub):
            ox = (ix + 0.5) / n_sub
            oy = (iy + 0.5) / n_sub
            for k in range(n_ang):
                a = k * step
                fs = state_faces(ox, oy, a)
                n_faces += len(fs)
                total_idx += IDX_ENTRY * len(fs) + 2
                for _slot, g in fs:
                    key = (repr(g),)
                    if key not in pool:
                        pool[key] = rec_bytes(g)
                        total_rec += pool[key]
    n_states = n_sub * n_sub * n_ang
    return dict(n_sub=n_sub, n_ang=n_ang, n_states=n_states,
                faces_per_state=n_faces / n_states,
                unique=len(pool), rec_bytes=total_rec, idx_bytes=total_idx,
                total=total_rec + total_idx)


def main():
    print("Precalculated-table size if we keep the current architecture")
    print("  frustum: dx,dy in -6..6, 4 sides;  headings 0..85 deg only "
          "(4-fold rotation is free)")
    print("  budget: ~64 KB of pageable RAM on a 6128 "
          "(4 x 16K banks at &4000)\n")
    hdr = (f"{'sub/cell':>9s} {'headings':>9s} {'states':>7s} "
           f"{'faces/st':>9s} {'unique recs':>12s} {'record KB':>10s} "
           f"{'index KB':>9s} {'TOTAL KB':>9s} {'x over 64K':>11s}")
    print(hdr)
    print("-" * len(hdr))
    cases = []
    for n_sub in (1, 2, 3, 4, 6, 8):
        for n_ang in (18,):
            cases.append((n_sub, n_ang))
    cases += [(4, 9), (4, 6), (2, 9)]
    for n_sub, n_ang in cases:
        r = survey(n_sub, n_ang)
        kb = r["total"] / 1024.0
        print(f"{n_sub:>4d}x{n_sub:<4d} {n_ang*4:>9d} {r['n_states']:>7d} "
              f"{r['faces_per_state']:>9.1f} {r['unique']:>12d} "
              f"{r['rec_bytes']/1024:>10.1f} {r['idx_bytes']/1024:>9.1f} "
              f"{kb:>9.1f} {kb/64:>11.1f}")
    print()
    print("  'headings' counts all 360 deg; only a quarter of them are stored.")
    print("  A left/right mirror would roughly halve the record bytes but a "
          "Mode 0\n  record bakes absolute screen addresses, so mirroring "
          "costs ~10 us/scanline\n  of address recomputation at runtime.")


if __name__ == "__main__":
    sys.exit(main())
