using Amaze.Editor.Models;
using Amaze.Editor.Services;

namespace Amaze.Editor.Tests;

/// <summary>
/// THE ONLY THING KEEPING THE TWO IMPLEMENTATIONS HONEST.
///
/// MapValidator is a second opinion about what a legal map is; world.py's
/// assertions are the first, and they are the ones the disc is built on.  So
/// the validator is run against the maps that actually ship -- written by
/// world.export_levels() into tools/maps -- and a rule that rejects one of
/// them is the validator being wrong, not the map.
/// </summary>
public class ShippedMapsTests
{
    public static TheoryData<string> ShippedMaps()
    {
        var data = new TheoryData<string>();
        foreach (var f in new MapIo(RepoPaths.Maps).List()) data.Add(f);
        return data;
    }

    [Fact]
    public void There_are_maps_to_test()
    {
        // A theory over an empty set PASSES, silently, and would go on
        // passing if tools/maps were deleted.  So the set is checked too.
        Assert.NotEmpty(new MapIo(RepoPaths.Maps).List());
    }

    [Theory]
    [MemberData(nameof(ShippedMaps))]
    public void A_shipped_map_has_no_errors(string fileName)
    {
        var map = new MapIo(RepoPaths.Maps).Load(fileName);
        var findings = new MapValidator().Validate(map);
        var errors = findings.Where(f => f.Severity == Severity.Error).ToList();
        Assert.True(errors.Count == 0,
            $"{fileName} is on the disc and the validator rejects it:\n  " +
            string.Join("\n  ", errors));
    }

    [Theory]
    [MemberData(nameof(ShippedMaps))]
    public void A_shipped_map_has_no_warnings_either(string fileName)
    {
        // The shipped maps are nine 4x4 rooms, so the room-size warning must
        // stay quiet on them.  If it ever fires here it is the rule that is
        // wrong -- the maps are measured, by engine2/tools/roomcost.py.
        var map = new MapIo(RepoPaths.Maps).Load(fileName);
        var warnings = new MapValidator().Validate(map)
                          .Where(f => f.Severity == Severity.Warning).ToList();
        Assert.True(warnings.Count == 0,
            $"{fileName}:\n  " + string.Join("\n  ", warnings));
    }

    [Theory]
    [MemberData(nameof(ShippedMaps))]
    public void A_shipped_map_round_trips_through_save_and_load(string fileName)
    {
        var io = new MapIo(RepoPaths.Maps);
        var map = io.Load(fileName);
        var tmp = Path.Combine(Path.GetTempPath(),
                               "amaze-editor-" + Guid.NewGuid().ToString("N"));
        try
        {
            new MapIo(tmp).Save(fileName, map, new MapValidator());
            var back = new MapIo(tmp).Load(fileName);
            Assert.Equal(map.Grid, back.Grid);
            Assert.Equal(map.Name, back.Name);
            Assert.Equal(map.Ammo.Select(c => (c[0], c[1])),
                         back.Ammo.Select(c => (c[0], c[1])));
            Assert.Equal(map.Monsters.Select(c => (c[0], c[1])),
                         back.Monsters.Select(c => (c[0], c[1])));
        }
        finally { if (Directory.Exists(tmp)) Directory.Delete(tmp, true); }
    }

    [Theory]
    [MemberData(nameof(ShippedMaps))]
    public void Saving_a_shipped_map_unchanged_does_not_change_the_file(string fileName)
    {
        // THE TWO WRITERS HAVE TO AGREE BYTE FOR BYTE.  world.export_levels()
        // writes these files and MapIo.Save rewrites them, so a formatting
        // difference makes every save churn the whole file -- and one of them
        // was worse than churn: System.Text.Json escapes '+' to \u002B by
        // default, which is valid JSON Python reads back perfectly and turns
        // "#....+....+.@..#" into a row no human can read.  The grid is a
        // list of strings so that it stays ASCII art; this is what keeps it.
        var io = new MapIo(RepoPaths.Maps);
        var before = File.ReadAllText(Path.Combine(RepoPaths.Maps, fileName));
        var tmp = Path.Combine(Path.GetTempPath(),
                               "amaze-editor-" + Guid.NewGuid().ToString("N"));
        try
        {
            new MapIo(tmp).Save(fileName, io.Load(fileName), new MapValidator());
            Assert.Equal(before, File.ReadAllText(Path.Combine(tmp, fileName)));
        }
        finally { if (Directory.Exists(tmp)) Directory.Delete(tmp, true); }
    }

    [Fact]
    public void The_blank_map_the_editor_starts_from_is_legal()
    {
        // ...except for its room size: a 14x14 open box is exactly what the
        // march cannot draw, so the blank must WARN and still be exportable.
        var findings = new MapValidator().Validate(MapIo.Blank("blank"));
        Assert.DoesNotContain(findings, f => f.Severity == Severity.Error);
        Assert.Contains(findings, f => f.Rule == "room size");
    }
}
