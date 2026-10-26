using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Dt = System.DateTime;

namespace OniCompanionLink
{
    /// <summary>
    /// App -> game commands (contracts/mod-command.schema.json, mod-ack.schema.json).
    /// A FileSystemWatcher on companion/commands only queues file paths (its callbacks run on pool threads and touch
    /// no game object). Game.Update (main thread) drains the queue: allow list (see Accept), 10 s age limit,
    /// 250 ms rate limit (focus), then runs the command and writes companion/acks/ack-SEQ.json, then deletes the command file.
    /// No timed folder polling: the queue is only looked at when the watcher put something in it.
    /// art_request {kind, id} = draw one catalog image now (Art.Request): queued, drawn a little each frame, acked after the
    /// manifest lists it. Only the known art kinds and a plain id (letters, digits, _ . -); a path is never taken from a command.
    /// Same age limit as focus; the 250 ms gap applies to focus only, art_request is one per frame (it only queues).
    /// focus = ONE camera move (CameraController.SetTargetPos, which clears any follow target) and, optionally, a select.
    /// The game's follow mode (SetFollowTarget) is never used. A command never supplies a path or code.
    /// </summary>
    internal static class Commands
    {
        private const double MaxAgeS = 10.0;
        private const float MinGapS = 0.25f;
        private const int MaxPending = 40;       // commands read but not finished; art_request commands handed to Art do not count (Art has its own limit)
        private const int MaxFileBytes = 4096;
        private const int MaxReadTries = 5;
        private const string ProbeName = ".watcher-probe";
        private static readonly Regex NameRx = new Regex("^cmd-([0-9]{1,18})\\.json$", RegexOptions.Compiled);

        private sealed class Item { public string Path; public int Tries; }

        private static readonly object gate = new object();
        private static readonly ConcurrentQueue<Item> queue = new ConcurrentQueue<Item>();
        private static readonly HashSet<string> inFlight = new HashSet<string>(StringComparer.Ordinal);   // guarded by gate
        // art_request commands Art accepted and acks later: still in inFlight (no second run of the same file), but not
        // counted against MaxPending, so a slow drawing queue never blocks focus, speed, build or sync (live test 0.4.0)
        private static readonly HashSet<string> artHeld = new HashSet<string>(StringComparer.Ordinal);    // guarded by gate
        private static FileSystemWatcher watcher;
        private static string cmdDir, ackDir;
        private static float lastRun = -10f;
        private static long pendingSwapSeq;                // a focus waiting for the world-switch fade, 0 = none
        private static string pendingSwapPath;
        private static volatile int probeSeen;            // ms since start when the probe event arrived, 0 = not yet
        private static long startTicks;
        private static float startReal = -1f;
        private static bool probeWarned;

        public static void Start()
        {
            try
            {
                string root = Env.CompanionDir();
                cmdDir = Path.Combine(root, "commands");
                ackDir = Path.Combine(root, "acks");
                Directory.CreateDirectory(cmdDir);
                Directory.CreateDirectory(ackDir);
                CleanOldAcks();

                FileSystemWatcher w = new FileSystemWatcher(cmdDir);
                w.IncludeSubdirectories = false;
                w.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size;
                w.Created += OnFile;
                w.Changed += OnFile;
                w.Renamed += OnRenamed;     // the core writes cmd-N.json.tmp then renames it
                w.Error += (s, e) => Log.Warn("commands watcher error: " + (e.GetException() != null ? e.GetException().Message : "?"));
                startTicks = Dt.UtcNow.Ticks;
                w.EnableRaisingEvents = true;
                watcher = w;
                Log.Info("commands: watching " + cmdDir + " (watcher " + WatcherImpl(w) + ")");

                // One-time self-test, no timer: the event for this file proves the watcher fires on this system.
                try { File.WriteAllText(Path.Combine(cmdDir, ProbeName), "probe"); } catch (Exception e) { Log.Warn("commands: probe write failed: " + e.Message); }

                // Files that were there before the mod started: handled (and refused as too old) like any other.
                foreach (string f in Directory.GetFiles(cmdDir, "cmd-*.json")) Enqueue(f);
            }
            catch (Exception e)
            {
                Log.Error("commands: could not start, commands are off", e);
                Stop();
            }
        }

