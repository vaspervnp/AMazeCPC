using System.Text.RegularExpressions;
using Amaze.Editor.Models;
using Amaze.Editor.Services;

namespace Amaze.Editor.Tests;

/// <summary>
/// EVERY CONSTANT IN EngineLimits IS A COPY, so every one of them is read
/// back out of the file that owns it here.  Without this the editor would go
/// on accepting eighteen doors long after game.asm stopped registering them,
/// and the map would build and ship with six doors that never open.
/// </summary>
public class EngineLimitsTests
{
    [Fact]
    public void MaxDoors_matches_game_asm()
    {
        Assert.Equal(EngineLimits.MaxDoors, Equ(RepoPaths.GameAsm, "MAXDOORS"));
    }

    [Fact]
    public void MaxAmmo_and_MaxMonsters_match_genaux()
    {
        Assert.Equal(EngineLimits.MaxAmmo, PyInt(RepoPaths.GenAux, "MAXAMMO"));
        Assert.Equal(EngineLimits.MaxMonsters, PyInt(RepoPaths.GenAux, "MAXMON"));
    }

    [Fact]
    public void The_score_still_has_to_fit_one_digit()
    {
        // main3.asm: `assert NAMMO + 1 <= 9`.  The 9 is what is checked --
        // it is MN_G0 + 9 = '9', and MN_G0 + 10 is 'A'.
        var src = File.ReadAllText(RepoPaths.Main3);
        var m = Regex.Match(src, @"assert\s+NAMMO\s*\+\s*1\s*<=\s*(\d+)");
        Assert.True(m.Success, "main3.asm no longer asserts NAMMO + 1 <= n");
        Assert.Equal(EngineLimits.MaxScoreDigit, int.Parse(m.Groups[1].Value));
    }

    [Fact]
    public void The_grid_is_still_the_size_the_maps_are()
    {
        // THE MAPS ARE THE SOURCE NOW.  world.py has no map literal left --
        // it does `MAZE_W = len(LEVELS[0]["src"][0])` on what it loaded from
        // tools/maps -- so the files are what this measures.
        //
        // 16x16 is the ENGINE's shape, not the map's choice: march.asm
        // indexes SOLID as cy*16 + cx and SOLID is 256 bytes.  A file of
        // another size would be rejected by MapValidator's size rule; this
        // catches the other direction, a shipped map the constant no longer
        // describes.
        var maps = new MapIo(RepoPaths.Maps);
        var files = maps.List();
        Assert.NotEmpty(files);
        foreach (var f in files)
        {
            var g = maps.Load(f).Grid;
            Assert.Equal(MapCells.Height, g.Count);
            Assert.All(g, row => Assert.Equal(MapCells.Width, row.Length));
        }
    }

    [Fact]
    public void world_py_has_no_map_literal_left()
    {
        // A LITERAL IS A SECOND COPY OF THE MAP, and a second copy is a
        // thing that can be edited: the editor would write level1.json, the
        // build would go on shipping the literal, and nothing would say so.
        // MAZE_SRC_M2 stays -- it is the mono prototype disc's layout, which
        // has no levels, no pickups and no way out.
        var src = File.ReadAllText(RepoPaths.World);
        Assert.DoesNotContain("MAZE_SRC = [", src);
        Assert.DoesNotContain("MAZE_SRC_L2 = [", src);
        Assert.Contains("load_levels()", src);
    }

    /// <summary>NAME equ N out of an asm source.</summary>
    private static int Equ(string path, string name)
    {
        var m = Regex.Match(File.ReadAllText(path),
                            $@"^{Regex.Escape(name)}\s+equ\s+(#?[0-9A-Fa-f]+)",
                            RegexOptions.Multiline | RegexOptions.IgnoreCase);
        Assert.True(m.Success, $"{name} is not an equ in {Path.GetFileName(path)}");
        var v = m.Groups[1].Value;
        return v.StartsWith('#') ? Convert.ToInt32(v[1..], 16) : int.Parse(v);
    }

    /// <summary>NAME = N out of a Python source.</summary>
    private static int PyInt(string path, string name)
    {
        var m = Regex.Match(File.ReadAllText(path),
                            $@"^{Regex.Escape(name)}\s*=\s*(\d+)",
                            RegexOptions.Multiline);
        Assert.True(m.Success, $"{name} is not assigned in {Path.GetFileName(path)}");
        return int.Parse(m.Groups[1].Value);
    }
}
