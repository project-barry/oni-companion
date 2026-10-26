using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace OniCompanionLink
{
    /// <summary>
    /// Alerts like the game (v1.2). Everything here mirrors the game's own NotificationScreen (decompiled, build 744825):
    ///  - the alert list shows ONE row per notification titleText (NotificationScreen.entriesByMessage, private) and that row
    ///    ("Entry") owns the notification list, the click cycle (clickIdx) and the dismiss button;
    ///  - the tooltip is notification.ToolTip(entry.notifications, notification.tooltipData) of the row's first notification
    ///    (for status-item alerts: the status item's tooltip text + notifications.ReduceMessages(), i.e. one "• Name(count)" line per source);
    ///  - a click is NotificationScreen.OnClick(entry): custom click callback, else camera + select of clickFocus / the notifier,
    ///    cycling through the row's notifications; clearOnClick clears it;
    ///  - dismiss exists only when the first notification has showDismissButton; its button listener clears the whole row.
    /// The mod calls those very methods (reflection on the private members), so the result is the game's, cycling included.
    /// Tooltips are built only when a group's members change (cache by member identity), with a time box per gather.
    /// </summary>
    internal static class Alerts
    {
        internal sealed class LinkInfo { public int Index; public string Label, Kind, Target; }
        internal sealed class Info
        {
            public string Id, Type, Title, Tooltip, ClickKind, ClickTarget;
            public bool Dismissable;
            public List<LinkInfo> Links = new List<LinkInfo>();
            public int Sig;
        }

        private const double BuildBudgetMs = 1.0;   // tooltips built per gather call; the rest follows on the next write

        // group key -> stable id while the group lasts
        private static readonly Dictionary<string, string> idByKey = new Dictionary<string, string>(StringComparer.Ordinal);
        private static readonly Dictionary<string, string> keyById = new Dictionary<string, string>(StringComparer.Ordinal);
        private static readonly Dictionary<string, Info> cache = new Dictionary<string, Info>(StringComparer.Ordinal);
        private static readonly Dictionary<string, int> linkCycle = new Dictionary<string, int>(StringComparer.Ordinal);
        private static int nextId = 1;
        private static bool needMore;                     // a gather ran out of budget: ask for another write

        // reflection into NotificationScreen (resolved once)
        private static bool reflected, reflectOk;
        private static FieldInfo fEntries, fNotifs, fClickIdx, fLabel;
        private static MethodInfo mOnClick;

        public static void Reset()
        {
            idByKey.Clear(); keyById.Clear(); cache.Clear(); linkCycle.Clear(); linkNameFor.Clear(); needMore = false;
        }

        /// <summary>True once when a gather left tooltips unbuilt (time box); the caller then forces another write.</summary>
        public static bool TakeNeedMore() { bool b = needMore; needMore = false; return b; }

        // ------------------------------------------------------------ grouping (shared with Live.GatherAlerts)

        /// <summary>The v1.1 grouping: world + level + cleaned title. Types the app cannot show (none now) return false.</summary>
        public static bool TryKey(Notification n, int activeWorld, out string key, out string level, out string text, out int world)
        {
            key = null; level = null; text = null; world = activeWorld;
            if (n == null) return false;
            switch (n.Type)
            {
                case NotificationType.Bad:
                case NotificationType.DuplicantThreatening: level = "bad"; break;
                case NotificationType.BadMinor: level = "warning"; break;
                default: level = "info"; break;      // good, neutral, event, tutorial, messages, messageImportant, custom
            }
            text = Txt.Clean(n.titleText);
            if (text.Length == 0) return false;
            try { if (n.Notifier != null) { int nw = n.Notifier.gameObject.GetMyWorldId(); if (nw >= 0) world = nw; } } catch { }
            key = world.ToString(CultureInfo.InvariantCulture) + "|" + level + "|" + text;
            return true;
        }

        public static string TypeName(NotificationType t)
        {
            switch (t)
            {
                case NotificationType.Bad: return "bad";
                case NotificationType.BadMinor: return "minorBad";
                case NotificationType.Good: return "good";
                case NotificationType.Neutral: return "neutral";
                case NotificationType.Tutorial: return "tutorial";
                case NotificationType.Messages: return "messages";
                case NotificationType.DuplicantThreatening: return "duplicantThreatening";
                case NotificationType.Event: return "event";
                case NotificationType.MessageImportant: return "messageImportant";
                case NotificationType.Custom: return "custom";
                default: return "neutral";
            }
        }

        public static string IdFor(string key)
        {
            string id;
            if (!idByKey.TryGetValue(key, out id))
            {
                id = "al" + (nextId++).ToString(CultureInfo.InvariantCulture);
                idByKey[key] = id; keyById[id] = key;
            }
            return id;
        }

        public static void Prune(HashSet<string> alive)
        {
            List<string> gone = null;
            foreach (string k in idByKey.Keys) if (!alive.Contains(k)) { if (gone == null) gone = new List<string>(); gone.Add(k); }
            if (gone == null) return;
            foreach (string k in gone)
            {
                string id = idByKey[k];
                idByKey.Remove(k); keyById.Remove(id); cache.Remove(k);
                List<string> lk = null;
                foreach (string c in linkCycle.Keys) if (c.StartsWith(id + "#", StringComparison.Ordinal)) { if (lk == null) lk = new List<string>(); lk.Add(c); }
                if (lk != null) foreach (string c in lk) linkCycle.Remove(c);
                lk = null;
                foreach (string c in linkNameFor.Keys) if (c.StartsWith(id + "#", StringComparison.Ordinal)) { if (lk == null) lk = new List<string>(); lk.Add(c); }
                if (lk != null) foreach (string c in lk) linkNameFor.Remove(c);
            }
        }

        // ------------------------------------------------------------ describe (tooltip, links, click, dismissable)

        /// <summary>Info for one group; rebuilt only when its members changed. Null budget = no time box.</summary>
        public static Info Describe(string key, string title, List<Notification> members, Stopwatch budget)
        {
            int sig = members.Count;
            for (int i = 0; i < members.Count; i++) sig = unchecked(sig * 31 + RuntimeHelpers.GetHashCode(members[i]));
            Info old;
            if (cache.TryGetValue(key, out old) && old.Sig == sig) return old;
            if (budget != null && budget.Elapsed.TotalMilliseconds > BuildBudgetMs && old == null)
            {
                needMore = true;
                return null;                                         // built on the next write; the alert itself is still listed
            }
            Info info = Build(key, title, members, sig);
            cache[key] = info;
            return info;
        }

        private static Info Build(string key, string title, List<Notification> members, int sig)
        {
            Info info = new Info { Id = IdFor(key), Sig = sig, Title = title };
            object entry = FindEntry(members[0].titleText);
            List<Notification> list = EntryNotifications(entry) ?? members;
            if (list.Count == 0) list = members;
            Notification first = list[0];
            info.Type = TypeName(first.Type);
            info.Dismissable = first.showDismissButton && entry != null && DismissButtonOf(entry) != null;

            // main click, as NotificationScreen.OnClick resolves it
            ManagementMenuNotification mm = first as ManagementMenuNotification;
            if (first.Type == NotificationType.Messages) { info.ClickKind = "screen"; info.ClickTarget = "message"; }
            else if (mm != null) { info.ClickKind = "screen"; info.ClickTarget = ScreenId(mm.targetMenu); }
            else if (first.customClickCallback != null) { info.ClickKind = "screen"; info.ClickTarget = "other"; }
            else if (first.clickFocus != null || first.Notifier != null) info.ClickKind = "focus";
            else info.ClickKind = "none";

            // tooltip exactly as the game builds it
            string tip = null;
            if (first.ToolTip != null)
            {
                try { tip = first.ToolTip(list, first.tooltipData); } catch (Exception e) { Log.Warn("alerts: tooltip failed for '" + info.Title + "': " + e.Message); }
            }
            if (!string.IsNullOrEmpty(tip))
            {
                // highlighted lines: the "• Name" source lines ReduceMessages appends; one link per distinct source, wrapped in the markup
                List<string> names = LinkNames(list);
                int from = 0;
                StringBuilder sb = new StringBuilder(tip.Length + 32);
                for (int i = 0; i < names.Count; i++)
                {
                    string needle = "\n" + names[i];
                    int at = tip.IndexOf(needle, from, StringComparison.Ordinal);
                    if (at < 0) continue;
                    int s = at + 1;
                    int idx = info.Links.Count;
                    sb.Append(tip, from, s - from).Append("<link=\"").Append(idx.ToString(CultureInfo.InvariantCulture)).Append("\">").Append(names[i]).Append("</link>");
                    from = s + names[i].Length;
                    string label = Txt.Clean(names[i]);
                    if (label.StartsWith("•")) label = label.Substring(1).Trim();
                    info.Links.Add(new LinkInfo { Index = idx, Label = label, Kind = "focus", Target = label });
                    linkNameFor[info.Id + "#" + idx.ToString(CultureInfo.InvariantCulture)] = names[i];
                }
                sb.Append(tip, from, tip.Length - from);
                info.Tooltip = sb.ToString();
            }
            return info;
        }

        // link index -> NotifierName it was built for (a link always resolves through the live entry again)
        private static readonly Dictionary<string, string> linkNameFor = new Dictionary<string, string>(StringComparer.Ordinal);

        /// <summary>Distinct NotifierName values, in the order ReduceMessages lists them, whose notifications the game focuses on click.</summary>
        private static List<string> LinkNames(List<Notification> list)
        {
            List<string> names = new List<string>();
            HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < list.Count; i++)
            {
                Notification n = list[i];
                if (n == null || string.IsNullOrEmpty(n.NotifierName)) continue;
                if (n.customClickCallback != null || n.Type == NotificationType.Messages) continue;
                if (n.clickFocus == null && n.Notifier == null) continue;
                if (seen.Add(n.NotifierName)) names.Add(n.NotifierName);
            }
            return names;
        }

        private static string ScreenId(global::Action a)
        {
            string s = a.ToString();
            switch (s)
            {
                case "ManageReport": return "report";
                case "ManageSkills": return "skills";
                case "ManageResearch": return "research";
                case "ManageSchedule": return "schedule";
                case "ManageConsumables": return "consumables";
                case "ManageDatabase": return "codex";          // the game binds its Codex toggle to ManageDatabase
                case "ManageVitals": return "vitals";
                case "ManagePriorities": return "jobs";         // the game binds its Jobs (priorities) toggle to ManagePriorities
                case "ManageResources": return "resources";
                case "ManageDiagnostics": return "diagnostics";
                case "ManageStarmap": return "starmap";
            }
            return s.StartsWith("Manage", StringComparison.Ordinal) && s.Length > 6 ? s.Substring(6).ToLowerInvariant() : s.ToLowerInvariant();
        }

        // ------------------------------------------------------------ the game's alert row (reflection)

        private static bool Reflect()
        {
            if (reflected) return reflectOk;
            reflected = true;
            try
            {
                BindingFlags all = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
                Type scr = typeof(NotificationScreen);
                Type entry = scr.GetNestedType("Entry", BindingFlags.NonPublic | BindingFlags.Public);
                fEntries = scr.GetField("entriesByMessage", all);
                mOnClick = scr.GetMethod("OnClick", all, null, new[] { entry }, null);
                fNotifs = entry.GetField("notifications", all);
                fClickIdx = entry.GetField("clickIdx", all);
                fLabel = entry.GetField("label", all);
                reflectOk = fEntries != null && mOnClick != null && fNotifs != null && fClickIdx != null && fLabel != null;
                if (!reflectOk) Log.Warn("alerts: NotificationScreen members not found; alert tooltips/clicks fall back to partial data");
            }
            catch (Exception e) { reflectOk = false; Log.Warn("alerts: reflection failed: " + e.Message); }
            return reflectOk;
        }

        private static object FindEntry(string title)
        {
            try
            {
                if (!Reflect() || NotificationScreen.Instance == null || title == null) return null;
                IDictionary d = fEntries.GetValue(NotificationScreen.Instance) as IDictionary;
                return d != null && d.Contains(title) ? d[title] : null;
            }
            catch { return null; }
        }

        private static List<Notification> EntryNotifications(object entry)
        {
            try { return entry == null ? null : fNotifs.GetValue(entry) as List<Notification>; } catch { return null; }
        }

        private static Button DismissButtonOf(object entry)
        {
            try
            {
                GameObject label = fLabel.GetValue(entry) as GameObject;
                if (label == null) return null;
                HierarchyReferences hr = label.GetComponent<HierarchyReferences>();
                if (hr == null) return null;
                Button b = hr.GetReference<Button>("DismissButton");
                return b != null && b.gameObject.activeSelf ? b : null;
            }
            catch { return null; }
        }

        // ------------------------------------------------------------ commands (main thread)

        private static List<Notification> LiveMembers(string key)
        {
            List<Notification> res = new List<Notification>();
            int active = ClusterManager.Instance.activeWorldId;
            List<Notification> all = LiveWriter.LiveNotifications();
            for (int i = 0; i < all.Count; i++)
            {
                string k, lv, tx; int w;
                if (TryKey(all[i], active, out k, out lv, out tx, out w) && k == key) res.Add(all[i]);
            }
            return res;
        }

        /// <summary>alert_activate. link &lt; 0 = the alert's own click. Returns the ack message; ok false = failed.</summary>
        public static bool Activate(string alertId, int link, out string message)
        {
            message = "Alert is gone";
            string key;
            if (alertId == null || !keyById.TryGetValue(alertId, out key)) return false;
            List<Notification> members = LiveMembers(key);
            if (members.Count == 0) return false;
            object entry = FindEntry(members[0].titleText);
            List<Notification> list = EntryNotifications(entry);
            if (entry == null || list == null || list.Count == 0) return false;
            int setIdx = -1;
            if (link >= 0)
            {
                string name;
                if (!linkNameFor.TryGetValue(alertId + "#" + link.ToString(CultureInfo.InvariantCulture), out name)) { message = "Link is gone"; return false; }
                List<int> cand = new List<int>();
                for (int i = 0; i < list.Count; i++)
                {
                    Notification n = list[i];
                    if (n != null && n.NotifierName == name && n.customClickCallback == null && n.Type != NotificationType.Messages && (n.clickFocus != null || n.Notifier != null)) cand.Add(i);
                }
                if (cand.Count == 0) { message = "Link is gone"; return false; }
                string ck = alertId + "#" + link.ToString(CultureInfo.InvariantCulture);
                int c; linkCycle.TryGetValue(ck, out c);
                setIdx = cand[c % cand.Count];
                linkCycle[ck] = c + 1;
            }
            if (setIdx >= 0) fClickIdx.SetValue(entry, setIdx);     // NextClickedNotification = notifications[clickIdx++ % Count]
            mOnClick.Invoke(NotificationScreen.Instance, new[] { entry });   // the game's own click path (camera, select, callbacks, clearOnClick)
            message = link >= 0 ? "Moved to the source" : "Clicked";
            return true;
        }

        /// <summary>alert_dismiss: the game's own dismiss button listener, only when the game shows that button.</summary>
        public static bool Dismiss(string alertId, out string message)
        {
            message = "Alert is gone";
            string key;
            if (alertId == null || !keyById.TryGetValue(alertId, out key)) return false;
            List<Notification> members = LiveMembers(key);
            if (members.Count == 0) return false;
            object entry = FindEntry(members[0].titleText);
            List<Notification> list = EntryNotifications(entry);
            if (entry == null || list == null || list.Count == 0) return false;
            Button b = list[0].showDismissButton ? DismissButtonOf(entry) : null;
            if (b == null) { message = "Can't be dismissed"; return false; }
            b.onClick.Invoke();
            message = "Dismissed";
            return true;
        }
    }
}
