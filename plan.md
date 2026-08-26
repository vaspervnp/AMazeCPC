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
| the tail (game step, flip, HUD events) | 8600 | 4.9% |
| march + project | 16000–24000 | 9–14% |

**Two numbers to keep in front of you:**

- Adding more than **1535 µs** at the head of a frame costs a whole
  19968 µs period, not 1536 µs. The accumulator holds the 8600 µs tail,
  `C_BG` rooms 9320 on top, and 19456 − 17920 = 1536 is what is left
  before the first `cost_unit` yields. It is a cliff, measured.
- `hud_rect` costs **~70 µs a row** — a LINETAB lookup per scanline. A
  tall narrow rectangle is nearly all rows. That single fact has shaped
  the ammo pips (3811 µs), the monster (capped at 28 rows) and the
  radar.

**The open problem.** With every door *in motion* the pessimistic sweep
puts 33% of states over budget, worst frame 242627 µs. That is the
moving-door overlay pass drawing a second time, and it is the one place
the engine cannot honour its own period. A player cannot make all
sixteen doors move at once, so it is a bound rather than a bug — but it
is the bound that will break first when anything else is added.

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

- **Sound.** The CPC's AY chip is untouched. A shot, a door, a hit, a
  footstep. This is the single biggest perceived-quality win per byte on
  an 8-bit machine, and it costs almost no frame time — the AY is
  written and forgotten.
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

1. **Sound.** Biggest perceived gain, almost no frame cost, independent
   of everything else.
2. **Monster hit points, death, and simple pursuit.** Closes the game
   loop — the thing that makes it a game rather than a demo.
3. **The editor**, once there is a reason to draw a second level.
4. **Health, score, exit, level progression.** Now the maps mean
   something.
5. **The cheap world blitter**, when the monster count wants it.
6. **The moving-door pass**, when the period has to hold under fire.

Byte-exact models for the world overlay belong beside whichever of these
touches it, not as a separate task — this repo's whole history says that
a drawn thing without a model is a defect waiting for a screenshot.
