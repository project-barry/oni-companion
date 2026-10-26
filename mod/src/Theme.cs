using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using UnityEngine;
using UnityEngine.UI;

namespace OniCompanionLink
{
    /// <summary>
    /// Writes companion/theme/&lt;build&gt;/theme.json plus 9-slice PNGs (contract: theme.schema.json, ModTheme), once per build and mod version.
    /// Nothing is hand-picked: every color is read from a named asset of the running game, every image is the game's own sprite
    /// rendered through a RenderTexture and multiplied by the tint the game itself draws it with. Sources (all found by decompiling;
    /// asset names confirmed against the game's data files):
    ///   background      colorstyle_darkBG.activeColor           (DetailsScreen window background)
    ///   panel           colorstyle_bodyBG.activeColor           (DetailsScreen body, AllResourcesScreen background)
    ///   header          colorstyle_title.activeColor            (title bars of DetailsScreen / AllResourcesScreen)
    ///   border          colorstyle_button.inactiveColor         (frame color of the game's buttons and search box)
    ///   buttonNormal / buttonHover / buttonPressed   colorstyle_button inactive / hover / active
    ///   text / textDim / textTitle   TextStyleSetting style_bodyText / style_bodyTextGrey / style_titleText (textColor)
    ///   positive / negative / warning   Constants.POSITIVE_COLOR / NEGATIVE_COLOR / WARNING_COLOR
    ///   info            GlobalAssets.Instance.colorSet.eventNeutral (follows the player's color set)
    ///   progressFill    ProgressBarsConfig bar "ProgressBar";  progressTrack = the non-fill Image of ProgressBarsConfig.progressBarUIPrefab (else colorstyle_darkBG)
    ///   meterHealth     ProgressBarsConfig bar "HealthBar"
    ///   meterCalories   ProgressBarsConfig bar "ProgressBar" (the game has no calories-specific bar color)
    ///   meterStress     Constants.WARNING_COLOR (the game has no stress-specific bar color)
    /// Slices: panel = sprite web_box tinted bodyBG, header = web_box tinted title, button / buttonHover / buttonPressed = web_button
    /// tinted colorstyle_button inactive / hover / active, tab / tabActive = the sprite and the Off / On colors of the details screen's
    /// tab prefab (MultiToggle states). Insets are the sprites' own Sprite.border.
    /// Main thread: ONE small step per frame, each timed (a step over 4 ms is logged by name): look up the style assets, one asset kind
    /// per frame; build the lists; one blit + read-back per slice; then a worker thread tints, encodes and writes the files, theme.json last.
    /// A frame in which the art code drew something, or a portrait is being drawn, is skipped.
    /// If an asset is missing nothing is written (no partial theme) and the next world load tries again.
    /// </summary>
    internal static class ThemeWriter
    {
        private enum Phase { Idle, Running, Done, Failed }

        private sealed class SliceJob
        {
            public string Name, File;
            public Sprite Sprite;
            public Color Tint;
            public bool Optional;
            public byte[] Rgba; public int W, H; public Vector4 Border;   // Rgba: bottom row first, straight from the read-back
        }

        private sealed class Step { public string Name; public System.Action Run; }

        private const double StepBudgetMs = 4.0;
        /// <summary>Bumped when this code writes a different theme (new tokens or slices). The theme is rebuilt only when the game build or this number changes.</summary>
        private const int RenderRev = 5;   // 5: + overlay and tool icons (Actions); 4: + speed-control and notification icons (UiIcons)

        private static Phase phase = Phase.Idle;
        private static bool forceRebuild;              // Sync: write the theme again even when this build + renderRev is on disk
        private static volatile bool writing;          // the worker thread is writing the files

        /// <summary>Sync: build the theme again (force) or only when it is not on disk. A run already in progress is left to finish.</summary>
        public static void Refresh(bool force)
        {
            forceRebuild = force;
            if (phase == Phase.Running) return;
            phase = Phase.Idle; jobs = null; colors = null; steps.Clear(); csMap = null; tsMap = null;
        }

        /// <summary>The theme run ended (done or failed) and its files are written.</summary>
        public static bool Settled { get { return (phase == Phase.Done || phase == Phase.Failed) && !writing; } }
        public static bool Ok { get { return phase == Phase.Done && File.Exists(Path.Combine(ThemeDir(), "theme.json")); } }
        private static List<KeyValuePair<string, string>> colors;
        private static List<SliceJob> jobs;
        private static readonly Queue<Step> steps = new Queue<Step>();
        private static Dictionary<string, ColorStyleSetting> csMap;
        private static Dictionary<string, TextStyleSetting> tsMap;
        private static int nSteps;
        private static double totalMs, worstMs;
        private static string worstName = "";
        private static int build;

