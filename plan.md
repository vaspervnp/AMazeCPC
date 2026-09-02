# AMAZE — plan

What exists, what a complete game still needs, and how the map editor
fits. Written against the engine as it stands, with the costs measured
rather than guessed, because on this machine the budget decides the
design.

---

## The constraint everything else answers to

The disc runs at **10 vsyncs a frame — 199.7 ms, 5.01 fps** — and for the
map as it loads that period is now *locked over the whole state space*,
not over a walked path. `main3.asm` carries a cost accumulator, every
unit of work is charged an upper bound before it runs, and `pace_drain`
spends whatever is left.

So the budget is **194560 µs a frame**:

| where it goes | µs | share |
|---|---:|---:|
| `rastcol` — the textured column renderer | 126000–205000 | 65–75% |
| `bg_fill` — ceiling and floor | 9320 | 4.8% |
| the world overlay (pickup, monster, shot) | 8200 | 4.2% |
| the tail carried into the next head (`C_TAIL`+`C_SND`+`C_DOORACT`) | 8100 | 4.2% |
| march + project | 16000–24000 | 8–12% |

**Two numbers to keep in front of you:**

- The head carries **8100 µs at worst**, not the 16430 the model once
  charged. `pace_drain` ends every frame with `ld h,a / ld l,a /
  ld (cost_acc),hl` at a = 0 — it **zeroes** the accumulator — and
  `hud_ammo`, `hud_scan` and `hud_radar` are all called *before* it. So
  `C_AMMO`, `C_SCAN`, `C_SWEEP`, `C_BLIP` and `C_RNEEDLE` can never
  reach the next frame. The only charge that outlives the drain is
  `game.asm`'s `C_DOORACT`. 8100 + `C_BG` 9320 = 17420, **2036 under**
  `COST_THI` — `bg_fill` does not yield at the head on any frame.
- `hud_rect` costs **~70 µs a row** — a LINETAB lookup per scanline. A
  tall narrow rectangle is nearly all rows. That single fact has shaped
  the ammo pips (3811 µs), the monster (capped at 28 rows) and the
  radar.

---

## The period, and what 9 → 10 bought

`pacescan.py` replays the accumulator over **every** state a player can
stand in — 112896 positions that pass `game.asm`'s own collision box,
times 72 headings — in each of the three door configurations.

| doors | at `PACE_FRAMES` 9 | at 10 | worst charged frame |
|---|---:|---:|---:|
| shut — the map as it loads | 1.768% | **0.000%** | 169232 µs |
| open | 4.974% | **0.199%** | 190152 µs |
| moving | 37.908% | 19.261% | 259107 µs |

Zero out of 8128512. That is the sentence this project has had to
withdraw twice, and this is the first time it rests on an exhaustive
sweep against constants `emu_holes.py` calls one-sided upper bounds on
the same build.

The cost was 20 ms a frame — 5.56 fps becomes 5.01, and walking slows
with it, because a step is per *frame*. What it bought, besides the
zero, is the headroom the monster's pursuit was then spent out of:
`C_TAIL` went 3700 → 3900 for `mon_move` the same day, and at
`PACE_FRAMES` 9 that alone would have put states back over.

**Doors open is still 0.199%** — one frame in 500 — and its worst frame,
190152, is *inside* the 194560 budget. So what remains is greedy-packing
waste, not work that does not fit. `cost_unit` yields when the next unit
does not fit and throws the rest of the interval away, so waste scales
with the biggest units; after `C_BG` the biggest is `C_PIP` at 8200, one
hook in front of all three of `pip.asm`'s drawers. Splitting it three
ways is the same move `RQ_SPLIT` is in `raster.asm`, and like `RQ_SPLIT`
it wants measuring before believing. Not done.

**Doors in motion is halved but not solved** — 19.261%, worst frame
259107, the moving-door overlay pass drawing a second time. A player
cannot make sixteen doors move at once, so it bounds a case that does not
occur rather than describing one that does; it is still the one
configuration this engine cannot claim.

