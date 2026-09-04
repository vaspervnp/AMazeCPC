# AMazeCPC

A first-person maze for the Amstrad CPC 6128 with **free movement and 5-degree
turning**, rendered by projecting wall segments at runtime and filling them
with horizontal `PUSH DE` runs.

    make            # build/amaze.dsk
    make verify     # boot it and check everything on a real 6128 model
    make test       # collision, sliding, doors, turning
    make rast       # the rasteriser, byte for byte, over 180 screens
                    # -- twice: with and without the mid-quad yield
    make gun        # the weapon: every bob offset, byte for byte, then timed
    make pace       # the frame period and the walking speed that follows

Boot with `RUN"AMAZE`. A loading screen comes up while the tables and the
game load; **SPACE** goes past it, or it goes by itself after ten seconds.
Then a title screen lists the keys, and **SPACE** starts.

Arrow keys move and turn; **SHIFT** runs (and turns twice as fast);
**SPACE** opens a door you are standing beside; **CTRL** or **Z** fires;
**ESC** returns to BASIC.

See [plan.md](plan.md) for what a complete game still needs, and for the
map editor.

Six rounds, shown as pips in the HUD's top-left slot. Firing spends one and
kicks the weapon up; there is no way to reload except to walk over one of the
six ammunition pickups scattered around the map, which refill the magazine
outright.

Pickups are drawn on the floor as orange blocks, occluded by walls. The
**slot below the pips is a direction pad** pointing at the nearest one —
eight bearings around a white hub, relative to where you are looking, the
lit block yellow / orange / red by distance. The **dial is also a radar**:
ammo shows as orange blips and the monster as mauve, at their bearing and
at a radius that is their distance, with a sweep round the ticks.

| | |
|---|---|
| Screen | Mode 0, 16 colours |
| Viewport | 88×96 px at (18,0), HUD below |
| Field of view | 60° horizontal |
| Movement | free, 8.8 fixed point, 0.25-cell collision radius |
| Turning | 72 headings, 5° apart |
| Weapon | 28×38 px, anchored 4 scanlines *below* the bottom edge, bobs ±4 scanlines and ±2 bytes about that |
| Frame period | 119.8 ms, 8.35 fps — **locked**, every frame of every state |

## Why it is built this way

`PUSH DE` writes two bytes in 4 µs — 2 µs/byte, the fastest store on the
machine, and about half the cost of an equivalent bitmap blit. It is a
**horizontal** primitive, which decides the whole architecture: a classic
Wolfenstein raycaster draws *vertical* strips, and on the CPC's interleaved
screen (`base + (y&7)·&800 + (y>>3)·80`) those cost 5.4 µs/byte flat and 9–14
textured. That penalty is permanent — no CRTC programming removes it.

So instead of casting a ray per column, the engine marches the grid, projects
each visible wall segment, and rasterises the resulting quad into horizontal
runs. A projected wall has *vertical* left and right edges, so it splits into
a top wedge, a constant-width body and a bottom wedge; only the wedges pay
per-scanline work, and the body runs on the cheap path.

Three things make the geometry affordable:

- **View-space coordinates of grid corners are affine in the grid indices**, so
  the march carries `(xv, zv)` forward with two 16-bit adds per cell instead of
  four multiplies per endpoint. The frustum half-planes are affine too and ride
  along the same adds.
- **No divide.** `SXS[zv]` and `HH[zv]` are table lookups; a 16-bit divide is
  ~350 µs, a lookup is ~12 µs.
- **Side clipping happens in screen space.** The projection of a straight 3D
  line is a straight 2D line, so clamping x and interpolating the edge y is
  exact, and far cheaper than clipping in view space and re-projecting.

## What it cost to learn

Two estimates in this project were wrong by **7×** and **4×**. Both were caught
by measuring on a cycle-accurate emulator rather than arguing. The rule the
tooling now enforces: 100 NOPs must calibrate to 100.0 µs, the empty-loop
baseline is subtracted, and nothing is claimed that was not measured.

