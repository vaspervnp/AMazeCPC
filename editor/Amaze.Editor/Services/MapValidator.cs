using Amaze.Editor.Models;

namespace Amaze.Editor.Services;

public enum Severity { Error, Warning }

/// <param name="Cells">The cells to light up in the grid, if any.</param>
public sealed record Finding(Severity Severity, string Rule, string Message,
                             IReadOnlyList<(int X, int Y)>? Cells = null)
{
    public override string ToString() => $"[{Severity}] {Rule}: {Message}";
}

/// <summary>
/// A PORT OF tools/world.py's ASSERTIONS, one method a rule.
///
/// The engine breaks -- silently or loudly -- if any of these is violated,
/// so the editor refuses to export rather than letting the build fail with
/// an AssertionError three tools downstream.  Being a second implementation
/// of "what a legal map is" is exactly the risk, which is why the tests run
/// it against the maps that actually ship (tools/maps/*.json, written by
/// world.export_levels()).
/// </summary>
public sealed class MapValidator
{
    public IReadOnlyList<Finding> Validate(MapModel map)
    {
        var f = new List<Finding>();
        // SHAPE FIRST, AND STOP IF IT IS WRONG.  Every rule below indexes
        // the grid; running them on a ragged one reports the exception, not
        // the defect.
        f.AddRange(CheckShape(map));
        if (f.Any(x => x.Severity == Severity.Error)) return f;

        f.AddRange(CheckStart(map));
        f.AddRange(CheckExit(map));
        f.AddRange(CheckConnected(map));
        f.AddRange(CheckDoors(map));
        f.AddRange(CheckAmmo(map));
        f.AddRange(CheckMonsters(map));
        f.AddRange(CheckScoreFitsADigit(map));
        f.AddRange(CheckRoomSize(map));
        return f;
    }

    public bool IsExportable(MapModel map) =>
        !Validate(map).Any(x => x.Severity == Severity.Error);

    // ---- world.py: load_maze's row check, and the cell alphabet ----------
    private static IEnumerable<Finding> CheckShape(MapModel map)
    {
        if (map.Grid.Count != MapCells.Height)
            yield return new(Severity.Error, "size",
                $"the grid is {map.Grid.Count} rows, not {MapCells.Height}");

        for (var y = 0; y < map.Grid.Count; y++)
        {
            if (map.Grid[y].Length != MapCells.Width)
                yield return new(Severity.Error, "size",
                    $"row {y} is {map.Grid[y].Length} cells, not {MapCells.Width}");
            for (var x = 0; x < map.Grid[y].Length; x++)
                if (!MapCells.Legal.Contains(map.Grid[y][x]))
                    yield return new(Severity.Error, "alphabet",
                        $"row {y} column {x} is '{map.Grid[y][x]}', and the packing "
                        + "is two bits a cell: 0 open, 1 wall, 2 shut door, 3 moving",
                        [(x, y)]);
        }

        if (map.Size.Length != 2 ||
            map.Size[0] != MapCells.Width || map.Size[1] != MapCells.Height)
            yield return new(Severity.Error, "size",
                $"size says [{string.Join(", ", map.Size)}] and the grid is "
                + $"{MapCells.Width}x{MapCells.Height}");
    }

    // ---- world.py: `assert sx >= 0, "maze has no '@' start position"` -----
    private static IEnumerable<Finding> CheckStart(MapModel map)
    {
        var found = Find(map, MapCells.Start);
        if (found.Count != 1)
            yield return new(Severity.Error, "start",
                $"the maze needs exactly one '{MapCells.Start}' and has "
                + $"{found.Count}", found);
    }

    // ---- world.py: exit_cell's four assertions ---------------------------
    private static IEnumerable<Finding> CheckExit(MapModel map)
    {
        var found = Find(map, MapCells.Exit);
        if (found.Count != 1)
        {
            yield return new(Severity.Error, "exit",
                $"the maze needs exactly one '{MapCells.Exit}' and has "
                + $"{found.Count}", found);
            yield break;
        }
        var exit = found[0];
        if (Cells(map.Ammo).Contains(exit))
            yield return new(Severity.Error, "exit",
                $"the exit {P(exit)} is under a pickup", [exit]);
        if (Cells(map.Monsters).Contains(exit))
            yield return new(Severity.Error, "exit",
                $"the exit {P(exit)} is under a monster", [exit]);
    }

