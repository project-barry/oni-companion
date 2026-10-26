using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using TMPro;
using UnityEngine;
using UnityEngine.TextCore;

namespace OniCompanionLink
{
    /// <summary>
    /// Art &amp; font sync (v1.2, contracts/mod-sync-status.schema.json). The command `sync_assets {scope: full|missing}` draws the
    /// WHOLE catalog from the user's own game (nothing from Klei is shipped), then rewrites the theme and exports the Graystroke
    /// TextMeshPro SDF atlas (companion/fonts/&lt;build&gt;/graystroke.png + graystroke.json, contracts/font-atlas.schema.json).
    /// - Because the user is waiting, it is NOT frame-budgeted like the on-demand art: the game is paused for the run
    ///   (SpeedControlScreen.Pause/Unpause, a counter, so a pause the player already had stays) and the previous speed comes
    ///   back at the end, also when the run fails or is cut short. Main-thread work is time-sliced at about 30 ms a frame so the
    ///   game stays responsive; PNG encoding and files stay on the art worker thread.
    /// - scope full: every catalog item is drawn again, the theme is rebuilt, the atlas exported again.
    ///   scope missing: only items the art manifest lacks or whose srcKey changed; the theme only if absent; the atlas only if absent.
    /// - Stages, in order: art, theme, fonts. A theme or fonts failure is counted (errors, lastError, the stage) but does not turn
    ///   the run into "failed"; only an art failure does.
    /// - companion/sync/status.json is written atomically about every 250 ms while running and once more when it ends.
    ///   `total` is the number of catalog items looked at (for missing too: the unchanged ones count as done at once).
    /// Anything that throws ends the run (state failed) and gives the speed back. Nothing here reaches the game's own state.
    /// </summary>
    internal static class Sync
    {
        private enum Phase { Idle, Starting, Art, Drain, Theme, Fonts, Finishing }

        private const double FrameBudgetMs = 30.0;     // main-thread art work per frame while syncing
        private const int MaxEncoderQueue = 32;        // images waiting for the encoder: wait, do not pile up
        private const float StatusGapS = 0.25f;
        private const float DrainTimeoutS = 60f;
        private const float ThemeTimeoutS = 40f;
        private const float FontsTimeoutS = 60f;
        private const int MaxSideAtlas = 4096;

        private static Phase phase = Phase.Idle;
        private static string scope = "full";
        private static int build;
        private static List<string> dlc = new List<string>();
        private static int total, done, errors, index;
        private static int noPicture, same, drawn, exceptionsInARow;
        private static string current, lastError;
        private static readonly string[] stageNames = { "art", "theme", "fonts" };
        private static readonly string[] stageState = { "pending", "pending", "pending" };
        private static bool heldPause;
        private static object heldInstance;
        private static Stopwatch run;
        private static string startedAt;
        private static float lastStatus = -10f, phaseStart;
        private static double worstFrameMs;
        private static int storeFailedAtStart;
        private static bool initDone;
        private static string statusPath;

        // fonts
        private static Thread fontThread;
        private static volatile int fontResult;        // 0 running, 1 ok, 2 failed
        private static string fontMessage;
        private static bool fontsStarted;

        public static bool Running { get { return phase != Phase.Idle; } }

        private static string StatusPath()
        {
            if (statusPath == null) statusPath = Path.Combine(Path.Combine(Env.CompanionDir(), "sync"), "status.json");
            return statusPath;
        }

        // ---------------------------------------------------------------- entry points

        /// <summary>Mod load: a "running" file left by a crash or a quit during a sync is rewritten as failed (it must not look alive).</summary>
        public static void Init()
        {
            if (initDone) return;
            initDone = true;
            try
            {
                string p = StatusPath();
                if (!File.Exists(p)) return;
                string fixedText = SyncStatus.Interrupted(File.ReadAllText(p), Env.ModVersion, Env.Now());
                if (fixedText == null) return;
                Files.WriteAtomic(p, fixedText);
                Log.Info("sync: an unfinished run from an earlier session was marked failed");
            }
            catch (Exception e) { Log.Warn("sync: init failed: " + e.Message); }
        }

