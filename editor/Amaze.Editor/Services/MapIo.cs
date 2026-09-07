using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using Amaze.Editor.Models;

namespace Amaze.Editor.Services;

/// <summary>
/// Reading and writing tools/maps/*.json -- the same files
/// <c>world.export_levels()</c> writes and <c>world.load_levels()</c> reads.
///
/// THE FILE NAME IS THE LEVEL ORDER.  world.load_levels() sorts by filename,
/// so level0.json comes before level1.json and the exit walks you through
/// them in that order.  Nothing else records the order.
/// </summary>
public sealed class MapIo(string mapsDirectory)
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        // '+' IS A DOOR AND IT HAS TO LOOK LIKE ONE.  The default encoder
        // escapes it to \u002B, which is valid JSON that Python reads back
        // perfectly -- and turns "#....+....+.@..#" into a row no human can
        // read.  These files are ASCII art on purpose; that is the whole
        // reason the grid is a list of strings and not a list of ints.
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public string Directory { get; } = mapsDirectory;

    public IReadOnlyList<string> List() =>
        System.IO.Directory.Exists(Directory)
            ? [.. System.IO.Directory.GetFiles(Directory, "*.json")
                        .Select(Path.GetFileName)
                        .Where(n => n is not null)
                        .Select(n => n!)
                        .Order(StringComparer.Ordinal)]
            : [];

    public MapModel Load(string fileName)
    {
        var path = Path.Combine(Directory, fileName);
        var map = JsonSerializer.Deserialize<MapModel>(File.ReadAllText(path), Json)
                  ?? throw new InvalidDataException($"{fileName} is not a map");
        return map;
    }

    /// <summary>
    /// Write it, but ONLY if it would build.  The whole point of the
    /// validator is that a broken map never reaches the generators, where it
    /// would surface as an AssertionError three tools downstream with no
    /// mention of which cell caused it.
    /// </summary>
    public void Save(string fileName, MapModel map, MapValidator validator)
    {
        var errors = validator.Validate(map)
                              .Where(f => f.Severity == Severity.Error).ToList();
        if (errors.Count > 0)
            throw new InvalidOperationException(
                "the map does not build:\n  " +
                string.Join("\n  ", errors.Select(e => e.ToString())));

        System.IO.Directory.CreateDirectory(Directory);
        File.WriteAllText(Path.Combine(Directory, fileName),
                          JsonSerializer.Serialize(map, Json) + "\n");
    }

    /// <summary>A blank 16x16: a wall border, floor inside, a start and an exit.</summary>
    public static MapModel Blank(string name)
    {
        var grid = new List<string>();
        for (var y = 0; y < MapCells.Height; y++)
        {
            var row = new char[MapCells.Width];
            for (var x = 0; x < MapCells.Width; x++)
                row[x] = (x == 0 || y == 0 ||
                          x == MapCells.Width - 1 || y == MapCells.Height - 1)
                         ? MapCells.Wall : MapCells.Floor;
            grid.Add(new string(row));
        }
        grid[1] = ReplaceAt(grid[1], 1, MapCells.Start);
        grid[MapCells.Height - 2] =
            ReplaceAt(grid[MapCells.Height - 2], MapCells.Width - 2, MapCells.Exit);
        return new MapModel { Name = name, Grid = grid };
    }

    public static string ReplaceAt(string row, int x, char c)
    {
        var a = row.ToCharArray();
        a[x] = c;
        return new string(a);
    }
}