        public static void Stop()
        {
            try
            {
                FileSystemWatcher w = watcher; watcher = null;
                if (w != null) { w.EnableRaisingEvents = false; w.Dispose(); }
                if (cmdDir != null) { try { File.Delete(Path.Combine(cmdDir, ProbeName)); } catch { } }
            }
            catch { }
        }

        private static string WatcherImpl(FileSystemWatcher w)
        {
            try
            {
                FieldInfo f = typeof(FileSystemWatcher).GetField("watcher", BindingFlags.Instance | BindingFlags.NonPublic);
                object o = f != null ? f.GetValue(w) : null;
                return o != null ? o.GetType().Name : "unknown";
            }
            catch { return "unknown"; }
        }

        // ---- watcher thread: queue paths only ----

        private static void OnRenamed(object s, RenamedEventArgs e) { Seen(e.Name, e.FullPath); }
        private static void OnFile(object s, FileSystemEventArgs e) { Seen(e.Name, e.FullPath); }

        private static void Seen(string name, string fullPath)
        {
            try
            {
                if (name == ProbeName)
                {
                    if (probeSeen == 0) probeSeen = Math.Max(1, (int)((Dt.UtcNow.Ticks - startTicks) / TimeSpan.TicksPerMillisecond));
                    return;
                }
                if (name == null) return;
                if (!NameRx.IsMatch(name))
                {
                    // *.tmp is the core's own half-written file; any other cmd-*.json that does not match is logged, never silent
                    if (name.StartsWith("cmd-", StringComparison.Ordinal) && name.EndsWith(".json", StringComparison.Ordinal))
                        Log.Warn("commands: ignored " + (name.Length > 60 ? name.Substring(0, 60) : name) + " (name is not cmd-<number up to 18 digits>.json)");
                    return;
                }
                Enqueue(Path.Combine(cmdDir, name));                   // never trust the event's path, only the matched name
            }
            catch { }
        }

        private static void Enqueue(string path)
        {
            lock (gate)
            {
                if (inFlight.Contains(path)) return;     // Created + Changed + Renamed for one file: one run
                if (inFlight.Count - artHeld.Count >= MaxPending) { Log.Warn("commands: too many pending, dropped " + Path.GetFileName(path)); TryDelete(path); return; }
                inFlight.Add(path);
            }
            queue.Enqueue(new Item { Path = path });
        }

        // ---- main thread (Game.Update postfix) ----

        public static void Pump()
        {
            if (Env.Disabled) return;
            try { Speed.Tick(); } catch (Exception e) { Log.Error("speed tick", e); }
            try { Exporter.Tick(); } catch (Exception e) { Log.Error("export tick", e); }
            try { Actions.Tick(); } catch (Exception e) { Log.Error("actions tick", e); }
            float now = Time.unscaledTime;
            if (startReal < 0f) startReal = now;
            if (!probeWarned && probeSeen == 0 && now - startReal > 5f && watcher != null)
            {
                probeWarned = true;
                Log.Warn("commands: the watcher gave no event for its probe file after 5 s; the app's commands will not arrive on this system");
            }
            else if (!probeWarned && probeSeen != 0)
            {
                probeWarned = true;
                Log.Info("commands: watcher self-test OK (" + WatcherImpl(watcher) + ", event after " + probeSeen + " ms)");
            }
            if (queue.IsEmpty) return;
            Item it;
            if (!queue.TryDequeue(out it)) return;
            try { Handle(it); }
            catch (Exception e)
            {
                Log.Error("commands: handler failed for " + Path.GetFileName(it.Path), e);
                Finish(it.Path, SeqFromName(it.Path), false, "Command failed");
            }
        }