---

## How the pacing tools came to be trusted

At `PACE_FRAMES` 9 the disc really did drop periods, and it was checked
on the machine rather than argued from the model. Five of the doors-shut
states the model damned were fed to `emu_pace`'s rig, a fresh boot each:

```
OVER    (0x0EB0,0x0B68,43)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0EA0,0x0E70,61)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0B90,0x0EA0, 7)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0B60,0x0B90,25)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0970,0x0B60,43)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
control (0x0350,0x0C80, 0)   [ 9] vsyncs = 179.5 ms   on pace
control (0x0680,0x0680,36)   [ 9] vsyncs = 179.5 ms   on pace
```

Five out of five, and `emu_verify3` still reported the period LOCKED
because the six views it walks were not among them. **That is what
`PACE_FRAMES` 10 is for**: those states now fit, and so does every other
one with the doors shut.

Three defects in the *tools* were hiding a fourth in the *engine*, and
none of it was findable while the first one was live.

### The one that hid all the others: `make pace` stopped at line 16

`make` halts on the first command that exits non-zero. `pacescan.py` was
the *first* line of the `pace` recipe, and it has been exiting 1 since
some point after `37ef9f2`. Everything below it — `emu_pacefit`,
**`emu_holes`**, `emu_atomic`, `emu_pace3`, `emu_pace` — silently stopped
running. **The noisier the pacing got, the less of it ran.**

`emu_holes.py` is the tool that benches the frame TAIL. Sixteen commits
after it last ran, `017e8ef` moved `ammo_scan`, `mon_scan` and
`fire_edge` inside `game_step`. Measured the day the gate was reopened:

```
flip                                62.7 µs
main_loop head                     168.5 µs
game_step, worst over 200 states  3342.2 µs
                                  --------
tail                              3573.4 µs   against C_TAIL 1950
```

**1623 µs under, in the head of the frame.** `emu_holes` printed
`EVERY CONSTANT A ONE-SIDED UPPER BOUND: False`, which is the sentence
the whole pacing argument rests on being True.

It is a self-sustaining failure: a state goes over budget → `pacescan`
exits 1 → the bench that would catch an under-charge never runs → a
constant drifts under the truth → the model says frames fit while the
disc drops periods → more states go over budget. The mechanism that
would catch the problem was disabled *by* the problem.

Fixed both ends: `C_TAIL` is 3700 (3573.4 + 126.6, the margin `C_HUD`
carries), and the `pace` recipe is a loop that runs every tool, collects
the exit codes and fails at the end.

### What the tools had wrong

**The two of them disagreed about what "over" means.**
`pacescan.py:152` flags `w >= PACE_FRAMES`; `pacemodel.py` returned pass
on `max(hist) <= PACE_FRAMES`. `pacescan`'s own legend reads
`{k} waits -> {k+1} periods` — nine waits is **ten periods**. So
`pacemodel` exited 0 on a state space `pacescan` called over budget, and
its histogram's last row was the over-budget row without saying so. Read
together they looked like a pass with headroom. Fixed: `<` not `<=`, and
the histogram now labels the periods and marks the bucket.

**Both put the HUD's `cost_add`s in the frame head.** The disc charges
them mid-frame and then `pace_drain` zeroes the accumulator, so they can
never reach the next head. A modelled head of 16230 forced `bg_fill`'s
`cost_unit` to yield on the first unit of *every* frame — and a yield
costs a wait, which put the whole histogram one column right. Fixed:
`units()` emits them where `main3.asm:1047-1051` runs them, and
`pacemodel.frame_head()` is now the single definition of what the head
carries. Five tools had four different answers; `emu_pace3.py` and
`guardfit.py` were 2200 µs light because nobody added `C_SND` to them.

For the record, since the intermediate numbers are misleading if quoted
alone: as-committed read 3.956% / 6.456% / 40.85%, and with the five
charges deleted outright 0.054% / 1.295% / 28.55%. The truth is between
them, and it is the table above.

