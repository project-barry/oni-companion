using System;
using System.IO;
using System.Text;
using OniCompanionLink;

// Offline check of the Connect a phone logic (no Unity): state.json parsing, request numbering and files, local-mode drive probing.
// Usage: ConnectTest <fixtures/synthetic> <outdir>. Request files land in <outdir>/requests for check.py (schema validation).
internal static class Program
{
    private static int failures;
    private static void Check(bool ok, string what) { if (!ok) { failures++; Console.WriteLine("FAIL " + what); } else Console.WriteLine("ok   " + what); }

    private static int Main(string[] args)
    {
        string fx = args[0], outDir = args[1];
        if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
        Directory.CreateDirectory(outDir);

        // ---- state.json
        PairState on = PairState.Parse(File.ReadAllText(Path.Combine(fx, "companion/pairing/state.json")));
        Check(on != null && on.Enabled && on.Listening && on.Port == 47615, "state on: enabled, listening, port");
        Check(on.Name == "spiffy-raccoon" && on.FingerprintTag == "A4CC", "state on: name and tag");
        Check(on.CodeDisplay == "K7M2-QX9P" && on.CodeFailuresLeft == 5, "state on: code");
        Check(on.QrText != null && on.QrText.StartsWith("{\"v\":1,\"t\":\"onic-pair\""), "state on: qrText is the exact text");
        Check(on.Addresses.Count == 2 && on.AddressKinds[1] == "tailscale", "state on: addresses");
        Check(on.Devices.Count == 1 && on.Devices[0].DeviceId == "d-a1b2c3d4e5f6" && on.Devices[0].Label == "Pixel 9", "state on: device");
        Check(on.LastSeq == 3 && on.LastState == "done", "state on: lastRequest");
        PairState off = PairState.Parse(File.ReadAllText(Path.Combine(fx, "companion/pairing/state-off.json")));
        Check(off != null && !off.Enabled && off.CodeDisplay == null && off.QrText == null && off.Addresses.Count == 0 && off.LastSeq == 0, "state off: no code, no qr, no addresses, lastRequest null");
        Check(PairState.Parse("{not json") == null && PairState.Parse("{\"schema\":2}") == null && PairState.Parse("") == null, "bad state text gives null");

        // ---- QR of the real payload fits
        int ver; bool[,] qr = Qr.Encode(on.QrText, out ver);
        Check(qr != null && ver >= 1 && ver <= 15, "the fixture qrText fits a QR code (version " + ver + ")");

        // ---- request numbering and files
        string comp = Path.Combine(outDir, "companion");
        CopyDir(Path.Combine(fx, "companion/pairing"), Path.Combine(comp, "pairing"));
        PairingFiles pf = new PairingFiles(comp);
        Check(pf.NextSeq(on) == 9, "NextSeq: highest req file (8) wins over lastRequest (3)");
        Check(pf.NextSeq(null) == 9, "NextSeq: no state still sees the req files");
        string empty = Path.Combine(outDir, "empty");
        PairingFiles pe = new PairingFiles(empty);
        Check(pe.NextSeq(null) == 1 && pe.NextSeq(on) == 4, "NextSeq: empty folder starts at 1, or after lastRequest");

        string reqs = Path.Combine(outDir, "requests");
        PairingFiles w = new PairingFiles(Path.Combine(outDir, "w"));
        long a = w.WriteRequest(on, "set_enabled", true);
        long b = w.WriteRequest(on, "new_code");
        long c = w.WriteRequest(on, "remove_device", null, "d-a1b2c3d4e5f6");
        long d = w.WriteRequest(on, "reset_identity", null, null, true);
        long e = w.WriteRequest(on, "set_plain_http", false);
        Check(a == 4 && b == 5 && c == 6 && d == 7 && e == 8, "WriteRequest numbers 4..8 after lastRequest 3 and its own files");
        Directory.CreateDirectory(reqs);
        foreach (string f in Directory.GetFiles(w.RequestsDir)) File.Copy(f, Path.Combine(reqs, Path.GetFileName(f)));
        bool tmpLeft = false; foreach (string f in Directory.GetFiles(w.RequestsDir)) if (f.EndsWith(".tmp")) tmpLeft = true;
        Check(!tmpLeft && Directory.GetFiles(w.RequestsDir, "req-*.json").Length == 5, "five request files, no .tmp left behind");

        // ---- local mode probing
        string marker = File.ReadAllText(Path.Combine(fx, "companion-local/ONICompanion/marker.json"));
        string why;
        string dir = LocalMode.FindCompanionDir(p => p == "E:\\ONICompanion\\marker.json", p => marker, out why);
        Check(dir == "E:\\ONICompanion\\companion", "marker on E: gives E:\\ONICompanion\\companion (" + why + ")");
        dir = LocalMode.FindCompanionDir(p => p == "D:\\ONICompanion\\marker.json" || p == "F:\\ONICompanion\\marker.json", p => p.StartsWith("D") ? "{\"schema\":1,\"app\":\"other\"}" : marker, out why);
        Check(dir == "F:\\ONICompanion\\companion", "an invalid marker on D: is skipped, the valid one on F: is used (" + why + ")");
        dir = LocalMode.FindCompanionDir(p => false, p => "", out why);
        Check(dir == null, "no marker: null (" + why + ")");
        dir = LocalMode.FindCompanionDir(p => p.StartsWith("C:") || p.StartsWith("A:"), p => marker, out why);
        Check(dir == null, "C: and A: are never probed");
        dir = LocalMode.FindCompanionDir(p => true, p => "garbage", out why);
        Check(dir == null, "unreadable marker: null (" + why + ")");
        Check(!LocalMode.RunsUnderWine(), "this machine is not Wine");

        Console.WriteLine(failures == 0 ? "ALL OK" : failures + " FAILED");
        return failures == 0 ? 0 : 1;
    }

    private static void CopyDir(string from, string to)
    {
        Directory.CreateDirectory(to);
        foreach (string f in Directory.GetFiles(from)) File.Copy(f, Path.Combine(to, Path.GetFileName(f)));
        foreach (string d in Directory.GetDirectories(from)) CopyDir(d, Path.Combine(to, Path.GetFileName(d)));
    }
}