        private static string ThemeDir() { return Path.Combine(Path.Combine(Env.CompanionDir(), "theme"), build.ToString()); }

        /// <summary>A new game session starts: a failed attempt may be retried (never a finished one).</summary>
        public static void OnUnload()
        {
            if (phase != Phase.Done) { phase = Phase.Idle; jobs = null; colors = null; steps.Clear(); csMap = null; tsMap = null; }
        }

        private static void Add(string name, System.Action run) { steps.Enqueue(new Step { Name = name, Run = run }); }

        /// <summary>Called every frame from Game.Update (postfix). Does nothing once done; otherwise at most one small timed step per frame.</summary>
        public static void Tick()
        {
            if (Env.Disabled || phase == Phase.Done || phase == Phase.Failed) return;
            if (Art.PortraitBusy || Art.LastWorkFrame == Time.frameCount) return;   // never in the same frame as the art code's heavy work
            Stopwatch sw = Stopwatch.StartNew();
            string name = "";
            try
            {
                if (!LiveWriter.Ready() || DetailsScreen.Instance == null || AllResourcesScreen.Instance == null || Assets.Sprites == null) return;   // the screens that reference the style assets exist, so the assets are loaded
                if (phase == Phase.Idle)
                {
                    build = Env.Build();
                    if (!forceRebuild && AlreadyWritten()) { phase = Phase.Done; Log.Info("theme: skipped, already written for build " + build + " renderRev " + RenderRev + " (nothing scanned, nothing rendered)"); return; }
                    phase = Phase.Running;
                    forceRebuild = false;
                    nSteps = 0; totalMs = 0; worstMs = 0; worstName = "";
                    csMap = new Dictionary<string, ColorStyleSetting>(); tsMap = new Dictionary<string, TextStyleSetting>();
                    // The style assets are read from the UI objects that hold them (one root per frame), never by scanning every loaded object.
                    Add("styles: details screen colors", delegate () { HarvestColors(DetailsScreen.Instance.gameObject); });
                    Add("styles: details screen text", delegate () { HarvestTexts(DetailsScreen.Instance.gameObject); });
                    Add("styles: resources screen", delegate () { HarvestColors(AllResourcesScreen.Instance.gameObject); HarvestTexts(AllResourcesScreen.Instance.gameObject); });
                    Add("styles: section panel prefab", delegate () { GameObject p = ScreenPrefabs.Instance.CollapsableContentPanel; if (p != null) { HarvestColors(p); HarvestTexts(p); } });
                    Add("styles: check", CheckStyles);
                    Add("read colors", ReadColors);
                    Add("list slices", ListSlices);
                    Add("warm blit", delegate () { Art.WarmBlit(); });
                    return;   // the check above counts as this frame's step
                }
                Step st = steps.Dequeue();
                name = st.Name;
                st.Run();
                nSteps++;
            }
            catch (Exception e)
            {
                phase = Phase.Failed;
                steps.Clear();
                Log.Warn("theme not written this session: " + e.GetType().Name + ": " + e.Message + (name != "" ? " (step " + name + ")" : ""));
                return;
            }
            double ms = sw.Elapsed.TotalMilliseconds;
            totalMs += ms;
            if (ms > worstMs) { worstMs = ms; worstName = name; }
            if (ms > StepBudgetMs) Log.Warn("theme: step '" + name + "' took " + ms.ToString("0.0") + " ms (target " + StepBudgetMs + " ms)");
            if (steps.Count == 0 && phase == Phase.Running) phase = Phase.Done;
        }

        private static bool AlreadyWritten()
        {
            string p = Path.Combine(ThemeDir(), "theme.json");
            if (!File.Exists(p)) return false;
            try { return File.ReadAllText(p).Contains("\"renderRev\":" + RenderRev + ","); } catch { return false; }
        }

        // ------------------------------------------------------------ step 1: colors and sprites (all or nothing)

        private static T Named<T>(Dictionary<string, T> map, string name) where T : UnityEngine.Object
        {
            T v;
            if (!map.TryGetValue(name, out v) || v == null) throw new InvalidOperationException("game asset not found: " + name);
            return v;
        }

