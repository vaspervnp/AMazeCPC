using System.Text.RegularExpressions;
using Amaze.Editor.Models;

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
    public void The_grid_is_still_the_size_world_py_says()
    {
        // world.py derives MAZE_W from the literal, so the literal is what
        // is measured: the first row of the first map.
        var src = File.ReadAllText(RepoPaths.World);
        var m = Regex.Match(src, "MAZE_SRC\\s*=\\s*\\[\\s*\r?\n\\s*\"([^\"]+)\"");
        Assert.True(m.Success, "world.py's MAZE_SRC no longer starts with a row literal");
        Assert.Equal(MapCells.Width, m.Groups[1].Value.Length);
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