### What that exposed: `cost_add` can overrun a whole period

This is the real finding, and it was invisible while the model kept
those charges in the tail.

`cost_add` neither rooms nor tests — that is its purpose. But
`hud_ammo`, `hud_scan` and `hud_radar` make **five of them in a row**
between `C_HUD`'s `cost_unit` and `C_PIP`'s, with nothing in between.
`cost_unit` lets the accumulator reach `COST_THI - 1` = 19455, so that
run can leave it at

```
19455 + C_AMMO 4000 + C_SCAN 650 + C_SWEEP 1000
      + 8*C_BLIP 3680 + C_RNEEDLE 750   =  29535 µs
```

in one interval, against a **19968 µs period**. And it does not need the
pessimistic case: from 19455, anything over **514 µs** overflows, and
`C_BLIP` alone is 460.

`main3.asm` states the invariant this breaks in its own words — *"every
interval between two waits therefore holds under 19530 µs of ESTIMATE
and so under 19530 µs of real time, inside a 19968 µs period, WITHOUT A
TIMER"*.

### The gate: built, measured, taken back out

It looked like the same defect `cost_gate` was added to fix. It is not,
and finding that out cost building it.

Two gates went in, each `COST_THI` less the worst run of `cost_add`s
that followed it, exactly the way `FACE_THI` sits one face below
`COST_THI`. Then the whole state space, per arrangement:

| `HUD_GATE` | over budget, doors shut | mean waits |
|---|---:|---:|
| **none — what ships** | 69381 = **0.854%** | 7.176 |
| one gate @9376 | 738216 = **9.082%** | 7.815 |
| two gates @14806 / @14026 | 222372 = **2.736%** | 7.440 |

**Three times worse** in the better arrangement, ten in the worse. And
re-measuring the five off-pace states on the booted disc with the gates
in returned exactly what it had without them: `[10] vsyncs`, five of
five, unchanged.

**Because these are two different failures with one symptom.** Either
an interval *overruns* a period — one `pace_wait` spans two vsync edges
while `pace_left` is decremented once — or the budget is *exhausted*,
the work honestly needing more yields than `PACE_FRAMES` has, and
`pace_wait` waits anyway without decrementing. Both end the frame one
period late, since every wait still lands on an edge either way, and
29535 is under two periods so an overrun cannot cost more than one.

Both were the **second** kind. The worst charged frame fits inside the
budget in every configuration but doors-moving — the work *fits*; the
greedy packing is what does not. A gate is one more yield, so it trades a
rare late frame for a common one. **Giving the frame a tenth period was
the fix, because the failure was a budget, not an overrun.**

`pacemodel.HUD_GATE` still models all three arrangements so the table
can be re-run; the disc is 0.

**And nothing ran `make pace` for the sound commit.** `emu_verify3`
walks a path; it does not sweep the space, and it passed because it
never stood on one of the bad states. The Makefile says why that is not
the test: *"the states that break a period are three in a million and a
sample does not visit them."*

### And the one the fixed tools then found: you walked west facing south

`emu_pace.py walk` crashed — `runs[0]`, IndexError — because
`corridors()` wants straight runs of ≥4 open cells and the map is nine
4×4 rooms, so the longest is 3. Lowering it to 3 made the tool run, and
the third corridor then measured **0.000 cells walked** along its own
axis.

That is not a tool bug. `corridors()` asks for heading 18 believing it is
south. Measured on the disc, poking `plr_a` and reading `mv_dx`/`mv_dy`:

```
 a    wanted      got
18     90.0 deg   180.0      <-- due WEST
24    120.0       150.3
30    150.0       119.7
```

Quadrants 0, 2 and 3 are exact. `step_vector` folds one quarter of
`STEPTAB` four ways, and the **quadrant 1 fold produced `(-cos t, sin t)`
where it wanted `(-sin t, cos t)`** — the `ex de,hl` dance after the swap
swapped it back. `sv_store` reads only D and E, so the whole HL detour
was moving a value that was already in place.