        private static Dictionary<string, T> ByName<T>() where T : UnityEngine.Object
        {
            Dictionary<string, T> map = new Dictionary<string, T>();
            foreach (T o in Resources.FindObjectsOfTypeAll<T>()) if (o != null && !map.ContainsKey(o.name)) map[o.name] = o;
            return map;
        }

        private static void HarvestColors(GameObject root)
        {
            foreach (KImage k in root.GetComponentsInChildren<KImage>(true))
                if (k != null && k.colorStyleSetting != null && !csMap.ContainsKey(k.colorStyleSetting.name)) csMap[k.colorStyleSetting.name] = k.colorStyleSetting;
        }

        private static void HarvestTexts(GameObject root)
        {
            foreach (LocText l in root.GetComponentsInChildren<LocText>(true))
                if (l != null && l.textStyleSetting != null && !tsMap.ContainsKey(l.textStyleSetting.name)) tsMap[l.textStyleSetting.name] = l.textStyleSetting;
        }

        private static readonly string[] NeedColorStyles = { "colorstyle_darkBG", "colorstyle_bodyBG", "colorstyle_title", "colorstyle_button" };
        private static readonly string[] NeedTextStyles = { "style_bodyText", "style_bodyTextGrey", "style_titleText" };

        /// <summary>
        /// Every style the theme needs must have been found on the UI objects. Only if one was not (a game update moved it) the old
        /// scan of all loaded objects runs, once, and the log names what was missing. A finished theme is never rebuilt, so this cost is
        /// paid at most once per game build.
        /// </summary>
        private static void CheckStyles()
        {
            List<string> missing = new List<string>();
            foreach (string n in NeedColorStyles) if (!csMap.ContainsKey(n)) missing.Add(n);
            foreach (string n in NeedTextStyles) if (!tsMap.ContainsKey(n)) missing.Add(n);
            if (missing.Count == 0) { Log.Info("theme: all " + (NeedColorStyles.Length + NeedTextStyles.Length) + " style assets found on the UI objects, no object scan"); return; }
            Log.Warn("theme: style assets not on the UI objects: " + string.Join(", ", missing.ToArray()) + "; scanning loaded objects once");
            foreach (KeyValuePair<string, ColorStyleSetting> kv in ByName<ColorStyleSetting>()) if (!csMap.ContainsKey(kv.Key)) csMap[kv.Key] = kv.Value;
            foreach (KeyValuePair<string, TextStyleSetting> kv in ByName<TextStyleSetting>()) if (!tsMap.ContainsKey(kv.Key)) tsMap[kv.Key] = kv.Value;
        }

        private static Color LabelColor(LocText l)
        {
            return (l.textStyleSetting != null && !l.allowOverride) ? l.textStyleSetting.textColor : l.color;   // LocText.Awake applies the style unless allowOverride
        }

        private static string Hex(Color c)
        {
            int r = Mathf.RoundToInt(Mathf.Clamp01(c.r) * 255f), g = Mathf.RoundToInt(Mathf.Clamp01(c.g) * 255f);
            int b = Mathf.RoundToInt(Mathf.Clamp01(c.b) * 255f), a = Mathf.RoundToInt(Mathf.Clamp01(c.a) * 255f);
            return a == 255 ? string.Format("#{0:X2}{1:X2}{2:X2}", r, g, b) : string.Format("#{0:X2}{1:X2}{2:X2}{3:X2}", r, g, b, a);
        }

