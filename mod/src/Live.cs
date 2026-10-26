using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using Database;
using Klei.AI;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// Writes companion/live/live.json (schema: contracts/mod-live.schema.json).
    /// Main thread: gather only, into plain snapshot objects (timed, goes into writeMs). A worker thread serializes
    /// the snapshot, skips unchanged content, and does the file I/O (tmp + rename).
    /// </summary>
    internal static partial class LiveWriter
    {
        private const float MinIntervalS = 1.0f;       // at most once per real second while running normally
        private const float MinForcedGapS = 0.15f;     // burst guard for forced writes
        private const float HeartbeatS = 60f;          // paused or unchanged: still rewrite this often, so readers see the game is there

        private static int seq;
        private static bool wroteRunning;                  // main thread: a running file exists for this session
        private static float lastWriteReal = -100f;
        private static bool forceNext;
        private static bool alertsDirty;
        private static int lastCycle = -1;
        private static bool lastPaused;
        private static int failures;

        // timing log
        private static int timedWrites;
        private static double timedSum, timedMax;

        // alerts
        private static readonly List<Notification> notifications = new List<Notification>();
        private static readonly Dictionary<string, int> alertFirstCycle = new Dictionary<string, int>();

        // I/O worker

        private static string LivePath() { return Path.Combine(Path.Combine(Env.CompanionDir(), "live"), "live.json"); }

        // ------------------------------------------------------------ triggers

        public static void NotificationAdded(Notification n)
        {
            if (Env.Disabled) return;
            try { if (!notifications.Contains(n)) notifications.Add(n); alertsDirty = true; } catch { }
        }

        public static void NotificationRemoved(Notification n)
        {
            if (Env.Disabled) return;
            try { notifications.Remove(n); alertsDirty = true; } catch { }
        }

        public static void MarkSave() { forceNext = true; }

        /// <summary>The notifications the game has delivered (NotificationManager.DoAddNotification), for the alert commands. Main thread only.</summary>
        internal static List<Notification> LiveNotifications() { return notifications; }

        public static bool Ready()
        {
            return Game.Instance != null && !Game.Instance.IsLoading() && SaveLoader.Instance != null && GameClock.Instance != null
                   && ClusterManager.Instance != null && SpeedControlScreen.Instance != null && Db.Get() != null;
        }

        /// <summary>Called every frame from Game.Update (postfix). Cheap unless a write is due.</summary>
        public static void Tick()
        {
            if (Env.Disabled) return;
            try
            {
                if (!Ready()) { curJob = null; return; }
                BuildLiveTick();
                if (curJob != null) { RunJob(); return; }
                if (WarmUp()) return;                        // first frames: compile the gather code, one method per frame
                if (!preWarmDone)
                {
                    if (preWarmJob == null) { StartPreWarm(); }
                    if (preWarmJob != null) { RunPreWarm(); return; }
                }
                float now = Time.unscaledTime;
                int cycle = GameClock.Instance.GetCycle();
                bool paused = SpeedControlScreen.Instance.IsPaused;
                if (Alerts.TakeNeedMore()) alertsDirty = true;      // tooltips left unbuilt by the time box
                bool force = forceNext || alertsDirty || cycle != lastCycle || paused != lastPaused;
                float since = now - lastWriteReal;
                if (force ? since < MinForcedGapS : since < MinIntervalS) return;
                if (!force && paused && wroteRunning && since < HeartbeatS) return;   // nothing moves while paused; the pause itself already forced a write

                forceNext = false; alertsDirty = false; lastCycle = cycle; lastPaused = paused;
                lastWriteReal = now;
                StartJob();
                RunJob();
                failures = 0;
            }
            catch (Exception e)
            {
                curJob = null;
                failures++;
                Log.Error("live write failed (" + failures + ")", e);
                if (failures >= 3) Env.Disable("live.json failed 3 times in a row", e);
            }
        }

        public static void OnUnload()
        {
            try
            {
                notifications.Clear();
                curJob = null; dupeCache.Clear(); critterCache = new Dictionary<int, Dictionary<string, int[]>>(); critterAt = -100f;
                worldNames.Clear(); catalog = new Catalog(); completedAt = -100f; preWarmDone = false; preWarmJob = null;
                alertFirstCycle.Clear(); Alerts.Reset();
                BuildLiveReset();
                wroteRunning = false; lastCycle = -1; lastPaused = false; forceNext = false;
                WriteMenu();
            }
            catch (Exception e) { Log.Error("menu write failed", e); }
        }

        public static void WriteMenu() { WriteState("menu"); }

        /// <summary>The game is quitting (Application.quitting): readers stop showing it as open at once.
        /// A crash writes nothing; readers then go by writtenAt (the menu heartbeat below, the running heartbeat in Tick).</summary>
        public static void WriteStopped()
        {
            stopped = true;
            try { menuHeartbeat?.Dispose(); } catch { }
            WriteState("stopped");
        }

        /// <summary>Main thread sets it in Game.OnSpawn / OnCleanUp: the heartbeat writes "menu" only outside a colony.</summary>
        public static volatile bool InGame;
        private static volatile bool stopped;
        private static System.Threading.Timer menuHeartbeat;
        private const int MenuHeartbeatMs = 60000;      // the same 60 s as the paused heartbeat

        /// <summary>At the main menu nothing else writes live.json: rewrite the menu state every 60 s (worker timer, file I/O only).</summary>
        public static void StartMenuHeartbeat()
        {
            menuHeartbeat = new System.Threading.Timer(_ =>
            {
                try { if (!InGame && !stopped && !Env.Disabled) WriteMenu(); } catch { }
            }, null, MenuHeartbeatMs, MenuHeartbeatMs);
        }

        private static void WriteState(string state)
        {
            lock (ioLock)
            {
                pending = null;   // a queued running write must not land after the menu write
                lastContent = null;
                seq++;
                Json j = new Json(256);
                j.Obj().PI("schema", 2).PI("seq", seq).P("state", state).P("writtenAt", Env.Now()).P("modVersion", Env.ModVersion);
                Env.WriteCompat(j);
                j.EndObj();
                Files.WriteAtomic(LivePath(), j.ToString());
            }
            wroteRunning = false;
        }

        // ------------------------------------------------------------ worker (serialize + I/O)

        private sealed class PostJob { public Snap Snap; public double GatherMs; }

        private static readonly object ioLock = new object();
        private static PostJob pending;            // latest wins
        private static string lastContent;     // worker/ioLock only
        private static System.DateTime lastFileWrite;  // worker/ioLock only
        private static Thread worker;
        private static readonly AutoResetEvent wake = new AutoResetEvent(false);

        private static void Post(PostJob job)
        {
            lock (ioLock) { pending = job; }
            if (worker == null)
            {
                worker = new Thread(WorkerLoop) { IsBackground = true, Name = "OniCompanionLink.io" };
                worker.Start();
            }
            wake.Set();
        }

        private static void WorkerLoop()
        {
            while (true)
            {
                wake.WaitOne();
                try
                {
                    lock (ioLock)
                    {
                        PostJob job = pending; pending = null;
                        if (job == null) continue;
                        Stopwatch sw = Stopwatch.StartNew();
                        string content = Serialize(job.Snap);
                        if (content == lastContent && (System.DateTime.UtcNow - lastFileWrite).TotalSeconds < HeartbeatS) continue;   // nothing changed
                        lastContent = content;
                        lastFileWrite = System.DateTime.UtcNow;
                        seq++;
                        Json j = new Json(content.Length + 256);
                        j.Obj().PI("schema", 2).PI("seq", seq).P("state", "running").P("writtenAt", Env.Now()).P("modVersion", Env.ModVersion);
                        Env.WriteCompat(j);
                        j.P("writeMs", Math.Round(job.GatherMs, 3));
                        j.Raw(content);
                        j.EndObj();
                        string text = j.ToString();
                        double serMs = sw.Elapsed.TotalMilliseconds;
                        Files.WriteAtomic(LivePath(), text);
                        workerWrites++; workerSerSum += serMs; workerTotSum += sw.Elapsed.TotalMilliseconds;
                    }
                }
                catch (Exception e) { Log.Error("live serialize/file I/O failed", e); }
            }
        }
        private static int workerWrites;
        private static double workerSerSum, workerTotSum;

        // ------------------------------------------------------------ snapshot types (plain data, no game objects)

        private sealed class Gauge { public double Value, Max; }
        private sealed class DupeSnap
        {
            public string Id, Name, Chore, AssignedSkill;
            public double Stress;
            public Gauge Health, Calories, Breath;
            public bool HasBladder; public double Bladder;
            public bool HasMorale; public double MoraleValue, MoraleRequired;
            public List<string> Skills, Traits;
            // schema 2
            public string AppearanceHash;
            public List<StatusSnap> StatusItems = new List<StatusSnap>();
            public List<KeyValuePair<string, string>> Diseases = new List<KeyValuePair<string, string>>();   // id, name
            public Gauge Stamina;                                                                             // null when the duplicant has none
            public bool HasBodyTemp; public double BodyTempC;
            public List<AttrSnap> Attributes = new List<AttrSnap>();
        }
        private sealed class StatusSnap { public string Id, Name, Severity; }
        private sealed class AttrSnap { public string Id, Name; public double Value; }
        private sealed class ResSnap { public string Id, Name, Category, Unit; public double Amount; public double Kcal = -1; }
        private sealed class CritterSnap { public string Id; public int Count, Tame; }
        private sealed class AlertSnap { public string Id, Level, Text; public int Cycle, Count; public Alerts.Info Info; }
        private sealed class TechSnap { public string Tech; public List<KeyValuePair<string, double>> Points, Cost; }
        private sealed class ResearchSnap { public TechSnap Current; public List<TechSnap> Queue = new List<TechSnap>(); public List<string> Completed = new List<string>(); }
        private sealed class WorldSnap
        {
            public int Id; public string Name; public bool IsStarter;
            public List<DupeSnap> Dupes = new List<DupeSnap>();
            public List<ResSnap> Resources = new List<ResSnap>();
            public List<CritterSnap> Critters = new List<CritterSnap>();
            public List<AlertSnap> Alerts = new List<AlertSnap>();
            public ResearchSnap Research;
            public Dictionary<string, double> Stock;      // v1.3 (LiveBuild.cs)
        }
        private sealed class Snap
        {
            public int Build; public List<string> Dlc; public string ColonyName, ColonyGuid;
            public int Cycle; public double TimeOfDay; public bool Paused; public int Speed, ActiveWorldId;
            public Actions.PadState Pad;
            public List<WorldSnap> Worlds = new List<WorldSnap>();
            public List<string> Unlocked;                  // v1.3 (LiveBuild.cs)
        }


        // ------------------------------------------------------------ gather (main thread, time-sliced)
        //
        // One write = one Job: a queue of small steps. Each frame runs steps until FrameBudgetMs is used up (a step is never split,
        // so every step is kept small: one duplicant part, one resource category, one chunk of creatures). The snapshot is posted
        // to the worker when the queue is empty. What does not change often is cached (component lookups per duplicant, skill and
        // attribute lists, status item names, the resource category list) and refreshed on a slower clock.

        private const double FrameBudgetMs = 1.2;       // soft: stop starting new steps once a frame has used this much
        private const double StepWarnMs = 2.0;          // a single step above this is logged by name
        private const float SlowRefreshS = 8f;          // skills, traits, attributes, diseases, appearance, name
        private const float DynamicStatusRefreshS = 3f; // status items whose text carries live numbers
        private const float CritterRefreshS = 3f;
        private const float CatalogRefreshS = 20f;
        private const float ResearchDoneRefreshS = 15f;
        private const int CritterChunk = 150, EdibleChunk = 8;

        private sealed class Step { public string Section; public System.Action Run; }

        private sealed class Job
        {
            public readonly Queue<Step> Steps = new Queue<Step>();
            public Snap S = new Snap();
            public double GatherMs;                 // sum of the step times (main thread CPU for this write)
            public int Frames;
            public Dictionary<int, List<MinionIdentity>> Dupes = new Dictionary<int, List<MinionIdentity>>();
            public Dictionary<int, Dictionary<string, int[]>> Critters;
            public ResearchSnap Research;
            public Dictionary<int, List<AlertSnap>> Alerts;
        }

        private static Job curJob;
        private static int warmIdx;
        private static System.Reflection.MethodInfo[] warmMethods;

        // timing log: per frame and per section
        private static int frames; private static double frameSum, frameMax; private static int frameOver2, frameOver4;
        private sealed class SecStat { public double Sum, Max; public int N; }
        private static readonly Dictionary<string, SecStat> secStats = new Dictionary<string, SecStat>();
        private static readonly List<string> secOrder = new List<string>();

        private static void Enq(Job j, string section, System.Action run) { j.Steps.Enqueue(new Step { Section = section, Run = run }); }

        /// <summary>Compiles the gather methods one per frame before the first write, so the JIT does not land in one frame.</summary>
        private static bool WarmUp()
        {
            if (warmMethods == null)
            {
                try
                {
                    System.Reflection.MethodInfo[] all = typeof(LiveWriter).GetMethods(System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public |
                                                                                     System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.DeclaredOnly);
                    List<System.Reflection.MethodInfo> ok = new List<System.Reflection.MethodInfo>();
                    foreach (System.Reflection.MethodInfo m in all) if (!m.IsGenericMethod && !m.IsAbstract) ok.Add(m);
                    warmMethods = ok.ToArray();
                }
                catch { warmMethods = new System.Reflection.MethodInfo[0]; }
                Log.Info("live: warming up " + warmMethods.Length + " methods, one per frame, before the first write");
            }
            if (warmIdx >= warmMethods.Length) return false;
            try { System.Runtime.CompilerServices.RuntimeHelpers.PrepareMethod(warmMethods[warmIdx].MethodHandle); } catch { }
            warmIdx++;
            return true;
        }

        // ---- pre-warm after a colony load: fills the caches the first write would otherwise fill in a few big steps
        // (catalog, names, kcal table, first component lookups on food, first inventory reads), a few items per frame.
        private static bool preWarmDone;
        private static Job preWarmJob;
        private const int WarmNameChunk = 6, WarmEdibleChunk = 3, WarmAmountChunk = 6;

        private static void StartPreWarm()
        {
            Job j = new Job();
            preWarmJob = j;
            Enq(j, "prewarm names", delegate ()
            {
                List<Tag> cats = new List<Tag>();
                foreach (Tag t in GameTags.MaterialCategories) cats.Add(t);
                foreach (Tag t in GameTags.CalorieCategories) cats.Add(t);
                foreach (Tag t in GameTags.UnitCategories) cats.Add(t);
                List<Step> steps = new List<Step>();
                for (int from = 0; from < cats.Count; from += WarmNameChunk)
                {
                    int a = from, b = Math.Min(cats.Count, from + WarmNameChunk);
                    steps.Add(new Step { Section = "prewarm names", Run = delegate () { for (int i = a; i < b; i++) ProperName(cats[i]); } });
                }
                steps.Add(CatalogStep(j));
                steps.Add(new Step { Section = "prewarm items", Run = delegate () { PreWarmItems(j); } });
                PushFront(j, steps);
            });
        }

        private static void PreWarmItems(Job j)
        {
            List<Step> steps = new List<Step>();
            List<Tag> items = new List<Tag>();
            foreach (Tag c in catalog.Order) items.AddRange(catalog.Items[c]);
            for (int from = 0; from < items.Count; from += WarmNameChunk)
            {
                int a = from, b = Math.Min(items.Count, from + WarmNameChunk);
                steps.Add(new Step { Section = "prewarm items", Run = delegate ()
                {
                    for (int i = a; i < b; i++)
                    {
                        Tag item = items[i];
                        ProperName(item);
                        float per;
                        if (!kcalPerUnit.TryGetValue(item, out per))
                        {
                            EdiblesManager.FoodInfo fi = EdiblesManager.GetFoodInfo(item.Name);
                            per = fi != null ? fi.CaloriesPerUnit / 1000f : -1f;
                            kcalPerUnit[item] = per;
                        }
                    }
                } });
            }
            // first inventory reads and first Edible lookups on the first world that has an inventory
            WorldInventory inv = null;
            foreach (WorldContainer wc in ClusterManager.Instance.WorldContainers)
                if (wc != null && wc.IsDiscovered && !wc.IsModuleInterior && wc.worldInventory != null && wc.worldInventory.HasValidCount) { inv = wc.worldInventory; break; }
            if (inv != null)
            {
                WorldInventory winv = inv;
                for (int from = 0; from < items.Count; from += WarmAmountChunk)
                {
                    int a = from, b = Math.Min(items.Count, from + WarmAmountChunk);
                    steps.Add(new Step { Section = "prewarm amounts", Run = delegate () { for (int i = a; i < b; i++) winv.GetAmount(items[i], false); } });
                }
                List<Pickupable> ed = new List<Pickupable>();
                steps.Add(new Step { Section = "prewarm edibles", Run = delegate ()
                {
                    ICollection<Pickupable> e = winv.GetPickupables(GameTags.Edible);
                    if (e != null) ed.AddRange(e);
                    int cnt = Math.Min(ed.Count, 24);
                    List<Step> more = new List<Step>();
                    for (int from = 0; from < cnt; from += WarmEdibleChunk)
                    {
                        int a = from, b = Math.Min(cnt, from + WarmEdibleChunk);
                        more.Add(new Step { Section = "prewarm edibles", Run = delegate ()
                        {
                            for (int i = a; i < b; i++)
                            {
                                Pickupable p = ed[i];
                                if (p == null || p.KPrefabID.HasTag(GameTags.StoredPrivate)) continue;
                                Edible x = p.GetComponent<Edible>();
                                if (x != null) { string id = x.FoodID; float c = x.Calories; }
                            }
                        } });
                    }
                    PushFront(j, more);
                } });
            }
            PushFront(j, steps);
        }

        private static void RunPreWarm()
        {
            Job j = preWarmJob;
            Stopwatch fsw = Stopwatch.StartNew();
            int n = 0;
            while (j.Steps.Count > 0)
            {
                Step st = j.Steps.Dequeue();
                Stopwatch ssw = Stopwatch.StartNew();
                try { st.Run(); } catch (Exception ex) { Log.Warn("live prewarm step '" + st.Section + "' skipped: " + ex.GetType().Name + ": " + ex.Message); }
                double ms = ssw.Elapsed.TotalMilliseconds;
                AddSection(st.Section, ms);
                if (ms > StepWarnMs) Log.Warn("live: prewarm step '" + st.Section + "' took " + ms.ToString("0.0") + " ms");
                n++; j.GatherMs += ms;
                if (fsw.Elapsed.TotalMilliseconds >= FrameBudgetMs) break;
            }
            j.Frames++;
            if (j.Steps.Count == 0)
            {
                preWarmDone = true; preWarmJob = null;
                Log.Info("live: pre-warm done in " + j.Frames + " frames, " + j.GatherMs.ToString("0.0") + " ms of work, " + catalog.Order.Count + " categories");
            }
        }

        private static void StartJob()
        {
            Job j = new Job();
            curJob = j;
            Enq(j, "head", delegate () { StepHead(j); });
        }

        /// <summary>Runs steps for this frame. Returns after the budget is used or the job is done (then the snapshot goes to the worker).</summary>
        private static void RunJob()
        {
            Job j = curJob;
            Stopwatch fsw = Stopwatch.StartNew();
            while (j.Steps.Count > 0)
            {
                Step st = j.Steps.Dequeue();
                Stopwatch ssw = Stopwatch.StartNew();
                st.Run();
                double ms = ssw.Elapsed.TotalMilliseconds;
                j.GatherMs += ms;
                AddSection(st.Section, ms);
                if (ms > StepWarnMs) Log.Warn("live: step '" + st.Section + "' took " + ms.ToString("0.0") + " ms (target " + StepWarnMs + " ms)");
                if (fsw.Elapsed.TotalMilliseconds >= FrameBudgetMs) break;
            }
            j.Frames++;
            double fms = fsw.Elapsed.TotalMilliseconds;
            frames++; frameSum += fms; if (fms > frameMax) frameMax = fms; if (fms > 2.0) frameOver2++; if (fms > 4.0) frameOver4++;
            if (j.Steps.Count == 0) FinishJob(j);
        }

        private static void AddSection(string name, double ms)
        {
            SecStat s;
            if (!secStats.TryGetValue(name, out s)) { s = new SecStat(); secStats[name] = s; secOrder.Add(name); }
            s.Sum += ms; s.N++; if (ms > s.Max) s.Max = ms;
        }

        private static void FinishJob(Job j)
        {
            curJob = null;
            Post(new PostJob { Snap = j.S, GatherMs = j.GatherMs });
            wroteRunning = true;
            timedWrites++; timedSum += j.GatherMs; if (j.GatherMs > timedMax) timedMax = j.GatherMs;
            if (timedWrites == 1 || timedWrites % 60 == 0)
            {
                System.Text.StringBuilder sb = new System.Text.StringBuilder();
                foreach (string n in secOrder) { SecStat s = secStats[n]; sb.Append(n).Append(' ').Append((s.Sum / Math.Max(1, timedWrites)).ToString("0.00")).Append('/').Append(s.Max.ToString("0.00")).Append("; "); }
                Log.Info("live timing (main thread, per frame, gather only): frames " + frames + ", avg " + (frameSum / Math.Max(1, frames)).ToString("0.00") +
                         " ms, max " + frameMax.ToString("0.00") + " ms, frames over 2 ms " + frameOver2 + ", over 4 ms " + frameOver4 +
                         "; per write: writes " + timedWrites + ", this " + j.GatherMs.ToString("0.00") + " ms over " + j.Frames + " frames, avg " +
                         (timedSum / timedWrites).ToString("0.00") + " ms, max " + timedMax.ToString("0.00") + " ms" +
                         "; per section avg-per-write/max-step ms: " + sb.ToString() +
                         "worker (serialize + I/O, off main thread): " + workerWrites + " files, avg " +
                         (workerWrites > 0 ? (workerTotSum / workerWrites).ToString("0.00") : "n/a") + " ms");
            }
        }

        // ---- head: header fields, grouping of duplicants, then the sections in order

        private static void StepHead(Job j)
        {
            Snap s = j.S;
            s.Build = Env.Build();
            s.Dlc = new List<string>();
            try
            {
                if (SaveLoader.Instance.GameInfo.dlcIds != null)
                    foreach (string d in SaveLoader.Instance.GameInfo.dlcIds)
                        if (!string.IsNullOrEmpty(d)) s.Dlc.Add(d);   // base game is stored as "" by the game; schema says empty list = base
            }
            catch { }
            s.Dlc.Sort(StringComparer.Ordinal);
            s.ColonyName = Txt.Clean(SaveLoader.Instance.GameInfo.baseName);
            s.ColonyGuid = SaveLoader.Instance.GameInfo.colonyGuid.ToString();
            s.Cycle = GameClock.Instance.GetCycle() + 1;
            s.TimeOfDay = GameClock.Instance.GetCurrentCycleAsPercentage();
            s.Paused = SpeedControlScreen.Instance.IsPaused;
            s.Speed = Math.Max(1, Math.Min(3, SpeedControlScreen.Instance.GetSpeed() + 1));
            s.ActiveWorldId = ClusterManager.Instance.activeWorldId;
            s.Pad = Actions.Capture();

            foreach (MinionIdentity m in Components.LiveMinionIdentities.Items)
            {
                if (m == null) continue;
                int w = m.GetMyWorldId();
                List<MinionIdentity> l;
                if (!j.Dupes.TryGetValue(w, out l)) { l = new List<MinionIdentity>(); j.Dupes[w] = l; }
                l.Add(m);
            }
            PruneDupeCache();

            StartCritters(j);
            Enq(j, "research", delegate () { j.Research = GatherResearch(); });
            Enq(j, "alerts", delegate () { j.Alerts = GatherAlerts(); });
            Enq(j, "build unlocked", delegate () { BuildUnlockedStep(j); });
            Enq(j, "worlds", delegate () { StepWorlds(j); });
        }

        // ---- creatures: counted in chunks, and only every CritterRefreshS (the counts barely move)

        private static Dictionary<int, Dictionary<string, int[]>> critterCache = new Dictionary<int, Dictionary<string, int[]>>();
        private static float critterAt = -100f;

        private static void StartCritters(Job j)
        {
            float now = Time.unscaledTime;
            if (now - critterAt < CritterRefreshS) { j.Critters = critterCache; return; }
            critterAt = now;
            List<Brain> brains = new List<Brain>(Components.Brains.Items);
            Dictionary<int, Dictionary<string, int[]>> acc = new Dictionary<int, Dictionary<string, int[]>>();
            for (int from = 0; from < brains.Count; from += CritterChunk)
            {
                int a = from, b = Math.Min(brains.Count, from + CritterChunk);
                bool last = b >= brains.Count;
                Enq(j, "critters", delegate ()
                {
                    for (int i = a; i < b; i++)
                    {
                        CreatureBrain cb = brains[i] as CreatureBrain;
                        if (cb == null) continue;
                        try
                        {
                            int w = cb.GetMyWorldId();
                            Dictionary<string, int[]> d;
                            if (!acc.TryGetValue(w, out d)) { d = new Dictionary<string, int[]>(); acc[w] = d; }
                            string id = cb.PrefabID().Name;
                            int[] c;
                            if (!d.TryGetValue(id, out c)) { c = new int[2]; d[id] = c; }
                            c[0]++;
                            if (!cb.HasTag(GameTags.Creatures.Wild)) c[1]++;
                        }
                        catch { }
                    }
                    if (last) { critterCache = acc; j.Critters = acc; }
                });
            }
            if (brains.Count == 0) { critterCache = acc; j.Critters = acc; }
            // a job must see a result even though the chunks run later: the worlds step runs after them
            Enq(j, "critters", delegate () { if (j.Critters == null) j.Critters = critterCache; });
        }

        // ---- worlds: queue the per-world sections

        private static void StepWorlds(Job j)
        {
            foreach (WorldContainer wc in ClusterManager.Instance.WorldContainers)
            {
                if (wc == null || !wc.IsDiscovered || wc.IsModuleInterior) continue;
                WorldSnap w = new WorldSnap { Id = wc.id, Name = WorldNameCached(wc), IsStarter = wc.IsStartWorld, Research = j.Research };
                j.S.Worlds.Add(w);
                WorldContainer world = wc;

                List<MinionIdentity> dl;
                if (j.Dupes.TryGetValue(wc.id, out dl))
                    foreach (MinionIdentity m in dl) QueueDupe(j, w, m);

                QueueResources(j, world, w);
                QueueStock(j, world, w);

                Enq(j, "world rest", delegate ()
                {
                    Dictionary<string, int[]> cd;
                    if (j.Critters != null && j.Critters.TryGetValue(world.id, out cd))
                    {
                        List<string> ids = new List<string>(cd.Keys);
                        ids.Sort(StringComparer.Ordinal);
                        foreach (string id in ids) w.Critters.Add(new CritterSnap { Id = id, Count = cd[id][0], Tame = cd[id][1] });
                    }
                    List<AlertSnap> al;
                    if (j.Alerts != null && j.Alerts.TryGetValue(world.id, out al)) w.Alerts = al;
                });
            }
        }

        private static readonly Dictionary<int, KeyValuePair<string, float>> worldNames = new Dictionary<int, KeyValuePair<string, float>>();

        private static string WorldNameCached(WorldContainer wc)
        {
            KeyValuePair<string, float> kv;
            float now = Time.unscaledTime;
            if (worldNames.TryGetValue(wc.id, out kv) && now - kv.Value < SlowRefreshS) return kv.Key;
            string n = WorldName(wc);
            worldNames[wc.id] = new KeyValuePair<string, float>(n, now);
            return n;
        }

        // ---- duplicants

        private sealed class DupeCache
        {
            public GameObject Go; public string Id;
            public ChoreDriver Driver; public MinionResume Resume; public Traits TraitsC; public KSelectable Sel; public Klei.AI.Attributes Attrs;
            public AmountInstance Stress, Bladder, Breath, Hp, Cal, Stamina, Temp;
            public AttributeInstance Q, Qe;
            public ChoreType Idle;
            // slow data
            public float SlowAt = -100f; public int SlowCycle = -1;
            public string Name, AssignedSkill, AppearanceHash;
            public List<string> Skills = new List<string>(), Traits = new List<string>();
            public List<KeyValuePair<string, string>> Diseases = new List<KeyValuePair<string, string>>();
            public List<AttrSnap> Attributes = new List<AttrSnap>();
            // status items
            public float StatusAt = -100f; public int StatusSig = int.MinValue; public bool StatusDynamic;
            public List<StatusSnap> Status = new List<StatusSnap>();
        }

        private static readonly Dictionary<MinionIdentity, DupeCache> dupeCache = new Dictionary<MinionIdentity, DupeCache>();
        private static int pruneCounter;

        private static void PruneDupeCache()
        {
            if (++pruneCounter % 30 != 0) return;
            List<MinionIdentity> dead = null;
            foreach (MinionIdentity m in dupeCache.Keys) if (m == null) { if (dead == null) dead = new List<MinionIdentity>(); dead.Add(m); }
            if (dead != null) foreach (MinionIdentity m in dead) dupeCache.Remove(m);
        }

        private static DupeCache CacheFor(MinionIdentity m)
        {
            DupeCache c;
            if (dupeCache.TryGetValue(m, out c)) return c;
            c = new DupeCache();
            GameObject go = m.gameObject;
            Database.Amounts a = Db.Get().Amounts;
            c.Go = go;
            c.Id = go.GetComponent<KPrefabID>().InstanceID.ToString();
            c.Driver = go.GetComponent<ChoreDriver>();
            c.Resume = go.GetComponent<MinionResume>();
            c.TraitsC = go.GetComponent<Traits>();
            c.Sel = go.GetComponent<KSelectable>();
            c.Attrs = go.GetAttributes();
            c.Stress = a.Stress.Lookup(go);
            c.Bladder = a.Bladder.Lookup(go);
            c.Breath = a.Breath.Lookup(go) ?? a.BionicOxygenTank.Lookup(go);
            c.Hp = a.HitPoints.Lookup(go);
            c.Cal = a.Calories.Lookup(go);
            c.Stamina = a.Stamina.Lookup(go);
            c.Temp = a.Temperature.Lookup(go);
            if (c.Attrs != null)
            {
                c.Q = c.Attrs.Get(Db.Get().Attributes.QualityOfLife);
                c.Qe = c.Attrs.Get(Db.Get().Attributes.QualityOfLifeExpectation);
            }
            c.Idle = Db.Get().ChoreTypes.Idle;
            dupeCache[m] = c;
            return c;
        }

        private static Gauge GatherGauge(AmountInstance ai, float scale = 1f)
        {
            return new Gauge { Value = ai != null ? ai.value * scale : 0.0, Max = ai != null ? ai.GetMax() * scale : 0.0 };
        }

        private static void QueueDupe(Job j, WorldSnap w, MinionIdentity m)
        {
            DupeSnap d = new DupeSnap();
            DupeCache c = null;
            Enq(j, "dupe fast", delegate ()
            {
                try
                {
                    c = CacheFor(m);
                    d.Id = c.Id;
                    d.Name = c.Name ?? "";
                    d.Stress = c.Stress != null ? Math.Max(0f, Math.Min(100f, c.Stress.value)) : 0.0;
                    d.Health = GatherGauge(c.Hp);
                    d.Calories = GatherGauge(c.Cal, 0.001f);   // game calories -> kcal
                    d.Breath = GatherGauge(c.Breath);
                    if (c.Bladder != null) { d.HasBladder = true; d.Bladder = Math.Max(0f, Math.Min(100f, c.Bladder.value)); }
                    if (c.Q != null && c.Qe != null) { d.HasMorale = true; d.MoraleValue = c.Q.GetTotalValue(); d.MoraleRequired = c.Qe.GetTotalValue(); }
                    Chore ch = c.Driver != null ? c.Driver.GetCurrentChore() : null;
                    if (ch != null && ch.choreType != null && ch.choreType != c.Idle) d.Chore = Txt.Clean(ch.choreType.Name);
                    if (c.Stamina != null) d.Stamina = GatherGauge(c.Stamina);
                    if (c.Temp != null) { d.HasBodyTemp = true; d.BodyTempC = Math.Round(Txt.C(c.Temp.value), 1); }
                    d.Skills = c.Skills; d.Traits = c.Traits; d.AssignedSkill = c.AssignedSkill; d.AppearanceHash = c.AppearanceHash;
                    d.Diseases = c.Diseases; d.Attributes = c.Attributes; d.StatusItems = c.Status;
                    w.Dupes.Add(d);
                }
                catch (Exception e) { Log.Warn("skipped a duplicant: " + e.GetType().Name + ": " + e.Message); c = null; }
            });
            QueueStatus(j, d, delegate () { return c; });
            QueueSlow(j, m, d, delegate () { return c; });
        }

        // The game's own severity for a status item is StatusItem.notificationType (the value its constructor was given).
        // Mapping follows how the game itself groups them in SimpleInfoScreen.DoAddStatusItem: Bad, DuplicantThreatening
        // and BadMinor are the "bad" group there; the contract keeps Bad (and threatening) apart from BadMinor.
        private static string Severity(NotificationType t)
        {
            switch (t)
            {
                case NotificationType.Bad:
                case NotificationType.DuplicantThreatening: return "bad";
                case NotificationType.BadMinor: return "minorBad";
                case NotificationType.Good: return "good";
                default: return "neutral";   // Neutral, Event, Tutorial, Messages, MessageImportant, Custom
            }
        }

        // Status item names: an item without a resolve callback has one fixed name per session (cached by item id); one with a
        // callback carries live numbers and is re-read every DynamicStatusRefreshS. The group's set of entries (their Guids) is
        // compared first; the list is rebuilt only when the set changed or a dynamic name is due.
        private static readonly Dictionary<string, string> staticStatusNames = new Dictionary<string, string>();

        private const int StatusChunk = 3, AttrChunk = 6, SlotChunk = 4, CatalogChunk = 4, ResChunk = 8;

        /// <summary>Status items in small steps: one step compares the entry set, then a few entries per step are named.</summary>
        private static void QueueStatus(Job j, DupeSnap d, System.Func<DupeCache> get)
        {
            Enq(j, "dupe status", delegate ()
            {
                DupeCache c = get();
                if (c == null) return;
                try
                {
                    StatusItemGroup group = c.Sel != null ? c.Sel.GetStatusItemGroup() : null;
                    if (group == null) return;
                    int sig = 17;
                    List<StatusItemGroup.Entry> entries = new List<StatusItemGroup.Entry>();
                    IEnumerator<StatusItemGroup.Entry> en = group.GetEnumerator();
                    while (en.MoveNext()) { sig = sig * 31 + en.Current.id.GetHashCode(); entries.Add(en.Current); }
                    float now = Time.unscaledTime;
                    if (sig == c.StatusSig && (!c.StatusDynamic || now - c.StatusAt < DynamicStatusRefreshS)) return;
                    List<StatusSnap> list = new List<StatusSnap>(entries.Count);
                    bool dyn = false;
                    List<Step> steps = new List<Step>();
                    for (int from = 0; from < entries.Count; from += StatusChunk)
                    {
                        int a = from, b = Math.Min(entries.Count, from + StatusChunk);
                        steps.Add(new Step { Section = "dupe status", Run = delegate ()
                        {
                            for (int i = a; i < b; i++)
                            {
                                StatusItemGroup.Entry e = entries[i];
                                try
                                {
                                    if (e.item == null || e.item.showInHoverCardOnly) continue;   // the details panel skips hover-card-only items too
                                    string name;
                                    if (e.item.resolveStringCallback == null)
                                    {
                                        if (!staticStatusNames.TryGetValue(e.item.Id, out name)) { name = Txt.Clean(e.GetName()); staticStatusNames[e.item.Id] = name; }
                                    }
                                    else { dyn = true; name = Txt.Clean(e.GetName()); }
                                    if (name.Length == 0) continue;
                                    list.Add(new StatusSnap { Id = e.item.Id, Name = name, Severity = Severity(e.item.notificationType) });
                                }
                                catch (Exception ex) { Log.Warn("skipped a status item: " + ex.GetType().Name); }
                            }
                        } });
                    }
                    steps.Add(new Step { Section = "dupe status", Run = delegate ()
                    {
                        c.Status = list; c.StatusSig = sig; c.StatusDynamic = dyn; c.StatusAt = now;
                        d.StatusItems = c.Status;
                    } });
                    PushFront(j, steps);
                }
                catch (Exception e) { Log.Warn("status items skipped: " + e.GetType().Name + ": " + e.Message); }
            });
        }

        /// <summary>The slow details (name, skills, traits, appearance, diseases, attributes) as separate small steps, only when due.</summary>
        private static void QueueSlow(Job j, MinionIdentity m, DupeSnap d, System.Func<DupeCache> get)
        {
            Enq(j, "dupe slow", delegate ()
            {
                DupeCache c = get();
                if (c == null) return;
                try
                {
                    int cycle = j.S.Cycle;
                    if (Time.unscaledTime - c.SlowAt < SlowRefreshS && c.SlowCycle == cycle) return;
                    c.SlowAt = Time.unscaledTime; c.SlowCycle = cycle;
                    GameObject go = c.Go;
                    List<Step> steps = new List<Step>();
                    string name = null, assigned = null, hash = c.AppearanceHash;
                    List<string> skills = null, traits = null;
                    List<KeyValuePair<string, string>> diseases = null;
                    List<AttrSnap> attrs = new List<AttrSnap>();
                    steps.Add(new Step { Section = "dupe name", Run = delegate () { name = Txt.Clean(m.GetProperName()); } });
                    steps.Add(new Step { Section = "dupe skills", Run = delegate ()
                    {
                        List<string> sk = new List<string>();
                        if (c.Resume != null)
                        {
                            foreach (KeyValuePair<string, bool> kv in c.Resume.MasteryBySkillID) if (kv.Value) sk.Add(kv.Key);
                            sk.Sort(StringComparer.Ordinal);
                        }
                        skills = sk;
                        assigned = c.Resume != null ? c.Resume.CurrentRole : null;
                    } });
                    steps.Add(new Step { Section = "dupe traits", Run = delegate ()
                    {
                        traits = c.TraitsC != null ? new List<string>(c.TraitsC.GetTraitIds()) : new List<string>();
                    } });
                    // appearance hash: a few accessory slots per step
                    uint h = 2166136261u;
                    List<AccessorySlot> slots = new List<AccessorySlot>();
                    Accessorizer acc = null;
                    steps.Add(new Step { Section = "dupe appearance", Run = delegate ()
                    {
                        try
                        {
                            acc = go.GetComponent<Accessorizer>();
                            if (acc != null) foreach (AccessorySlot slot in Db.Get().AccessorySlots.resources) slots.Add(slot);
                        }
                        catch (Exception e) { Log.Warn("appearance hash failed: " + e.GetType().Name); }
                    } });
                    // the number of slots is only known when the step above has run, so the slot steps queue themselves
                    steps.Add(new Step { Section = "dupe appearance", Run = delegate ()
                    {
                        List<Step> more = new List<Step>();
                        for (int from = 0; from < slots.Count; from += SlotChunk)
                        {
                            int sa = from, sb = Math.Min(slots.Count, from + SlotChunk);
                            more.Add(new Step { Section = "dupe appearance", Run = delegate ()
                            {
                                for (int i = sa; i < sb; i++) { Accessory a = acc.GetAccessory(slots[i]); h = Fnv(h, a != null ? a.Id : "-"); }
                            } });
                        }
                        more.Add(new Step { Section = "dupe appearance", Run = delegate ()
                        {
                            try
                            {
                                MinionResume resume = go.GetComponent<MinionResume>();
                                h = Fnv(h, "|hat:" + (resume != null ? resume.CurrentHat : ""));
                                WearableAccessorizer wear = go.GetComponent<WearableAccessorizer>();
                                if (wear != null)
                                {
                                    string[] ids = wear.GetClothingItemsIds(ClothingOutfitUtility.OutfitType.Clothing);
                                    if (ids != null) foreach (string id in ids) h = Fnv(h, "|c:" + id);
                                }
                                if (acc != null) hash = h.ToString("x8");
                            }
                            catch (Exception e) { Log.Warn("appearance hash failed: " + e.GetType().Name); }
                        } });
                        PushFront(j, more);
                    } });
                    steps.Add(new Step { Section = "dupe diseases", Run = delegate () { diseases = GatherDiseases(go); } });
                    steps.Add(new Step { Section = "dupe attributes", Run = delegate ()
                    {
                        List<AttrSnap> r = new List<AttrSnap>();
                        Klei.AI.Attributes at = c.Attrs;
                        if (at != null)
                        {
                            List<AttributeInstance> table = new List<AttributeInstance>(at.AttributeTable);
                            List<Step> more = new List<Step>();
                            for (int from = 0; from < table.Count; from += AttrChunk)
                            {
                                int aa = from, ab = Math.Min(table.Count, from + AttrChunk);
                                more.Add(new Step { Section = "dupe attributes", Run = delegate () { GatherAttributesChunk(table, aa, ab, r); } });
                            }
                            more.Add(new Step { Section = "dupe attributes", Run = delegate ()
                            {
                                r.Sort(delegate (AttrSnap x, AttrSnap y) { return string.Compare(x.Name, y.Name, StringComparison.CurrentCulture); });
                                attrs = r;
                            } });
                            PushFront(j, more);
                        }
                    } });
                    steps.Add(new Step { Section = "dupe slow", Run = delegate ()
                    {
                        c.Name = name; c.Skills = skills ?? new List<string>(); c.Traits = traits ?? new List<string>(); c.AssignedSkill = assigned;
                        if (hash != null) c.AppearanceHash = hash;
                        c.Diseases = diseases ?? new List<KeyValuePair<string, string>>(); c.Attributes = attrs;
                        d.Name = c.Name; d.Skills = c.Skills; d.Traits = c.Traits; d.AssignedSkill = c.AssignedSkill; d.AppearanceHash = c.AppearanceHash;
                        d.Diseases = c.Diseases; d.Attributes = c.Attributes;
                    } });
                    PushFront(j, steps);
                }
                catch (Exception e) { Log.Warn("duplicant details skipped: " + e.GetType().Name + ": " + e.Message); }
            });
        }

        private static List<KeyValuePair<string, string>> GatherDiseases(GameObject go)
        {
            List<KeyValuePair<string, string>> r = new List<KeyValuePair<string, string>>();
            Klei.AI.Sicknesses sick = go.GetSicknesses();
            if (sick == null) return r;
            for (int i = 0; i < sick.ModifierList.Count; i++)
            {
                SicknessInstance si = sick.ModifierList[i];
                if (si == null || si.modifier == null) continue;
                r.Add(new KeyValuePair<string, string>(si.modifier.Id, Txt.Clean(si.modifier.Name)));
            }
            return r;
        }

        // The skill attributes the game lists for a duplicant (CharacterContainer.SetAttributes): ShowInUI == Skill, ordered by name.
        private static readonly Dictionary<string, string> attrNames = new Dictionary<string, string>();

        private static void GatherAttributesChunk(List<AttributeInstance> table, int from, int to, List<AttrSnap> r)
        {
            for (int i = from; i < to; i++)
            {
                AttributeInstance ai = table[i];
                if (ai == null || ai.Attribute == null || ai.Attribute.ShowInUI != Klei.AI.Attribute.Display.Skill) continue;
                string name;
                if (!attrNames.TryGetValue(ai.Id, out name)) { name = Txt.Clean(ai.Name); attrNames[ai.Id] = name; }
                r.Add(new AttrSnap { Id = ai.Id, Name = name, Value = Math.Round(ai.GetTotalValue(), 2) });
            }
        }

        // FNV-1a over everything the portrait is drawn from: all accessories (hair, face, body parts), the hat, the clothing outfit.
        private static string AppearanceHash(GameObject go)
        {
            uint h = 2166136261u;
            Accessorizer acc = go.GetComponent<Accessorizer>();
            if (acc != null)
            {
                foreach (AccessorySlot slot in Db.Get().AccessorySlots.resources)
                {
                    Accessory a = acc.GetAccessory(slot);
                    h = Fnv(h, a != null ? a.Id : "-");
                }
            }
            MinionResume resume = go.GetComponent<MinionResume>();
            h = Fnv(h, "|hat:" + (resume != null ? resume.CurrentHat : ""));
            WearableAccessorizer wear = go.GetComponent<WearableAccessorizer>();
            if (wear != null)
            {
                string[] ids = wear.GetClothingItemsIds(ClothingOutfitUtility.OutfitType.Clothing);
                if (ids != null) foreach (string id in ids) h = Fnv(h, "|c:" + id);
            }
            return h.ToString("x8");
        }

        private static uint Fnv(uint h, string s)
        {
            for (int i = 0; i < s.Length; i++) { h ^= s[i]; h *= 16777619u; }
            return h;
        }

        // ------------------------------------------------------------ resources (the game's Resources panel: AllResourcesScreen)

        private static readonly Dictionary<Tag, string> properNames = new Dictionary<Tag, string>();
        private static readonly Dictionary<Tag, float> kcalPerUnit = new Dictionary<Tag, float>();

        private static string ProperName(Tag t)
        {
            string n;
            if (!properNames.TryGetValue(t, out n)) { n = Txt.Clean(t.ProperNameStripLink()); properNames[t] = n; }
            return n;
        }

        // The category list is the same for every world and changes only when something is discovered: cached, rebuilt when the
        // number of discovered resources changes or after CatalogRefreshS.
        private sealed class Catalog
        {
            public int DiscoveredCount = -1; public float At = -100f;
            public List<Tag> Order = new List<Tag>();
            public Dictionary<Tag, List<Tag>> Items = new Dictionary<Tag, List<Tag>>();
            public Dictionary<Tag, string> Unit = new Dictionary<Tag, string>();
        }
        private static Catalog catalog = new Catalog();

        /// <summary>
        /// Same rows, order and numbers as AllResourcesScreen: categories = GameTags.MaterialCategories (mass), CalorieCategories
        /// (kcal), UnitCategories (units), sorted by display name (the screen sorts its category rows that way); a resource is listed
        /// under the first category that claims it; items are the discovered resources of the category (zero amounts are listed, as the
        /// screen does); amount = the screen's "available" column: WorldInventory.GetAmount (mass, units) or the sum of Edible calories
        /// per food id (RationTracker.CountAmountForItemWithID rule), shown in kcal.
        /// </summary>
        private static Step CatalogStep(Job j)
        {
            return new Step { Section = "resources catalog", Run = delegate ()
            {
                int count = DiscoveredResources.Instance.GetDiscovered().Count;
                float now = Time.unscaledTime;
                if (count == catalog.DiscoveredCount && now - catalog.At < CatalogRefreshS) return;
                Catalog cat = new Catalog { DiscoveredCount = count, At = now };
                List<KeyValuePair<Tag, string>> cats = new List<KeyValuePair<Tag, string>>();   // processing order: tag, unit
                foreach (Tag t in GameTags.MaterialCategories) cats.Add(new KeyValuePair<Tag, string>(t, "kg"));
                foreach (Tag t in GameTags.CalorieCategories) cats.Add(new KeyValuePair<Tag, string>(t, "kcal"));
                foreach (Tag t in GameTags.UnitCategories) cats.Add(new KeyValuePair<Tag, string>(t, "units"));
                HashSet<Tag> placed = new HashSet<Tag>();
                List<Step> steps = new List<Step>();
                for (int from = 0; from < cats.Count; from += CatalogChunk)
                {
                    int a = from, b = Math.Min(cats.Count, from + CatalogChunk);
                    steps.Add(new Step { Section = "resources catalog", Run = delegate ()
                    {
                        for (int i = a; i < b; i++)
                        {
                            KeyValuePair<Tag, string> kv = cats[i];
                            if (cat.Unit.ContainsKey(kv.Key)) continue;
                            cat.Unit[kv.Key] = kv.Value;
                            List<Tag> items = new List<Tag>();
                            foreach (Tag item in DiscoveredResources.Instance.GetDiscoveredResourcesFromTag(kv.Key))
                                if (placed.Add(item)) items.Add(item);
                            if (items.Count > 0) { cat.Items[kv.Key] = items; cat.Order.Add(kv.Key); }
                        }
                    } });
                }
                steps.Add(new Step { Section = "resources catalog", Run = delegate ()
                {
                    cat.Order.Sort(delegate (Tag x, Tag y) { return ProperName(x).CompareTo(ProperName(y)); });
                    catalog = cat;
                } });
                PushFront(j, steps);
            } };
        }

        private static void QueueResources(Job j, WorldContainer wc, WorldSnap w)
        {
            Dictionary<string, double> cal = new Dictionary<string, double>();
            List<Pickupable> edibles = null;
            WorldInventory inv = wc.worldInventory;
            bool ok = false;
            Enq(j, "resources inventory", delegate ()
            {
                try
                {
                    if (inv == null || !inv.HasValidCount || DiscoveredResources.Instance == null) return;
                    ok = true;
                    PushFront(j, "resources catalog", CatalogStep(j).Run);   // runs next; it queues its own small steps in front of the rest
                }
                catch (Exception ex) { Log.Warn("resources skipped for world " + wc.id + ": " + ex.GetType().Name + ": " + ex.Message); }
            });
            Enq(j, "resources edibles copy", delegate ()
            {
                if (!ok) return;
                try
                {
                    ICollection<Pickupable> e = inv.GetPickupables(GameTags.Edible);   // calories per food id (same filter as RationTracker: not StoredPrivate)
                    edibles = e != null ? new List<Pickupable>(e) : new List<Pickupable>();
                }
                catch (Exception ex) { Log.Warn("resources skipped for world " + wc.id + ": " + ex.GetType().Name + ": " + ex.Message); ok = false; }
            });
            // The number of edible chunks is not known yet: one step per chunk is queued from inside the previous one.
            Enq(j, "resources edibles", delegate () { if (ok) EdibleChunkStep(j, w, wc, inv, cal, edibles, 0); });
        }

        private static void EdibleChunkStep(Job j, WorldSnap w, WorldContainer wc, WorldInventory inv, Dictionary<string, double> cal, List<Pickupable> edibles, int from)
        {
            try
            {
                int to = Math.Min(edibles.Count, from + EdibleChunk);
                for (int i = from; i < to; i++)
                {
                    Pickupable p = edibles[i];
                    if (p == null || p.KPrefabID.HasTag(GameTags.StoredPrivate)) continue;
                    Edible e = p.GetComponent<Edible>();
                    if (e == null) continue;
                    double c; cal.TryGetValue(e.FoodID, out c); cal[e.FoodID] = c + e.Calories;
                }
                if (to < edibles.Count)
                {
                    // the next chunk goes to the FRONT of this world's remaining work: rebuild the queue with it first
                    PushFront(j, "resources edibles", delegate () { EdibleChunkStep(j, w, wc, inv, cal, edibles, to); });
                    return;
                }
                // all calories known: one step per category, in the screen's order
                Catalog cat = catalog;
                List<Step> catSteps = new List<Step>();
                foreach (Tag tag in cat.Order)
                {
                    Tag category = tag;
                    int n = cat.Items[category].Count;
                    for (int at = 0; at < n || at == 0; at += ResChunk)
                    {
                        int a = at, b = Math.Min(n, at + ResChunk);
                        catSteps.Add(new Step
                        {
                            Section = "resources category",
                            Run = delegate () { try { GatherCategory(cat, category, inv, cal, w.Resources, a, b); } catch (Exception ex) { Log.Warn("resources category skipped: " + ex.GetType().Name + ": " + ex.Message); } }
                        });
                    }
                }
                PushFront(j, catSteps);
            }
            catch (Exception ex) { Log.Warn("resources skipped for world " + wc.id + ": " + ex.GetType().Name + ": " + ex.Message); w.Resources.Clear(); }
        }

        private static void PushFront(Job j, string section, System.Action run)
        {
            List<Step> one = new List<Step>(); one.Add(new Step { Section = section, Run = run });
            PushFront(j, one);
        }

        private static void PushFront(Job j, List<Step> first)
        {
            Step[] rest = j.Steps.ToArray();
            j.Steps.Clear();
            foreach (Step s in first) j.Steps.Enqueue(s);
            foreach (Step s in rest) j.Steps.Enqueue(s);
        }

        private static void GatherCategory(Catalog cat, Tag category, WorldInventory inv, Dictionary<string, double> cal, List<ResSnap> outList, int from, int to)
        {
            string unit = cat.Unit[category], catName = ProperName(category);
            List<Tag> items = cat.Items[category];
            for (int i = from; i < to; i++)
            {
                Tag item = items[i];
                ResSnap r = new ResSnap { Id = item.Name, Name = ProperName(item), Category = catName, Unit = unit };
                if (unit == "kcal")
                {
                    double c; cal.TryGetValue(item.Name, out c);
                    r.Amount = Math.Max(0.0, c / 1000.0);
                    float per;
                    if (!kcalPerUnit.TryGetValue(item, out per))
                    {
                        EdiblesManager.FoodInfo fi = EdiblesManager.GetFoodInfo(item.Name);
                        per = fi != null ? fi.CaloriesPerUnit / 1000f : -1f;
                        kcalPerUnit[item] = per;
                    }
                    if (per >= 0f) r.Kcal = per;
                }
                else r.Amount = inv.GetAmount(item, false);
                outList.Add(r);
            }
        }

        // ------------------------------------------------------------ research

        private static List<string> completedCache = new List<string>();
        private static float completedAt = -100f;

        private static ResearchSnap GatherResearch()
        {
            ResearchSnap rs = new ResearchSnap();
            Research r = Research.Instance;
            if (r == null) return rs;
            TechInstance cur = r.GetActiveResearch();
            if (cur != null) rs.Current = GatherTech(cur);
            foreach (TechInstance ti in r.GetResearchQueue()) rs.Queue.Add(GatherTech(ti));
            float now = Time.unscaledTime;
            if (now - completedAt >= ResearchDoneRefreshS)   // the completed list moves rarely: read it on a slow clock
            {
                completedAt = now;
                List<string> done = new List<string>();
                foreach (Tech t in Db.Get().Techs.resources)
                {
                    TechInstance ti = r.GetTechInstance(t.Id);
                    if (ti != null && ti.IsComplete()) done.Add(t.Id);
                }
                done.Sort(StringComparer.Ordinal);
                completedCache = done;
            }
            rs.Completed = completedCache;
            return rs;
        }


        private static TechSnap GatherTech(TechInstance ti)
        {
            TechSnap t = new TechSnap { Tech = ti.tech.Id, Points = new List<KeyValuePair<string, double>>(), Cost = new List<KeyValuePair<string, double>>() };
            foreach (KeyValuePair<string, float> kv in ti.progressInventory.PointsByTypeID) t.Points.Add(new KeyValuePair<string, double>(kv.Key, kv.Value));
            foreach (KeyValuePair<string, float> kv in ti.tech.costsByResearchTypeID) t.Cost.Add(new KeyValuePair<string, double>(kv.Key, kv.Value));
            t.Points.Sort(delegate (KeyValuePair<string, double> a, KeyValuePair<string, double> b) { return string.CompareOrdinal(a.Key, b.Key); });
            t.Cost.Sort(delegate (KeyValuePair<string, double> a, KeyValuePair<string, double> b) { return string.CompareOrdinal(a.Key, b.Key); });
            return t;
        }


        private static string Serialize(Snap s)
        {
            Json j = new Json(8192);
            j.Obj();
            j.PI("build", s.Build);
            j.Key("dlcIds").StrArr(s.Dlc);
            j.P("colonyName", s.ColonyName);
            j.P("colonyGuid", s.ColonyGuid);
            j.PI("cycle", s.Cycle);
            j.P("timeOfDay", s.TimeOfDay);
            j.P("paused", s.Paused);
            j.PI("speed", s.Speed);
            j.PI("activeWorldId", s.ActiveWorldId);
            Actions.WriteLive(j, s.Pad);
            SerializeUnlocked(j, s);
            j.Key("worlds").Arr();
            foreach (WorldSnap w in s.Worlds)
            {
                j.Obj().PI("id", w.Id).P("name", w.Name).P("isStarter", w.IsStarter);
                j.Key("dupes").Arr();
                foreach (DupeSnap d in w.Dupes) SerializeDupe(j, d);
                j.EndArr();
                j.Key("resources").Arr();
                foreach (ResSnap r in w.Resources)
                {
                    j.Obj().P("id", r.Id).P("name", r.Name).P("category", r.Category).P("amount", r.Amount).P("unit", r.Unit);
                    if (r.Kcal >= 0) j.P("kcal", r.Kcal);
                    j.EndObj();
                }
                j.EndArr();
                j.Key("critters").Arr();
                foreach (CritterSnap c in w.Critters) j.Obj().P("id", c.Id).PI("count", c.Count).PI("tame", c.Tame).EndObj();
                j.EndArr();
                j.Key("alerts").Arr();
                foreach (AlertSnap a in w.Alerts)
                {
                    j.Obj().P("id", a.Id).P("level", a.Level).P("text", a.Text).PI("cycle", a.Cycle).PI("count", a.Count);
                    Alerts.Info ai = a.Info;
                    if (ai != null)
                    {
                        j.P("title", ai.Title).P("type", ai.Type);
                        if (ai.Tooltip != null) j.P("tooltipMarkup", ai.Tooltip);
                        j.Key("links").Arr();
                        foreach (Alerts.LinkInfo l in ai.Links)
                        {
                            j.Obj().PI("index", l.Index).P("label", l.Label).P("kind", l.Kind);
                            if (l.Target != null) j.P("target", l.Target);
                            j.EndObj();
                        }
                        j.EndArr();
                        j.Key("click").Obj().P("kind", ai.ClickKind);
                        if (ai.ClickTarget != null) j.P("target", ai.ClickTarget);
                        j.EndObj();
                        j.P("dismissable", ai.Dismissable);
                    }
                    j.EndObj();
                }
                j.EndArr();
                SerializeStock(j, w);
                j.Key("research");
                SerializeResearch(j, w.Research);
                j.EndObj();
            }
            j.EndArr();
            j.EndObj();
            string str = j.ToString();
            return str.Substring(1, str.Length - 2);   // members only
        }

        private static void SerializeGauge(Json j, string key, Gauge g)
        {
            j.Key(key).Obj().P("value", g.Value).P("max", g.Max).EndObj();
        }

        private static void SerializeDupe(Json j, DupeSnap d)
        {
            j.Obj();
            j.P("id", d.Id);
            if (d.AppearanceHash != null) j.P("appearanceHash", d.AppearanceHash);
            j.P("name", d.Name);
            j.P("stress", d.Stress);
            SerializeGauge(j, "health", d.Health);
            SerializeGauge(j, "calories", d.Calories);
            SerializeGauge(j, "breath", d.Breath);
            if (d.HasBladder) j.P("bladder", d.Bladder);
            if (d.HasMorale) j.Key("morale").Obj().P("value", d.MoraleValue).P("required", d.MoraleRequired).EndObj();
            j.Key("chore"); if (d.Chore != null) j.Str(d.Chore); else j.Null();
            j.Key("skills").StrArr(d.Skills);
            j.Key("traits").StrArr(d.Traits);
            j.Key("assignedSkill"); if (!string.IsNullOrEmpty(d.AssignedSkill)) j.Str(d.AssignedSkill); else j.Null();
            j.Key("statusItems").Arr();
            foreach (StatusSnap st in d.StatusItems) j.Obj().P("id", st.Id).P("name", st.Name).P("severity", st.Severity).EndObj();
            j.EndArr();
            j.Key("diseases").Arr();
            foreach (KeyValuePair<string, string> di in d.Diseases) j.Obj().P("id", di.Key).P("name", di.Value).EndObj();
            j.EndArr();
            if (d.Stamina != null) SerializeGauge(j, "stamina", d.Stamina);
            if (d.HasBodyTemp) j.P("bodyTempC", d.BodyTempC);
            j.Key("attributes").Arr();
            foreach (AttrSnap a in d.Attributes) j.Obj().P("id", a.Id).P("name", a.Name).P("value", a.Value).EndObj();
            j.EndArr();
            j.EndObj();
        }

        private static void SerializeTech(Json j, TechSnap t)
        {
            j.Obj().P("tech", t.Tech);
            j.Key("points").Obj();
            foreach (KeyValuePair<string, double> kv in t.Points) j.P(kv.Key, kv.Value);
            j.EndObj();
            j.Key("cost").Obj();
            foreach (KeyValuePair<string, double> kv in t.Cost) j.P(kv.Key, kv.Value);
            j.EndObj();
            j.EndObj();
        }

        private static void SerializeResearch(Json j, ResearchSnap r)
        {
            j.Obj();
            j.Key("current"); if (r.Current != null) SerializeTech(j, r.Current); else j.Null();
            j.Key("queue").Arr();
            foreach (TechSnap t in r.Queue) SerializeTech(j, t);
            j.EndArr();
            j.Key("completed").StrArr(r.Completed);
            j.EndObj();
        }

        private static string WorldName(WorldContainer wc)
        {
            try
            {
                ClusterGridEntity ge = wc.GetComponent<ClusterGridEntity>();
                if (ge != null && !string.IsNullOrEmpty(ge.Name)) return Txt.Clean(ge.Name);
            }
            catch { }
            return Txt.Clean(wc.worldName);
        }



        private static Dictionary<int, List<AlertSnap>> GatherAlerts()
        {
            Dictionary<int, List<AlertSnap>> result = new Dictionary<int, List<AlertSnap>>();
            // group by world + level + text (Alerts.TryKey); ids are stable while a group lasts
            Dictionary<string, List<Notification>> groups = new Dictionary<string, List<Notification>>();
            Dictionary<string, string[]> meta = new Dictionary<string, string[]>();   // key -> {worldId, level, text}
            List<string> order = new List<string>();
            int activeWorld = ClusterManager.Instance.activeWorldId;
            for (int i = 0; i < notifications.Count; i++)
            {
                Notification n = notifications[i];
                string key, level, text; int w;
                if (!Alerts.TryKey(n, activeWorld, out key, out level, out text, out w)) continue;
                List<Notification> g;
                if (!groups.TryGetValue(key, out g)) { g = new List<Notification>(); groups[key] = g; meta[key] = new[] { w.ToString(), level, text }; order.Add(key); }
                g.Add(n);
            }
            int cycle = GameClock.Instance.GetCycle() + 1;
            HashSet<string> alive = new HashSet<string>(order);
            foreach (string k in new List<string>(alertFirstCycle.Keys)) if (!alive.Contains(k)) alertFirstCycle.Remove(k);
            Alerts.Prune(alive);
            System.Diagnostics.Stopwatch budget = System.Diagnostics.Stopwatch.StartNew();
            foreach (string key in order)
            {
                int firstCycle;
                if (!alertFirstCycle.TryGetValue(key, out firstCycle)) { firstCycle = cycle; alertFirstCycle[key] = cycle; }
                string[] m = meta[key];
                int wid = int.Parse(m[0]);
                List<Notification> members = groups[key];
                AlertSnap a = new AlertSnap { Id = Alerts.IdFor(key), Level = m[1], Text = m[2], Cycle = firstCycle, Count = members.Count };
                try { a.Info = Alerts.Describe(key, members[0].titleText, members, budget); } catch (Exception e) { Log.Warn("alerts: describe failed for '" + m[2] + "': " + e.Message); }
                List<AlertSnap> l;
                if (!result.TryGetValue(wid, out l)) { l = new List<AlertSnap>(); result[wid] = l; }
                l.Add(a);
            }
            return result;
        }
    }
}