    // ---- world.py: _check_connected, doors passable ----------------------
    private static IEnumerable<Finding> CheckConnected(MapModel map)
    {
        var start = Find(map, MapCells.Start).FirstOrDefault();
        if (Find(map, MapCells.Start).Count != 1) yield break;

        var seen = new HashSet<(int, int)>();
        var stack = new Stack<(int X, int Y)>();
        seen.Add(start);
        stack.Push(start);
        while (stack.Count > 0)
        {
            var (x, y) = stack.Pop();
            foreach (var (nx, ny) in new[] { (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1) })
            {
                if (nx < 0 || nx >= MapCells.Width || ny < 0 || ny >= MapCells.Height)
                    continue;
                if (seen.Contains((nx, ny)) || !MapCells.IsWalkable(map.Grid[ny][nx]))
                    continue;
                seen.Add((nx, ny));
                stack.Push((nx, ny));
            }
        }

        var missing = new List<(int X, int Y)>();
        for (var y = 0; y < MapCells.Height; y++)
            for (var x = 0; x < MapCells.Width; x++)
                if (MapCells.IsWalkable(map.Grid[y][x]) && !seen.Contains((x, y)))
                    missing.Add((x, y));

        if (missing.Count > 0)
            yield return new(Severity.Error, "connected",
                $"{missing.Count} cells cannot be reached from the start, "
                + "even walking through every door", missing);
    }

    // ---- game.asm: game_init drops doors past MAXDOORS, silently ---------
    private static IEnumerable<Finding> CheckDoors(MapModel map)
    {
        var doors = Find(map, MapCells.Door);
        if (doors.Count > EngineLimits.MaxDoors)
            yield return new(Severity.Error, "doors",
                $"{doors.Count} doors against MAXDOORS {EngineLimits.MaxDoors} -- "
                + "game_init registers the first few and the rest are shut for ever",
                doors);
    }

    // ---- world.py: ammo_cells' four assertions, plus the record's size ---
    private static IEnumerable<Finding> CheckAmmo(MapModel map)
    {
        var start = Find(map, MapCells.Start).FirstOrDefault();
        foreach (var c in Cells(map.Ammo))
        {
            if (!OnMap(c))
            {
                yield return new(Severity.Error, "ammo", $"pickup {P(c)} is off the map");
                continue;
            }
            if (!MapCells.IsFloor(map.Grid[c.Y][c.X]))
                yield return new(Severity.Error, "ammo",
                    $"pickup {P(c)} is not on floor", [c]);
            if (Find(map, MapCells.Start).Count == 1 && c == start)
                yield return new(Severity.Error, "ammo",
                    $"pickup {P(c)} is on the player's start cell", [c]);
        }
        foreach (var d in Duplicates(Cells(map.Ammo)))
            yield return new(Severity.Error, "ammo",
                $"two pickups on {P(d)}", [d]);

        if (map.Ammo.Count > EngineLimits.MaxAmmo)
            yield return new(Severity.Error, "ammo",
                $"{map.Ammo.Count} pickups against MAXAMMO {EngineLimits.MaxAmmo} -- "
                + "the level record has no room for more");
    }

    // ---- world.py: monster_cells' assertions -----------------------------
    private static IEnumerable<Finding> CheckMonsters(MapModel map)
    {
        var starts = Find(map, MapCells.Start);
        var ammo = Cells(map.Ammo).ToHashSet();
        foreach (var c in Cells(map.Monsters))
        {
            if (!OnMap(c))
            {
                yield return new(Severity.Error, "monsters", $"monster {P(c)} is off the map");
                continue;
            }
            if (!MapCells.IsFloor(map.Grid[c.Y][c.X]))
                yield return new(Severity.Error, "monsters",
                    $"monster {P(c)} is not on floor", [c]);
            if (starts.Count == 1 && c == starts[0])
                yield return new(Severity.Error, "monsters",
                    $"monster {P(c)} is on the player's start cell", [c]);
            if (ammo.Contains(c))
                yield return new(Severity.Error, "monsters",
                    $"monster {P(c)} is standing on a pickup", [c]);
            // THE ROOM YOU START IN MUST BE EMPTY.  The opening is
            // unsurvivable otherwise: the thing bites from frame 12 and a
            // 180-degree turn takes 36.  See world.monster_cells.
            if (starts.Count == 1 && Room(c) == Room(starts[0]))
                yield return new(Severity.Error, "monsters",
                    $"monster {P(c)} is in the room the player starts in", [c]);
        }
        foreach (var d in Duplicates(Cells(map.Monsters)))
            yield return new(Severity.Error, "monsters",
                $"two monsters on {P(d)}", [d]);

        var perRoom = Cells(map.Monsters).Where(OnMap).GroupBy(Room)
                                         .Where(g => g.Count() > 1).ToList();
        foreach (var g in perRoom)
            yield return new(Severity.Error, "monsters",
                $"{g.Count()} monsters in room {g.Key} -- one a room",
                [.. g]);

        if (map.Monsters.Count > EngineLimits.MaxMonsters)
            yield return new(Severity.Error, "monsters",
                $"{map.Monsters.Count} monsters against MAXMON "
                + $"{EngineLimits.MaxMonsters}");
    }

