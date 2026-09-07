namespace Amaze.Editor.Tests;

/// <summary>
/// Where the repository is, found by walking up from the test binary until
/// tools/world.py turns up.  A relative path with the right number of "../"
/// in it is a path that breaks the first time the build layout moves.
/// </summary>
public static class RepoPaths
{
    public static string Root { get; } = Find();

    public static string Maps => Path.Combine(Root, "tools", "maps");
    public static string World => Path.Combine(Root, "tools", "world.py");
    public static string GameAsm => Path.Combine(Root, "engine2", "src", "game.asm");
    public static string GenAux => Path.Combine(Root, "engine2", "tools", "genaux.py");
    public static string Main3 => Path.Combine(Root, "engine2", "src", "main3.asm");

    private static string Find()
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null)
        {
            if (File.Exists(Path.Combine(d.FullName, "tools", "world.py")))
                return d.FullName;
            d = d.Parent;
        }
        throw new DirectoryNotFoundException(
            "tools/world.py is not above " + AppContext.BaseDirectory);
    }
}
