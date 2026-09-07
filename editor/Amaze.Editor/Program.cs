using Amaze.Editor.Components;
using Amaze.Editor.Services;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

// WHERE THE MAPS ARE, and it is the repository's own tools/maps -- the same
// directory world.export_levels() writes and world.load_levels() reads.  The
// editor writes the build's input; it does not keep a copy of its own.
builder.Services.AddSingleton(new MapIo(RepoLocator.MapsDirectory()));
builder.Services.AddSingleton<MapValidator>();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}
app.UseStatusCodePagesWithReExecute("/not-found", createScopeForStatusCodePages: true);
app.UseHttpsRedirection();

app.UseAntiforgery();

app.MapStaticAssets();
app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();