        /// <summary>Commands, main thread: a validated sync_assets. Acks at once.</summary>
        public static void Request(string path, long seq, string requestedScope)
        {
            if (Env.Disabled) { Commands.Finish(path, seq, false, "The link is off"); return; }
            if (phase != Phase.Idle) { Commands.Finish(path, seq, false, "Already running"); return; }
            if (!LiveWriter.Ready()) { Commands.Finish(path, seq, false, "No colony is loaded"); return; }
            if (!Art.SyncReady()) { Commands.Finish(path, seq, false, "Art is not available"); return; }
            scope = requestedScope == "missing" ? "missing" : "full";
            build = Env.Build();
            dlc = Env.ActiveDlc();
            total = done = errors = index = 0;
            noPicture = same = drawn = exceptionsInARow = 0;
            current = null; lastError = null;
            for (int i = 0; i < stageState.Length; i++) stageState[i] = "pending";
            stageState[0] = "running";
            worstFrameMs = 0;
            storeFailedAtStart = Art.StoreFailures;
            fontsStarted = false; fontResult = 0; fontMessage = null; fontThread = null;
            run = Stopwatch.StartNew();
            startedAt = Env.Now();
            phaseStart = Time.unscaledTime;
            phase = Phase.Starting;
            HoldPause();
            Log.Info("sync: started, scope " + scope + ", build " + build + ", dlc " + Env.DlcSetName(dlc) + (heldPause ? ", game paused" : ", game was already paused or has no speed control"));
            WriteStatus(true);
            Commands.Finish(path, seq, true, "Started");
        }

        /// <summary>Game.OnCleanUp: the colony is going away.</summary>
        public static void OnUnload()
        {
            if (phase == Phase.Idle) return;
            Abort("The colony was closed during the sync");
        }

        /// <summary>Game.Update postfix, every frame. Does nothing unless a run is going.</summary>
        public static void Tick()
        {
            if (phase == Phase.Idle) return;
            if (Env.Disabled) { Abort("The link turned itself off"); return; }
            Stopwatch fw = Stopwatch.StartNew();
            try
            {
                switch (phase)
                {
                    case Phase.Starting: StartRun(); break;
                    case Phase.Art: ArtStep(fw); break;
                    case Phase.Drain: DrainStep(); break;
                    case Phase.Theme: ThemeStep(); break;
                    case Phase.Fonts: FontsStep(); break;
                    case Phase.Finishing: Finish(); break;
                }
            }
            catch (Exception e)
            {
                Log.Error("sync: step failed in phase " + phase, e);
                if (phase == Phase.Art || phase == Phase.Starting || phase == Phase.Drain) { stageState[0] = "failed"; Abort("Sync failed: " + e.GetType().Name); }
                else { SetStage(phase == Phase.Theme ? 1 : 2, false, "Sync step failed: " + e.GetType().Name); NextPhase(); }
            }
            double ms = fw.Elapsed.TotalMilliseconds;
            if (ms > worstFrameMs) worstFrameMs = ms;
            if (phase != Phase.Idle) WriteStatus(false);
        }

        // ---------------------------------------------------------------- the run

        private static void HoldPause()
        {
            heldPause = false; heldInstance = null;
            try
            {
                SpeedControlScreen s = SpeedControlScreen.Instance;
                if (s != null && !s.IsPaused)
                {
                    s.Pause(false);        // no sound; Unpause(false) at the end puts the previous speed back
                    heldPause = true;
                    heldInstance = s;
                }
            }
            catch (Exception e) { Log.Warn("sync: could not pause the game: " + e.Message); }
        }

        private static void ReleasePause()
        {
            if (!heldPause) return;
            heldPause = false;
            try
            {
                SpeedControlScreen s = SpeedControlScreen.Instance;
                if (s != null && ReferenceEquals(s, heldInstance)) s.Unpause(false);
            }
            catch (Exception e) { Log.Warn("sync: could not restore the speed: " + e.Message); }
            heldInstance = null;
        }

        private static void StartRun()
        {
            Art.SyncPrepare();
            total = Art.SyncCount;
            phase = Phase.Art;
            Log.Info("sync: " + total + " catalog items");
        }

        private static void ArtStep(Stopwatch fw)
        {
            if (index >= total) { Art.SyncDone(); stageState[0] = "done"; current = null; phase = Phase.Drain; phaseStart = Time.unscaledTime; return; }
            while (index < total && fw.Elapsed.TotalMilliseconds < FrameBudgetMs && ArtWorker.QueueLength <= MaxEncoderQueue)
            {
                int i = index++;
                current = Art.SyncName(i);
                try
                {
                    string r = Art.SyncDraw(i, scope == "full");
                    if (r == null) drawn++;
                    else if (r == Art.SyncSame) same++;
                    else noPicture++;       // the game has no picture for it: normal, not an error
                    exceptionsInARow = 0;
                }
                catch (Exception e)
                {
                    errors++;
                    lastError = ("item " + current + ": " + e.GetType().Name).Replace('\n', ' ');
                    Log.Warn("sync: drawing " + current + " failed: " + e.Message);
                    if (++exceptionsInARow >= 8) { stageState[0] = "failed"; Abort("Drawing failed again and again"); return; }
                }
                done = index;
            }
        }

