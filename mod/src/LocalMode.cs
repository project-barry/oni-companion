using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace OniCompanionLink
{
    /// <summary>
    /// Android local mode (plan 4.2, contracts/pairing.schema.json LocalMarker). When the game runs as the Windows build inside a
    /// Windows-game emulator on Android (Wine under Winlator, GameNative and similar), the emulator's private storage cannot be read by
    /// the ONI Companion app. So the mod writes its companion folder to a drive the emulator maps to Android shared storage:
    /// the drive that holds the fixed folder ONICompanion with the app's marker.json. Nothing else changes.
    /// What is known about the emulators (read from their public source, not run here): Winlator and GameNative make a drive
    /// letter by pointing a Wine drive at an Android folder; the default container has D: = the Android Download folder and
    /// E: = the app's private storage; extra drives (D: to K:, up to 8) are added by the user in the container's Drives tab.
    /// So the marker is found at D:\ONICompanion when the app made /storage/emulated/0/Download/ONICompanion, or at X:\ONICompanion
    /// on a drive the user mapped to /storage/emulated/0. GameHub is closed source: its drive mapping is not verified.
    /// The mod never takes a path from a command or from the marker; it only checks fixed names.
    /// No Unity types here (tested offline by mod/tests/ConnectTest).
    /// </summary>
    internal static class LocalMode
    {
        public const string FolderName = "ONICompanion";

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)] private static extern IntPtr GetModuleHandleA(string name);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)] private static extern IntPtr GetProcAddress(IntPtr module, string name);

        /// <summary>True when this Windows build runs under Wine: ntdll.dll exports wine_get_version (a real Windows has no such export).</summary>
        public static bool RunsUnderWine()
        {
            try
            {
                if (Environment.OSVersion.Platform != PlatformID.Win32NT) return false;   // native Linux/Mac build: never
                IntPtr ntdll = GetModuleHandleA("ntdll.dll");
                return ntdll != IntPtr.Zero && GetProcAddress(ntdll, "wine_get_version") != IntPtr.Zero;
            }
            catch { return false; }
        }

        /// <summary>
        /// The companion folder on the first drive D: to Z: that holds ONICompanion\marker.json (a valid marker), or null.
        /// `exists` and `read` are the file system (injected so the check runs offline). `why` says what was found, for the log.
        /// </summary>
        public static string FindCompanionDir(Func<string, bool> exists, Func<string, string> read, out string why)
        {
            for (char d = 'D'; d <= 'Z'; d++)
            {
                string marker = d + ":\\" + FolderName + "\\marker.json";
                bool there;
                try { there = exists(marker); } catch { there = false; }
                if (!there) continue;
                string reason = ValidMarker(read, marker);
                if (reason != null) { why = d + ": has " + FolderName + " but " + reason; continue; }
                why = "marker on " + d + ":";
                return d + ":\\" + FolderName + "\\companion";
            }
            why = "no marker on D: to Z:";
            return null;
        }

        private static string ValidMarker(Func<string, string> read, string path)
        {
            try
            {
                string text = read(path);
                JObject o;
                using (JsonTextReader r = new JsonTextReader(new StringReader(text)) { DateParseHandling = DateParseHandling.None })
                    o = JObject.Load(r);
                if ((int?)o["schema"] != 1) return "marker.json schema is not 1";
                if ((string)o["app"] != "oni-companion") return "marker.json app is not oni-companion";
                return null;
            }
            catch (Exception e) { return "marker.json unreadable (" + e.GetType().Name + ")"; }
        }

        public static string FindCompanionDir(out string why)
        {
            if (!RunsUnderWine()) { why = "not under Wine"; return null; }
            return FindCompanionDir(File.Exists, delegate (string p) { return File.ReadAllText(p, Encoding.UTF8); }, out why);
        }
    }
}
