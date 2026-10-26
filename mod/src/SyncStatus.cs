using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace OniCompanionLink
{
    /// <summary>
    /// The text of companion/sync/status.json (contracts/mod-sync-status.schema.json). No Unity types here, so an offline program can
    /// compile it with Json.cs and check the output against the schema (mod/tests/SyncStatusSample, mod/check_output.py).
    /// </summary>
    internal static class SyncStatus
    {
        public static string Compose(string modVersion, string state, string scope, int build, IEnumerable<string> dlcIds, int done, int total,
            string current, int errors, string lastError, string[] stageNames, string[] stageState, bool pausedBySync,
            string startedAt, string updatedAt, long elapsedMs, double worstFrameMs)
        {
            Json j = new Json(768);
            j.Obj().PI("schema", 1).P("modVersion", modVersion).P("state", state).P("scope", scope).PI("build", build);
            j.Key("dlcIds").StrArr(dlcIds);
            j.PI("done", Math.Min(done, Math.Max(total, done))).PI("total", total);
            if (current != null) j.P("current", current); else j.Key("current").Null();
            j.PI("errors", errors);
            if (!string.IsNullOrEmpty(lastError)) j.P("lastError", lastError.Length > 160 ? lastError.Substring(0, 160) : lastError);
            j.Key("stages").Arr();
            for (int i = 0; i < stageNames.Length; i++) j.Obj().P("name", stageNames[i]).P("state", stageState[i]).EndObj();
            j.EndArr();
            j.P("gamePausedBySync", pausedBySync);
            j.P("startedAt", startedAt).P("updatedAt", updatedAt);
            j.PI("elapsedMs", elapsedMs);
            j.P("worstFrameMs", Math.Round(worstFrameMs, 1));
            j.EndObj();
            return j.ToString();
        }

        /// <summary>
        /// A file that still says "running" belongs to a session that is gone (crash or quit during the run): the same file rewritten as
        /// failed, or null when the file is not in that state.
        /// </summary>
        public static string Interrupted(string oldText, string modVersion, string now)
        {
            if (oldText.IndexOf("\"state\":\"running\"", StringComparison.Ordinal) < 0) return null;
            Match ms = Regex.Match(oldText, "\"scope\":\"(full|missing)\"");
            Match md = Regex.Match(oldText, "\"done\":(\\d+)");
            Match mt = Regex.Match(oldText, "\"total\":(\\d+)");
            Match mb = Regex.Match(oldText, "\"build\":(\\d+)");
            Match mst = Regex.Match(oldText, "\"startedAt\":\"([^\"]+)\"");
            Json j = new Json(512);
            j.Obj().PI("schema", 1).P("modVersion", modVersion).P("state", "failed").P("scope", ms.Success ? ms.Groups[1].Value : "full");
            if (mb.Success) j.PI("build", long.Parse(mb.Groups[1].Value, CultureInfo.InvariantCulture));
            j.PI("done", md.Success ? long.Parse(md.Groups[1].Value, CultureInfo.InvariantCulture) : 0);
            j.PI("total", mt.Success ? long.Parse(mt.Groups[1].Value, CultureInfo.InvariantCulture) : 0);
            j.Key("current").Null().PI("errors", 1).P("lastError", "The game closed during the sync");
            j.P("gamePausedBySync", false);
            if (mst.Success) j.P("startedAt", mst.Groups[1].Value);
            j.P("updatedAt", now).EndObj();
            return j.ToString();
        }
    }

    internal sealed class AtlasGlyph { public uint U; public int X, Y, W, H; public float BX, BY, Adv; }
    internal sealed class AtlasKern { public uint A, B; public float X; }

    /// <summary>The text of companion/fonts/&lt;build&gt;/graystroke.json (contracts/font-atlas.schema.json). No Unity types.</summary>
    internal static class FontAtlasJson
    {
        public static string Compose(string modVersion, int build, string name, string family, int w, int h, int padding, float spread, float pointSize,
            float lineHeight, float ascent, float descent, float scale, float tabWidth, List<AtlasGlyph> rows, List<AtlasKern> kern)
        {
            Json j = new Json(64 + rows.Count * 110);
            j.Obj().PI("schema", 1).P("modVersion", modVersion).PI("build", build).P("name", name).P("family", family);
            j.Key("atlas").Obj().P("file", "graystroke.png").PI("width", w).PI("height", h).PI("padding", padding).P("spread", spread)
                .P("pointSize", pointSize).P("encoding", "sdf-red").EndObj();
            j.Key("face").Obj().P("lineHeight", lineHeight).P("ascent", ascent).P("descent", descent).P("scale", scale).P("tabWidth", tabWidth).EndObj();
            j.Key("glyphs").Arr();
            foreach (AtlasGlyph g in rows)
                j.Obj().PI("unicode", g.U).PI("x", g.X).PI("y", g.Y).PI("w", g.W).PI("h", g.H).P("bearingX", g.BX).P("bearingY", g.BY).P("advance", g.Adv).EndObj();
            j.EndArr();
            if (kern != null && kern.Count > 0)
            {
                j.Key("kerning").Arr();
                foreach (AtlasKern k in kern) j.Obj().PI("first", k.A).PI("second", k.B).P("x", k.X).EndObj();
                j.EndArr();
            }
            j.EndObj();
            return j.ToString();
        }
    }
}