        private static void DrainStep()
        {
            if (ArtWorker.Idle) { StartTheme(); return; }
            if (Time.unscaledTime - phaseStart > DrainTimeoutS)
            {
                errors++; lastError = "The picture writer did not finish in time";
                Log.Warn("sync: " + lastError);
                StartTheme();
            }
        }

        private static void StartTheme()
        {
            errors += Math.Max(0, Art.StoreFailures - storeFailedAtStart);
            if (Art.StoreFailures > storeFailedAtStart) lastError = "Some pictures could not be saved";
            stageState[1] = "running";
            current = "theme";
            ThemeWriter.Refresh(scope == "full");
            phase = Phase.Theme;
            phaseStart = Time.unscaledTime;
        }

        private static void ThemeStep()
        {
            if (ThemeWriter.Settled)
            {
                if (ThemeWriter.Ok) SetStage(1, true, null); else SetStage(1, false, "The theme could not be written");
                NextPhase();
                return;
            }
            if (Time.unscaledTime - phaseStart > ThemeTimeoutS) { SetStage(1, false, "The theme did not finish in time"); NextPhase(); }
        }

        private static void NextPhase()
        {
            if (phase == Phase.Theme)
            {
                stageState[2] = "running";
                current = "font: graystroke";
                phase = Phase.Fonts;
                phaseStart = Time.unscaledTime;
                fontsStarted = false;
            }
            else if (phase == Phase.Fonts) { phase = Phase.Finishing; }
        }

        private static void SetStage(int i, bool ok, string error)
        {
            stageState[i] = ok ? "done" : "failed";
            if (!ok) { errors++; if (error != null) lastError = error; Log.Warn("sync: stage " + stageNames[i] + " failed: " + error); }
        }

        private static string FontsDir() { return Path.Combine(Path.Combine(Env.CompanionDir(), "fonts"), build.ToString(CultureInfo.InvariantCulture)); }

        private static void FontsStep()
        {
            if (!fontsStarted)
            {
                fontsStarted = true;
                string png = Path.Combine(FontsDir(), "graystroke.png"), js = Path.Combine(FontsDir(), "graystroke.json");
                if (scope == "missing" && File.Exists(png) && File.Exists(js)) { SetStage(2, true, null); NextPhase(); return; }
                string why = FontAtlas.Begin(FontsDir(), build, out fontThread, ResultSink);
                if (why != null) { SetStage(2, false, why); NextPhase(); }
                return;
            }
            if (fontResult == 1) { SetStage(2, true, null); NextPhase(); return; }
            if (fontResult == 2) { SetStage(2, false, fontMessage ?? "The font atlas could not be exported"); NextPhase(); return; }
            if (Time.unscaledTime - phaseStart > FontsTimeoutS) { SetStage(2, false, "The font export did not finish in time"); NextPhase(); }
        }

        private static void ResultSink(bool ok, string message) { fontMessage = message; fontResult = ok ? 1 : 2; }

        private static void Finish()
        {
            ReleasePause();
            phase = Phase.Idle;
            current = null;
            bool ok = stageState[0] == "done";
            WriteStatus(true, ok ? "done" : "failed");
            Log.Info("sync: " + (ok ? "done" : "failed") + " in " + (run.ElapsedMilliseconds / 1000.0).ToString("0.0", CultureInfo.InvariantCulture) + " s: " + drawn + " drawn, " + same +
                     " unchanged, " + noPicture + " without a picture, " + errors + " errors; stages art " + stageState[0] + ", theme " + stageState[1] + ", fonts " + stageState[2] +
                     "; worst main-thread step " + worstFrameMs.ToString("0.0", CultureInfo.InvariantCulture) + " ms");
        }

        private static void Abort(string why)
        {
            lastError = why;
            errors++;
            ReleasePause();
            Art.SyncDone();
            phase = Phase.Idle;
            current = null;
            for (int i = 0; i < stageState.Length; i++) if (stageState[i] == "running") stageState[i] = "failed";
            try { WriteStatus(true, "failed"); } catch { }
            Log.Warn("sync: ended early: " + why);
        }

        // ---------------------------------------------------------------- status file