    // ---- menu.asm: the score is ONE glyph --------------------------------
    private static IEnumerable<Finding> CheckScoreFitsADigit(MapModel map)
    {
        var points = map.Ammo.Count + map.Monsters.Count;
        if (points > EngineLimits.MaxScoreDigit)
            yield return new(Severity.Error, "score",
                $"{map.Ammo.Count} pickups + {map.Monsters.Count} monsters is "
                + $"{points} points, and the score is drawn as a single digit "
                + $"(MN_G0 + n, and MN_G0 + 10 is 'A')");
    }

    // ---- world.py's R_MAX note: a room bigger than this reads as a field --
    private static IEnumerable<Finding> CheckRoomSize(MapModel map)
    {
        // A ROOM IS FLOOR THAT DOES NOT CROSS A DOORWAY.  Flooding through
        // doors would join the whole map into one "room" and the rule would
        // never fire; a door is where one room stops and the next starts.
        var seen = new HashSet<(int, int)>();
        for (var y0 = 0; y0 < MapCells.Height; y0++)
            for (var x0 = 0; x0 < MapCells.Width; x0++)
            {
                if (!MapCells.IsFloor(map.Grid[y0][x0]) || seen.Contains((x0, y0)))
                    continue;
                var region = new List<(int X, int Y)>();
                var stack = new Stack<(int X, int Y)>();
                seen.Add((x0, y0));
                stack.Push((x0, y0));
                while (stack.Count > 0)
                {
                    var c = stack.Pop();
                    region.Add(c);
                    foreach (var (nx, ny) in new[]
                             { (c.X + 1, c.Y), (c.X - 1, c.Y), (c.X, c.Y + 1), (c.X, c.Y - 1) })
                    {
                        if (nx < 0 || nx >= MapCells.Width || ny < 0 || ny >= MapCells.Height)
                            continue;
                        if (seen.Contains((nx, ny)) || !MapCells.IsFloor(map.Grid[ny][nx]))
                            continue;
                        seen.Add((nx, ny));
                        stack.Push((nx, ny));
                    }
                }
                int minX = region.Min(c => c.X), minY = region.Min(c => c.Y);
                var w = region.Max(c => c.X) - minX + 1;
                var h = region.Max(c => c.Y) - minY + 1;
                if (w > EngineLimits.MaxRoomSide || h > EngineLimits.MaxRoomSide)
                    yield return new(Severity.Warning, "room size",
                        $"a {w}x{h} room at {P((minX, minY))} -- the march "
                        + $"files faces to L1 R_MAX+1, so a room past "
                        + $"{EngineLimits.MaxRoomSide}x{EngineLimits.MaxRoomSide} is drawn "
                        + "as an open field with a sliver of wall on the horizon",
                        region);
            }
    }

    // ---- helpers ---------------------------------------------------------
    private static (int X, int Y) Room((int X, int Y) c) =>
        (c.X / MapCells.RoomPitch, c.Y / MapCells.RoomPitch);

    private static bool OnMap((int X, int Y) c) =>
        c.X >= 0 && c.X < MapCells.Width && c.Y >= 0 && c.Y < MapCells.Height;

    private static string P((int X, int Y) c) => $"({c.X},{c.Y})";

    private static List<(int X, int Y)> Find(MapModel map, char ch)
    {
        var found = new List<(int X, int Y)>();
        for (var y = 0; y < map.Grid.Count; y++)
            for (var x = 0; x < map.Grid[y].Length; x++)
                if (map.Grid[y][x] == ch) found.Add((x, y));
        return found;
    }

    private static IEnumerable<(int X, int Y)> Cells(List<int[]> raw) =>
        raw.Where(c => c.Length == 2).Select(c => (c[0], c[1]));

    private static IEnumerable<(int X, int Y)> Duplicates(IEnumerable<(int X, int Y)> cells) =>
        cells.GroupBy(c => c).Where(g => g.Count() > 1).Select(g => g.Key);
}