**Precalculating the geometry is impossible here, and that is worth knowing.**
Cell-centres-only at 72 headings fits in 51.5 KB — but buys no free movement.
Adding sub-cell positions explodes it: 2×2 = 199 KB, 8×8 = **2.31 MB against
64 KB of banked RAM**. The cause is not more visible cells; it is that at any
non-multiple of 90° *no wall is parallel to the image plane*, so a whole-face
rectangle record collapses into a per-scanline span list.

That is also why this runs at 8.35 fps where a cell-stepped, 4-facing engine
runs at 25: free movement charges twice. Geometry costs a fixed ~20 ms
regardless of viewport size, and a span record that a precalculated engine
*reads* for 28 µs must here be *computed* for ~88 µs.

## A constant frame period matters more than a fast one

The engine paces itself with a cost accumulator: each unit of work adds a
measured constant, and when the total approaches one 50 Hz period it yields to
vsync. That bounds every chunk below a frame without reading a clock, so the
loop takes exactly 6 vsyncs every time.

This was learned the hard way. An earlier build averaged 11.8 fps but ran
80/100/120/140 ms depending on the view, which made walking speed vary by
1.75×. Motion that changes speed reads far worse than motion that is uniformly
slower. Verified on the booted disc, 2013 states, 16104 game frames, period
sampled at 250 µs and not rounded: **one bar in the histogram, 119.8 ms,
100.000%** — and three corridors of quite different draw cost all walk the same
cells/s, spread 1.0000×.

## Stop sampling a state space you can afford to enumerate

The pacing question — *does any view need one more vsync wait than the budget
has?* — has 4 055 040 answers: 56 320 positions on the 24/256 movement lattice
that pass `game.asm`'s own collision box, times 72 headings. It used to be
answered by replaying a few thousand of them and measuring a few hundred on the
disc. **That is not enough, and the failures prove it.** Raising `C_QUAD` from
740 to 920 puts exactly **13 states out of 4 055 040** a whole period late — a
rock-steady 139.8 ms, confirmed on the disc at three of them by name. A
3000-state sample finds that with probability 0.01.

`engine2/tools/pacescan.py` replays the rule — same constants, same order, same
greedy — for **every** state, in about a minute on sixteen cores. There was
never a reason to sample it.

The disc sweep can't be exhaustive, so it is *seeded* instead:
`engine2/tools/emu_pace3.py` measures the states the offline replay names as the
worst packers alongside a uniform sample. The difference is not subtle. Built at
`PACE_FRAMES = 5` and swept:

| class | states | on pace | a period late |
|---|---|---|---|
| uniformly sampled | 300 | 300 | **0** |
| named by the model | 60 | 5 | **55** |

The uniform sample reports a clean lock on a disc where one frame in eight is
late.

**Every unit of work has to be charged, including the ones added last.** The
weapon was 3.16 ms of a 119.8 ms frame, and for one build it was charged to
nobody; two reachable states out of three hundred then sat at a rock-steady
139.8 ms. Not a jitter — a *reproducible* extra period, on exactly the states
whose last interval was already near the threshold. That is the failure mode of
an uncharged unit, and it is invisible to any check that only asks whether a
state is internally constant. `main3.asm`'s `GUN_CHARGED equ 0` rebuilds the
broken disc so the fix stays a controlled comparison rather than a claim.

**And a charge that stops being true is the same defect wearing a different
hat — in both directions.** The weapon was 3.16 ms at 28×38, 4.38 ms at 28×46,
and it is **3.31 ms** at 28×38 again; `C_GUN` went 3250 → 4500 → **3400** with
it. At 4500 the exhaustive replay named **28 states of 4 055 040** that ask for
a sixth wait, and 26 of those 28 measured a rock-steady **139.8 ms** on the
booted disc while 600 uniformly sampled states on the *same* disc all read
119.81.

