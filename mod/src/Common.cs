using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace OniCompanionLink
{
    internal static class Log
    {
        private const string Prefix = "[OniCompanionLink] ";
        public static void Info(string msg) { try { UnityEngine.Debug.Log(Prefix + msg); } catch { } }
        public static void Warn(string msg) { try { UnityEngine.Debug.LogWarning(Prefix + msg); } catch { } }
        public static void Error(string msg, Exception e = null)
        {
            try { UnityEngine.Debug.LogWarning(Prefix + "ERROR " + msg + (e != null ? ": " + e : "")); } catch { }
        }
    }

    internal static class Env
    {
        public const string ModVersion = "0.5.0";
        /// <summary>Contract level this mod was built for (3 = v1.3) and the core versions it works with (mod-export / mod-live schemas).</summary>
        public const int Contract = 3;
        public const string RequiresCoreMin = "1.3.0";
        public static void WriteCompat(Json j)
        {
            j.PI("contract", Contract);
            j.Key("requiresCore").Obj().P("min", RequiresCoreMin).EndObj();
        }

        /// <summary>Set when something went wrong badly enough that the mod turns itself off.</summary>
        public static volatile bool Disabled;

        public static void Disable(string why, Exception e = null)
        {
            if (Disabled) return;
            Disabled = true;
            Log.Error("disabled for this session: " + why, e);
        }

        // <ONI user folder>/companion  (next to mods/). Util.RootFolder() is what KMod.Manager uses for "mods/".
        // Android local mode (LocalMode.cs): inside a Windows-game emulator on Android the folder moves to the shared drive that holds the
        // app's marker; found once at load. Everything else (including the Connect a phone pairing folder) stays in the user folder.
        private static string companionDir, localWhy;
        public static string CompanionDir()
        {
            if (companionDir == null)
            {
                string local = null;
                try { local = LocalMode.FindCompanionDir(out localWhy); } catch (Exception e) { localWhy = "probe failed: " + e.GetType().Name; }
                companionDir = local ?? UserCompanionDir();
                LocalNote = local != null ? "Android local mode: companion folder " + local : null;
            }
            return companionDir;
        }
        public static string LocalNote;
        public static bool IsLocal { get { CompanionDir(); return LocalNote != null; } }
        public static string LocalWhy { get { CompanionDir(); return localWhy; } }
        /// <summary>The user-folder companion directory: where the service (core) and the Connect a phone files live.</summary>
        public static string UserCompanionDir()
        {
            return Path.Combine(Util.RootFolder(), "companion");
        }

        // KleiVersion.ChangeList is a compile-time constant; read it by reflection so a game update is reflected
        // even if this DLL is not rebuilt.
        public static int Build()
        {
            try
            {
                FieldInfo f = typeof(KleiVersion).GetField("ChangeList", BindingFlags.Public | BindingFlags.Static);
                if (f != null)
                {
                    object v = f.IsLiteral ? f.GetRawConstantValue() : f.GetValue(null);
                    return Convert.ToInt32(v, CultureInfo.InvariantCulture);
                }
            }
            catch { }
            return 0;
        }

        public static List<string> ActiveDlc()
        {
            List<string> ids = new List<string>(DlcManager.GetActiveDLCIds());
            ids.Sort(StringComparer.Ordinal);
            return ids;
        }

        public static string DlcSetName(List<string> ids)
        {
            return ids.Count == 0 ? "base" : string.Join("+", ids.ToArray());
        }

        public static string Now()
        {
            return System.DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
        }
    }

    internal static class Txt
    {
        private static readonly Regex Tags = new Regex("<[^>]*>", RegexOptions.Compiled);

        /// <summary>Game text with rich-text/link markup removed.</summary>
        public static string Clean(object o)
        {
            if (o == null) return "";
            string s;
            try { s = o.ToString(); } catch { return ""; }
            if (string.IsNullOrEmpty(s)) return "";
            if (s.IndexOf('<') >= 0) s = Tags.Replace(s, "");
            return s.Trim();
        }

        public static double C(float kelvin) { return kelvin - 273.15; }
    }
}