        private static void ReadColors()
        {
            Dictionary<string, ColorStyleSetting> cs = csMap;
            Dictionary<string, TextStyleSetting> ts = tsMap;
            ColorStyleSetting darkBg = Named(cs, "colorstyle_darkBG");
            ColorStyleSetting bodyBg = Named(cs, "colorstyle_bodyBG");
            ColorStyleSetting title = Named(cs, "colorstyle_title");
            ColorStyleSetting button = Named(cs, "colorstyle_button");
            TextStyleSetting body = Named(ts, "style_bodyText");
            TextStyleSetting bodyGrey = Named(ts, "style_bodyTextGrey");
            TextStyleSetting titleText = Named(ts, "style_titleText");

            ProgressBarsConfig pb = ProgressBarsConfig.Instance;
            if (pb == null || pb.progressBarUIPrefab == null) throw new InvalidOperationException("ProgressBarsConfig missing");
            // The prefab's ProgressBar.bar is the fill (an Image, fillAmount); the track is another Image of the same prefab
            // (named like a background, or simply not the fill). Looked up by structure, never by a guessed path.
            Color trackColor = darkBg.activeColor;
            string trackFrom = "colorstyle_darkBG (no separate track image in the progress bar prefab)";
            try
            {
                ProgressBar pbc = pb.progressBarUIPrefab.GetComponent<ProgressBar>();
                Image fillImg = pbc != null ? pbc.bar : null;
                Image found = null;
                foreach (Image im in pb.progressBarUIPrefab.GetComponentsInChildren<Image>(true))
                {
                    if (im == null || im == fillImg) continue;
                    string n = im.gameObject.name.ToLowerInvariant();
                    if (n.Contains("bg") || n.Contains("back") || n.Contains("track")) { found = im; break; }
                    if (found == null && im.type != Image.Type.Filled) found = im;
                }
                if (found != null) { trackColor = found.color; trackFrom = "prefab image " + found.gameObject.name; }
            }
            catch (Exception e) { Log.Warn("theme: progress bar track lookup failed: " + e.Message); }
            Log.Info("theme: progressTrack from " + trackFrom);
            Color fill = pb.GetBarColor("ProgressBar"), health = pb.GetBarColor("HealthBar");
            if (fill.a == 0f || health.a == 0f) throw new InvalidOperationException("ProgressBarsConfig bar colors missing");

            colors = new List<KeyValuePair<string, string>>();
            Action<string, Color> add = delegate (string k, Color c) { colors.Add(new KeyValuePair<string, string>(k, Hex(c))); };
            add("background", darkBg.activeColor);
            add("panel", bodyBg.activeColor);
            add("header", title.activeColor);
            add("border", button.inactiveColor);
            add("buttonNormal", button.inactiveColor);
            add("buttonHover", button.hoverColor);
            add("buttonPressed", button.activeColor);
            add("text", body.textColor);
            add("textDim", bodyGrey.textColor);
            add("textTitle", titleText.textColor);
            add("positive", Constants.POSITIVE_COLOR);
            add("negative", Constants.NEGATIVE_COLOR);
            add("warning", Constants.WARNING_COLOR);
            add("info", GlobalAssets.Instance.colorSet.eventNeutral);
            add("progressFill", fill);
            add("progressTrack", trackColor);
            add("meterStress", Constants.WARNING_COLOR);
            add("meterHealth", health);
            add("meterCalories", fill);
            // v1.2 tokens: how the game draws section bars, tabs and the alert list
            ColorSet cset = GlobalAssets.Instance.colorSet;
            add("alertBg", cset.NotificationNormalBG);            // NotificationScreen: the list entry's button color
            add("alertText", cset.NotificationNormal);            // ... and its label color
            add("alertBadBg", cset.NotificationBadBG);
            add("alertBadText", cset.NotificationBad);
            CollapsibleDetailContentPanel sec = ScreenPrefabs.Instance.CollapsableContentPanel.GetComponent<CollapsibleDetailContentPanel>();
            if (sec == null || sec.HeaderLabel == null) throw new InvalidOperationException("section panel prefab has no header label");
            add("sectionHeaderText", LabelColor(sec.HeaderLabel));
            secToggle = sec.collapseButton;
            FieldInfo fh = typeof(DetailsScreen).GetField("tabHeader", BindingFlags.NonPublic | BindingFlags.Instance);
            object th = fh != null ? fh.GetValue(DetailsScreen.Instance) : null;
            FieldInfo fp = th != null ? th.GetType().GetField("tabPrefab", BindingFlags.NonPublic | BindingFlags.Instance) : null;
            tabPrefabGo = fp != null ? fp.GetValue(th) as GameObject : null;
            if (tabPrefabGo == null) throw new InvalidOperationException("details screen tab prefab not found");
            HierarchyReferences hr = tabPrefabGo.GetComponent<HierarchyReferences>();
            LocText tabLabel = hr != null ? hr.GetReference<LocText>("label") : null;
            if (tabLabel == null) throw new InvalidOperationException("tab prefab has no label");
            add("tabText", LabelColor(tabLabel));
            add("tabTextActive", LabelColor(tabLabel));   // the prefab has one label; the states only recolor the tab image

            csMap = null; tsMap = null;
            bodyBgC = bodyBg.activeColor; titleC = title.activeColor; btnC = button.inactiveColor; btnHoverC = button.hoverColor; btnActiveC = button.activeColor;
        }

        private static Color bodyBgC, titleC, btnC, btnHoverC, btnActiveC;
        private static MultiToggle secToggle;
        private static GameObject tabPrefabGo;

