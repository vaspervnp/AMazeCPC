namespace Amaze.Editor.Services;

/// <summary>
/// Finds the repository by walking up from the running binary until
/// tools/world.py turns up -- the same trick the tests use, and for the same
/// reason: a relative path with the right number of "../" in it breaks the
/// first time the build layout moves.
///
/// AMAZE_REPO overrides it, for running the editor from somewhere else.
/// </summary>
public static class RepoLocator
{
    public static string MapsDirectory() => Path.Combine(Root(), "tools", "maps");

    public static string Root()
    {
        var env = Environment.GetEnvironmentVariable("AMAZE_REPO");
        if (!string.IsNullOrWhiteSpace(env)) return env;

        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d is not null)
        {
            if (File.Exists(Path.Combine(d.FullName, "tools", "world.py")))
                return d.FullName;
            d = d.Parent;
        }
        throw new DirectoryNotFoundException(
            "tools/world.py is not above " + AppContext.BaseDirectory +
            " -- set AMAZE_REPO to the repository root");
    }
}
