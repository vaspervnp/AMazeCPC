# The map editor

A Blazor Server page that draws AMazeCPC's maps and **refuses to save one
that would not build**.

```bash
dotnet run --project editor/Amaze.Editor --urls http://localhost:5199
dotnet test editor            # 31 tests
```

## What it writes

`tools/maps/level<N>.json`, one file a level, sorted by filename — which is
also the order the exit walks you through them in. Nothing else records that
order.

A file is **one entry of `tools/world.py`'s `LEVELS` and nothing more**:

```json
{
  "name": "level 1",
  "size": [16, 16],
  "grid": ["################", "#....#....#....#", "..."],
  "ammo": [[2, 2], [8, 3]],
  "monsters": [[7, 2]]
}
```

**The grid carries the start and the exit**, as `@` and `X`, exactly the way
the Python literals carry them. There are deliberately no separate `start`
and `exit` fields: a file that said both could disagree with itself, and
`world.py` would then have two opinions about where the player stands.

The grid is a list of strings so a person can read the map in the file. That
is not decoration — it is why `MapIo` sets `UnsafeRelaxedJsonEscaping`, and
why a test asserts the C# and Python writers agree byte for byte. The default
`System.Text.Json` encoder escapes `+` to `\u002B`, which is valid JSON that
Python reads back perfectly and turns `#....+....+.@..#` into a row nobody
can read.

## The seam

**These files are the game's levels.** `world.py` calls `load_levels()` at
import and has no map literal left to fall back on — deliberately. A fallback
is a second copy of the map, and a second copy is a thing that can be edited:
the editor would write `level1.json`, the build would go on shipping the
literal, and the two would part company with nothing to say so. A missing or
malformed map file stops every tool in the repository with the reason
attached.

Adding a level is adding a file. **Filename order is level order** — it is
what the exit walks the player through, and nothing else records it.

The generators stay the only writers of the `.inc` files. The editor's output
is the *input* to them, never a replacement.

Verified across the switch: the disc built from the files alone is
byte-identical to the one built from the literals, moving a monster one cell
in the JSON changes the disc, and putting it back gives the original md5.

## The validator is the interesting part

`Services/MapValidator.cs` is a port of `tools/world.py`'s assertions — one
method a rule, each naming the rule it came from. It is therefore a **second
implementation of what a legal map is**, which is exactly the risk. Two
things keep it honest:

- `ShippedMapsTests` runs it against the maps that actually ship
  (`tools/maps/*.json`, written by `world.export_levels()`). A rule that
  rejects one of them is the validator being wrong, not the map.
- `MapValidatorTests` breaks exactly one thing per test, starting from a
  shipped map. A validator that returned an empty list would pass every test
  in the first class and fail every test in the second.

`EngineLimitsTests` reads `MAXDOORS` back out of `game.asm`, `MAXAMMO` and
`MAXMON` out of `genaux.py`, and the single-digit score limit out of
`main3.asm`'s own `assert`. Every number in `EngineLimits.cs` is a copy, and
copies drift: without that test the editor would go on accepting eighteen
doors long after `game_init` stopped registering them, and the map would
build and ship with six doors that never open.

## What it does not do

- It does not run the generators. Save, then `make amaze`.
- It does not check **pacing**. Whether a map's worst frame fits the budget
  is `engine2/tools/pacescan.py`'s answer, over all 8,128,512 states, and it
  takes minutes on sixteen cores. The room-size warning is the cheap
  approximation of the same worry and no substitute for the sweep.
- It does not check that the monster can reach the player —
  `engine2/tools/monmodel.py` does, per level, in both door states.