**That item is now closed, and it was not closed by lowering `C_GUN`.** The
sprite came back to 38 rows, `emu_pacefit.py` re-benched the charged block at
**3307.7 µs** worst, `C_GUN` is 3400 — and then `C_QUAD` was **re-searched
against that number**, which is the lever that was always the right one: at
`C_GUN` 3400 a `C_QUAD` of 820 still leaves 2 states over budget, and 780/22 is
the largest charge with **zero**. The 28 states stay in
`emu_pace.py:OVERBUDGET` as the seed, because they are still the heaviest
packers in the maze and a uniform sample cannot find 28 states in four million:
on the booted disc all 28 now read **119.81 ms**.

Four more constants failed that test and are now fixed, all measured by
`engine2/tools/emu_holes.py` on the booted disc:

- `march_setup` cleared its 256-byte flood-mark array in one go with 128
  `PUSH HL`, on the one frame in 255 that the generation counter wrapped:
  **1884.1 µs against a flat `C_MSETUP` of 1450**. The wipe is now spread over
  64 frames, four bytes each, so every frame reads the same **1372.8 µs** — the
  generation only comes round every 255 frames, so a byte is always zeroed long
  before its value can be read as current again.
- `C_TAIL` was fitted to a `game_step` benched with **no keys held**. A
  `game_step` that turns and walks is 1120.4 µs and one that opens a door
  1463.0, so the real tail was 1305.9 µs against a constant of 1050. `C_TAIL`
  is now 1450, and the door — 691.9 µs, and only on the frame SPACE is
  tapped — is charged where it happens, through `cost_add`, which charges
  without waiting because `game_step` runs after `pace_drain` with the budget
  already spent.
- `C_MSETUP` was 1450, fitted to **one** bench of `march_setup` at **one**
  state. Its four seed multiplies and its L1 build depend on where the player
  stands and which way he faces: swept over the movement lattice the real
  range is 1372.8–1445.1 µs, so 1450 cleared its own worst case by 4.9 µs.
  That is a coincidence, not a bound. It is 1550.
- `C_HUD` had the same fault and was *already* under the truth: 1420 against a
  measured worst of **1422.5 µs at heading 54**, because the compass needle's
  eight blocks do not cross the same number of character rows at every angle.
  The 1360.2 µs it was fitted to is one heading transition. It is 1550.

Two more failed it when the viewport went from 40 to 44 bytes wide, and both
are the same mistake: **a constant that depends on the viewport, living in a
file that does not.**

- `C_BG` is bg_fill, a straight-line fill of a rectangle — the same number on
  every state, and a *different* number at every width: **8501.3 µs at 40×96,
  9215.8 at 44×96**, 178.6 µs a byte. It stayed at 8600 across the change,
  616 µs under the truth, and nothing spilled only because the march and the
  projector over-charged by more than bg\_fill under-charged. `pacemodel.py`
  kept its own copy of it and agreed, because both were wrong the same way; it
  now reads every `C_*` out of `main3.asm` instead.
- `C_QUAD` is worse, because it decays *silently*. `pace_quad` charges a
  scanline `C_QS + 2·bw` where the machine pays `18.78 + 1.976·bw`, so the
  per-scanline margin is ~4 µs at any width and the fixed `C_QUAD` is what
  actually carries the quad — while `bw` grows with the viewport. At 44×96 the
  tightest whole-frame margin was **+155 µs spread over 15 quads**, i.e. +10 µs
  a quad on a reading good to ±5.

That second number was almost missed, and how is worth recording:
`emu_pacefit.py` benched into a fixed 600 ms window, which gives 65 iterations
on bg\_fill but **17 on `raster_paced`**, because `raster_paced` is 35 ms a
call. 1/17 is 6%, or ±2000 µs — and it duly reported the same 35279.1 µs for
three states with quite different quad lists, then called the charge 1227 µs
*under* at one state and 3681 *over* at another. The bench now runs until the
counter reaches 400.