        private static void ListSlices()
        {
            jobs = new List<SliceJob>();
            jobs.Add(new SliceJob { Name = "panel", File = "panel.png", Sprite = RequireSprite("web_box"), Tint = bodyBgC });
            jobs.Add(new SliceJob { Name = "header", File = "header.png", Sprite = RequireSprite("web_box"), Tint = titleC });
            jobs.Add(new SliceJob { Name = "button", File = "button.png", Sprite = RequireSprite("web_button"), Tint = btnC });
            jobs.Add(new SliceJob { Name = "buttonHover", File = "buttonHover.png", Sprite = RequireSprite("web_button"), Tint = btnHoverC });
            jobs.Add(new SliceJob { Name = "buttonPressed", File = "buttonPressed.png", Sprite = RequireSprite("web_button"), Tint = btnActiveC });
            try
            {
                // the details screen's tab prefab: states[0] = Off, states[1] = On (sprite + tint)
                MultiToggle mt = tabPrefabGo != null ? tabPrefabGo.GetComponent<MultiToggle>() : null;
                if (mt == null || mt.states == null || mt.states.Length < 2 || mt.states[0].sprite == null || mt.states[1].sprite == null)
                    throw new InvalidOperationException("tab prefab states not found");
                jobs.Add(new SliceJob { Name = "tab", File = "tab.png", Sprite = mt.states[0].sprite, Tint = mt.states[0].color, Optional = true });
                jobs.Add(new SliceJob { Name = "tabActive", File = "tabActive.png", Sprite = mt.states[1].sprite, Tint = mt.states[1].color, Optional = true });
            }
            catch (Exception e) { Log.Warn("theme: tab slices skipped: " + e.Message); }
            try
            {
                // the section bars (STATUS, CONDITION ...): the collapse button of the section panel prefab, state 0
                if (secToggle == null || secToggle.states == null || secToggle.states.Length < 1 || secToggle.states[0].sprite == null)
                    throw new InvalidOperationException("section header toggle state not found");
                jobs.Add(new SliceJob { Name = "sectionHeader", File = "sectionHeader.png", Sprite = secToggle.states[0].sprite, Tint = secToggle.states[0].color, Optional = true });
            }
            catch (Exception e) { Log.Warn("theme: section header slice skipped: " + e.Message); }

            foreach (SliceJob job in jobs)
            {
                SliceJob jb = job;
                Add("slice " + jb.Name, delegate ()
                {
                    try { Render(jb); }
                    catch (Exception e) { if (!jb.Optional) throw; jb.Rgba = null; Log.Warn("theme: optional slice " + jb.Name + " skipped: " + e.Message); }
                });
            }
            UiIcons.Reset();
            Add("list icons", delegate () { UiIcons.List(Add); Add("write theme", Finish); });   // the icon render steps queue before the write
        }

        private static Sprite RequireSprite(string name)
        {
            Sprite s = Assets.GetSprite(name);
            if (s == null) throw new InvalidOperationException("game sprite not found: " + name);
            return s;
        }

        // ------------------------------------------------------------ step 2..n: one slice per frame

        private static void Render(SliceJob job)
        {
            // sprites may live in atlases that are not CPU-readable: copy the sprite's rectangle on the GPU (the sprite's own size, no scaling)
            int w, h;
            byte[] raw = Art.BlitSprite(job.Sprite, 0, false, out w, out h);
            if (raw == null) throw new InvalidOperationException("sprite " + job.Sprite.name + " has no usable texture rect");
            job.Rgba = raw; job.W = w; job.H = h; job.Border = job.Sprite.border;   // x = left, y = bottom, z = right, w = top
        }

        // ------------------------------------------------------------ last step: hand everything to the writer thread

