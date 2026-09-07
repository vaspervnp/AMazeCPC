using Amaze.Editor.Models;
using Amaze.Editor.Services;

namespace Amaze.Editor.Tests;

/// <summary>
/// EVERY RULE, BROKEN ON PURPOSE.
///
/// ShippedMapsTests proves the validator accepts a good map, and a validator
/// that returned an empty list would pass every one of those.  These start
/// from the same shipped map and break exactly one thing each, so a rule
/// that stopped firing shows up here as a test that stopped failing.
/// </summary>
public class MapValidatorTests
{
    private static MapModel Good() =>
        new MapIo(RepoPaths.Maps).Load(new MapIo(RepoPaths.Maps).List()[0]);

    private static IReadOnlyList<Finding> Check(MapModel m) =>
        new MapValidator().Validate(m);

    private static void AssertRule(MapModel m, string rule)
    {
        var f = Check(m);
        Assert.True(f.Any(x => x.Rule == rule && x.Severity == Severity.Error),
            $"expected an error from '{rule}', got:\n  " +
            (f.Count == 0 ? "(nothing)" : string.Join("\n  ", f)));
    }

    [Fact]
    public void The_good_map_is_good()
    {
        Assert.True(new MapValidator().IsExportable(Good()));
    }

    [Fact]
    public void A_ragged_row_is_an_error()
    {
        var m = Good();
        m.Grid[3] = m.Grid[3][..^1];
        AssertRule(m, "size");
    }

    [Fact]
    public void A_character_outside_the_alphabet_is_an_error()
    {
        var m = Good();
        m.Grid[2] = MapIo.ReplaceAt(m.Grid[2], 2, '?');
        AssertRule(m, "alphabet");
    }

    [Fact]
    public void No_start_is_an_error()
    {
        var m = Good();
        m.Grid = [.. m.Grid.Select(r => r.Replace(MapCells.Start, MapCells.Floor))];
        AssertRule(m, "start");
    }

    [Fact]
    public void Two_starts_are_an_error()
    {
        var m = Good();
        var (x, y) = FirstFloorAwayFromEverything(m);
        m.Grid[y] = MapIo.ReplaceAt(m.Grid[y], x, MapCells.Start);
        AssertRule(m, "start");
    }

    [Fact]
    public void No_exit_is_an_error()
    {
        var m = Good();
        m.Grid = [.. m.Grid.Select(r => r.Replace(MapCells.Exit, MapCells.Floor))];
        AssertRule(m, "exit");
    }

    [Fact]
    public void An_exit_under_a_pickup_is_an_error()
    {
        var m = Good();
        var e = Find(m, MapCells.Exit);
        m.Ammo.Add([e.X, e.Y]);
        AssertRule(m, "exit");
    }

    [Fact]
    public void A_walled_off_pocket_is_an_error()
    {
        // Seal one room by walling its only doorway.  A pocket looks fine in
        // a preview and only shows up as a part of the map you cannot get to.
        var m = Good();
        var doors = AllOf(m, MapCells.Door);
        foreach (var d in doors) m.Grid[d.Y] = MapIo.ReplaceAt(m.Grid[d.Y], d.X, MapCells.Wall);
        AssertRule(m, "connected");
    }

    [Fact]
    public void More_doors_than_MAXDOORS_is_an_error()
    {
        var m = Good();
        // Punch doors along the inner wall columns until the count is over.
        for (var y = 1; y < MapCells.Height - 1 &&
                        AllOf(m, MapCells.Door).Count <= EngineLimits.MaxDoors; y++)
            if (m.Grid[y][5] == MapCells.Wall)
                m.Grid[y] = MapIo.ReplaceAt(m.Grid[y], 5, MapCells.Door);
        AssertRule(m, "doors");
    }

    [Fact]
    public void A_pickup_in_a_wall_is_an_error()
    {
        var m = Good();
        var w = AllOf(m, MapCells.Wall)[0];
        m.Ammo.Add([w.X, w.Y]);
        AssertRule(m, "ammo");
    }