**And the renderer was right the whole time.** `gen_march.py` writes
`MARCHTB` for all 72 headings out of Python's own cos/sin, with no
folding; `MARCHTB[18]`'s forward vector is `(0, 1024)` — due south. So on
**eighteen of the seventy-two headings the player looked south and walked
west.**

Nothing caught it because nothing tested quadrant 1: `emu_verify3`
checked heading 0 and heading 63, the walk test walks east, and the
pacing sweeps index the view by heading (correct table) and the movement
by position (no heading at all). `emu_verify3` now sweeps all 72 against
5a.

### Where `make pace` stands now

| tool | |
|---|---|
| `pacescan.py` | **exits 1 by design** — doors open 0.199%, doors moving 19.261% |
| `pacemodel.py 3000` | PASS |
| `emu_pacefit.py 40 worst` | PASS — every unit a one-sided upper bound |
| `emu_holes.py 60` | PASS — `EVERY CONSTANT A ONE-SIDED UPPER BOUND: True` |
| `emu_atomic.py 6` | **FAILS TO BUILD, and not from anything here** |
| `emu_pace3.py` | `LOCKED: True`, 10184 frames |
| `emu_pace.py 600` | `LOCKED: True`, 4800 frames, 39 named bad states |
| `emu_pace.py walk` | `spread 1.0000x` — all three corridors at 0.4695 cells/s |

**`emu_atomic` is a pre-existing breakage.** It assembles
`engine2/test/tst_rast.asm`, which references `RASTER_QUAD`,
`RASTER_FRAME`, `RC_BUF` and `RC_EBUF` — symbols the raster restructure
removed. Nothing in this work touches `raster.asm` or `engine2/test/`.
It is the *span* renderer's harness and `VPCOL` is 1, so it guards the
fallback rather than the disc — but it has been unbuildable for a long
time and only became visible once the recipe stopped halting at line 16.

### And a fourth, in the rig every pacing tool boots on

`emu_pace.Rig.place()` teleports the player by writing a six-byte stub —
`DI / LD SP,#3FF0 / JP main_loop` — at **#39C0** and jumping to it. That
address is not free RAM: `march.asm` has `FTAB equ #3900`, 256 bytes of
L1 tables refilled **every frame**. The stub was written once, at boot.

```
stub bytes at #39C0 after a few frames of play:
   03020100010203   expected  f331f03fc3b000
```

That is an L1 distance ramp sitting where the code should be. Measured:
the *first* `place()` works and the *second* hangs the machine — 0 game
frames in 30 CPC frames, on every state tried. `emu_verify3.py` has
always rewritten the bytes before each jump, which is exactly why it
never saw this and why its results stand. Fixed by doing the same.

---

## What is in the disc today

- Free movement on an 8.8 lattice, 72 headings, 0.25-cell collision box.
- Textured column renderer, byte-exact against `colmodel.py` over 166
  screens; flat far plane; doors that slide up over six frames.
- HUD: compass dial with needle, six ammo pips, an eight-point direction
  pad, and a radar — ammo blips in orange and the monster in mauve at a
  bearing and a radius, with an eight-step sweep round the ticks.
- Shooting: CTRL or Z, six rounds, recoil, muzzle flash, and an impact
  mark that is blood or stone depending on what the centre column pair
  had in it.
- Six ammunition pickups drawn on the floor, occluded exactly by the
  wall line the renderer leaves in `rc_dn`.
- **One monster that walks at you and can be killed.** 3 hit points, one
  cell every 6 frames, greedy pursuit; at 0 it leaves the map and its
  radar blip goes out. The aim cone is the three column pairs it actually
  paints, so you have to point at it.
- A title screen with the keys and the credit line.
- Sound: six AY effects, ticked at a true 50 Hz out of `wait_vsync` —
  the shot picks stone or flesh from the same test the impact mark does.

---

## What a complete game still needs

Ordered by what unlocks the most, with the honest cost of each.

### 1. The monster — *half done*