        private static long SeqFromName(string path)
        {
            Match m = NameRx.Match(Path.GetFileName(path));
            long n;
            return m.Success && long.TryParse(m.Groups[1].Value, NumberStyles.None, CultureInfo.InvariantCulture, out n) ? n : 0;
        }

        private static void Handle(Item it)
        {
            string path = it.Path;
            long nameSeq = SeqFromName(path);
            if (nameSeq <= 0) { Release(path); return; }
            string text;
            try
            {
                FileInfo fi = new FileInfo(path);
                if (!fi.Exists) { Release(path); return; }
                if (fi.Length > MaxFileBytes) { Finish(path, nameSeq, false, "Command too large"); return; }
                text = File.ReadAllText(path);
            }
            catch (IOException)
            {
                if (++it.Tries < MaxReadTries) { queue.Enqueue(it); return; }      // writer may still hold it: next frames
                Finish(path, nameSeq, false, "Command file unreadable");
                return;
            }

            JObject o;
            // DateParseHandling.None: by default Newtonsoft turns "createdAt" into a Date token, not a String
            try
            {
                using (var reader = new Newtonsoft.Json.JsonTextReader(new StringReader(text)) { DateParseHandling = Newtonsoft.Json.DateParseHandling.None })
                    o = JObject.Load(reader);
            }
            catch { Finish(path, nameSeq, false, "Command is not valid JSON"); return; }

            JToken tSeq = o["seq"];
            if (tSeq == null || tSeq.Type != JTokenType.Integer || (long)tSeq != nameSeq || (int?)o["schema"] != 1)
            { Finish(path, nameSeq, false, "Command malformed"); return; }

            // allow list: focus, art_request, alert_activate, alert_dismiss, set_speed, sync_assets, overlay_set, tool_select, build_select
            string type = o["type"] != null && o["type"].Type == JTokenType.String ? (string)o["type"] : null;
            if (type != "focus" && type != "art_request" && type != "alert_activate" && type != "alert_dismiss" && type != "set_speed" && type != "sync_assets"
                && type != "overlay_set" && type != "tool_select" && type != "build_select")
            {
                Log.Warn("commands: dropped command " + nameSeq + " of type '" + (type ?? "?") + "' (not on the allow list)");
                Finish(path, nameSeq, false, "Command not allowed");
                return;
            }

            // age limit (UTC createdAt against this machine's clock)
            Dt created;
            string ca = o["createdAt"] != null && o["createdAt"].Type == JTokenType.String ? (string)o["createdAt"] : null;
            if (ca == null || !Dt.TryParse(ca, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out created))
            { Finish(path, nameSeq, false, "Command malformed"); return; }
            double age = (Dt.UtcNow - created).TotalSeconds;
            if (age > MaxAgeS) { Finish(path, nameSeq, false, "Command too old"); return; }
            if (age < -MaxAgeS) { Finish(path, nameSeq, false, "Command dated in the future (clocks differ)"); return; }

            if (type == "alert_activate" || type == "alert_dismiss")
            {
                if (!AlertCommand(it, path, nameSeq, type, o)) return;
                return;
            }
            if (type == "overlay_set" || type == "tool_select")
            {
                PadCommand(path, nameSeq, type, o);
                return;
            }
            if (type == "build_select")
            {
                BuildInfo.Command(path, nameSeq, o);       // validates, runs on this (main) thread, acks
                return;
            }
            if (type == "sync_assets")
            {
                string scope = o["scope"] != null && o["scope"].Type == JTokenType.String ? (string)o["scope"] : null;
                if (scope != "full" && scope != "missing") { Finish(path, nameSeq, false, "Command malformed"); return; }
                Sync.Request(path, nameSeq, scope);     // acks at once
                return;
            }

            JObject target = o["target"] as JObject;
            string kind = target != null && target["kind"] != null && target["kind"].Type == JTokenType.String ? (string)target["kind"] : null;
            string id = target != null && target["id"] != null && target["id"].Type == JTokenType.String ? (string)target["id"] : null;
            if (type == "set_speed")
            {
                string st = o["state"] != null && o["state"].Type == JTokenType.String ? (string)o["state"] : null;
                int sp = 0;
                if (o["speed"] != null)
                {
                    if (o["speed"].Type != JTokenType.Integer) { Finish(path, nameSeq, false, "Command malformed"); return; }
                    sp = (int)o["speed"];
                    if (sp < 1 || sp > 3 || st == "pause") { Finish(path, nameSeq, false, "Command malformed"); return; }
                }
                if (st != "pause" && st != "play" && !(st == "speed" && sp > 0)) { Finish(path, nameSeq, false, "Command malformed"); return; }
                string msg;
                bool ok = Speed.Apply(st, sp, out msg);
                Finish(path, nameSeq, ok, msg);
                return;
            }
            if (type == "art_request")
            {
                if (!Art.KnownKind(kind) || !Art.SafeIdOk(id)) { Finish(path, nameSeq, false, "Command malformed"); return; }
                Art.Request(path, nameSeq, kind, id);   // acks later (or at once if it cannot be queued)
                return;
            }
            if (kind != "dupe" || string.IsNullOrEmpty(id) || id.Length > 32) { Finish(path, nameSeq, false, "Command malformed"); return; }
            bool select = true;
            if (o["select"] != null && o["select"].Type == JTokenType.Boolean) select = (bool)o["select"];
            if (Time.unscaledTime - lastRun < MinGapS) { queue.Enqueue(it); return; }   // rate limit: wait for the next frames (the age limit still applies)

            lastRun = Time.unscaledTime;
            FocusDupe(path, nameSeq, id, select);
        }