        private static void WriteStatus(bool force, string finalState = null)
        {
            float now = Time.unscaledTime;
            if (!force && now - lastStatus < StatusGapS) return;
            lastStatus = now;
            try
            {
                string text = SyncStatus.Compose(Env.ModVersion, finalState ?? "running", scope, build, dlc, done, total, current, errors, lastError,
                    stageNames, stageState, heldPause, startedAt, Env.Now(), run != null ? run.ElapsedMilliseconds : 0, worstFrameMs);
                Files.WriteAtomic(StatusPath(), text);
            }
            catch (Exception e) { Log.Warn("sync: status write failed: " + e.Message); }
        }
    }

    /// <summary>
    /// Exports the game's Graystroke TextMeshPro font asset (the header font): the SDF atlas texture as a PNG and the glyph tables as
    /// JSON (contracts/font-atlas.schema.json). Found by name among the loaded TMP_FontAsset objects (the game's own
    /// "GRAYSTROKE REGULAR SDF"); nothing is bundled and nothing is guessed: the numbers are the asset's own.
    /// The atlas is blitted through a RenderTexture (the texture is usually not CPU readable). The distance is in the alpha channel
    /// for an Alpha8 atlas; the exported PNG carries it in red, green and blue (opaque), encoding "sdf-red".
    /// Main thread: find + blit + read-back + glyph tables (one frame); a background thread encodes and writes (the PNG first, the JSON last).
    /// </summary>
    internal static class FontAtlas
    {
        public static string Begin(string dir, int build, out Thread thread, Action<bool, string> done)
        {
            thread = null;
            TMP_FontAsset fa = Find();
            if (fa == null) return "The game's Graystroke font was not found";
            Texture2D tex = fa.atlasTexture;
            if (tex == null) return "The Graystroke font has no atlas texture";
            int w = tex.width, h = tex.height;
            if (w < 16 || h < 16 || w > MaxSide || h > MaxSide) return "The Graystroke atlas has an odd size (" + w + "x" + h + ")";

            byte[] raw;
            RenderTexture rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
            RenderTexture prev = RenderTexture.active;
            Texture2D rd = null;
            try
            {
                rt.filterMode = FilterMode.Point;
                Graphics.Blit(tex, rt);
                RenderTexture.active = rt;
                rd = new Texture2D(w, h, TextureFormat.RGBA32, false, true);
                rd.ReadPixels(new Rect(0, 0, w, h), 0, 0, false);
                raw = rd.GetRawTextureData();
            }
            finally
            {
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                if (rd != null) UnityEngine.Object.Destroy(rd);
            }

            // which channel holds the distance
            int minA = 255, maxA = 0, minR = 255, maxR = 0;
            for (int i = 0; i < raw.Length; i += 4 * 7)   // a sample of the pixels is enough
            {
                byte r = raw[i], a = raw[i + 3];
                if (a < minA) minA = a; if (a > maxA) maxA = a;
                if (r < minR) minR = r; if (r > maxR) maxR = r;
            }
            int channel = (maxA - minA) >= 16 ? 3 : (maxR - minR) >= 16 ? 0 : -1;
            Log.Info("sync: Graystroke atlas '" + fa.name + "' " + w + "x" + h + " format " + tex.format + ", alpha range " + minA + ".." + maxA + ", red range " + minR + ".." + maxR + ", using " + (channel == 3 ? "alpha" : channel == 0 ? "red" : "none"));
            if (channel < 0) return "The Graystroke atlas came out empty";

            // glyph tables, main thread (they are managed objects)
            FaceInfo fi = fa.faceInfo;
            float spread = fa.atlasPadding + 1;
            try { Material m = fa.material; if (m != null && m.HasProperty("_GradientScale")) spread = m.GetFloat("_GradientScale"); } catch { }
            List<AtlasGlyph> rows = new List<AtlasGlyph>();
            Dictionary<uint, uint> glyphToUnicode = new Dictionary<uint, uint>();
            int skipped = 0;
            if (fa.characterTable != null)
                foreach (TMP_Character c in fa.characterTable)
                {
                    if (c == null || c.glyph == null) continue;
                    Glyph g = c.glyph;
                    if (g.atlasIndex != 0) { skipped++; continue; }
                    GlyphRect r = g.glyphRect;
                    GlyphMetrics m = g.metrics;
                    rows.Add(new AtlasGlyph
                    {
                        U = c.unicode, X = r.x, Y = h - (r.y + r.height), W = r.width, H = r.height,
                        BX = m.horizontalBearingX, BY = m.horizontalBearingY, Adv = m.horizontalAdvance
                    });
                    if (!glyphToUnicode.ContainsKey(c.glyphIndex)) glyphToUnicode[c.glyphIndex] = c.unicode;
                }
            rows.Sort(delegate (AtlasGlyph a, AtlasGlyph b) { return a.U.CompareTo(b.U); });
            List<AtlasKern> kern = new List<AtlasKern>();
            try
            {
                TMP_FontFeatureTable ft = fa.fontFeatureTable;
                if (ft != null && ft.glyphPairAdjustmentRecords != null)
                    foreach (var pr in ft.glyphPairAdjustmentRecords)
                    {
                        uint u1, u2;
                        float x = pr.firstAdjustmentRecord.glyphValueRecord.xAdvance;
                        if (x == 0f) continue;
                        if (glyphToUnicode.TryGetValue(pr.firstAdjustmentRecord.glyphIndex, out u1) && glyphToUnicode.TryGetValue(pr.secondAdjustmentRecord.glyphIndex, out u2))
                            kern.Add(new AtlasKern { A = u1, B = u2, X = x });
                        if (kern.Count >= 20000) break;
                    }
            }
            catch (Exception e) { Log.Warn("sync: kerning not exported: " + e.Message); }
            Log.Info("sync: Graystroke glyphs " + rows.Count + (skipped > 0 ? " (" + skipped + " on other atlas pages skipped)" : "") + ", kerning pairs " + kern.Count + ", padding " + fa.atlasPadding + ", spread " + spread + ", point size " + fi.pointSize);

            string family = string.IsNullOrEmpty(fi.familyName) ? "Graystroke" : fi.familyName;
            string name = fa.name;
            int padding = fa.atlasPadding;
            int ch = channel;
            Thread t = new Thread(delegate ()
            {
                try
                {
                    byte[] rgba = new byte[w * h * 4];      // top row first, R=G=B=distance, opaque
                    for (int y = 0; y < h; y++)
                    {
                        int src = (h - 1 - y) * w * 4, dst = y * w * 4;
                        for (int x = 0; x < w; x++)
                        {
                            byte v = raw[src + x * 4 + ch];
                            int o = dst + x * 4;
                            rgba[o] = v; rgba[o + 1] = v; rgba[o + 2] = v; rgba[o + 3] = 255;
                        }
                    }
                    byte[] png = PngCodec.Encode(w, h, rgba);
                    Directory.CreateDirectory(dir);
                    string pngPath = Path.Combine(dir, "graystroke.png");
                    string tmp = pngPath + ".tmp";
                    File.WriteAllBytes(tmp, png);
                    if (File.Exists(pngPath)) File.Delete(pngPath);
                    File.Move(tmp, pngPath);

                    string text = FontAtlasJson.Compose(Env.ModVersion, build, name, family, w, h, padding, spread, fi.pointSize,
                        fi.lineHeight, fi.ascentLine, fi.descentLine, fi.scale, fi.tabWidth, rows, kern);
                    Files.WriteAtomic(Path.Combine(dir, "graystroke.json"), text);    // last: its presence means the pair is complete
                    Log.Info("sync: Graystroke written, " + png.Length + " byte PNG, " + rows.Count + " glyphs");
                    done(true, null);
                }
                catch (Exception e)
                {
                    Log.Error("sync: font export failed", e);
                    done(false, "The font atlas could not be written");
                }
            });
            t.IsBackground = true; t.Name = "OniCompanionLink.fonts";
            thread = t;
            t.Start();
            return null;
        }

        private const int MaxSide = 4096;

        /// <summary>The loaded font asset named Graystroke: the one with the most glyphs, a "regular" name first. Logs every font asset it saw.</summary>
        private static TMP_FontAsset Find()
        {
            TMP_FontAsset best = null;
            int bestScore = -1;
            StringBuilder seen = new StringBuilder();
            foreach (TMP_FontAsset f in Resources.FindObjectsOfTypeAll<TMP_FontAsset>())
            {
                if (f == null) continue;
                if (seen.Length < 400) seen.Append(f.name).Append("; ");
                string n = f.name.ToLowerInvariant();
                if (n.IndexOf("graystroke", StringComparison.Ordinal) < 0 || f.atlasTexture == null) continue;
                int score = (f.characterTable != null ? f.characterTable.Count : 0) + (n.IndexOf("regular", StringComparison.Ordinal) >= 0 ? 100000 : 0);
                if (score > bestScore) { bestScore = score; best = f; }
            }
            Log.Info("sync: font assets loaded: " + seen);
            return best;
        }
    }
}
