using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using Klei.AI;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// Game art, rendered from the running game into companion/art/&lt;build&gt;/&lt;kind&gt;/&lt;id&gt;.png
    /// (contracts/mod-art-manifest.schema.json). None of it ships with the mod: the user's own game draws it.
    ///
    /// ON DEMAND ONLY (0.2.2): there is no catalog run. The core sends an `art_request {kind, id}` command when an app asks for
    /// an image that is not there yet. Requests wait in a queue that is drawn a little each frame (about 2 ms of main-thread
    /// work). Drawn images are kept per game build and listed in manifest.json (rewritten at most once a second). Each request
    /// is acknowledged (done, or failed with the reason) after the manifest lists the image.
    /// Catalog art (building, element, critter, plant, seed, egg, food, medicine, item): the game's own UI sprite
    /// (Def.GetUISprite / BuildingDef.GetUISprite) blitted through a RenderTexture (works for sprites whose
    /// atlas is not CPU readable), 128 px on the long side.
    /// srcKey: a cheap, stable fingerprint of the game asset an image is drawn from (see SrcKeyOf), computed WITHOUT drawing.
    /// Duplicant portraits: the game's own FullBodyUIMinionWidget, drawn by a private camera into two
    /// RenderTextures (on black and on white, so the alpha comes out exact whatever the UI shader does), cropped and
    /// scaled to at most 256 px. Drawn for the duplicants of the loaded colony right after the world loads, and again when
    /// the appearance hash changes (at most one per second). The stage is set up over several frames.
    ///
    /// Speed: everything on the main thread is split over frames; PNG encoding, hashing and file writes run on one
    /// background thread. Nothing here may reach the game: every step is in a try/catch, and after 5 failures in a row art
    /// switches itself off for the session (the rest of the mod keeps running).
    /// </summary>
    internal static class Art
    {
        private const int CatalogPx = 128;
        private const int DupeMaxPx = 256;
        private const int StageW = 320, StageH = 384;        // portrait stage: RenderTexture size
        private const float AnchorW = 200f, AnchorH = 240f;  // 2x the game's 100x120 portrait rectangle
        private const double BudgetMs = 2.0;                 // main-thread work per frame for requests (soft: no new item starts if it would not fit)
        private const double HardMs = 3.0;                   // an item that costs more than this earns idle frames
        private const double FrameTargetMs = 4.0;
        private const int MaxQueued = 48;                    // PNG jobs waiting for the encoder
        private const int MaxRequests = 64;                  // art_request commands waiting to be drawn
        public const int RenderRev = 1;                      // bump when the look of drawn images changes: old ones are drawn again

        private static readonly string[] CatalogKinds = { "building", "element", "critter", "plant", "seed", "egg", "food", "medicine", "item" };
        private static readonly Regex SafeId = new Regex("^[A-Za-z0-9_.\\-]{1,100}$", RegexOptions.Compiled);

        private sealed class Req { public string Kind, Id; public long QueuedMs; }

        // ---- diagnostics for slow on-demand art (live test 0.4.0, Linux build under FEX: ~5 min per picture, cause unknown).
        // Per gate in TickRequests: how many frames it held the queue back. A request slower than SlowMs logs where its time went.
        private const long SlowMs = 5000;
        private static readonly Stopwatch reqClock = Stopwatch.StartNew();
        private static readonly Dictionary<string, long> drawnAtMs = new Dictionary<string, long>();      // rel -> handed to the encoder (main thread writes, lock waiters)
        private static readonly Dictionary<string, long> queuedAtMs = new Dictionary<string, long>();     // rel -> accepted (lock waiters)
        private static int gPortrait, gNotLoaded, gCoolDown, gLoading, gSlowFrame, gEncoderBehind, gRan;   // main thread only
        private static void ResetGates() { gPortrait = gNotLoaded = gCoolDown = gLoading = gSlowFrame = gEncoderBehind = gRan = 0; }
        private static string Gates()
        {
            return "frames held by: portrait busy " + gPortrait + ", worker not loaded " + gNotLoaded + ", cool-down " + gCoolDown +
                   ", game loading " + gLoading + ", slow frame " + gSlowFrame + ", encoder behind " + gEncoderBehind + "; frames that drew " + gRan;
        }
        private sealed class AckRef { public string Path; public long Seq; }

        private static ArtRunner runner;
        private static bool portraitBusy;
        private static bool off;
        private static bool wantPortraits;      // a world just loaded: look for portraits to draw at once
        private static bool blitWarm;
        private static int failStreak;
        private static float nextPortraitCheck;
        private static int build;
        private static List<string> dlcIds;
        private static int coolDown, slowSkips;
        private static double avgItemMs = 1.0;

        private static readonly Queue<Req> requests = new Queue<Req>();                      // main thread only
        private static readonly Dictionary<string, List<AckRef>> waiters = new Dictionary<string, List<AckRef>>();   // rel -> acks owed; guarded by itself
        private static readonly HashSet<string> drawnPortraits = new HashSet<string>();               // "id-hash"; guarded by itself
        private static readonly Dictionary<string, int> attempts = new Dictionary<string, int>();

        // frame-time log (main thread only)
        private static double worstMs;
        private static int overBudgetFrames, frames, overLogged, drawnThisBurst;

        /// <summary>Frame number of the last frame in which art did heavy work (the theme writer keeps out of that frame).</summary>
        internal static int LastWorkFrame = -1;
        internal static bool PortraitBusy { get { return portraitBusy; } }

        public static string ArtDir() { return Path.Combine(Env.CompanionDir(), "art"); }

        // ---------------------------------------------------------------- entry points (called from Mod.cs hooks)

        /// <summary>MainMenu.OnSpawn / Game.OnSpawn. Starts the art runner once per session. Draws nothing by itself.</summary>
        public static void Start(string reason)
        {
            if (Env.Disabled || off || runner != null) return;
            try
            {
                build = Env.Build();
                dlcIds = Env.ActiveDlc();
                GameObject go = new GameObject("OniCompanionArt");
                UnityEngine.Object.DontDestroyOnLoad(go);
                go.hideFlags = HideFlags.HideAndDontSave;
                runner = go.AddComponent<ArtRunner>();
                Log.Info("art: on demand only, no catalog run [" + reason + "], build " + build + ", dlc " + Env.DlcSetName(dlcIds));
                ArtWorker.Begin(build, dlcIds);
                ArtWorker.Enqueue(new ArtWorker.LoadJob());
                runner.StartCoroutine(JitWarm());
            }
            catch (Exception e) { Fail("start", e); }
        }

        /// <summary>Game.OnSpawn: a colony was loaded. Its duplicants get their portraits first, ahead of everything else.</summary>
        public static void WorldLoaded()
        {
            wantPortraits = true;
            nextPortraitCheck = 0f;
            attempts.Clear();
        }

        /// <summary>Game.Update postfix, every frame. Cheap unless there is something to draw.</summary>
        public static void Tick()
        {
            if (Env.Disabled || off || runner == null) return;
            try { TickPortraits(); }
            catch (Exception e) { portraitBusy = false; Fail("tick", e); }
            try { TickRequests(); }
            catch (Exception e) { Fail("requests", e); }
        }

        /// <summary>Called by Commands for a validated art_request. Acks later (or at once on failure).</summary>
        public static void Request(string path, long seq, string kind, string id)
        {
            if (Array.IndexOf(CatalogKinds, kind) < 0) { Commands.Finish(path, seq, false, kind == "dupe" ? "Portraits draw themselves" : "Unknown art kind"); return; }
            if (!SafeId.IsMatch(id)) { Commands.Finish(path, seq, false, "Unknown id"); return; }
            if (off || runner == null) { Commands.Finish(path, seq, false, "Art is not available"); return; }
            string rel = build + "/" + kind + "/" + id + ".png";
            lock (waiters)
            {
                List<AckRef> l;
                if (waiters.TryGetValue(rel, out l)) { l.Add(new AckRef { Path = path, Seq = seq }); Commands.HeldByArt(path); return; }   // same item already queued
                if (requests.Count >= MaxRequests) { Commands.Finish(path, seq, false, "Art queue is full"); return; }
                l = new List<AckRef>(); l.Add(new AckRef { Path = path, Seq = seq });
                waiters[rel] = l;
                queuedAtMs[rel] = reqClock.ElapsedMilliseconds;
            }
            Commands.HeldByArt(path);
            if (requests.Count == 0) ResetGates();
            requests.Enqueue(new Req { Kind = kind, Id = id, QueuedMs = reqClock.ElapsedMilliseconds });
        }

        private static void Complete(string rel, bool ok, string message)
        {
            List<AckRef> l;
            long q, d, now = reqClock.ElapsedMilliseconds;
            bool hasQ, hasD;
            lock (waiters)
            {
                if (!waiters.TryGetValue(rel, out l)) return;
                waiters.Remove(rel);
                hasQ = queuedAtMs.TryGetValue(rel, out q); queuedAtMs.Remove(rel);
                hasD = drawnAtMs.TryGetValue(rel, out d); drawnAtMs.Remove(rel);
            }
            foreach (AckRef a in l) Commands.Finish(a.Path, a.Seq, ok, message);
            if (hasQ && now - q > SlowMs)
                Log.Warn("art: slow request " + rel + " (" + message + "): " + (now - q) + " ms in all; " +
                         (hasD ? (d - q) + " ms waiting to be drawn, " + (now - d) + " ms in the encoder until the manifest listed it" : "never handed to the encoder") +
                         "; " + Gates() + "; encoder queue " + ArtWorker.QueueLength);
        }

        /// <summary>Worker thread: these images are now in the manifest on disk.</summary>
        internal static void Stored(List<string> rels)
        {
            foreach (string r in rels) Complete(r, true, "Drawn");
        }

        /// <summary>Worker thread: the PNG could not be written.</summary>
        internal static void StoreFailed(string rel, string why) { Interlocked.Increment(ref storeFailures); Complete(rel, false, why); }

        public static string DupeId(MinionIdentity m)
        {
            KPrefabID k = m.GetComponent<KPrefabID>();
            return k != null ? k.InstanceID.ToString(CultureInfo.InvariantCulture) : null;
        }

        /// <summary>
        /// 8 hex digits over everything the portrait shows: each accessory slot (hair, face, body parts...), the hat and
        /// the clothing items. This is the value for live.json duplicants[].appearanceHash (Live.cs should call it so the
        /// portrait file name and the live value always match).
        /// </summary>
        public static string AppearanceHash(MinionIdentity m)
        {
            try
            {
                StringBuilder sb = new StringBuilder(160);
                Accessorizer acc = m.GetComponent<Accessorizer>();
                if (acc != null)
                    foreach (AccessorySlot slot in Db.Get().AccessorySlots.resources)
                    {
                        Accessory a = acc.GetAccessory(slot);
                        sb.Append(a != null ? a.Id : "-").Append('|');
                    }
                MinionResume res = m.GetComponent<MinionResume>();
                sb.Append(res != null ? res.CurrentHat : "").Append('|');
                WearableAccessorizer wa = m.GetComponent<WearableAccessorizer>();
                if (wa != null)
                {
                    string[] ids = wa.GetClothingItemsIds(ClothingOutfitUtility.OutfitType.Clothing);
                    if (ids != null) foreach (string s in ids) sb.Append(s).Append(',');
                }
                uint h = 2166136261;   // FNV-1a
                string str = sb.ToString();
                for (int i = 0; i < str.Length; i++) { h ^= str[i]; h *= 16777619; }
                return h.ToString("x8", CultureInfo.InvariantCulture);
            }
            catch { return null; }
        }

        private static void Fail(string where, Exception e)
        {
            failStreak++;
            Log.Error("art " + where + " failed (" + failStreak + ")", e);
            if (failStreak >= 5 && !off)
            {
                off = true;
                portraitBusy = false;
                Log.Warn("art switched off for this session after 5 failures in a row");
                List<string> all; lock (waiters) { all = new List<string>(waiters.Keys); }
                foreach (string r in all) Complete(r, false, "Art is switched off");
            }
        }

        // ---------------------------------------------------------------- frame timing

        private static void FrameDone(double ms, string what)
        {
            frames++;
            if (ms > worstMs) worstMs = ms;
            if (ms > FrameTargetMs)
            {
                overBudgetFrames++;
                if (overLogged < 20) { overLogged++; Log.Warn("art frame over " + FrameTargetMs + " ms: " + ms.ToString("0.0", CultureInfo.InvariantCulture) + " ms (" + what + ")"); }
            }
        }

        // ---------------------------------------------------------------- JIT warm-up

        /// <summary>
        /// JIT-compiles the live.json writer, the art code and the theme writer one method per frame while the player is still
        /// in the menu, so their first use in a world does not pay for it in one frame. Compile only, nothing runs.
        /// </summary>
        private static IEnumerator JitWarm()
        {
            Stopwatch total = Stopwatch.StartNew();
            List<MethodBase> todo = new List<MethodBase>();
            try
            {
                BindingFlags bf = BindingFlags.Static | BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
                foreach (Type t in new[] { typeof(LiveWriter), typeof(Json), typeof(Txt), typeof(ThemeWriter), typeof(Art), typeof(ArtWorker), typeof(PngCodec) })
                {
                    foreach (MethodInfo m in t.GetMethods(bf)) todo.Add(m);
                    foreach (Type n in t.GetNestedTypes(BindingFlags.NonPublic | BindingFlags.Public))
                        if (!n.IsGenericTypeDefinition) { foreach (MethodInfo m in n.GetMethods(bf)) todo.Add(m); foreach (ConstructorInfo c in n.GetConstructors(bf)) todo.Add(c); }
                }
            }
            catch (Exception e) { Log.Warn("art: jit warm-up list failed: " + e.Message); yield break; }
            int done = 0; double worst = 0;
            for (int i = 0; i < todo.Count && !off; i++)
            {
                MethodBase m = todo[i];
                if (m.IsAbstract || m.ContainsGenericParameters || m.DeclaringType.ContainsGenericParameters) continue;
                Stopwatch sw = Stopwatch.StartNew();
                try { System.Runtime.CompilerServices.RuntimeHelpers.PrepareMethod(m.MethodHandle); done++; } catch { }
                double ms = sw.Elapsed.TotalMilliseconds;
                if (ms > worst) worst = ms;
                yield return null;
            }
            Log.Info("jit warm-up: " + done + " methods compiled over " + todo.Count + " frames, " + total.Elapsed.TotalMilliseconds.ToString("0", CultureInfo.InvariantCulture) + " ms elapsed, worst method " + worst.ToString("0.0", CultureInfo.InvariantCulture) + " ms");
        }

        // ---------------------------------------------------------------- on-demand catalog images

        private sealed class Item
        {
            public string Kind, Id;
            public BuildingDef Def;
            public object Source;   // element, prefab GameObject or tag, for Def.GetUISprite
        }

        private static void TickRequests()
        {
            if (requests.Count == 0) return;
            if (portraitBusy) { gPortrait++; return; }
            if (!ArtWorker.Loaded) { gNotLoaded++; return; }
            if (coolDown > 0) { coolDown--; gCoolDown++; return; }
            // the game itself is struggling this frame (loading, a hitch): leave it alone (but never wait forever)
            if (Game.Instance != null && Game.Instance.IsLoading()) { slowSkips++; gLoading++; return; }
            if (Time.unscaledDeltaTime > 0.05f && slowSkips < 20) { slowSkips++; gSlowFrame++; return; }
            slowSkips = 0;
            if (!blitWarm)
            {
                // warm-up in its own frame: first use of the blit shader, a RenderTexture and a Texture2D (no sprite involved)
                Stopwatch ww = Stopwatch.StartNew();
                try { WarmBlit(); } catch (Exception e) { Log.Warn("art: blit warm-up failed: " + e.Message); }
                blitWarm = true;
                FrameDone(ww.Elapsed.TotalMilliseconds, "blit warm-up");
                LastWorkFrame = Time.frameCount;
                return;
            }
            if (ArtWorker.QueueLength > MaxQueued) { gEncoderBehind++; return; }   // encoder is behind: wait, do not pile up

            gRan++;
            Stopwatch fw = Stopwatch.StartNew();
            string last = "";
            while (requests.Count > 0)
            {
                double before = fw.Elapsed.TotalMilliseconds;
                if (before > 0 && before + avgItemMs * 1.5 > BudgetMs) break;   // the next item would not fit: next frame
                Req r = requests.Dequeue();
                last = r.Kind + "/" + r.Id;
                string rel = build + "/" + r.Kind + "/" + r.Id + ".png";
                try
                {
                    lock (waiters) drawnAtMs[rel] = reqClock.ElapsedMilliseconds;
                    string why = Draw(r, rel);
                    if (why != null) Complete(rel, false, why); else { drawnThisBurst++; failStreak = 0; }
                }
                catch (Exception e) { Complete(rel, false, "Drawing failed"); Fail("item " + last, e); if (off) break; }
                double cost = fw.Elapsed.TotalMilliseconds - before;
                avgItemMs = avgItemMs * 0.8 + cost * 0.2;
                if (cost > HardMs) break;   // one item alone blew the budget: stop here
            }
            double frameMs = fw.Elapsed.TotalMilliseconds;
            FrameDone(frameMs, last);
            LastWorkFrame = Time.frameCount;
            if (frameMs > HardMs) coolDown = Math.Min(30, (int)(frameMs / HardMs));   // pay a spike back with idle frames
            if (requests.Count == 0 && drawnThisBurst > 0)
            {
                Log.Info("art: request queue done: " + drawnThisBurst + " handed to the encoder, worst main-thread step " + worstMs.ToString("0.00", CultureInfo.InvariantCulture) +
                         " ms, steps over " + FrameTargetMs + " ms: " + overBudgetFrames + " of " + frames);
                drawnThisBurst = 0;
            }
        }

        /// <summary>Hands the image to the encoder (ack comes after the manifest lists it) or returns why not. Already drawn and unchanged: acks done at once.</summary>
        private static string Draw(Req r, string rel)
        {
            Item it = Resolve(r.Kind, r.Id);
            if (it == null) return "Unknown id";
            Sprite sprite; Color tint; string key;
            string why = Prepare(it, out sprite, out tint, out key);
            if (why != null) return why;
            if (ArtWorker.Has(rel))
            {
                string have = ArtWorker.SrcKeyOf(rel);
                if (have == null || have == key) { Complete(rel, true, "Already drawn"); return null; }   // no key stored (older image): keep it
            }
            int w, h;
            byte[] raw = BlitSprite(sprite, CatalogPx, true, out w, out h);
            if (raw == null) return "The game has no picture for it";
            ArtWorker.Enqueue(new ArtWorker.PngJob { Kind = it.Kind, Id = it.Id, Rel = rel, Rgba = raw, W = w, H = h, Tint = tint, SrcKey = key });
            return null;
        }

        /// <summary>Finds the game object behind (kind, id), with the same filters as the data export. null = the game has no such item.</summary>
        private static Item Resolve(string kind, string id)
        {
            switch (kind)
            {
                case "building":
                    foreach (BuildingDef d in Assets.BuildingDefs)
                        if (d != null && !d.Deprecated && !d.DebugOnly && d.PrefabID == id) return new Item { Kind = kind, Id = id, Def = d };
                    return null;
                case "element":
                    if (id == "Vacuum" || id == "Void") return null;
                    foreach (Element el in ElementLoader.elements)
                        if (el != null && el.id.ToString() == id) return new Item { Kind = kind, Id = id, Source = el };
                    return null;
                case "food":
                    foreach (EdiblesManager.FoodInfo f in EdiblesManager.GetAllLoadedFoodTypes())
                        if (f.Id == id)
                        {
                            GameObject fp = Assets.TryGetPrefab(new Tag(id));
                            return fp != null ? new Item { Kind = kind, Id = id, Source = fp } : null;
                        }
                    return null;
                default:
                    GameObject go = Assets.TryGetPrefab(new Tag(id));
                    Item it = go != null ? Classify(go) : null;
                    return it != null && it.Kind == kind && it.Id == id ? it : null;
            }
        }

        private static Item Classify(GameObject go)
        {
            if (go == null || go.GetComponent<MinionIdentity>() != null) return null;
            string id = go.PrefabID().Name;
            if (go.HasTag(GameTags.Creature))
            {
                // same filter as the export: adults with a calorie monitor
                StateMachineController smc = go.GetComponent<StateMachineController>();
                if (smc == null || smc.GetDef<CreatureCalorieMonitor.Def>() == null || smc.GetDef<BabyMonitor.Def>() != null) return null;
                return new Item { Kind = "critter", Id = id, Source = go };
            }
            if (go.HasTag(GameTags.Plant) && (go.GetComponent<Crop>() != null || go.GetComponent<TemperatureVulnerable>() != null))
                return new Item { Kind = "plant", Id = id, Source = go };
            if (go.GetComponent<PlantableSeed>() != null) return new Item { Kind = "seed", Id = id, Source = go };
            if (go.HasTag(GameTags.Egg)) return new Item { Kind = "egg", Id = id, Source = go };
            if (go.GetComponent<MedicinalPill>() != null) return new Item { Kind = "medicine", Id = id, Source = go };
            if (go.GetComponent<Edible>() != null) return null;   // foods come from the food list
            if (go.GetComponent<Pickupable>() != null && go.GetComponent<KBatchedAnimController>() != null && ElementLoader.GetElement(go.PrefabID()) == null)
                return new Item { Kind = "item", Id = id, Source = go };
            return null;
        }

        /// <summary>The game's UI sprite for the item. Returns null when fine, else the reason there is nothing to draw.</summary>
        private static string Prepare(Item it, out Sprite sprite, out Color tint, out string srcKey)
        {
            sprite = null; tint = Color.white; srcKey = null;
            if (!SafeId.IsMatch(it.Id)) return "Unknown id";
            if (it.Def != null) sprite = it.Def.GetUISprite("ui", false);
            else
            {
                var t = global::Def.GetUISprite(it.Source, "ui", false);
                if (t == null) return "The game has no picture for it";
                sprite = t.first;
                tint = t.second;
            }
            if (sprite == null || tint.a <= 0f) return "The game has no picture for it";
            Sprite unknown = Assets.GetSprite("unknown");
            if (unknown != null && sprite == unknown) return "The game has no picture for it";   // the game's placeholder: let the app show its own glyph
            srcKey = SrcKeyOf(it.Kind, sprite, tint);
            return null;
        }

        /// <summary>
        /// srcKey: 16 hex digits (FNV-1a 64) over what identifies the picture in the game's own data, without drawing it:
        /// kind, the sprite's name (for animation sprites the game names it "&lt;atlas texture&gt;:&lt;symbol&gt;:&lt;centered&gt;"),
        /// the atlas texture's name and size, the sprite's rectangle in the atlas, and the tint the game draws it with.
        /// It changes when Klei renames, repacks, resizes or retints the art; it does not see a same-size repaint of the very same
        /// rectangle (Unity exposes no content hash at run time), so a later comparison should also compare the game build.
        /// Cost: one sprite lookup (the game caches these sprites; the first lookup of an animation sprite creates it, well under
        /// a millisecond) plus hashing a string of about 100 characters.
        /// </summary>
        private static string SrcKeyOf(string kind, Sprite sprite, Color tint)
        {
            Texture tex = sprite.texture;
            Rect r;
            try { r = sprite.textureRect; } catch { r = sprite.rect; }
            Color32 t = tint;
            string s = kind + "|" + sprite.name + "|" + (tex != null ? tex.name : "-") + "|" + (tex != null ? tex.width + "x" + tex.height : "-") + "|" +
                       ((int)r.x) + "," + ((int)r.y) + "," + ((int)r.width) + "," + ((int)r.height) + "|" + t.r.ToString("x2") + t.g.ToString("x2") + t.b.ToString("x2") + t.a.ToString("x2");
            ulong h = 14695981039346656037UL;   // FNV-1a 64
            for (int i = 0; i < s.Length; i++) { h ^= s[i]; h *= 1099511628211UL; }
            return h.ToString("x16", CultureInfo.InvariantCulture);
        }

        /// <summary>The srcKey of an item WITHOUT drawing it, or null (unknown id, no picture). Main thread. For comparing with a bundled manifest.</summary>
        internal static string SrcKey(string kind, string id)
        {
            if (Array.IndexOf(CatalogKinds, kind) < 0 || !SafeId.IsMatch(id)) return null;
            Item it = Resolve(kind, id);
            if (it == null) return null;
            Sprite sp; Color tint; string key;
            return Prepare(it, out sp, out tint, out key) == null ? key : null;
        }

        // ---------------------------------------------------------------- sync (Sync.cs): the whole catalog, not frame-budgeted

        internal const string SyncSame = "=";           // SyncDraw: the image is there and its srcKey is unchanged
        private static List<Item> syncItems;
        private static int storeFailures;

        /// <summary>Images the encoder could not save (counted for the sync's error total).</summary>
        internal static int StoreFailures { get { return storeFailures; } }

        internal static bool SyncReady() { return !off && runner != null && ArtWorker.Loaded; }
        internal static int SyncCount { get { return syncItems != null ? syncItems.Count : 0; } }
        internal static string SyncName(int i) { Item it = syncItems[i]; return it.Kind + ": " + it.Id; }
        internal static void SyncDone() { syncItems = null; }

        /// <summary>Lists every catalog item (the same filters as the data export and Resolve) and warms the blit. Main thread, one frame.</summary>
        internal static void SyncPrepare()
        {
            if (!blitWarm) { WarmBlit(); }
            List<Item> list = new List<Item>(1400);
            HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (BuildingDef d in Assets.BuildingDefs)
                if (d != null && !d.Deprecated && !d.DebugOnly && SafeId.IsMatch(d.PrefabID) && seen.Add("building|" + d.PrefabID))
                    list.Add(new Item { Kind = "building", Id = d.PrefabID, Def = d });
            foreach (Element el in ElementLoader.elements)
            {
                if (el == null) continue;
                string id = el.id.ToString();
                if (id == "Vacuum" || id == "Void" || !SafeId.IsMatch(id) || !seen.Add("element|" + id)) continue;
                list.Add(new Item { Kind = "element", Id = id, Source = el });
            }
            foreach (EdiblesManager.FoodInfo f in EdiblesManager.GetAllLoadedFoodTypes())
            {
                if (!SafeId.IsMatch(f.Id) || !seen.Add("food|" + f.Id)) continue;
                GameObject fp = Assets.TryGetPrefab(new Tag(f.Id));
                if (fp != null) list.Add(new Item { Kind = "food", Id = f.Id, Source = fp });
            }
            foreach (KPrefabID k in Assets.Prefabs)
            {
                if (k == null) continue;
                Item it = Classify(k.gameObject);
                if (it != null && SafeId.IsMatch(it.Id) && seen.Add(it.Kind + "|" + it.Id)) list.Add(it);
            }
            syncItems = list;
        }

        /// <summary>
        /// Draws catalog item i now (no frame budget). Returns null = handed to the encoder, SyncSame = already there and unchanged
        /// (not with force), else the reason there is no picture. Throws on a real failure.
        /// </summary>
        internal static string SyncDraw(int i, bool force)
        {
            Item it = syncItems[i];
            string rel = build + "/" + it.Kind + "/" + it.Id + ".png";
            Sprite sprite; Color tint; string key;
            string why = Prepare(it, out sprite, out tint, out key);
            if (why != null) return why;
            if (!force && ArtWorker.Has(rel))
            {
                string have = ArtWorker.SrcKeyOf(rel);
                if (have == null || have == key) return SyncSame;
            }
            int w, h;
            byte[] raw = BlitSprite(sprite, CatalogPx, true, out w, out h);
            if (raw == null) return "The game has no picture for it";
            ArtWorker.Enqueue(new ArtWorker.PngJob { Kind = it.Kind, Id = it.Id, Rel = rel, Rgba = raw, W = w, H = h, Tint = tint, SrcKey = key });
            return null;
        }

        internal static bool KnownKind(string kind) { return Array.IndexOf(CatalogKinds, kind) >= 0 || kind == "dupe"; }
        internal static bool SafeIdOk(string id) { return id != null && SafeId.IsMatch(id); }

        internal static void WarmBlit()
        {
            Texture2D src = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            RenderTexture rt = RenderTexture.GetTemporary(8, 8, 0, RenderTextureFormat.ARGB32);
            RenderTexture prev = RenderTexture.active;
            Texture2D rd = new Texture2D(8, 8, TextureFormat.RGBA32, false);
            try
            {
                Graphics.Blit(src, rt, new Vector2(1f, 1f), new Vector2(0f, 0f));
                RenderTexture.active = rt;
                rd.ReadPixels(new Rect(0, 0, 8, 8), 0, 0, false);
                rd.GetRawTextureData();
            }
            finally
            {
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                UnityEngine.Object.Destroy(src); UnityEngine.Object.Destroy(rd);
            }
            blitWarm = true;
        }

        /// <summary>Sprite -> RenderTexture -> RGBA32 bytes (bottom row first). maxPx = long side (0 = the sprite's own size). Works for unreadable atlases.</summary>
        internal static byte[] BlitSprite(Sprite sprite, int maxPx, bool refuseTight, out int w, out int h)
        {
            w = h = 0;
            Texture tex = sprite.texture;
            if (tex == null || tex.width == 0 || tex.height == 0) return null;
            Rect r;
            try { r = sprite.textureRect; } catch { r = sprite.rect; }
            if (r.width < 1f || r.height < 1f) return null;
            if (refuseTight && sprite.packed && sprite.packingMode == SpritePackingMode.Tight) return null;   // tight atlas sprites: no plain rectangle

            if (maxPx > 0)
            {
                float k = (float)maxPx / Mathf.Max(r.width, r.height);
                w = Mathf.Max(1, Mathf.RoundToInt(r.width * k));
                h = Mathf.Max(1, Mathf.RoundToInt(r.height * k));
            }
            else { w = Mathf.RoundToInt(r.width); h = Mathf.RoundToInt(r.height); if (w < 1 || h < 1 || w > 512 || h > 512) return null; }
            Vector2 scale = new Vector2(r.width / tex.width, r.height / tex.height);
            Vector2 offset = new Vector2(r.x / tex.width, r.y / tex.height);

            RenderTexture rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
            RenderTexture prev = RenderTexture.active;
            Texture2D rd = null;
            try
            {
                rt.filterMode = FilterMode.Bilinear;
                Graphics.Blit(tex, rt, scale, offset);
                RenderTexture.active = rt;
                rd = new Texture2D(w, h, TextureFormat.RGBA32, false);
                rd.ReadPixels(new Rect(0, 0, w, h), 0, 0, false);
                return rd.GetRawTextureData();
            }
            finally
            {
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                if (rd != null) UnityEngine.Object.Destroy(rd);
            }
        }

        // ---------------------------------------------------------------- portraits: when to draw

        /// <summary>
        /// Only the duplicants of the loaded colony. After a world load this looks every few frames until it has seen the colony
        /// (no waiting behind anything); afterwards once a second for an appearance hash that changed.
        /// </summary>
        private static void TickPortraits()
        {
            if (portraitBusy || !ArtWorker.Loaded) return;
            float now = Time.unscaledTime;
            if (now < nextPortraitCheck) return;
            if (!LiveWriter.Ready()) return;   // wantPortraits stays set: the next frame asks again
            nextPortraitCheck = now + (wantPortraits ? 0.1f : 1f);   // at most one portrait per second once settled
            bool any = false;
            foreach (MinionIdentity m in Components.LiveMinionIdentities.Items)
            {
                if (m == null) continue;
                string id = DupeId(m);
                string hash = AppearanceHash(m);
                if (id == null || hash == null) continue;
                bool have; lock (drawnPortraits) { have = drawnPortraits.Contains(id + "-" + hash); }
                if (have) continue;
                string akey = id + "-" + hash;
                int tries;
                attempts.TryGetValue(akey, out tries);
                if (tries >= 3) continue;   // blank three times: give up on this look until it changes
                attempts[akey] = tries + 1;
                portraitBusy = true;
                any = true;
                LastWorkFrame = Time.frameCount;
                runner.StartCoroutine(PortraitRun(m, id, hash, tries == 1 ? 1 : 0, tries == 2));
                break;
            }
            if (!any) wantPortraits = false;
        }

        // ---------------------------------------------------------------- duplicant portraits

        private static GameObject stageRoot;
        private static Camera stageCam;
        private static RectTransform anchor;
        private static RenderTexture rtBlack, rtWhite;
        private static int stageMode = -1;

        /// <summary>
        /// The game's UI anim (KBatchedAnimController, UI material) places itself from its ROOT CANVAS (GetTransformMatrix):
        /// position = (localToWorld(pivot) * 1/scaleFactor) - screenOffset, where screenOffset is half the canvas rect for every
        /// render mode except WorldSpace (0), and the size is multiplied by the rect's lossyScale. The first version used a
        /// ScreenSpaceCamera canvas whose rect came from the GAME window (the camera had no target texture while the canvas laid
        /// itself out), so the figure was placed far outside the stage. Mode 0 (default) = WorldSpace canvas of exactly the stage
        /// size at the world origin, scale 1: local = world, screenOffset 0, 1 unit = 1 pixel. Mode 1 (second try) = the game's
        /// own setup: ScreenSpaceCamera, camera permanently targeting the stage texture (so the canvas rect IS the stage size),
        /// camera at the stage center so the world position minus half the rect is center-relative.
        /// </summary>
        private static void StageReset(int mode)
        {
            if (stageRoot != null && stageMode != mode)
            {
                UnityEngine.Object.Destroy(stageRoot);
                if (stageCam != null) UnityEngine.Object.Destroy(stageCam.gameObject);
                stageRoot = null; stageCam = null; anchor = null;
            }
        }

        /// <summary>Stage step 1: the two RenderTextures.</summary>
        private static void StageTextures()
        {
            if (rtBlack == null) rtBlack = new RenderTexture(StageW, StageH, 0, RenderTextureFormat.ARGB32);
            if (rtWhite == null) rtWhite = new RenderTexture(StageW, StageH, 0, RenderTextureFormat.ARGB32);
            if (!rtBlack.IsCreated()) rtBlack.Create();
            if (!rtWhite.IsCreated()) rtWhite.Create();
        }

        /// <summary>Stage step 2: the private camera.</summary>
        private static void StageCamera(int mode)
        {
            stageMode = mode;
            int ui = LayerMask.NameToLayer("UI");
            if (ui < 0) ui = 5;

            GameObject camGo = new GameObject("OniCompanionArtCamera");
            camGo.hideFlags = HideFlags.HideAndDontSave;
            UnityEngine.Object.DontDestroyOnLoad(camGo);
            camGo.transform.position = mode == 0 ? new Vector3(0f, 0f, -10f) : new Vector3(StageW / 2f, StageH / 2f, -10f);
            stageCam = camGo.AddComponent<Camera>();
            stageCam.orthographic = true;
            stageCam.orthographicSize = StageH / 2f;   // 1 world unit = 1 pixel
            stageCam.nearClipPlane = 0.1f;
            stageCam.farClipPlane = 100f;
            stageCam.clearFlags = CameraClearFlags.SolidColor;
            stageCam.cullingMask = 1 << ui;
            stageCam.allowHDR = false;
            stageCam.allowMSAA = false;
            stageCam.useOcclusionCulling = false;
            stageCam.enabled = false;   // only ever drawn by our explicit Render() call
            if (mode == 1) stageCam.targetTexture = rtBlack;
        }

        /// <summary>Stage step 3: the canvas and the anchor the portrait widget hangs on.</summary>
        private static void StageCanvas(int mode)
        {
            int ui = LayerMask.NameToLayer("UI");
            if (ui < 0) ui = 5;
            stageRoot = new GameObject("OniCompanionArtStage", typeof(RectTransform));
            stageRoot.hideFlags = HideFlags.HideAndDontSave;
            stageRoot.layer = ui;
            UnityEngine.Object.DontDestroyOnLoad(stageRoot);
            Canvas canvas = stageRoot.AddComponent<Canvas>();
            if (mode == 0)
            {
                canvas.renderMode = RenderMode.WorldSpace;
                canvas.worldCamera = stageCam;
                RectTransform crt = stageRoot.GetComponent<RectTransform>();
                crt.pivot = new Vector2(0.5f, 0.5f);
                crt.sizeDelta = new Vector2(StageW, StageH);
                crt.position = Vector3.zero;
                crt.localScale = Vector3.one;
            }
            else
            {
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = stageCam;
                canvas.planeDistance = 10f;
            }

            GameObject a = new GameObject("Anchor", typeof(RectTransform));
            a.layer = ui;
            a.transform.SetParent(stageRoot.transform, false);
            anchor = a.GetComponent<RectTransform>();
            anchor.anchorMin = anchor.anchorMax = new Vector2(0.5f, 0.5f);
            anchor.pivot = new Vector2(0.5f, 0f);   // feet at the bottom middle, like the game's portrait rectangle
            anchor.sizeDelta = new Vector2(AnchorW, AnchorH);
            anchor.anchoredPosition = new Vector2(0f, -StageH / 2f + 30f);
        }

        private static void SetLayerRecursive(GameObject go, int layer)
        {
            go.layer = layer;
            foreach (Transform c in go.transform) SetLayerRecursive(c.gameObject, layer);
        }

        private static void RenderStage(RenderTexture target, Color bg)
        {
            stageCam.backgroundColor = bg;
            stageCam.targetTexture = target;
            stageCam.Render();
            if (stageMode != 1) stageCam.targetTexture = null;
        }

        private static byte[] Read(RenderTexture rt)
        {
            RenderTexture prev = RenderTexture.active;
            Texture2D rd = null;
            try
            {
                RenderTexture.active = rt;
                rd = new Texture2D(rt.width, rt.height, TextureFormat.RGBA32, false);
                rd.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0, false);
                return rd.GetRawTextureData();
            }
            finally
            {
                RenderTexture.active = prev;
                if (rd != null) UnityEngine.Object.Destroy(rd);
            }
        }

        private static IEnumerator PortraitRun(MinionIdentity m, string id, string hash, int mode, bool slow)
        {
            GameObject widgetGo = null;
            FullBodyUIMinionWidget widget = null;
            bool ok = true;
            byte[] black = null, white = null;
            Stopwatch sw = Stopwatch.StartNew();
            // Stage set-up, one step per frame (first use only): textures, camera, canvas. Then the widget in its own frame.
            bool fresh = stageRoot == null || stageMode != mode;
            try { StageReset(mode); StageTextures(); }
            catch (Exception e) { ok = false; Fail("portrait stage textures", e); }
            if (fresh) { FrameDone(sw.Elapsed.TotalMilliseconds, "stage textures"); yield return null; sw.Reset(); sw.Start(); }
            if (ok && stageRoot == null)
            {
                try { StageCamera(mode); } catch (Exception e) { ok = false; Fail("portrait stage camera", e); }
                FrameDone(sw.Elapsed.TotalMilliseconds, "stage camera"); yield return null; sw.Reset(); sw.Start();
                if (ok)
                {
                    try { StageCanvas(mode); } catch (Exception e) { ok = false; Fail("portrait stage canvas", e); }
                    FrameDone(sw.Elapsed.TotalMilliseconds, "stage canvas"); yield return null; sw.Reset(); sw.Start();
                }
            }
            if (ok) try
            {
                stageRoot.SetActive(true);
                // The game's own portrait widget builds the dupe exactly as its screens do (accessories, hat, clothing).
                widgetGo = new GameObject("PortraitWidget", typeof(RectTransform));
                widgetGo.transform.SetParent(anchor, false);
                widget = widgetGo.AddComponent<FullBodyUIMinionWidget>();
                FieldInfo anchorField = typeof(FullBodyUIMinionWidget).GetField("duplicantAnimAnchor", BindingFlags.NonPublic | BindingFlags.Instance);
                if (anchorField == null) throw new MissingFieldException("FullBodyUIMinionWidget.duplicantAnimAnchor");
                anchorField.SetValue(widget, anchor.gameObject);
                widget.SetPortraitAnimator(m);
                int ui = LayerMask.NameToLayer("UI"); if (ui < 0) ui = 5;
                SetLayerRecursive(stageRoot, ui);
            }
            catch (Exception e) { ok = false; Fail("portrait setup", e); }
            FrameDone(sw.Elapsed.TotalMilliseconds, "portrait setup " + id);

            if (ok)
            {
                // let the animation register, update its batch and let the canvas renderer build its mesh (LateUpdate)
                int wait = slow ? 24 : 8;
                for (int i = 0; i < wait; i++) yield return null;
                yield return new WaitForEndOfFrame();   // after every LateUpdate of this frame: the mesh and material are current

                sw.Reset(); sw.Start();
                try
                {
                    Diag(widget, mode, id);
                    Canvas.ForceUpdateCanvases();
                    RenderStage(rtBlack, new Color(0f, 0f, 0f, 1f));
                }
                catch (Exception e) { ok = false; Fail("portrait render", e); }
                FrameDone(sw.Elapsed.TotalMilliseconds, "portrait render black " + id);
                yield return new WaitForEndOfFrame();
                if (ok)
                {
                    sw.Reset(); sw.Start();
                    try { RenderStage(rtWhite, new Color(1f, 1f, 1f, 1f)); }
                    catch (Exception e) { ok = false; Fail("portrait render", e); }
                    FrameDone(sw.Elapsed.TotalMilliseconds, "portrait render white " + id);
                    yield return null;
                }

                if (ok)
                {
                    sw.Reset(); sw.Start();
                    try { black = Read(rtBlack); } catch (Exception e) { ok = false; Fail("portrait read 1", e); }
                    FrameDone(sw.Elapsed.TotalMilliseconds, "portrait read black " + id);
                    yield return null;
                }
                if (ok)
                {
                    sw.Reset(); sw.Start();
                    try { white = Read(rtWhite); } catch (Exception e) { ok = false; Fail("portrait read 2", e); }
                    FrameDone(sw.Elapsed.TotalMilliseconds, "portrait read white " + id);
                }
            }

            // the widget spawns its anim controller as a child of the ANCHOR, not of itself: destroy that too
            try
            {
                if (widget != null && widget.animController != null) UnityEngine.Object.Destroy(widget.animController.gameObject);
            }
            catch (Exception e) { Log.Error("portrait cleanup (controller)", e); }
            try
            {
                if (widgetGo != null) UnityEngine.Object.Destroy(widgetGo);
                if (stageRoot != null) stageRoot.SetActive(false);
            }
            catch (Exception e) { Log.Error("portrait cleanup", e); }

            if (ok && black != null && white != null)
            {
                failStreak = 0;
                ArtWorker.Enqueue(new ArtWorker.PortraitJob { Id = id, Hash = hash, Black = black, White = white, W = StageW, H = StageH, Build = build });
            }
            // renderedHash is set by the worker callback once the portrait was not blank
            portraitBusy = false;
        }

        /// <summary>One line per portrait attempt: what the game's anim looks like at render time (for the next round if it is still blank).</summary>
        private static void Diag(FullBodyUIMinionWidget w, int mode, string id)
        {
            try
            {
                KBatchedAnimController c = w != null ? w.animController : null;
                Canvas root = stageRoot.GetComponent<Canvas>();
                RectTransform rt = c != null ? c.GetComponent<RectTransform>() : null;
                Log.Info("art: portrait try " + id + " mode " + mode + ": controller " + (c != null) + ", batch " + (c != null && c.GetBatch() != null) +
                         ", ctrlRect " + (rt != null ? rt.rect.width.ToString("0") + "x" + rt.rect.height.ToString("0") : "-") +
                         ", ctrlWorld " + (rt != null ? rt.position.x.ToString("0") + "," + rt.position.y.ToString("0") : "-") +
                         ", canvas " + root.renderMode + " " + root.pixelRect.width.ToString("0") + "x" + root.pixelRect.height.ToString("0") +
                         ", canvasRect " + stageRoot.GetComponent<RectTransform>().rect.width.ToString("0") + "x" + stageRoot.GetComponent<RectTransform>().rect.height.ToString("0") +
                         ", renderer " + (c != null && c.GetComponent<KBatchedAnimCanvasRenderer>() != null));
            }
            catch (Exception e) { Log.Warn("art: portrait diag failed: " + e.Message); }
        }

        /// <summary>Worker -> main: a portrait for this look was written (or was blank).</summary>
        internal static void PortraitResult(string id, string hash, bool written)
        {
            if (written) lock (drawnPortraits) { drawnPortraits.Add(id + "-" + hash); }
        }

        // ---------------------------------------------------------------- the runner component

        /// <summary>Host for the coroutines. Plain MonoBehaviour on a hidden object that survives scene loads.</summary>
        internal sealed class ArtRunner : MonoBehaviour { }
    }

    /// <summary>
    /// The one background thread: PNG encoding, hashing, file writes and the manifest. Jobs come from the main thread
    /// through a queue; nothing here touches Unity objects. The manifest is rewritten at most once a second after catalog
    /// images (at once after a portrait), and a request is acknowledged only after the manifest that lists its image is on disk.
    /// </summary>
    internal static class ArtWorker
    {
        internal abstract class Job { }
        internal sealed class LoadJob : Job { }
        internal sealed class PngJob : Job { public string Kind, Id, Rel, SrcKey; public byte[] Rgba; public int W, H; public Color Tint; }
        internal sealed class PortraitJob : Job { public string Id, Hash; public byte[] Black, White; public int W, H, Build; }

        private sealed class Entry { public string Kind, Id, Rel, Hash, Sha, SrcKey; public long Size; public int W, H; }

        private const long ManifestGapMs = 1000;

        private static readonly object qLock = new object();
        private static readonly Queue<Job> queue = new Queue<Job>();
        private static Thread thread;

        private static readonly object stLock = new object();
        private static readonly Dictionary<string, Entry> files = new Dictionary<string, Entry>();
        private static int build;
        private static List<string> dlc;
        private static volatile bool loaded;

        // worker thread only
        private static volatile bool dirty;
        private static volatile bool busy;      // a job (or a manifest flush) is being worked on
        private static long lastManifestMs = -100000;
        private static readonly Stopwatch clock = Stopwatch.StartNew();
        private static readonly List<string> storedRels = new List<string>();

        public static bool Loaded { get { return loaded; } }
        public static int Count { get { lock (stLock) return files.Count; } }
        public static int QueueLength { get { lock (qLock) return queue.Count; } }
        /// <summary>Nothing queued, nothing being worked on, and the manifest is written (the sync waits for this).</summary>
        public static bool Idle { get { lock (qLock) return queue.Count == 0 && !busy && !dirty; } }

        public static void Begin(int b, List<string> dlcIds)
        {
            lock (stLock) { build = b; dlc = new List<string>(dlcIds); }
            if (thread != null) return;
            thread = new Thread(Loop) { IsBackground = true, Name = "OniCompanionArt", Priority = System.Threading.ThreadPriority.BelowNormal };
            thread.Start();
        }

        public static bool Has(string rel)
        {
            lock (stLock) { return files.ContainsKey(rel); }
        }

        /// <summary>The srcKey stored with an image, or null (none stored, or no such image).</summary>
        public static string SrcKeyOf(string rel)
        {
            lock (stLock) { Entry e; return files.TryGetValue(rel, out e) ? e.SrcKey : null; }
        }

        public static void Enqueue(Job j)
        {
            lock (qLock) { queue.Enqueue(j); Monitor.Pulse(qLock); }
        }

        private static void Loop()
        {
            while (true)
            {
                Job j = null;
                lock (qLock)
                {
                    while (queue.Count == 0)
                    {
                        if (!dirty) { Monitor.Wait(qLock); continue; }
                        long left = ManifestGapMs - (clock.ElapsedMilliseconds - lastManifestMs);
                        if (left <= 0) break;
                        long w0 = clock.ElapsedMilliseconds;
                        Monitor.Wait(qLock, (int)left);
                        long over = clock.ElapsedMilliseconds - w0 - left;
                        if (over > 2000 && overslept++ < 5) Log.Warn("art worker: a " + left + " ms timed wait came back " + over + " ms late");
                    }
                    if (queue.Count > 0) j = queue.Dequeue();
                    busy = true;
                }
                try
                {
                    if (j == null) { Flush(); continue; }
                    LoadJob l = j as LoadJob;
                    if (l != null) { DoLoad(); continue; }
                    PngJob p = j as PngJob;
                    if (p != null)
                    {
                        try { DoPng(p); }
                        catch (Exception e) { Log.Error("art: writing " + p.Rel, e); Art.StoreFailed(p.Rel, "Could not save the picture"); }
                        if (dirty && clock.ElapsedMilliseconds - lastManifestMs >= ManifestGapMs) Flush();
                        continue;
                    }
                    PortraitJob d = j as PortraitJob;
                    if (d != null) { DoPortrait(d); continue; }
                }
                catch (Exception e)
                {
                    Log.Error("art worker job " + (j != null ? j.GetType().Name : "flush"), e);
                    if (j is LoadJob) loaded = true;   // never leave the main thread waiting
                }
                finally { busy = false; }
            }
        }

        // ---- load the previous manifest (our own format: written by WriteManifest below, same key order)

        private static readonly Regex RxFile = new Regex(
            "\\{\"kind\":\"(?<k>[a-z]+)\",\"id\":\"(?<id>[^\"]+)\",\"path\":\"(?<p>[^\"]+)\"(?:,\"appearanceHash\":\"(?<h>[0-9a-f]{8})\")?(?:,\"srcKey\":\"(?<sk>[0-9a-f]{16})\")?,\"size\":(?<s>\\d+),\"sha256\":\"(?<sha>[0-9a-f]{64})\",\"width\":(?<w>\\d+),\"height\":(?<ht>\\d+)\\}",
            RegexOptions.Compiled);

        private static void DoLoad()
        {
            string path = Art.ArtDir();
            string mf = Path.Combine(path, "manifest.json");
            bool keep = false;
            try
            {
                if (File.Exists(mf))
                {
                    string text = File.ReadAllText(mf, Encoding.UTF8);
                    Match mb = Regex.Match(text, "\"build\":(\\d+),");
                    bool sameBuild = mb.Success && mb.Groups[1].Value == build.ToString(CultureInfo.InvariantCulture);
                    Match mr = Regex.Match(text, "\"renderRev\":(\\d+)");
                    int rev = mr.Success ? int.Parse(mr.Groups[1].Value, CultureInfo.InvariantCulture) : 1;   // 0.2.1 manifests have none: they were drawn as revision 1
                    keep = sameBuild && rev == Art.RenderRev;
                    if (keep)
                        lock (stLock)
                        {
                            foreach (Match m in RxFile.Matches(text))
                            {
                                string rel = m.Groups["p"].Value;
                                if (!File.Exists(Path.Combine(path, rel.Replace('/', Path.DirectorySeparatorChar)))) continue;   // file gone: drawn again on demand
                                files[rel] = new Entry
                                {
                                    Kind = m.Groups["k"].Value, Id = m.Groups["id"].Value, Rel = rel,
                                    Hash = m.Groups["h"].Success ? m.Groups["h"].Value : null,
                                    SrcKey = m.Groups["sk"].Success ? m.Groups["sk"].Value : null,
                                    Size = long.Parse(m.Groups["s"].Value, CultureInfo.InvariantCulture), Sha = m.Groups["sha"].Value,
                                    W = int.Parse(m.Groups["w"].Value, CultureInfo.InvariantCulture), H = int.Parse(m.Groups["ht"].Value, CultureInfo.InvariantCulture)
                                };
                            }
                        }
                }
            }
            catch (Exception e) { Log.Error("art: reading the old manifest failed, everything is drawn again on demand", e); keep = false; lock (stLock) files.Clear(); }

            int portraits = 0;
            lock (stLock)
            {
                foreach (Entry e in files.Values)
                    if (e.Kind == "dupe" && e.Hash != null) { Art.PortraitResult(e.Id, e.Hash, true); portraits++; }   // already drawn: not drawn again
            }
            // art of other builds is of no use any more
            try
            {
                if (Directory.Exists(path))
                    foreach (string d in Directory.GetDirectories(path))
                    {
                        string name = Path.GetFileName(d);
                        int n;
                        if (int.TryParse(name, NumberStyles.None, CultureInfo.InvariantCulture, out n) && (n != build || !keep))
                        {
                            Directory.Delete(d, true);
                            Log.Info("art: removed art of " + (n != build ? "old build " : "an older drawing revision of build ") + name);
                        }
                    }
            }
            catch (Exception e) { Log.Error("art: cleaning old builds", e); }
            WriteManifest();   // tells the core that this mod draws on demand (onDemand), even before the first image
            lastManifestMs = clock.ElapsedMilliseconds;
            Log.Info("art: manifest loaded, " + Count + " images kept (" + portraits + " portraits), build " + build);
            loaded = true;
        }

        // ---- files

        private static string FullPath(string rel)
        {
            return Path.Combine(Art.ArtDir(), rel.Replace('/', Path.DirectorySeparatorChar));
        }

        private static void WriteBytesAtomic(string path, byte[] data)
        {
            string dir = Path.GetDirectoryName(path);
            if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
            string tmp = path + ".tmp";
            File.WriteAllBytes(tmp, data);
            if (File.Exists(path))
            {
                try { File.Replace(tmp, path, null); return; }
                catch { }
                File.Delete(path);
            }
            File.Move(tmp, path);
        }

        private static string Sha256Hex(byte[] data)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] h = sha.ComputeHash(data);
                StringBuilder sb = new StringBuilder(64);
                for (int i = 0; i < h.Length; i++) sb.Append(h[i].ToString("x2", CultureInfo.InvariantCulture));
                return sb.ToString();
            }
        }

        private static void Store(string kind, string id, string rel, string hash, string srcKey, byte[] png, int w, int h)
        {
            WriteBytesAtomic(FullPath(rel), png);
            Entry e = new Entry { Kind = kind, Id = id, Rel = rel, Hash = hash, SrcKey = srcKey, Size = png.Length, Sha = Sha256Hex(png), W = w, H = h };
            lock (stLock) { files[rel] = e; }
        }

        private static void DoPng(PngJob j)
        {
            long p0 = clock.ElapsedMilliseconds;
            try { DoPngInner(j); }
            finally
            {
                long pms = clock.ElapsedMilliseconds - p0;
                if (pms > 1000) Log.Warn("art worker: encoding and writing " + j.Rel + " took " + pms + " ms");
            }
        }

        private static void DoPngInner(PngJob j)
        {
            byte[] top = PngCodec.FlipRows(j.Rgba, j.W, j.H);
            if (j.Tint.r != 1f || j.Tint.g != 1f || j.Tint.b != 1f || j.Tint.a != 1f) PngCodec.Tint(top, j.Tint.r, j.Tint.g, j.Tint.b, j.Tint.a);
            PngCodec.ClearHidden(top);
            byte[] png = PngCodec.Encode(j.W, j.H, top);
            Store(j.Kind, j.Id, j.Rel, null, j.SrcKey, png, j.W, j.H);
            dirty = true;
            storedRels.Add(j.Rel);   // acknowledged by the next manifest write
        }
        private static void DoPortrait(PortraitJob j)
        {
            int w = j.W, h = j.H;
            byte[] rgba = new byte[w * h * 4];
            int minX = w, minY = h, maxX = -1, maxY = -1, solid = 0;
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++)
                {
                    int i = (y * w + x) * 4;
                    // on black: C*a. On white: C*a + 255*(1-a). So a = 1 - mean(white - black) / 255, C = black / a.
                    float d = ((j.White[i] - j.Black[i]) + (j.White[i + 1] - j.Black[i + 1]) + (j.White[i + 2] - j.Black[i + 2])) / (3f * 255f);
                    float a = 1f - d;
                    if (a <= 0.02f) continue;
                    if (a > 1f) a = 1f;
                    rgba[i] = ClampByte(j.Black[i] / a);
                    rgba[i + 1] = ClampByte(j.Black[i + 1] / a);
                    rgba[i + 2] = ClampByte(j.Black[i + 2] / a);
                    rgba[i + 3] = (byte)(a * 255f + 0.5f);
                    if (rgba[i + 3] > 8)
                    {
                        solid++;
                        if (x < minX) minX = x; if (x > maxX) maxX = x;
                        if (y < minY) minY = y; if (y > maxY) maxY = y;
                    }
                }
            }
            if (solid < 200)
            {
                Log.Warn("art: portrait for dupe " + j.Id + " came out blank (" + solid + " px)");
                Art.PortraitResult(j.Id, j.Hash, false);
                return;
            }
            if (minX == 0 || minY == 0 || maxX == w - 1 || maxY == h - 1)
                Log.Warn("art: portrait for dupe " + j.Id + " touches the stage edge (clipped): enlarge the stage");

            // crop to the figure with a small margin, then scale down to at most DupeMaxPx on the long side
            const int pad = 6;
            minX = Math.Max(0, minX - pad); minY = Math.Max(0, minY - pad);
            maxX = Math.Min(w - 1, maxX + pad); maxY = Math.Min(h - 1, maxY + pad);
            int cw = maxX - minX + 1, ch = maxY - minY + 1;
            byte[] crop = new byte[cw * ch * 4];
            for (int y = 0; y < ch; y++) Buffer.BlockCopy(rgba, ((minY + y) * w + minX) * 4, crop, y * cw * 4, cw * 4);
            int ow = cw, oh = ch;
            int maxSide = Math.Max(cw, ch);
            if (maxSide > 256)
            {
                float k = 256f / maxSide;
                ow = Math.Max(1, (int)Math.Round(cw * k)); oh = Math.Max(1, (int)Math.Round(ch * k));
                crop = PngCodec.Downscale(crop, cw, ch, ow, oh);
            }
            byte[] top = PngCodec.FlipRows(crop, ow, oh);
            byte[] png = PngCodec.Encode(ow, oh, top);

            string rel = j.Build + "/dupe/" + j.Id + "-" + j.Hash + ".png";
            Store("dupe", j.Id, rel, j.Hash, null, png, ow, oh);

            // keep this look and the one before it; delete older ones
            List<Entry> mine = new List<Entry>();
            lock (stLock) { foreach (Entry e in files.Values) if (e.Kind == "dupe" && e.Id == j.Id && e.Hash != j.Hash) mine.Add(e); }
            if (mine.Count > 1)
            {
                mine.Sort(delegate (Entry a, Entry b)
                {
                    try { return File.GetLastWriteTimeUtc(FullPath(b.Rel)).CompareTo(File.GetLastWriteTimeUtc(FullPath(a.Rel))); } catch { return 0; }
                });
                for (int i = 1; i < mine.Count; i++)
                {
                    lock (stLock) files.Remove(mine[i].Rel);
                    try { File.Delete(FullPath(mine[i].Rel)); } catch { }
                }
            }
            Flush();   // portraits change the list: the manifest goes out again at once, atomically
            Art.PortraitResult(j.Id, j.Hash, true);
        }

        private static byte ClampByte(float v)
        {
            return v <= 0f ? (byte)0 : v >= 255f ? (byte)255 : (byte)(v + 0.5f);
        }


        /// <summary>Writes the manifest, then acknowledges the requests whose images it lists. Worker thread.</summary>
        private static int overslept;   // worker thread only: diagnostics (live test 0.4.0, Linux build under FEX)

        private static void Flush()
        {
            long f0 = clock.ElapsedMilliseconds;
            WriteManifest();
            long fms = clock.ElapsedMilliseconds - f0;
            if (fms > 1000) Log.Warn("art worker: writing the manifest took " + fms + " ms (" + Count + " images)");
            lastManifestMs = clock.ElapsedMilliseconds;
            dirty = false;
            if (storedRels.Count > 0)
            {
                List<string> done = new List<string>(storedRels);
                storedRels.Clear();
                Art.Stored(done);
            }
        }

        /// <summary>Written after the PNGs it lists exist, write-tmp-then-rename.</summary>
        private static void WriteManifest()
        {
            List<Entry> list;
            List<string> dl; int b;
            lock (stLock)
            {
                list = new List<Entry>(files.Values);
                dl = new List<string>(dlc); b = build;
            }
            list.Sort(delegate (Entry x, Entry y) { return string.CompareOrdinal(x.Rel, y.Rel); });
            Json j = new Json(64 + list.Count * 230);
            j.Obj();
            j.PI("schema", 1);
            j.P("modVersion", Env.ModVersion);
            j.PI("build", b);
            j.Key("dlcIds").StrArr(dl);
            j.P("writtenAt", Env.Now());
            j.P("onDemand", true);
            j.PI("renderRev", Art.RenderRev);
            j.Key("files").Arr();
            foreach (Entry e in list)
            {
                j.Obj().P("kind", e.Kind).P("id", e.Id).P("path", e.Rel);
                if (e.Hash != null) j.P("appearanceHash", e.Hash);
                if (e.SrcKey != null) j.P("srcKey", e.SrcKey);
                j.PI("size", e.Size).P("sha256", e.Sha).PI("width", e.W).PI("height", e.H).EndObj();
            }
            j.EndArr().EndObj();
            Files.WriteAtomic(Path.Combine(Art.ArtDir(), "manifest.json"), j.ToString());
        }
    }


    /// <summary>PNG encoding and the little pixel helpers, no Unity types (tested offline: see mod/tests/PngTest).</summary>
    internal static class PngCodec
    {
        // BEGIN PNG
        private static uint[] crcTable;

        private static uint Crc(byte[] buf, int off, int len, uint crc)
        {
            if (crcTable == null)
            {
                uint[] t = new uint[256];
                for (uint n = 0; n < 256; n++)
                {
                    uint c = n;
                    for (int k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                    t[n] = c;
                }
                crcTable = t;
            }
            uint r = crc ^ 0xFFFFFFFFu;
            for (int i = 0; i < len; i++) r = crcTable[(r ^ buf[off + i]) & 0xFF] ^ (r >> 8);
            return r ^ 0xFFFFFFFFu;
        }

        private static void Chunk(Stream s, string type, byte[] data, int len)
        {
            byte[] head = new byte[8];
            head[0] = (byte)(len >> 24); head[1] = (byte)(len >> 16); head[2] = (byte)(len >> 8); head[3] = (byte)len;
            for (int i = 0; i < 4; i++) head[4 + i] = (byte)type[i];
            s.Write(head, 0, 8);
            uint crc = Crc(head, 4, 4, 0);
            if (len > 0)
            {
                s.Write(data, 0, len);
                crc = Crc(data, 0, len, crc);
            }
            byte[] tail = { (byte)(crc >> 24), (byte)(crc >> 16), (byte)(crc >> 8), (byte)crc };
            s.Write(tail, 0, 4);
        }

        /// <summary>8-bit RGBA PNG from rows given top row first. Sub filter on every row, zlib by DeflateStream.</summary>
        public static byte[] Encode(int w, int h, byte[] rgbaTopDown)
        {
            int stride = w * 4;
            byte[] raw = new byte[(stride + 1) * h];
            for (int y = 0; y < h; y++)
            {
                int o = y * (stride + 1);
                int src = y * stride;
                raw[o] = 1;   // filter type Sub
                for (int i = 0; i < stride; i++)
                {
                    int left = i >= 4 ? rgbaTopDown[src + i - 4] : 0;
                    raw[o + 1 + i] = (byte)(rgbaTopDown[src + i] - left);
                }
            }
            uint a = 1, b = 0;   // Adler-32 of the raw data
            for (int i = 0; i < raw.Length; i++) { a = (a + raw[i]) % 65521u; b = (b + a) % 65521u; }

            MemoryStream z = new MemoryStream(raw.Length / 2 + 64);
            z.WriteByte(0x78); z.WriteByte(0x9C);
            using (DeflateStream ds = new DeflateStream(z, CompressionMode.Compress, true))
                ds.Write(raw, 0, raw.Length);
            uint ad = (b << 16) | a;
            z.WriteByte((byte)(ad >> 24)); z.WriteByte((byte)(ad >> 16)); z.WriteByte((byte)(ad >> 8)); z.WriteByte((byte)ad);
            byte[] idat = z.ToArray();

            MemoryStream o2 = new MemoryStream(idat.Length + 128);
            byte[] sig = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
            o2.Write(sig, 0, 8);
            byte[] ihdr = { (byte)(w >> 24), (byte)(w >> 16), (byte)(w >> 8), (byte)w, (byte)(h >> 24), (byte)(h >> 16), (byte)(h >> 8), (byte)h, 8, 6, 0, 0, 0 };
            Chunk(o2, "IHDR", ihdr, ihdr.Length);
            Chunk(o2, "IDAT", idat, idat.Length);
            Chunk(o2, "IEND", null, 0);
            return o2.ToArray();
        }
        // END PNG

        /// <summary>Unity reads pixels bottom row first; PNG wants the top row first.</summary>
        public static byte[] FlipRows(byte[] src, int w, int h)
        {
            int stride = w * 4;
            byte[] dst = new byte[src.Length];
            for (int y = 0; y < h; y++) Buffer.BlockCopy(src, y * stride, dst, (h - 1 - y) * stride, stride);
            return dst;
        }

        /// <summary>Fully transparent pixels get RGB 0: the game's atlases keep a light matte color under their transparent texels,
        /// which shows as a white background in any viewer that ignores or mis-blends alpha.</summary>
        public static void ClearHidden(byte[] rgba)
        {
            for (int i = 0; i + 3 < rgba.Length; i += 4)
                if (rgba[i + 3] == 0) { rgba[i] = 0; rgba[i + 1] = 0; rgba[i + 2] = 0; }
        }

        public static void Tint(byte[] rgba, float r, float g, float b, float a)
        {
            for (int i = 0; i + 3 < rgba.Length; i += 4)
            {
                rgba[i] = (byte)Math.Min(255f, rgba[i] * r + 0.5f);
                rgba[i + 1] = (byte)Math.Min(255f, rgba[i + 1] * g + 0.5f);
                rgba[i + 2] = (byte)Math.Min(255f, rgba[i + 2] * b + 0.5f);
                rgba[i + 3] = (byte)Math.Min(255f, rgba[i + 3] * a + 0.5f);
            }
        }

        /// <summary>Area average, weighted by alpha so transparent pixels do not darken the edge.</summary>
        public static byte[] Downscale(byte[] src, int sw, int sh, int dw, int dh)
        {
            byte[] dst = new byte[dw * dh * 4];
            for (int y = 0; y < dh; y++)
            {
                int y0 = y * sh / dh, y1 = Math.Max(y0 + 1, (y + 1) * sh / dh);
                for (int x = 0; x < dw; x++)
                {
                    int x0 = x * sw / dw, x1 = Math.Max(x0 + 1, (x + 1) * sw / dw);
                    float r = 0, g = 0, b = 0, a = 0; int n = 0;
                    for (int yy = y0; yy < y1 && yy < sh; yy++)
                        for (int xx = x0; xx < x1 && xx < sw; xx++)
                        {
                            int i = (yy * sw + xx) * 4;
                            float al = src[i + 3];
                            r += src[i] * al; g += src[i + 1] * al; b += src[i + 2] * al; a += al; n++;
                        }
                    int o = (y * dw + x) * 4;
                    if (a > 0f)
                    {
                        dst[o] = (byte)(r / a + 0.5f); dst[o + 1] = (byte)(g / a + 0.5f); dst[o + 2] = (byte)(b / a + 0.5f);
                        dst[o + 3] = (byte)(a / Math.Max(1, n) + 0.5f);
                    }
                }
            }
            return dst;
        }
    }
}