- ~~**Hit points and death.**~~ **Done.** `MON_HPMAX` 3, taken off in
  `mon_hit` on the frames `fx_fire` comes back `FX_BLOOD`; at zero
  `MONCELL` goes `#FF`, which `mon_draw`, `mon_scan` and the radar's
  `hr_one` all already tested for, so death needed no new branch
  anywhere. A seventh AY effect, `SFX_MONDIE`, is the only feedback that
  the third round did something the first two did not.
- ~~**Movement.**~~ **Done, and its limits are measured.** `mon_move`
  steps one cell every `MON_RATE` = 6 frames along the axis you are
  further away on, falling back to the other when that cell is solid.
  `monmodel.py` replays the same rule over every pair the monster's own
  steps could join:

  | doors | reaches the player | worst |
  |---|---:|---:|
  | shut — the map as it loads | **2160 / 2160 = 100%** | 5 steps, 6.0 s |
  | open | 13054 / 24180 = 54% | 24 steps |

  100% with the doors shut is the map, not luck: a shut door reads 2 in
  `SOLID`, so the monster is sealed into one 4×4 room, and inside an
  empty rectangle greedy is complete. That is the fight this game
  actually has. Three richer rules were modelled over the same space —
  momentum 57%, momentum-plus-turn 62%, wall-slide 62% — and the best
  buys eight points, costs a byte of state and a dozen instructions, and
  is still stuck a third of the time. What would fix it is aiming at the
  *doorway*, and that is a search.

  The rate is scaled to the player: a walk is 0.094 cells a frame and
  SHIFT doubles it, so 1/6 = 0.167 is **faster than walking and slower
  than running**. You cannot stroll away from it and you can run.
- **The aim cone was the whole field of view, and hit points made that
  matter.** `box_draw` writes `bx_bot` once for the box, not once per
  pair, so "the monster drew" and "the monster drew where the gun points"
  were the same test. Measured on the disc: it read flesh on 10 of the 11
  headings the monster was visible on. `mon_draw` now copies `bx_bot`
  only when the pairs it painted include the crosshair's — measured
  again, **2 headings of 11, 10° of 55**.
- **Damage and player death — the obvious next piece.** The monster now
  walks up to you and stands there. Contact needs to cost health, which
  needs a health readout (a third HUD slot, same machinery as the pips)
  and a death state. Note `MENUBUF equ SOLID`: death has to restart the
  world, not resume it.
- **More than one.** `mon_draw` handles a single monster from one cell
  in `gen_maze.inc`. A list of four, like `AMMOTAB`, is the same shape —
  but four monsters at 8200 µs of overlay is where the frame budget
  says stop. **Budget first, then count.**

### 2. A reason to be in the maze

- **An exit.** A door that ends the level, or a key to find first. Trivial
  in the map format; needs a "level complete" screen.
- **Score.** Kills, pickups, time. The menu font is already there — a
  score line in the HUD is `menu.asm`'s blitter pointed at the HUD.
- **More than one level.** The map is 256 bytes packed and the whole
  engine reads it from `SOLID`. Several maps on the disc, one `LDIR`
  apart, is nearly free — the work is the level-select and the
  progression, not the loading.

### 3. Presentation

