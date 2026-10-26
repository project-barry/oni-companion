using System;
using System.Collections.Generic;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// v1.3 lane M9, live part of the build menu data (see Build.cs for the game's rules):
    /// - `unlockedBuildings` (top level): the buildings the player can build now. Recomputed when the game says research finished
    ///   (GameHashes.ResearchComplete, which the game also triggers for POI unlocks) or when sandbox mode flips; that event forces
    ///   a live write at once, so a newly researched building is active in the app within the normal write delay.
    /// - `worlds[].stock`: element id -> kg, from the same call the game's picker uses
    ///   (worldInventory.GetAmount(tag, includeRelatedWorlds: true)), only for candidates the game shows (discovered ones;
    ///   everything in sandbox / instant build). A candidate that is absent is not offered. Gathered in small chunks per frame
    ///   inside the normal live job (frame budget FrameBudgetMs), amounts floored to 1/100 kg so an unchanged colony writes an
    ///   identical file (the writer skips those).
    /// </summary>
    internal static partial class LiveWriter
    {
        private const int StockChunk = 30;

        private static List<string> unlockedIds;               // replaced, never changed in place (the worker reads it)
        private static bool unlockedDirty = true;
        private static bool lastSandbox;
        private static List<KeyValuePair<string, Tag>> stockTags;
        private static Game subscribedTo;

        private static void OnResearchDone(object data)
        {
            unlockedDirty = true;
            forceNext = true;                                   // live write at once (burst guard still applies)
        }

        /// <summary>Called from Tick when the colony is ready: subscribe once per Game, notice sandbox flips.</summary>
        private static void BuildLiveTick()
        {
            Game g = Game.Instance;
            if (g == null) return;
            if (subscribedTo != g)
            {
                try
                {
                    g.Subscribe((int)GameHashes.ResearchComplete, OnResearchDone);
                    subscribedTo = g;
                    unlockedDirty = true;
                    stockTags = null;
                }
                catch (Exception e) { Log.Warn("build: could not subscribe to research events: " + e.Message); }
            }
            bool sb = g.SandboxModeActive || DebugHandler.InstantBuildMode;
            if (sb != lastSandbox) { lastSandbox = sb; unlockedDirty = true; forceNext = true; }
        }

        private static void BuildLiveReset()
        {
            try { if (subscribedTo != null) subscribedTo.Unsubscribe((int)GameHashes.ResearchComplete, OnResearchDone); } catch { }
            subscribedTo = null; unlockedIds = null; unlockedDirty = true; stockTags = null; lastSandbox = false;
        }

        /// <summary>Step: the unlocked list for this write (recomputed only when something changed).</summary>
        private static void BuildUnlockedStep(Job j)
        {
            try
            {
                if (unlockedDirty || unlockedIds == null)
                {
                    List<string> now = BuildInfo.UnlockedIds();
                    bool changed = unlockedIds != null && (unlockedIds.Count != now.Count);
                    if (!changed && unlockedIds != null) for (int i = 0; i < now.Count; i++) if (unlockedIds[i] != now[i]) { changed = true; break; }
                    unlockedIds = now;
                    unlockedDirty = false;
                    if (changed) forceNext = true;
                }
                j.S.Unlocked = unlockedIds;
            }
            catch (Exception ex) { BuildInfo.WarnOnce("unlocked", ex); }
        }

        private static void QueueStock(Job j, WorldContainer wc, WorldSnap w)
        {
            Enq(j, "build stock", delegate ()
            {
                try
                {
                    WorldInventory inv = wc.worldInventory;
                    if (inv == null || !inv.HasValidCount || DiscoveredResources.Instance == null) return;
                    if (stockTags == null) stockTags = BuildInfo.AllCandidates();
                    w.Stock = new Dictionary<string, double>();
                    StockChunkStep(j, w, inv, 0);
                }
                catch (Exception ex) { BuildInfo.WarnOnce("stock", ex); }
            });
        }

        private static void StockChunkStep(Job j, WorldSnap w, WorldInventory inv, int from)
        {
            List<KeyValuePair<string, Tag>> tags = stockTags;
            int to = Math.Min(from + StockChunk, tags.Count);
            bool all = DebugHandler.InstantBuildMode || (Game.Instance != null && Game.Instance.SandboxModeActive);
            for (int i = from; i < to; i++)
            {
                Tag t = tags[i].Value;
                if (!all && !DiscoveredResources.Instance.IsDiscovered(t)) continue;
                double kg = inv.GetAmount(t, true);
                w.Stock[tags[i].Key] = Math.Floor(kg * 100.0) / 100.0;
            }
            if (to < tags.Count) PushFront(j, "build stock", delegate () { StockChunkStep(j, w, inv, to); });
        }

        private static void SerializeStock(Json j, WorldSnap w)
        {
            if (w.Stock == null) return;
            List<string> keys = new List<string>(w.Stock.Keys);
            keys.Sort(StringComparer.Ordinal);
            j.Key("stock").Obj();
            foreach (string k in keys) j.P(k, w.Stock[k]);
            j.EndObj();
        }

        private static void SerializeUnlocked(Json j, Snap s)
        {
            if (s.Unlocked != null) j.Key("unlockedBuildings").StrArr(s.Unlocked);
        }
    }
}
