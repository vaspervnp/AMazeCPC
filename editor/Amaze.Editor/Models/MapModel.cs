namespace Amaze.Editor.Models;

/// <summary>
/// One map file -- which is one entry of <c>tools/world.py</c>'s LEVELS and
/// nothing more.
///
/// THE GRID CARRIES THE START AND THE EXIT, as '@' and 'X', exactly the way
/// the Python literals carry them.  There are deliberately no separate
/// Start/Exit properties: a file that said both could disagree with itself,
/// and world.py would then have two opinions about where the player stands.
/// </summary>
public sealed class MapModel
{
    public string Name { get; set; } = "";

    /// <summary>[width, height].  Redundant with Grid, and checked against it.</summary>
    public int[] Size { get; set; } = [MapCells.Width, MapCells.Height];

    /// <summary>One string a row, '#' wall, '.' floor, '+' door, '@' start, 'X' exit.</summary>
    public List<string> Grid { get; set; } = [];

    /// <summary>Pickup cells as [x, y].</summary>
    public List<int[]> Ammo { get; set; } = [];

    /// <summary>Monster cells as [x, y].</summary>
    public List<int[]> Monsters { get; set; } = [];

    public MapModel Clone() => new()
    {
        Name = Name,
        Size = [.. Size],
        Grid = [.. Grid],
        Ammo = [.. Ammo.Select(c => new[] { c[0], c[1] })],
        Monsters = [.. Monsters.Select(c => new[] { c[0], c[1] })],
    };
}

/// <summary>The cell alphabet, and the two things that are floor in disguise.</summary>
public static class MapCells
{
    public const char Wall = '#';
    public const char Floor = '.';
    public const char Door = '+';
    public const char Start = '@';
    public const char Exit = 'X';

    /// <summary>world.py's MAZE_W / MAZE_H.  The march's tables are 16x16.</summary>
    public const int Width = 16;
    public const int Height = 16;

    /// <summary>Rooms sit on a five-cell pitch, so a cell's room is (x/5, y/5).</summary>
    public const int RoomPitch = 5;

    public static readonly char[] Legal = [Wall, Floor, Door, Start, Exit];

    /// <summary>'@' and 'X' stand ON floor -- world.py's load_maze reads both as FLOOR.</summary>
    public static bool IsFloor(char c) => c is Floor or Start or Exit;

    /// <summary>What the march can see through once a door is open.</summary>
    public static bool IsWalkable(char c) => c != Wall;
}