- ~~**Sound.**~~ **Done** — `sound.asm`, `gensnd.py`. Six effects, 2200 µs
  charged a frame for nine ticks, measured at 1944 worst. What is *not*
  done: the envelopes were written on paper and verified only by reading
  the AY registers back, because the emulator has no audio. Whether a
  shot sounds like a shot is still an open question, and answering it
  needs a real machine or an emulator that makes noise. Still missing:
  a footstep, and anything for taking damage.

  **It is also not wired into the build, and that is a live defect.**
  `grep gensnd Makefile` returns nothing, and `$(SRC)` lists neither
  `sound.asm` nor `rastcol.asm`, `pip.asm` or `menu.asm`. Editing the
  driver does not rebuild `GAME3.BIN`; editing `EFFECTS` does not
  regenerate `gen_snd.inc`, which is committed and therefore frozen.
  Three consequences, all bad: a change can be made and tested against
  a stale disc; the generator's asserts never run; and the disc in
  `build/` is not reproducible from source. Fix before touching sound
  again.

  **And `gensnd.py`'s one safety assert is unreachable.** `step_bytes`
  sets `mix = SILENT` (#3F, bits 6 and 7 already clear) and thereafter
  only ever clears more bits (`&= ~0x01`, `&= ~0x08`), so
  `assert not (mix & 0xC0)` at `gensnd.py:146` cannot fire. The
  invariant it guards is the one that would leave the machine unable to
  read a key — so the guard on it is currently worth zero lines. It
  needs to be an assert on a value that could actually differ, or the
  comment claiming it is checked needs to go.

  **The bound is not checked either.** `C_SND = 2200` rests on "no
  effect produces more than four step changes plus a stop inside a
  nine-tick window" (4 changes + stop = 1944 µs, 5 = 2323 and it
  breaks). Nothing asserts it. `SFX_SHOT` [1,2,3,2] *and*
  `SFX_SHOT_STONE` [1,2,2,3] both sit on that ceiling — the comment in
  `main3.asm` names only the first. A window slide in `gensnd.build()`
  reading 2200 out of `main3.asm` with `pacemodel`'s `_equ` trick would
  turn the claim into a checked number.
- **Death and victory screens.** `menu.asm` generalised to take a
  different word list. Small.
- **A real monster sprite.** It is a coloured box. `enemyart.py` exists
  in the tree with a baked-sizes sprite pipeline and is *not in the
  Makefile* — it was written and abandoned. Wiring it up is the obvious
  next visual step, but see the budget: a sprite is per-row work and
  `hud_rect`'s 70 µs a row is why the box is capped at 28.

### 4. Engine work that unblocks the above

- **A cheaper world-space blitter.** Everything drawn in the world goes
  through `hud_rect` at ~70 µs a row. `rc_band` does the same job at
  20.25 µs a *pair-scanline* — 3.5× better — but needs bank 5 paged for
  its texture read. A solid-fill variant of `rc_band` would pay for
  itself the moment there is more than one monster.
- **The moving-door pass.** See the open problem above.
- **Byte-exact models for the world overlay.** The HUD is verified byte
  for byte against `genhud.py`; `box_draw`, `mon_draw` and `fx_draw` are
  not. Every one of the five bugs found while writing them was found by
  eye or by a pixel count. In this repo that is the pattern that hides
  defects — `colmodel.py` for the renderer and `genhud.py` for the HUD
  both exist because of it.

---

## The map editor — C# MVC Blazor

A browser editor that writes the same map the build already consumes, so
that drawing a level and running it are one step.

### What it has to produce

`tools/world.py` owns the map today: a 16×16 grid of characters, plus
the pickup list, plus the monster cell. `gen_march.py` turns that into
`gen_maze.inc` — the grid **packed two bits a cell** (64 bytes), the
pickup cells, the monster cell, and `START_X`/`START_Y`.

The editor's output must be **the input to that generator, not a
replacement for it** — the generator is where the invariants live and it
must stay the only writer of the `.inc`.

So: the editor writes a **map file** (JSON), and `world.py` grows a
loader for it. One new file format, one new reader, nothing else moves.

```json
{
  "name": "level 1",
  "size": [16, 16],
  "grid": ["################", "#....#....#....#", ...],
  "start": [3, 12],
  "ammo":  [[2,2], [8,3], [13,2], [3,8], [12,7], [7,13]],
  "monsters": [[1,12]]
}
```

### The rules the editor must enforce

These are not style — the engine breaks, silently or loudly, if any is
violated. They are all asserted in `world.py` today, and the editor
should refuse to export rather than let the build fail:

- **16×16, and every row the same length.** `MAZE_W`/`MAZE_H`.
- **Exactly one start**, on a floor cell.
- **Every floor cell reachable** from the start, treating doors as
  passable. `world._check_connected` walks it; the editor should show
  unreachable cells in red as you draw.