        private static void Finish()
        {
            string dir = ThemeDir();
            List<SliceJob> mine = new List<SliceJob>();
            foreach (SliceJob sj in jobs) if (sj.Rgba != null) mine.Add(sj);
            List<KeyValuePair<string, string>> cols = colors;
            double total = totalMs, worst = worstMs; string worstAt = worstName; int stepCount = nSteps + 1;
            int bld = build;

            writing = true;
            Thread t = new Thread(delegate ()
            {
                try
                {
                    Directory.CreateDirectory(dir);
                    Dictionary<string, Color> surface = new Dictionary<string, Color>();
                    foreach (SliceJob sj in mine)   // tint, encode and write here, off the main thread
                    {
                        byte[] top = PngCodec.FlipRows(sj.Rgba, sj.W, sj.H);
                        PngCodec.Tint(top, sj.Tint.r, sj.Tint.g, sj.Tint.b, sj.Tint.a);   // the game multiplies a sprite by its Image color
                        PngCodec.ClearHidden(top);
                        surface[sj.Name] = CenterColor(top, sj);
                        WriteBytesAtomic(Path.Combine(dir, sj.File), PngCodec.Encode(sj.W, sj.H, top));
                    }
                    // Flat colors for the same surfaces (front ends without the image): the average of the slice's fill area
                    // (inside its 9-slice insets), taken from the rendered, tinted image.
                    List<KeyValuePair<string, string>> all = new List<KeyValuePair<string, string>>(cols);
                    Color c;
                    if (surface.TryGetValue("sectionHeader", out c)) all.Add(new KeyValuePair<string, string>("sectionHeader", Hex(c)));
                    if (surface.TryGetValue("tab", out c)) all.Add(new KeyValuePair<string, string>("tabBg", Hex(c)));
                    if (surface.TryGetValue("tabActive", out c)) all.Add(new KeyValuePair<string, string>("tabActiveBg", Hex(c)));

                    Json j = new Json(2048);
                    j.Obj().PI("schema", 1).P("modVersion", Env.ModVersion).PI("renderRev", RenderRev).PI("build", bld).P("writtenAt", Env.Now());
                    j.Key("colors").Obj();
                    foreach (KeyValuePair<string, string> kv in all) j.P(kv.Key, kv.Value);
                    j.EndObj();
                    j.Key("slices").Arr();
                    foreach (SliceJob s in mine)
                    {
                        j.Obj().P("name", s.Name).P("file", s.File).PI("width", s.W).PI("height", s.H);
                        j.Key("insets").Obj().PI("left", (long)Mathf.RoundToInt(s.Border.x)).PI("top", (long)Mathf.RoundToInt(s.Border.w))
                            .PI("right", (long)Mathf.RoundToInt(s.Border.z)).PI("bottom", (long)Mathf.RoundToInt(s.Border.y)).EndObj();
                        j.EndObj();
                    }
                    j.EndArr();
                    int iconFiles = 0;
                    try { iconFiles = UiIcons.Write(dir, j); } catch (Exception e) { Log.Warn("theme: icons not written: " + e.Message); }
                    j.EndObj();
                    Files.WriteAtomic(Path.Combine(dir, "theme.json"), j.ToString());   // last: its presence means the set is complete
                    Log.Info("theme written: " + mine.Count + " slices, " + iconFiles + " icon files, " + all.Count + " colors; main thread total " + total.ToString("0.00") +
                             " ms over " + stepCount + " frames, worst step " + worst.ToString("0.00") + " ms ('" + worstAt + "', target 4 ms)");
                }
                catch (Exception e) { Log.Error("theme write failed", e); }
                finally { writing = false; }
            });
            t.IsBackground = true; t.Name = "OniCompanionLink.theme"; t.Start();
        }

        // Average color of the fill area of a rendered slice (RGBA, top row first), alpha-weighted; the whole image when the insets leave nothing.
        private static Color CenterColor(byte[] rgba, SliceJob sj)
        {
            int l = Mathf.RoundToInt(sj.Border.x), b = Mathf.RoundToInt(sj.Border.y), r = Mathf.RoundToInt(sj.Border.z), tp = Mathf.RoundToInt(sj.Border.w);
            int x0 = l, x1 = sj.W - r, y0 = tp, y1 = sj.H - b;
            if (x1 <= x0 || y1 <= y0) { x0 = 0; x1 = sj.W; y0 = 0; y1 = sj.H; }
            double sr = 0, sg = 0, sb = 0, sa = 0; int n = 0;
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                {
                    int i = (y * sj.W + x) * 4;
                    double a = rgba[i + 3] / 255.0;
                    sr += rgba[i] * a; sg += rgba[i + 1] * a; sb += rgba[i + 2] * a; sa += a; n++;
                }
            if (sa <= 0 || n == 0) return new Color(0, 0, 0, 0);
            return new Color((float)(sr / sa / 255.0), (float)(sg / sa / 255.0), (float)(sb / sa / 255.0), (float)(sa / n));
        }

        internal static void WriteBytesAtomic(string path, byte[] data)
        {
            string tmp = path + ".tmp";
            File.WriteAllBytes(tmp, data);
            if (File.Exists(path)) { try { File.Replace(tmp, path, null); return; } catch { } File.Delete(path); }
            File.Move(tmp, path);
        }
    }
}
