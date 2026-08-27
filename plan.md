# AMAZE — plan

What exists, what a complete game still needs, and how the map editor
fits. Written against the engine as it stands, with the costs measured
rather than guessed, because on this machine the budget decides the
design.

---

## The constraint everything else answers to

The disc runs at **9 vsyncs a frame — 179.7 ms, 5.56 fps** — and that
period is *locked*: `main3.asm` carries a cost accumulator, every unit of
work is charged an upper bound before it runs, and `pace_drain` spends
whatever is left. `emu_verify3.py` measures the real period on the booted
machine and fails if any frame is not exactly 9.

So the budget is **175104 µs a frame**, and it is nearly spent:

| where it goes | µs | share |
|---|---:|---:|
| `rastcol` — the textured column renderer | 126000–205000 | 75–80% |
| `bg_fill` — ceiling and floor | 9320 | 5.3% |
| the world overlay (pickup, monster, shot) | 8200 | 4.7% |
| the tail carried into the next head (`C_TAIL`+`C_SND`+`C_DOORACT`) | 6150 | 3.5% |
| march + project | 16000–24000 | 9–14% |

**Two numbers to keep in front of you:**

- The head carries **6150 µs at worst**, not the 16230 the model charges.
  `pace_drain` ends every frame with `ld h,a / ld l,a / ld (cost_acc),hl`
  at a = 0 — it **zeroes** the accumulator — and `hud_ammo`, `hud_scan`
  and `hud_radar` are all called *before* it (`main3.asm:1047-1051`,
  drain at `:1060`). So `C_AMMO`, `C_SCAN`, `C_SWEEP`, `C_BLIP` and
  `C_RNEEDLE` can never reach the next frame. The only charge that
  outlives the drain is `game.asm`'s `C_DOORACT`. 6150 + `C_BG` 9320 =
  15470, **3986 under** `COST_THI` — `bg_fill` does not yield at the
  head on any frame.
- `hud_rect` costs **~70 µs a row** — a LINETAB lookup per scanline. A
  tall narrow rectangle is nearly all rows. That single fact has shaped
  the ammo pips (3811 µs), the monster (capped at 28 rows) and the
  radar.

---

## The open problem: the period is not currently proven

`make pace` **fails**, and has been failing since before the sound
commit. Sound is not the cause — the exhaustive sweep is byte-identical
with `C_SND` at 2200 and at 0, because the charge lands where the first
yield discards it.

Two defects in the *tools* were hiding a third in the *engine*. The
tools are fixed; here is what they now say, and what they exposed.

### The number, exhaustively, with the model corrected

| doors | over budget | worst charged frame |
|---|---:|---:|
| shut — the map as it loads | 69381 / 8128512 = **0.854%** | 169232 µs |
| open | 314225 / 8792064 = **3.574%** | 190152 µs |
| moving | 2858875 / 8128512 = **35.171%** | 259107 µs |

Doors shut is about **one frame in 117**. The budget is 175104 µs, so
the doors-open worst frame is over on its own.

**And this is not model pessimism — it was checked on the machine.**
Five of the doors-shut states the model damns were fed to `emu_pace`'s
rig, a fresh boot each, and the period measured:

```
OVER    (0x0EB0,0x0B68,43)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0EA0,0x0E70,61)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0B90,0x0EA0, 7)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0B60,0x0B90,25)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
OVER    (0x0970,0x0B60,43)   [10] vsyncs = 199.5 ms   *** OFF PACE ***
control (0x0350,0x0C80, 0)   [ 9] vsyncs = 179.5 ms   on pace
control (0x0680,0x0680,36)   [ 9] vsyncs = 179.5 ms   on pace
```

Five out of five. The disc really does drop to 199.5 ms — 5.01 fps
instead of 5.56 — on those states, and `emu_verify3` still reports the
period LOCKED because the six views it walks are not among them.

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

The 0.854% is the **second** kind. The worst charged frame is 169232
against a 175104 budget — the work *fits*; the greedy packing is what
does not. A gate is one more yield, so it trades a rare late frame for a
common one.