The invariant the pacing rests on is not "no spill observed" but **every unit
is charged and every constant is a one-sided upper bound** — and a constant
fitted at one state, or measured at 6% resolution, is not a bound.

The binding constraint is **the largest atomic unit, not the total slack**. The
weapon is the easy case and the reason it was easy: 3.25 ms is a sixth of an
interval, so it always fits *somewhere* in six of them. A `raster_quad` is up
to 12.5 ms and fits nowhere in particular.

`C_QUAD` is therefore not fitted, it is **searched**: it is the largest charge
with zero over-budget states across all 4 055 040 of them, which is a minute a
candidate rather than a rebuild (`pacescan.py sweep`, at 44×96):

| `C_QUAD`/`C_QS` | states needing a 6th wait |
|---|---|
| 740 / 22 | 0 |
| **780 / 22** | **0 — shipped** |
| 740 / 23 | 1 |
| 820 / 22 | 2 |
| 860 / 22 | 7 |
| 780 / 23 | 8 |
| 960 / 23 | 54 |

Bigger is safer and bigger packs worse, and at `C_GUN` 3400 the two meet at
780. **The number moves whenever any other charge moves**, which is the whole
reason it is searched and not fitted: the same table read 820 when the weapon
was charged 3250, and 700 when it was charged 4500. Re-run
`pacescan.py sweep` after touching *any* `C_*`.

**And shrinking that atomic unit costs more than it buys — measured.**
`raster.asm`'s `RQ_SPLIT` yields *inside* `raster_quad`, every 32 body
scanlines and every 8 wedge scanline pairs, charging what it has already
drawn rather than what the whole quad will cost. It works and it is exact:
`make rast` compares 180 screens byte for byte in **both** builds, and
`engine2/tools/emu_atomic.py` — which times `raster_quad` up to the *k*-th
hook and differences the result, so the intervals are measured and not
modelled — puts the largest atomic unit at **3415 µs against 12665**, 17% of
a vsync period instead of 63%.

What it costs is a hook, and the hook is **≈200 µs measured**. The worst
frame in this maze draws 16 quads, which is 42 chunk hooks where there was
one `pace_quad` each:

| | before | after |
|---|---|---|
| largest atomic unit | 12665 µs | 3415 µs |
| worst frame work | 93.00 ms | 101.50 ms |
| worst frame *charged* | ~95 ms | 116.34 ms |
| budget (`PACE_FRAMES × COST_THI`) | 116.74 ms | 116.74 ms |

The charge runs the accumulator out of budget, the greedy rule asks for a
sixth wait, and the frame takes a seventh period: sampled on the booted disc
over 1400 states and 11200 frames, **6 vsyncs 99.79%, 7 vsyncs 0.21%** — the
three states `(0160,0DE0) h69`, `(0160,0DE0) h67` and `(0150,0DF0) h67`, all
of them rock-steady at 139.8 ms. That is the *same* defect an uncharged unit
makes, arrived at from the opposite direction, and a constant period is worth
more than a small atomic unit. So `RQ_SPLIT` is **0** and the disc still
reads one bar at 119.8 ms. Chunk sizes were swept first (`pacemodel.py`
replays the rule offline): no power-of-two pair from 16/8 to 96/48 gets the
worst state back to five waits, because the floor is one body hook and one
wedge hook per quad whatever the chunk size, and 32 hooks is already 8.3 ms
of charge. The lever that would unlock it is a **cheaper hook**, not a finer
one.