    [Fact]
    public void Two_pickups_on_one_cell_is_an_error()
    {
        var m = Good();
        m.Ammo.Add([m.Ammo[0][0], m.Ammo[0][1]]);
        AssertRule(m, "ammo");
    }

    [Fact]
    public void A_monster_in_the_players_own_room_is_an_error()
    {
        var m = Good();
        var s = Find(m, MapCells.Start);
        // Any floor cell in the same 5x5 room block that is not the start.
        for (var y = 0; y < MapCells.Height; y++)
            for (var x = 0; x < MapCells.Width; x++)
                if (MapCells.IsFloor(m.Grid[y][x]) && (x, y) != (s.X, s.Y)
                    && x / MapCells.RoomPitch == s.X / MapCells.RoomPitch
                    && y / MapCells.RoomPitch == s.Y / MapCells.RoomPitch)
                {
                    m.Monsters = [[x, y]];
                    AssertRule(m, "monsters");
                    return;
                }
        Assert.Fail("the start's room has no other floor cell");
    }

    [Fact]
    public void Two_monsters_in_one_room_is_an_error()
    {
        var m = Good();
        var mon = m.Monsters[0];
        // Its neighbour is in the same room unless the monster is on an edge
        // of the block; the shipped monsters are not.
        m.Monsters = [[mon[0], mon[1]], [mon[0] + 1, mon[1]]];
        AssertRule(m, "monsters");
    }

    [Fact]
    public void A_score_past_one_digit_is_an_error()
    {
        var m = Good();
        m.Ammo = [.. AllOf(m, MapCells.Floor).Take(EngineLimits.MaxScoreDigit)
                       .Select(c => new[] { c.X, c.Y })];
        AssertRule(m, "score");
    }

    [Fact]
    public void A_room_bigger_than_the_march_can_draw_is_a_warning_not_an_error()
    {
        // Knock the wall out between two rooms: 4x4 becomes 4x9, which the
        // march draws as an open field with a sliver of wall on the horizon.
        var m = Good();
        for (var x = 1; x <= 4; x++)
            m.Grid[5] = MapIo.ReplaceAt(m.Grid[5], x, MapCells.Floor);
        var f = Check(m);
        Assert.Contains(f, x => x.Rule == "room size" && x.Severity == Severity.Warning);
        Assert.DoesNotContain(f, x => x.Severity == Severity.Error);
    }

    [Fact]
    public void Save_refuses_a_map_that_would_not_build()
    {
        var m = Good();
        m.Grid = [.. m.Grid.Select(r => r.Replace(MapCells.Start, MapCells.Floor))];
        var tmp = Path.Combine(Path.GetTempPath(), "amaze-" + Guid.NewGuid().ToString("N"));
        var ex = Assert.Throws<InvalidOperationException>(
            () => new MapIo(tmp).Save("x.json", m, new MapValidator()));
        Assert.Contains("start", ex.Message);
        Assert.False(Directory.Exists(tmp), "it wrote the directory anyway");
    }

    // ---- helpers ---------------------------------------------------------
    private static (int X, int Y) Find(MapModel m, char ch) => AllOf(m, ch)[0];

    private static List<(int X, int Y)> AllOf(MapModel m, char ch)
    {
        var o = new List<(int X, int Y)>();
        for (var y = 0; y < m.Grid.Count; y++)
            for (var x = 0; x < m.Grid[y].Length; x++)
                if (m.Grid[y][x] == ch) o.Add((x, y));
        return o;
    }

    private static (int X, int Y) FirstFloorAwayFromEverything(MapModel m)
    {
        var taken = m.Ammo.Concat(m.Monsters).Select(c => (c[0], c[1])).ToHashSet();
        foreach (var c in AllOf(m, MapCells.Floor))
            if (!taken.Contains(c)) return c;
        throw new InvalidOperationException("no free floor cell");
    }
}
