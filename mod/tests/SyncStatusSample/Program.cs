using System;
using System.IO;
using OniCompanionLink;

// Writes status files with the same call the mod makes (SyncStatus.Compose / Interrupted), for mod/check_output.py.
internal static class Program
{
    private static int Main(string[] args)
    {
        string dir = args.Length > 0 ? args[0] : ".";
        Directory.CreateDirectory(dir);
        string[] names = { "art", "theme", "fonts" };
        string[] dlc = { "EXPANSION1_ID", "DLC2_ID" };
        string t0 = "2026-10-25T12:00:00Z", t1 = "2026-10-25T12:00:41Z";

        File.WriteAllText(Path.Combine(dir, "status-running.json"), SyncStatus.Compose("0.3.0", "running", "full", 744825, dlc, 312, 1033,
            "building: \"Quote\"\nLine", 0, null, names, new[] { "running", "pending", "pending" }, true, t0, t1, 41250, 28.4));
        File.WriteAllText(Path.Combine(dir, "status-done.json"), SyncStatus.Compose("0.3.0", "done", "missing", 744825, new string[0], 1033, 1033,
            null, 2, "item: Foo: NullReferenceException", names, new[] { "done", "done", "failed" }, false, t0, t1, 138800, 61.5));
        File.WriteAllText(Path.Combine(dir, "status-failed.json"), SyncStatus.Compose("0.3.0", "failed", "full", 744825, dlc, 0, 0,
            null, 1, new string('x', 400), names, new[] { "failed", "pending", "pending" }, false, t0, t1, 10, 0));

        string running = SyncStatus.Compose("0.3.0", "running", "missing", 744825, dlc, 5, 9, "food: Meat", 0, null, names,
            new[] { "running", "pending", "pending" }, true, t0, t1, 1000, 3);
        string interrupted = SyncStatus.Interrupted(running, "0.3.0", "2026-10-25T13:00:00Z");
        if (interrupted == null) { Console.Error.WriteLine("Interrupted returned null for a running file"); return 1; }
        File.WriteAllText(Path.Combine(dir, "status-interrupted.json"), interrupted);
        if (SyncStatus.Interrupted(interrupted, "0.3.0", "2026-10-25T13:00:00Z") != null) { Console.Error.WriteLine("Interrupted rewrote a failed file"); return 1; }

        System.Collections.Generic.List<AtlasGlyph> rows = new System.Collections.Generic.List<AtlasGlyph>();
        rows.Add(new AtlasGlyph { U = 65, X = 3, Y = 5, W = 40, H = 52, BX = 2.5f, BY = 48f, Adv = 44.25f });
        rows.Add(new AtlasGlyph { U = 66, X = 50, Y = 5, W = 38, H = 52, BX = 3f, BY = 48f, Adv = 42f });
        System.Collections.Generic.List<AtlasKern> kern = new System.Collections.Generic.List<AtlasKern>();
        kern.Add(new AtlasKern { A = 65, B = 66, X = -1.5f });
        File.WriteAllText(Path.Combine(dir, "graystroke.json"), FontAtlasJson.Compose("0.3.0", 744825, "GRAYSTROKE REGULAR SDF", "Graystroke", 1024, 512, 5, 6f, 72f,
            80f, 60f, -20f, 1f, 40f, rows, kern));
        File.WriteAllText(Path.Combine(dir, "graystroke-nokern.json"), FontAtlasJson.Compose("0.3.0", 744825, "GRAYSTROKE REGULAR SDF", "Graystroke", 1024, 512, 5, 6f, 72f,
            80f, 60f, -20f, 1f, 40f, rows, null));
        return 0;
    }
}