- **Room size against the march radius.** `R_MAX` is 6 and faces are
  filed at L1 1..R_MAX+1, so a room whose visible faces sit past that is
  drawn as an open field with a sliver of wall on the horizon. 4×4 rooms
  work; the note in `world.py` explains why the obvious W+H ≤ 7 rule is
  too strict. **The editor should warn on rooms bigger than 4×4.**
- **Door count** must not exceed `MAXDOORS` (16). The build asserts it;
  the editor should count as you place.
- **Pickups and monsters on floor**, not on the start cell, not on each
  other.
- **Cell values fit two bits** — 0 open, 1 wall, 2 shut door, 3 door in
  motion. There is no room for a fifth kind without changing the packing
  *and* the march's hot loop.

### Shape of the project

```
editor/
  Amaze.Editor/                 ASP.NET Core MVC + Blazor Server
    Models/MapModel.cs          the JSON above, with validation attributes
    Services/MapValidator.cs    the rules above, one method each
    Services/MapIo.cs           load/save, and export to tools/maps/*.json
    Pages/Editor.razor          the grid, the palette, the live warnings
    Shared/GridCell.razor       one cell: click to paint, right-click to erase
    wwwroot/                    a small sprite sheet for the palette
  Amaze.Editor.Tests/           MapValidator against the same cases
```

**Blazor Server rather than WebAssembly**: the editor writes files into
the repo, which wants a server anyway, and Server gives that without a
separate API.

**The validator is the interesting part.** It is a port of
`world._check_connected` and the assertions around it, and it should be
tested against the *same* maps — export the current map from `world.py`
as JSON, load it in the editor's tests, and assert it validates. That is
the only thing that keeps the two implementations honest about what a
legal map is.

### The seam

1. `world.py` gains `load_json(path)` and keeps `MAZE_SRC` as the
   fallback, so nothing breaks on day one.
2. The editor writes `tools/maps/level1.json`.
3. `make` picks the map from an environment variable or a default, and
   `gen_march.py` is unchanged — it still takes a grid and emits the
   packed `.inc`.
4. Only then does multi-level loading become a map-list question rather
   than an engine question.

---

## Order I would build it in

0. ~~**Fix the pacing tools, before any feature.**~~ **Done.** The
   off-by-one, the build wiring, the HUD charges' placement, the
   `C_SND` window assert, the recipe that stopped at line 16, the
   `C_TAIL` re-fit, and the teleport stub in the march's FTAB. "The
   period is locked" is now a statement about the disc.
1. ~~**Sound.**~~ Done, `ae0c6d0` — with the caveats above.
2. ~~**Monster hit points, death, and simple pursuit.**~~ **Done**, with
   `PACE_FRAMES` 10 underneath it to pay for the pursuit.
3. **Player health and death — the half of the loop that is missing.**
   The monster walks up to you and nothing happens. Contact is `L1 == 1`
   (it cannot be 0: `box_draw` rejects at the near plane, so a monster on
   your own cell is invisible and unshootable, which is why `mon_move`
   stops at 1). Needs: a health byte, a readout — one rectangle at
   560–704 µs, **not** a bar at 1905–3811 — and a death state that
   restarts the world, because `MENUBUF equ SOLID`.
4. **An exit, and a score.** Now killing the monster and crossing the
   maze mean something.
5. **The editor**, once there is a reason to draw a second level.
6. **The cheap world blitter**, when the monster count wants it.
7. **The moving-door pass** — 19.261% and the one configuration the
   engine still cannot claim.
8. **`emu_snd.py`** — hook `snd_wr` by address, run `snd_tick` N times
   after each `snd_play(i)`, assert the write stream equals
   `gensnd.EFFECTS`. The one thing that would catch a step order, a
   duration off by one, or an effect that never reaches `st_stop`.

Byte-exact models for the world overlay belong beside whichever of these
touches it, not as a separate task — this repo's whole history says that
a drawn thing without a model is a defect waiting for a screenshot.