(That table was measured at 40×96, which is what the disc was at the time. The
viewport is 44 now and `RQ_SPLIT` is still 0: widening makes every body scanline
more expensive, so the split's charge grows faster than the budget does.)

## Layout

    engine2/src/     the engine
      vpcfg.inc      viewport, FOV and MAXPUSH -- every table derives from this
      march.asm      incremental view-space grid flood
      project.asm    table-driven projection, screen-space side clipping
      kernel.asm     march + project -> painter-ordered quad list
      raster.asm     quads -> PUSH DE runs (wedge / body / wedge)
      bg.asm         floor and ceiling bands
      game.asm       movement, collision, doors, turning
      hud2.asm       compass and furniture
      gun.asm        the first-person weapon and its walking bob
      main3.asm      the frame loop and the cost accumulator
    engine2/tools/   generators, models and emulator harnesses
      pacemodel.py   the Python twin of the cost accumulator; reads every
                     C_* out of main3.asm rather than copying them
      pacescan.py    that rule replayed over ALL 4055040 reachable states,
                     and `sweep` -- the largest C_QUAD that still locks
      emu_pace3.py   the PERIOD on the booted disc, over the states the
                     model NAMES as worst as well as a uniform sample
      emu_pacefit.py the constants benched on the disc, each unit checked
                     one-sided on its own, at >= 400 iterations a reading
      emu_atomic.py  the LARGEST ATOMIC UNIT, measured by timing
                     raster_quad up to the k'th yield and differencing
      guardfit.py    the same exhaustive replay with ONE extra atomic unit
                     at the foot of the frame -- how much enemy fits
      enemyart.py    the guard: seven poses, five sizes, quantised BY HUE
                     and cut into per-scanline SEGMENT lists
    prototype/       the Python design study this engine was derived from
    tools/           the Python model the prototype imports

## The weapon

A hand holding a pistol sits at the bottom centre of the viewport and sways
while the player walks. `engine2/tools/gunart.py` owns the picture; the whole
design rests on one property of it — **every scanline of the silhouette is one
contiguous run**, so there is no mask, each row is a plain byte copy, and the
blitter has no inner test at all. `gentab.py` encodes it into bank 4 (262 bytes
of run data, 6 bands, two bob tables), because `main3.asm` has a couple of
hundred bytes of code space and no more.

It is drawn over the finished 3D view every frame and **never cleaned up**:
`bg_fill` repaints the whole viewport at the head of the next frame, so last
frame's gun is already gone.

**It is anchored below the bottom edge, and that is the whole difference
between a weapon that is carried and one that hovers.** The first version
bobbed 0–6 scanlines *upward only*, so the blitter could never be asked to
clip. The side effect was that the **resting** pose was the **lowest** one:
every step *lifted* the gun, it sat entirely inside the frame, and it read as
floating in front of the camera. Now 4 scanlines of the sprite hang past the
bottom of the viewport at the centre of the travel and are simply not drawn,
and the vertical bob swings **−4 … +4** about that anchor.

What that costs is **one comparison per band** — `gd_rem` carries the rows
still above `VP_Y+VP_H`, each band subtracts its own count, and the first band
that does not fit draws what is left and returns. It is not per-pixel clipping
and there is no test in the row loop at all. **The bottom is the only edge that
can clip**: the horizontal bob is ±2 whole *bytes* and stops 14 bytes short of
both sides, and the highest the sprite ever sits leaves its last row exactly on
the bottom edge, so it can never run off the top either. `gentab.py:self_check`
asserts all three at all 45 offsets.

The vertical table is a **triangle**, and it has to be: the smoothness rule is
that nothing moves more than one scanline a frame, and swinging 8 scanlines
down and 8 back up inside a 16-frame period is 16 unit moves in 16 frames — so
every frame moves by exactly one and there is no freedom left for a sine to
shape. Keeping the period at 16 is what keeps it mutually prime with the
horizontal 23; the horizontal has slack and stays a rounded sine, with an LFSR
nudging its phase, so the path is still a Lissajous that does not repeat. Both
offsets are stored **biased** and *ease* by at most one step a frame, which is
what makes it smooth and what walks the weapon back to the **anchor** — now the
middle of the travel, so it can ease either way — when the player stops.

`make gun` proves it rather than asserting it: all 45 bob offsets, **the whole
16 KB screen** compared byte for byte against the model — 737280 bytes, 0 wrong
— then `gun_step` run on the machine for 200 frames against the same rule in
Python, then timed. The comparison went from the viewport to the whole screen
*because* of the clamp: a row drawn past the bottom edge lands in the HUD,
which a viewport-only check cannot see. **`gun_draw` measures 2.40–3.09 ms and
`gun_step` 0.16 ms.**

### The blitter cannot silently disagree with the art

The sprite has been 38, 46, 30 and 38 rows, and every one of those changes
re-derives `GUN_ROWS0`, `GUN_Y0`, the band list, the size of `GUNPIX` and where
`BOBV`/`BOBH` land in bank 4. The failure that produced *4770 wrong bytes and
no orange hand at all* was never arithmetic in `gun.asm` — the blit is exact at
38 rows and, rebuilt and re-run at 46, still exact — it was the disc and the
Python art being **different generations of that derivation**. A pixel diff
cannot tell a broken blitter from a stale disc, and neither can it see a
correct-but-inconsistent build.

So the agreement is now checked in three places, not one:

- **`GUN_SIG`**, an FNV over the run list *and* the geometry, planted in
  `GAME3.BIN` and read off the running machine — `emu_gun.py` refuses to
  compare a pixel until it matches. This catches a **stale disc**.
- **Nine `assert`s in `gun.asm`**, against the equs `gentab.py` derived from
  the art: `GUN_ROWS0 == GUN_H-GUN_CUT-GUN_BOBVA`, rows-at-the-top-of-the-swing
  `<= GUN_H`, `GUN_CUT >= GUN_BOBVA`, `GUNPIX-GUNBAND == 5*GUN_NBAND+1`,
  `BOBV-GUNPIX == GUN_PIXN`, and the three placement bounds the blitter has no
  clip for. This catches a **stale assembly** — a disc whose tables and code
  are each self-consistent and disagree with each other, which is invisible to
  any byte comparison because the picture it draws is the one it was built to
  draw.
- **`assert len(blob) <= BANK_SIZE` in `gentab.py`.** The bank end was only
  ever *printed*. `TABLES.BIN` is `LOAD`ed flat at `&4000`, so one byte past
  `&7FFF` is a byte written into the back buffer — and `GUNPIX` is the table
  nearest the end and the one whose size follows the art. 180 bytes are free.

And it is **paid for**. `main3.asm:gun_paced` is `ld bc,C_GUN / cost_unit /
gun_step / gun_draw`: one more room-then-charge unit, so the accumulator takes
its vsync *in front of* the weapon on a frame the view has already filled and
*behind* it on one it has not.

**The blit is no longer the same cost on every frame, and that changed what the
charge has to be and how it has to be measured.** Rows drawn is `GUN_ROWS0`= 30
at the bottom of the swing and `GUN_H` = 38 at the top — a 684 µs spread — so
`C_GUN` bounds the *top*, not the mean. Measuring that needed a fix to the
harness first: `gun_paced` calls `gun_step`, `gun_step` walks the bob, and a
bench loop runs hundreds of iterations, so benching the block whole reports the
**mean over the bob cycle** whatever offset was poked in. `emu_pacefit.py`
stubs `gun_step` to `RET` so the offset stays put, sweeps `dy`, and adds
`gun_step`'s own walking cost back: **3307.7 µs** worst, at `dy` = +4.
`C_GUN` is **3400**.

**And that number is what `C_QUAD` is searched against.** `pacescan.py`,
exhaustive over all 4 055 040 states, at `C_QUAD` 820:

| `C_GUN` | states needing a 6th wait |
|---|---|
| 3250 (the old sprite's charge) | **0** |
| **3400 (the 28×38 truth)** | **2** |
| 4500 (the 28×46 truth) | 28 |

The honest weapon charge does *not* pack at the `C_QUAD` that was shipped with
it — at either sprite size. **The fix is never to lower `C_GUN`**, which is the
defect `GUN_CHARGED` exists to document; it is to re-run the search. At
`C_GUN` 3400 the largest `C_QUAD` with zero over-budget states is **780/22**,
and that is what ships. `pacescan.py` at the shipped constants reads:

| waits asked for | states | |
|---|---|---|
| 1 | 14 325 | 0.353 % |
| 2 | 2 529 775 | 62.386 % |
| 3 | 1 063 957 | 26.238 % |
| 4 | 434 489 | 10.715 % |
| 5 | 12 494 | 0.308 % |
| **6 — over budget** | **0** | **0 %** |

Worst charged frame **103 494 µs** of a 116 736 µs budget.

That worst frame is itself a case for enumerating: benched at the 40 heaviest
states a *sampled* replay could find, it measured 90.63 ms; benched at the 40
heaviest states there **are**, it measures **98.43 ms** — 21.38 ms of slack in
a 119.81 ms period. The sample understated the thing the whole slack figure is
about by nearly 8 ms.

And the disc agrees. Swept after the re-charge — 250 µs sampling, period read
off the CRTC R12 flip, the sample **seeded** with the 28 states the model used
to name as over budget:

| class | states | 119.81 ms | 139.78 ms |
|---|---|---|---|
| uniformly sampled + named worst packers | 300 | **300** | **0** |

2400 game frames, one bar in the histogram, 100.00 %. The named states matter:
a sweep that did not seed itself from the model reported a clean lock on the
disc where 26 of those 28 sat a whole period late, and it was wrong.

(Two harness bugs were found getting to that number, both of which had produced
readings that were simply not true. `emu_pace.py` read `(frame_ctr)` as sixteen
bits, but `LD (nn),HL` stores L and then H — so on the one frame in 256 the low
byte wraps, the pair reads `02FF → 0200`, and dividing by that delta reports a
frame drawn in **0.0 ms**. And `emu_pacefit.py`'s bench wrote its scratch
assembly to a fixed filename, so running it alongside `emu_gun.py` had each
process benching the other's blob: `gun_draw`, which is 2950.4 µs and stays
2950.4 with all sixteen cores spinning, read **19619.7**.)

## The enemy does not fit in six vsyncs, and the number is not close

`engine2/tools/enemyart.py` reads `engine2/art/guard/*.png` — seven poses on one
common canvas — quantises them **by hue** (nearest-RGB puts a brown uniform
closer to grey than to the only warm pen there is, which painted the whole
figure grey with orange speckles) and cuts each into per-scanline **segment
lists** at five widths. An enemy is not one run per scanline the way the weapon
is: a standing figure has a gap between the legs and between an arm and the
body, and filling those would paint the maze out behind him.

    24x41px  worst pose stand   307 bytes   55 segments
    18x31px  worst pose stand   176 bytes   42 segments
    12x21px  worst pose stand    81 bytes   25 segments
     8x14px  worst pose stand    41 bytes   14 segments
      6x10px worst pose shoot0   23 bytes   12 segments
    all poses, all sizes: 3780 bytes

At the weapon's **measured** blit rates — 4.99 µs a byte and 46.9 µs a
scanline, and a segment costs a scanline's worth of setup — the worst single
guard at 24 px is **≈ 4.1 ms**. That is the size of the problem.

**The frame has 21.38 ms of slack and cannot afford it, because the binding
constraint is the largest atomic unit and not the total.** The enemy pass has
to be one atomic unit: every guard is projected with bank 4 paged in (the
projector needs its tables), then the sprite bank is paged in and all of them
are blitted, so no vsync wait can fall inside it — the same argument that makes
`gun_draw` one unit. `engine2/tools/guardfit.py` replays `pacescan.py`'s rule
over all 4 055 040 states with exactly one extra room-then-charge unit of
`C_GUARD` µs appended after `gun_paced`:

| `C_QUAD` | largest `C_GUARD` with 0 over-budget states |
|---|---|
| **780 — shipped** | **0** (1000 puts 13 states over) |
| 740 | 0 (1000 puts 1 state over) |
| 700 | 1000 |
| 640 | 1000 |
| 580 | 1000 |
| 520 | 2000 |
| 460 | 2000 |

Buying room by lowering `C_QUAD` stops being honest below about 740 — the
measured per-quad margin at 740/22 was **+10 µs on a reading good to ±5** — and
even at an indefensible 460 the answer is 2000 µs. So at `PACE_FRAMES` 6:

- a guard in the **6×10 or 8×14** band (≈ 0.7–0.9 ms) is the only one that
  fits, and only if `C_QUAD` comes down to 700;
- **12×21 (≈ 1.6 ms), 18×31 and 24×41 do not fit at all**;
- and this is *before* charging the projector, the depth-sorted insertion into
  the quad list or the per-segment viewport clip.

Guards therefore are **not in the build**. Drawing them anyway would put some
frames a whole period late, which is the one thing this engine will not do.

**What *would* fit is one more vsync.** The same exhaustive replay at
`PACE_FRAMES` 7, `C_QUAD` 780 unchanged:

| `C_GUARD` | 2000 | 4000 | 6000 | 8000 | 10000 | 12000 | 14000 | 16000 |
|---|---|---|---|---|---|---|---|---|
| states over budget | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

16 ms of enemy — four near guards at the largest size, with the projector and
the sort paid for — locks at seven periods with zero over-budget states out of
4 055 040. The price is the frame period: **139.8 ms, 7.15 fps**, 17 % slower
everywhere. That is the trade, stated rather than taken: a constant 7.15 fps
with enemies, or a constant 8.35 fps without them. It is not a decision to make
silently, and it is not one to make by shipping frames that run long.

## The door still has no retraction animation

`game.asm` already runs the five states 2 (shut) … 6 (open) one step per game
frame on the existing door timer, and `emu_game.py` reads the intermediate
states off the machine. What is missing is the *picture*: `SOLID` is set to 2
for every state but 6, so a partly open door is opaque, impassable, and drawn
as a whole door face — and then vanishes between one frame and the next.

The projection identity the retraction needs is cheap and is the one the stone
courses used: at a fixed screen x the projection of wall **height** is linear,
so the panel bottom at openness *t* is `ytop + (ybot - ytop)·(1 - t)` at each
end of the quad the kernel already emitted. No reprojection and no new face.

**What blocks it is the rasteriser's shape, not the maths.** `raster_quad`
draws a region bounded by `CY - h(x)` and `CY + h(x)` — symmetric about the
horizon — and the panel is bounded by `CY - h(x)` and `CY + s·h(x)` with
`s = 1 - 2t`. For `s >= 0` that decomposes into two things the existing code
can already draw (the top half at `h`, the bottom half at `s·h`, which is just
the same quad with `hlo`/`hhi` scaled). For `s < 0` — which is every state past
half open, and a portcullis has to pass through them to reach zero height at
the **ceiling** — the panel is a band between *two* sloped edges above the
horizon, and no combination of row windows and height scaling produces it. It
needs a scanline loop with **two** Bresenham edges, which is a new ~200-byte
routine, its own charge, and its own entry in `emu_rast.py`'s byte-for-byte
model. Under 383 bytes are free below `BUCKETS`.

## Known issues

- Walking speed varies 1.042× with heading: `STEPTAB` is built with `int()`,
  which floors, so the step is 23.431–24.413/256 depending on direction.
- At 8.35 fps the keyboard is polled once per frame, so taps under ~100 ms are
  dropped.
- `COURSES` in `vpcfg.inc` switches on stone-course mortar joints. It is `0`,
  and it can no longer simply be switched to `1`: the joints' pen 14 is now the
  weapon's slide, and the 500 bytes of `raster_joint` are only assembled when
  `COURSES` is set, which is what paid for `gun.asm`. `gentab.py` refuses the
  combination rather than building glowing joints.
