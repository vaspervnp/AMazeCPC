namespace Amaze.Editor.Models;

/// <summary>
/// The numbers the Z80 side cannot exceed.  EVERY ONE OF THESE IS A COPY,
/// and copies drift -- so Amaze.Editor.Tests.EngineLimitsTests reads each of
/// them back out of the source that owns it and fails if they have moved.
/// That test is the only reason it is safe to write them here at all.
/// </summary>
public static class EngineLimits
{
    /// <summary>game.asm.  game_init registers this many doors and SILENTLY drops the rest.</summary>
    public const int MaxDoors = 16;

    /// <summary>genaux.py.  Cells a level record has room for.</summary>
    public const int MaxAmmo = 8;

    /// <summary>genaux.py.</summary>
    public const int MaxMonsters = 4;

    /// <summary>
    /// menu.asm draws the score as ONE glyph, MN_G0 + n, and MN_G0+10 is 'A'.
    /// A level scores one a pickup plus one a monster.
    /// </summary>
    public const int MaxScoreDigit = 9;

    /// <summary>
    /// world.py: the march floods to R_MAX and files faces at L1 1..R_MAX+1,
    /// so a room whose far corner sits past that is drawn as an open field.
    /// 4x4 works; see the long note in world.py for why W+H &lt;= 7 is too strict.
    /// </summary>
    public const int MaxRoomSide = 4;
}