        /// <summary>overlay_set {mode} / tool_select {tool?, priority?} (Actions.cs does the game calls; mod-command.schema.json).</summary>
        private static void PadCommand(string path, long seq, string type, JObject o)
        {
            string msg;
            if (type == "overlay_set")
            {
                string mode = o["mode"] != null && o["mode"].Type == JTokenType.String ? (string)o["mode"] : null;
                if (!Actions.IdOk(mode)) { Finish(path, seq, false, "Command malformed"); return; }
                Finish(path, seq, Actions.SetOverlay(mode, out msg), msg);
                return;
            }
            string tool = null, priority = null;
            if (o["tool"] != null)
            {
                tool = o["tool"].Type == JTokenType.String ? (string)o["tool"] : null;
                if (!Actions.IdOk(tool)) { Finish(path, seq, false, "Command malformed"); return; }
            }
            JToken pt = o["priority"];
            if (pt != null)
            {
                if (pt.Type == JTokenType.Integer && (long)pt >= 1 && (long)pt <= 9) priority = ((long)pt).ToString(CultureInfo.InvariantCulture);
                else if (pt.Type == JTokenType.String && (string)pt == "emergency") priority = "emergency";
                else { Finish(path, seq, false, "Command malformed"); return; }
            }
            if (tool == null && priority == null) { Finish(path, seq, false, "Command malformed"); return; }
            Finish(path, seq, Actions.SelectTool(tool, priority, out msg), msg);
        }

        /// <summary>alert_activate / alert_dismiss (Alerts.cs does the game calls). Returns false when it re-queued itself (rate limit).</summary>
        private static bool AlertCommand(Item it, string path, long seq, string type, JObject o)
        {
            string alertId = o["alertId"] != null && o["alertId"].Type == JTokenType.String ? (string)o["alertId"] : null;
            if (string.IsNullOrEmpty(alertId) || alertId.Length > 100) { Finish(path, seq, false, "Command malformed"); return true; }
            int link = -1;
            if (o["link"] != null)
            {
                if (o["link"].Type != JTokenType.Integer || (long)o["link"] < 0 || (long)o["link"] > 10000) { Finish(path, seq, false, "Command malformed"); return true; }
                link = (int)(long)o["link"];
            }
            if (type == "alert_dismiss" && o["link"] != null) { Finish(path, seq, false, "Command malformed"); return true; }
            if (!LiveWriter.Ready() || NotificationScreen.Instance == null) { Finish(path, seq, false, "No colony is loaded"); return true; }
            if (type == "alert_activate")
            {
                if (Time.unscaledTime - lastRun < MinGapS) { queue.Enqueue(it); return false; }   // one camera move per 250 ms, like focus
                lastRun = Time.unscaledTime;
            }
            string msg;
            bool ok = type == "alert_activate" ? Alerts.Activate(alertId, link, out msg) : Alerts.Dismiss(alertId, out msg);
            Finish(path, seq, ok, msg);
            return true;
        }

