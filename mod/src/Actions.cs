using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// v1.3 Actions: the game's overlay bar and tool bar, mirrored and driven (contracts: mod-export Overlay / PadTool,
    /// mod-live activeOverlay / activeTool / priority, commands overlay_set / tool_select). Found by decompiling build 744825:
    ///   Overlays = OverlayMenu.overlayToggleInfos (private list built by InitializeToggles, in the bar's order; Radiation is added
    ///     only when Sim.IsRadiationEnabled()). Each entry: text, icon (sprite name), hotKey, simView (HashedString), IsUnlocked().
    ///     A tap in the game is OverlayMenu.OnToggleSelect(toggle): active again = OverlayScreen.ToggleOverlay(None), else
    ///     ToggleOverlay(simView) when unlocked. overlay_set calls that same method, so sound, menus and legend behave normally.
    ///   Tools = ToolMenu.basicTools (filled in ToolMenu.OnSpawn; every collection here holds one tool; sandbox tools are not listed).
    ///     A tap in the game is the collection toggle's onClick: deactivate sound when the collection is already selected, then
    ///     ToolMenu.ChooseCollection(tc) (selects, or clears when it is the selected one). tool_select does the same through the
    ///     private ChooseCollection, so the tool bar's own state, the priority bar and the cursor follow.
    ///   Priority = ToolMenu.Instance.PriorityScreen: a button click is PlayPriorityConfirmSound + SetScreenPriority. basic 1..9, or
    ///     topPriority 1 = the Emergency button.
    /// Live state is written at once when it changes: the overlay and the tool through the game's own events (OverlayChanged
    /// 1798162660, ToolActivated 1174281782: they fire for changes made in the game too), the priority by comparing one struct per frame
    /// (the game has no event for it). All of that is a few comparisons per frame, far below 2 ms.
    /// Icons: the sprites of the lists go into the theme as icons (UiIcons) under the game's sprite name; the lists name them.
    /// </summary>
    internal static class Actions
    {
        // ids of the overlay modes, copied from the OverlayModes.*.ID constants (a HashedString keeps only its hash)
        private static readonly string[] ModeIds =
        {
            "Oxygen", "Power", "Temperature", "TileMode", "Light", "LiquidConduit", "GasConduit", "Decor", "Disease", "Crop",
            "Rooms", "Suit", "Logic", "SolidConveyor", "Radiation"
        };

        // Tools whose OnActivateTool shows the priority bar (PriorityScreen.Show()): Attack, Capture, Clear, Deconstruct, Dig,
        // EmptyPipe, Harvest, Mop, Prioritize. Cancel, Disinfect and Disconnect do not show it.
        private static readonly HashSet<string> PriorityTools = new HashSet<string>
        {
            "DigTool", "DeconstructTool", "PrioritizeTool", "ClearTool", "AttackTool", "MopTool", "CaptureTool", "HarvestTool", "EmptyPipeTool"
        };

        private static readonly System.Text.RegularExpressions.Regex IdRx = new System.Text.RegularExpressions.Regex("^[A-Za-z0-9_.\\-]{1,100}$");

        private sealed class OverlayEntry
        {
            public string Id, Name, Hotkey, Icon;
            public bool NeedsDlc;                  // listed for the DLC, but the game being played has no such overlay
            public KIconToggleMenu.ToggleInfo Toggle;
        }

        private sealed class ToolEntry
        {
            public string Id, Name, Hotkey, Icon;
            public bool Available, UsesPriority;
            public ToolMenu.ToolCollection Collection;
        }

        // the lists are built once per game (keyed by the two screens) and kept
        private static OverlayMenu listsForOverlay;
        private static ToolMenu listsForTools;
        private static readonly List<OverlayEntry> overlays = new List<OverlayEntry>();
        private static readonly List<ToolEntry> tools = new List<ToolEntry>();
        private static readonly Dictionary<int, string> idByHash = new Dictionary<int, string>();

        private static FieldInfo toggleListField, simViewField, techField;
        private static MethodInfo isUnlockedM, onToggleSelectM, chooseCollectionM;

        // live state
        private static Game subscribedGame;
        private static int lastPrio = int.MinValue;

        // ------------------------------------------------------------ lists

        /// <summary>True when both bars exist in this game and the lists are built.</summary>
        public static bool Ready()
        {
            if (Env.Disabled) return false;
            OverlayMenu om = OverlayMenu.Instance;
            ToolMenu tm = ToolMenu.Instance;
            if (om == null || tm == null || OverlayScreen.Instance == null || PlayerController.Instance == null) return false;
            if (om == listsForOverlay && tm == listsForTools) return overlays.Count > 0 && tools.Count > 0;
            return BuildLists(om, tm);
        }

        private static bool BuildLists(OverlayMenu om, ToolMenu tm)
        {
            if (tm.basicTools == null || tm.basicTools.Count == 0) return false;      // ToolMenu.OnSpawn has not run yet
            if (toggleListField == null)
            {
                toggleListField = typeof(OverlayMenu).GetField("overlayToggleInfos", BindingFlags.NonPublic | BindingFlags.Instance);
                onToggleSelectM = typeof(OverlayMenu).GetMethod("OnToggleSelect", BindingFlags.NonPublic | BindingFlags.Instance);
                chooseCollectionM = typeof(ToolMenu).GetMethod("ChooseCollection", BindingFlags.NonPublic | BindingFlags.Instance);
                if (idByHash.Count == 0) foreach (string s in ModeIds) idByHash[new HashedString(s).HashValue] = s;
            }
            if (toggleListField == null || onToggleSelectM == null || chooseCollectionM == null)
            {
                Log.Warn("actions: the game's overlay/tool members were not found; overlays and tools are off");
                return false;
            }
            List<ToggleInfoLike> infos = ReadToggles(om);
            if (infos == null || infos.Count == 0) return false;

            overlays.Clear(); tools.Clear();
            bool radiationListed = false;
            foreach (ToggleInfoLike t in infos)
            {
                OverlayEntry e = new OverlayEntry { Name = Txt.Clean(t.Text), Icon = t.Icon, Hotkey = HotkeyText(t.Hotkey), Toggle = t.Ref };
                string id;
                if (!idByHash.TryGetValue(t.Mode.HashValue, out id)) id = "Mode" + t.Mode.HashValue.ToString("X", CultureInfo.InvariantCulture);
                e.Id = id;
                if (t.Mode == OverlayModes.Radiation.ID) radiationListed = true;
                overlays.Add(e);
            }
            if (!radiationListed)
            {
                // the game builds this button only with Spaced Out; list it anyway so the app can say why it is greyed
                overlays.Add(new OverlayEntry
                {
                    Id = "Radiation", Name = Txt.Clean(STRINGS.UI.OVERLAYS.RADIATION.BUTTON), Icon = "overlay_radiation",
                    Hotkey = HotkeyText(global::Action.Overlay15), NeedsDlc = true
                });
            }

            foreach (ToolMenu.ToolCollection tc in tm.basicTools)
            {
                if (tc == null || tc.tools == null) continue;
                foreach (ToolMenu.ToolInfo ti in tc.tools)
                {
                    if (ti == null || string.IsNullOrEmpty(ti.toolName)) continue;
                    ToolEntry e = new ToolEntry
                    {
                        Id = ti.toolName, Name = Txt.Clean(ti.text), Icon = !string.IsNullOrEmpty(tc.icon) ? tc.icon : ti.icon,
                        Hotkey = HotkeyText(ti.hotkey), Collection = tc, UsesPriority = PriorityTools.Contains(ti.toolName)
                    };
                    e.Available = FindInterfaceTool(ti.toolName) != null;
                    tools.Add(e);
                }
            }
            listsForOverlay = om; listsForTools = tm;
            Log.Info("actions: " + overlays.Count + " overlays, " + tools.Count + " tools");
            return overlays.Count > 0 && tools.Count > 0;
        }

        // OverlayMenu.OverlayToggleInfo is a private nested class: read it by reflection, once per entry.
        private struct ToggleInfoLike { public string Text, Icon; public global::Action Hotkey; public HashedString Mode; public KIconToggleMenu.ToggleInfo Ref; }

        private static List<ToggleInfoLike> ReadToggles(OverlayMenu om)
        {
            List<KIconToggleMenu.ToggleInfo> list = toggleListField.GetValue(om) as List<KIconToggleMenu.ToggleInfo>;
            if (list == null) return null;
            List<ToggleInfoLike> r = new List<ToggleInfoLike>();
            foreach (KIconToggleMenu.ToggleInfo ti in list)
            {
                if (ti == null) continue;
                Type t = ti.GetType();
                if (simViewField == null || simViewField.DeclaringType != t)
                {
                    simViewField = t.GetField("simView", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                    techField = t.GetField("requiredTechItem", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                    isUnlockedM = t.GetMethod("IsUnlocked", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                }
                if (simViewField == null || isUnlockedM == null) { Log.Warn("actions: OverlayToggleInfo members not found"); return null; }
                r.Add(new ToggleInfoLike
                {
                    Text = ti.text, Icon = ti.icon, Hotkey = ti.hotKey, Mode = (HashedString)simViewField.GetValue(ti),
                    Ref = ti
                });
            }
            return r;
        }

        private static bool Unlocked(OverlayEntry e)
        {
            try { return (bool)isUnlockedM.Invoke(e.Toggle, null); } catch { return true; }
        }

        private static string HotkeyText(global::Action a)
        {
            try
            {
                if (a == global::Action.NumActions || KInputManager.currentControllerIsGamepad) return null;
                string s = GameUtil.GetActionString(a);
                return string.IsNullOrEmpty(s) ? null : s;
            }
            catch { return null; }
        }

        private static InterfaceTool FindInterfaceTool(string name)
        {
            InterfaceTool[] all = PlayerController.Instance.tools;
            if (all == null) return null;
            foreach (InterfaceTool t in all) if (t != null && t.name == name) return t;
            return null;
        }

        // ------------------------------------------------------------ export + icons

        /// <summary>Writes the "overlays" array (Exporter.Section body). Throws when the bars do not exist yet, so the section is empty.</summary>
        public static void ExportOverlays(Json j)
        {
            if (!Ready()) throw new InvalidOperationException("overlay bar not ready");
            j.Arr();
            foreach (OverlayEntry e in overlays)
            {
                bool available = !e.NeedsDlc && Unlocked(e);
                j.Obj().P("id", e.Id).P("name", e.Name);
                if (e.Hotkey != null) j.P("hotkey", e.Hotkey);
                if (!string.IsNullOrEmpty(e.Icon)) j.P("icon", e.Icon);
                j.Key("dlc").StrArr(e.NeedsDlc || e.Id == "Radiation" ? new[] { DlcManager.EXPANSION1_ID } : new string[0]);
                j.P("available", available).EndObj();
            }
            j.EndArr();
        }

        /// <summary>Writes the "tools" array (Exporter.Section body). Throws when the bars do not exist yet.</summary>
        public static void ExportTools(Json j)
        {
            if (!Ready()) throw new InvalidOperationException("tool bar not ready");
            j.Arr();
            foreach (ToolEntry e in tools)
            {
                j.Obj().P("id", e.Id).P("name", e.Name);
                if (e.Hotkey != null) j.P("hotkey", e.Hotkey);
                if (!string.IsNullOrEmpty(e.Icon)) j.P("icon", e.Icon);
                j.Key("dlc").StrArr(new string[0]);
                j.P("available", e.Available).P("usesPriority", e.UsesPriority).EndObj();
            }
            j.EndArr();
        }

        /// <summary>Theme step (UiIcons.List): one icon per list entry, under the game's sprite name.</summary>
        public static void ListIcons()
        {
            if (!Ready()) { Log.Warn("theme: pad icons skipped: the overlay and tool bars are not ready"); return; }
            HashSet<string> seen = new HashSet<string>();
            foreach (OverlayEntry e in overlays) AddIcon(e.Icon, seen);
            foreach (ToolEntry e in tools) AddIcon(e.Icon, seen);
        }

        private static void AddIcon(string name, HashSet<string> seen)
        {
            if (string.IsNullOrEmpty(name) || !seen.Add(name)) return;
            Sprite sp = Assets.GetSprite(name);
            if (sp == null) { Log.Warn("theme: pad icon '" + name + "': the game has no such sprite"); return; }
            UiIcons.AddIcon(name, sp, Color.white);
        }

        // ------------------------------------------------------------ live state

        /// <summary>What live.json carries for the three pad fields; taken on the main thread by the live head step.</summary>
        internal sealed class PadState
        {
            public string Overlay, Tool;
            public string Priority;          // "emergency" or "1".."9"; null = unknown
        }

        public static PadState Capture()
        {
            PadState p = new PadState();
            try
            {
                Ready();                                  // builds the lists once per game (overlay ids, tool names)
                if (OverlayScreen.Instance != null)
                {
                    HashedString m = OverlayScreen.Instance.GetMode();
                    if (m != OverlayModes.None.ID)
                    {
                        string id;
                        if (idByHash.TryGetValue(m.HashValue, out id) && ModeListed(id)) p.Overlay = id;
                    }
                }
                if (PlayerController.Instance != null && PlayerController.Instance.ActiveTool != null)
                {
                    string n = PlayerController.Instance.ActiveTool.name;
                    foreach (ToolEntry e in tools) if (e.Id == n) { p.Tool = n; break; }
                }
                p.Priority = PriorityText(CurrentPriority());
            }
            catch (Exception e) { Log.Warn("actions: live state failed: " + e.Message); }
            return p;
        }

        private static bool ModeListed(string id)
        {
            foreach (OverlayEntry e in overlays) if (e.Id == id) return true;
            return false;
        }

        public static void WriteLive(Json j, PadState p)
        {
            if (p == null) return;
            if (p.Overlay != null) j.P("activeOverlay", p.Overlay); else j.Key("activeOverlay").Null();
            if (p.Tool != null) j.P("activeTool", p.Tool); else j.Key("activeTool").Null();
            if (p.Priority == "emergency") j.P("priority", "emergency");
            else if (p.Priority != null) j.PI("priority", int.Parse(p.Priority, CultureInfo.InvariantCulture));
        }

        private static PrioritySetting CurrentPriority()
        {
            ToolMenu tm = ToolMenu.Instance;
            PriorityScreen ps = tm != null ? tm.PriorityScreen : null;
            return ps != null ? ps.GetLastSelectedPriority() : new PrioritySetting(PriorityScreen.PriorityClass.basic, -1);
        }

        private static string PriorityText(PrioritySetting p)
        {
            if (p.priority_class == PriorityScreen.PriorityClass.topPriority) return "emergency";
            if (p.priority_value >= 1 && p.priority_value <= 9) return p.priority_value.ToString(CultureInfo.InvariantCulture);
            return null;
        }

        /// <summary>Main thread, every frame (Commands.Pump). Cheap: forces a live write when something changed.</summary>
        public static void Tick()
        {
            if (!LiveWriter.Ready() || Game.Instance == null) { subscribedGame = null; lastPrio = int.MinValue; return; }
            if (!ReferenceEquals(Game.Instance, subscribedGame))
            {
                subscribedGame = Game.Instance;
                subscribedGame.Subscribe(1798162660, OnGameChange);       // OverlayChanged (also fires for changes made in the game)
                subscribedGame.Subscribe(1174281782, OnGameChange);       // a tool was activated
                lastPrio = int.MinValue;
            }
            PrioritySetting p = CurrentPriority();
            int key = ((int)p.priority_class << 8) + p.priority_value;
            if (key != lastPrio)
            {
                if (lastPrio != int.MinValue) LiveWriter.MarkSave();
                lastPrio = key;
            }
        }

        private static void OnGameChange(object data) { LiveWriter.MarkSave(); }

        // ------------------------------------------------------------ commands (main thread)

        /// <summary>overlay_set {mode}: the overlay button's own click, or none. Returns the ack message.</summary>
        public static bool SetOverlay(string mode, out string message)
        {
            message = null;
            if (!LiveWriter.Ready() || !Ready()) { message = "No colony is loaded"; return false; }
            if (mode == "None")
            {
                if (OverlayScreen.Instance.GetMode() == OverlayModes.None.ID) { message = "No overlay"; return true; }
                OverlayScreen.Instance.ToggleOverlay(OverlayModes.None.ID);        // what the toggle does for the active overlay
                LiveWriter.MarkSave();
                message = "Overlay off";
                return true;
            }
            OverlayEntry entry = null;
            foreach (OverlayEntry e in overlays) if (e.Id == mode) { entry = e; break; }
            if (entry == null || entry.NeedsDlc || entry.Toggle == null) { message = "Not available in this game"; return false; }
            if (!Unlocked(entry)) { message = "Not researched yet"; return false; }
            bool wasActive = OverlayScreen.Instance.GetMode() == ModeOf(entry);
            onToggleSelectM.Invoke(OverlayMenu.Instance, new object[] { entry.Toggle });
            LiveWriter.MarkSave();
            message = wasActive ? "Overlay off" : entry.Name;
            return true;
        }

        private static HashedString ModeOf(OverlayEntry e)
        {
            return (HashedString)simViewField.GetValue(e.Toggle);
        }

        /// <summary>tool_select {tool?, priority?}. priority is "1".."9" or "emergency" (already validated), or null.</summary>
        public static bool SelectTool(string tool, string priority, out string message)
        {
            message = null;
            if (!LiveWriter.Ready() || !Ready()) { message = "No colony is loaded"; return false; }
            ToolEntry entry = null;
            if (tool != null)
            {
                foreach (ToolEntry e in tools) if (e.Id == tool) { entry = e; break; }
                if (entry == null || !entry.Available) { message = "Not available in this game"; return false; }
            }
            string done = null;
            if (priority != null)
            {
                PriorityScreen ps = ToolMenu.Instance.PriorityScreen;
                if (ps == null) { message = "Not available in this game"; return false; }
                PrioritySetting p = priority == "emergency"
                    ? new PrioritySetting(PriorityScreen.PriorityClass.topPriority, 1)
                    : new PrioritySetting(PriorityScreen.PriorityClass.basic, int.Parse(priority, CultureInfo.InvariantCulture));
                if (ps.GetLastSelectedPriority() != p)
                {
                    PriorityScreen.PlayPriorityConfirmSound(p);              // PriorityButton.OnClick
                    ps.SetScreenPriority(p);                                 // ToolMenu.OnPriorityClicked
                }
                done = priority == "emergency" ? "Priority emergency" : "Priority " + priority;
            }
            if (entry != null)
            {
                ToolMenu tm = ToolMenu.Instance;
                bool selected = tm.currentlySelectedCollection == entry.Collection;
                if (selected && entry.Collection.tools.Count >= 1 && PlayerController.Instance.ActiveTool != null)
                {
                    // the collection toggle's onClick: clicking the selected one plays the active tool's deactivate sound, then clears it
                    string snd = GlobalAssets.GetSound(PlayerController.Instance.ActiveTool.GetDeactivateSound());
                    if (!string.IsNullOrEmpty(snd)) KMonoBehaviour.PlaySound(snd);
                }
                chooseCollectionM.Invoke(tm, new object[] { entry.Collection, true });
                done = (selected ? "Tool off: " : "") + entry.Name + (done != null ? ", " + done.ToLowerInvariant() : "");
            }
            LiveWriter.MarkSave();
            message = done;
            return true;
        }

        internal static bool IdOk(string s) { return s != null && IdRx.IsMatch(s); }
    }
}