**What would actually move it is less packing waste, not more testing.**
`cost_unit` yields when the next unit does not fit and throws away the
rest of the interval, so waste scales with the size of the biggest
units — and after `C_BG` the biggest is `C_PIP` at 8200, one hook in
front of all three of `pip.asm`'s drawers. Splitting it three ways is
the same move `RQ_SPLIT` is in `raster.asm`, and like `RQ_SPLIT` it
wants measuring before believing. Not done.

`pacemodel.HUD_GATE` still models all three arrangements so the table
can be re-run; the disc is 0.

**Doors in motion remains a separate problem**: 35.171%, worst frame
259107 µs, the moving-door overlay pass drawing a second time. A player
cannot make sixteen doors move at once, so it bounds a case that does
not occur rather than describing one that does.

**And nothing ran `make pace` for the sound commit.** `emu_verify3`
walks a path; it does not sweep the space, and it passed because it
never stood on one of the bad states. The Makefile says why that is not
the test: *"the states that break a period are three in a million and a
sample does not visit them."*

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
- One monster that stands still, scaled by distance, as a test target.
- A title screen with the keys and the credit line.
- Sound: six AY effects, ticked at a true 50 Hz out of `wait_vsync` —
  the shot picks stone or flesh from the same test the impact mark does.

---

## What a complete game still needs

Ordered by what unlocks the most, with the honest cost of each.

### 1. The monster has to do something — *the biggest single gap*

It stands there. A game needs it to **notice, approach, and hurt you**,
and you need to be able to **kill it**.

- **Hit points and death.** The shot already knows it hit (`fx_fire`
  compares two screen rows). Give the monster 3 HP, remove it at 0, and
  the loop closes: see it, shoot it, it dies.
- **Movement.** One cell a game frame toward the player when in line of
  sight. The march already computes visibility; reuse it rather than
  writing a second one. **Cost: cheap** — a few hundred µs of decision,
  and it reuses `box_draw`.
- **Damage and player death.** Contact costs health. Needs a health
  readout (a third HUD slot, same machinery as the pips) and a death
  state.
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

0. **Fix the pacing tools, before any feature.** In this order, because
   each makes the next mean something:
   a. `pacemodel.py:527` — `<=` to `<`. It grades a fail as a pass.
   b. Wire the build: `gensnd.py` into the `amaze` recipe, and
      `sound.asm` / `rastcol.asm` / `pip.asm` / `menu.asm` /
      `gen_*.inc` into `$(SRC)`.
   c. Move the HUD's `cost_add`s out of both models' `tail=` and into
      `units()` where the disc runs them.
   d. Re-run `make pace` and write the *real* over-budget count into
      `main3.asm:345-354`, `:274-279` and `vpcfg.inc:49-50` — which
      today quote a distribution with no over-budget bucket at all,
      and a worst frame of 156501 against a measured 159152.
   e. `gensnd.build()` — assert the nine-tick window that `C_SND`
      rests on.

   Only then is "the period is locked" a statement about the disc
   rather than about a model that disagrees with it.
1. ~~**Sound.**~~ Done, `ae0c6d0` — with the caveats above.
2. **Monster hit points, death, and simple pursuit.** Closes the game
   loop — the thing that makes it a game rather than a demo.
3. **The editor**, once there is a reason to draw a second level.
4. **Health, score, exit, level progression.** Now the maps mean
   something.
5. **The cheap world blitter**, when the monster count wants it.
6. **The moving-door pass**, when the period has to hold under fire.
7. **`emu_snd.py`** — hook `snd_wr` by address, run `snd_tick` N times
   after each `snd_play(i)`, assert the write stream equals
   `gensnd.EFFECTS`. The one thing that would catch a step order, a
   duration off by one, or an effect that never reaches `st_stop`.

Byte-exact models for the world overlay belong beside whichever of these
touches it, not as a separate task — this repo's whole history says that
a drawn thing without a model is a defect waiting for a screenshot.