        private static void FocusDupe(string path, long seq, string id, bool select)
        {
            if (!LiveWriter.Ready()) { Finish(path, seq, false, "No colony is loaded"); return; }
            MinionIdentity found = null;
            foreach (MinionIdentity m in Components.LiveMinionIdentities.Items)
            {
                if (m == null) continue;
                KPrefabID kp = m.GetComponent<KPrefabID>();
                if (kp != null && kp.InstanceID.ToString(CultureInfo.InvariantCulture) == id) { found = m; break; }
            }
            if (found == null) { Finish(path, seq, false, "Duplicant not found"); return; }

            Vector3 pos = found.transform.GetPosition();
            WorldContainer world = ClusterManager.Instance.GetWorldFromPosition(pos);
            if (world == null) { Finish(path, seq, false, "Duplicant is not on a known world"); return; }
            KSelectable sel = select ? found.GetComponent<KSelectable>() : null;
            bool otherWorld = world.id != ClusterManager.Instance.activeWorldId;

            if (otherWorld) { pendingSwapSeq = seq; pendingSwapPath = path; }
            // The game's own "go to this place" (what clicking a notification does): same world = one pan/zoom via
            // CameraController.SetTargetPos (clears any follow target); other world = star-wipe switch, then the same.
            // The callback runs after the switch (or at once in the same world), so the select sees the right world.
            // show_back_button false: no extra "return" button. No follow target is ever set.
            GameUtil.FocusCameraOnWorld(world.id, pos, 10f, () =>
            {
                try
                {
                    if (sel != null) SelectTool.Instance.Select(sel);
                }
                catch (Exception e) { Log.Warn("commands: select failed: " + e.Message); }
                if (pendingSwapSeq == seq) { pendingSwapSeq = 0; pendingSwapPath = null; }
                Finish(path, seq, true, otherWorld ? "Switched world and moved the camera" : "Camera moved");
            }, false);
        }

        // ---- ack + cleanup ----

        internal static void Finish(string path, long seq, bool ok, string message)
        {
            try
            {
                if (seq > 0)
                {
                    Json j = new Json(256);
                    j.Obj().PI("schema", 1).PI("seq", seq).P("state", ok ? "done" : "failed").P("message", message).P("ackedAt", Env.Now()).EndObj();
                    Files.WriteAtomic(Path.Combine(ackDir, "ack-" + seq.ToString(CultureInfo.InvariantCulture) + ".json"), j.ToString());
                }
            }
            catch (Exception e) { Log.Warn("commands: ack write failed: " + e.Message); }
            TryDelete(path);
            Release(path);
        }

        private static void Release(string path) { lock (gate) { inFlight.Remove(path); artHeld.Remove(path); } }

        /// <summary>Art accepted this art_request and acks it later (Finish): it stops counting against MaxPending.</summary>
        internal static void HeldByArt(string path) { lock (gate) { if (inFlight.Contains(path)) artHeld.Add(path); } }

        private static void TryDelete(string path) { try { File.Delete(path); } catch { } }

        private static void CleanOldAcks()
        {
            try
            {
                foreach (string f in Directory.GetFiles(ackDir, "ack-*.json*"))
                    if ((Dt.UtcNow - File.GetLastWriteTimeUtc(f)).TotalHours > 1.0) TryDelete(f);
            }
            catch { }
        }
    }
}
