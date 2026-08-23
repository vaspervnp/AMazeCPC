# Free-movement / 5°-turn prototype

A working Python model of a **runtime-projection** renderer: free float `x, y`,
72 headings (5°), wall segments projected per frame and rasterised into the
same byte-granular, even-length `PUSH DE` horizontal runs the Z80 engine
already consumes. This is the feasibility study for "can we do Wolfenstein
here"; it is not wired into the build.

    python3 main.py        # render out/*.png and sweep the state space
    python3 vpsweep.py     # frame cost vs viewport size
    python3 precalc_size.py  # how big a precalculated table would have to be
    python3 verify_rays.py   # check the geometry against an independent DDA raycast

It needs `world.py`, `geom.py`, `cost.py`, `preview.py`, `cpchw.py` from
`../../tools` on `PYTHONPATH`.

## What it establishes

**Precalculating the span lists is impossible.** Cell-centres-only at 72
headings is 51.5 KB and fits — but buys no free movement. Adding sub-cell
positions explodes it: 2×2 = 199 KB, 4×4 = 717 KB, 8×8 (today's step
granularity) = **2.31 MB against 64 KB of banked RAM, 35× over**.

The cause is not more visible cells (32.8 face slots at cardinal facings vs
33.1 averaged over 72 angles). It is that **at any non-multiple of 90° no wall
is parallel to the image plane**, so the cheap RECT record — 8 bytes for a
whole face — collapses into a per-scanline SPANS record. The rect fraction
falls 76% → 36% and the mean config grows 1110 → 2556 bytes. Dedup already
saves 54% and mirroring only 28–45%; neither closes a 35× gap.

**Runtime projection is affordable, because the maths was never the problem.**
Marching the grid, projecting two corners through a reciprocal table and
setting up the edges costs ~2.3 ms mean / 11.6 ms worst. Fill dominates
everything. Sensitivity: moving the per-face cost 200 → 1200 µs shifts the
worst frame only 51.9 → 59.9 ms.

**Frame cost is set by viewport area, not by the movement model** — which is
the finding that actually matters. Measured, worst reachable state, both
corrections applied:

| Viewport | Bytes | Worst | Frames | fps |
|---|---|---|---|---|
| 64×92 | 32×92 | 35.1 ms | 2 | **25 (locked)** |
| 72×104 (shipped) | 36×104 | 41.6 ms | 3 | 16.7 |
| 112×144 | 56×144 | 73.5 ms | 4 | 12.5 |
| 160×160 | 80×160 | 110.5 ms | 6 | 8.3 |
| 160×160, 104° FOV | 80×160 | 98.2 ms | 5 | 10.0 |

## Accuracy

Checked against an independent per-column DDA raycast over 13080 views /
941760 columns: 94.7% of columns land within 1 px of truth. Of the 2.8% beyond
1.5 px, 2.72% is quantisation — byte-granular x plus the even-length rule
pinning sloped edges to a 4-pixel grid, which is the visible staircase in
`03_corridor_15deg.png` — and 0.12% is structural. 87 columns total (0.009%)
leak background through a wall corner.

## Caveats

- Painter's **back-to-front**, sorted by descending L1 cell distance. Exact for
  axis-aligned uniform grid boxes. Front-to-back would halve the 1.91× mean
  overdraw but needs a per-column clip array, which `PUSH DE` cannot test
  against — that is Doom's cost model, not this one.
- Shading is per face by radial distance to the face midpoint, not view-space
  z; z-based shading makes a whole wall jump a ramp step when you merely turn.
- At the shipped 38° FOV one 5° step slides the vanishing point 13% of the
  viewport width, which reads as a coarse turn. Widening the FOV fixes the feel
  and is roughly free.
- Pens 5 and 12 are both firmware ink 1, so far walls vanish into the near
  ceiling far more often at free angles than at four facings. Repalette before
  building this for real.
- The per-face and per-march-cell microsecond costs are hand-counted (±2×) and
  nothing in the repo constrains them. Write and measure that kernel on the
  emulator before committing to a viewport.
