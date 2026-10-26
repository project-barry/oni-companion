using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// v1.3 lane M9: what the game's build menu knows, for the app's Buildings tab and material picker.
    ///
    /// Rules read from the decompiled game (build 744825), not guessed:
    /// - In the build menu: BuildingDef.IsAvailable() (not deprecated, not debug-only) and ShouldShowInBuildMenu() and
    ///   Game.IsCorrectDlcActiveForCurrentSave(def) (PlanScreen.BuildButtonList). Groups and order are
    ///   TUNING.BUILDINGS.PLANORDER (PlanInfo order, then the order of buildingAndSubcategoryData).
    /// - Unlocked: PlanScreen.TechRequirementsMet(Db.Get().TechItems.TryGet(id)): no tech item = free, else TechItem.IsComplete()
    ///   (its tech is researched, or it was unlocked from a POI); sandbox and instant-build make everything buildable.
    /// - Material slots: BuildingDef.MaterialCategory[i] / Mass[i] (the craft recipe's ingredients). The picker offers
    ///   MaterialSelector.GetValidMaterials(tag) (solid elements with that tag, plus MaterialBuildingElements prefabs), shows only
    ///   DiscoveredResources.IsDiscovered ones, in the ElementSorter order, with the active world's
    ///   worldInventory.GetAmount(tag, includeRelatedWorlds: true) against the slot's mass. Under-stocked entries are disabled.
    /// - Default pick (MaterialSelector.AutoSelectAvailableMaterial): the choice remembered for this world, slot and building
    ///   (SaveGame.materialSelectorSerializer) when it is still enough, else the entry with the most stock that is enough
    ///   (wood, fabricated wood, mercury and lead count at most the needed mass, so they only win when nothing else is enough).
    /// </summary>
    internal static class BuildInfo
    {
        // ------------------------------------------------------------------ build menu rules

        /// <summary>Is this building listed in the game's build menu (apart from the DLC check)?</summary>
        public static bool InMenu(BuildingDef d)
        {
            return d != null && d.IsAvailable() && d.ShouldShowInBuildMenu();
        }

        /// <summary>The game's own unlock rule (PlanScreen.TechRequirementsMet). Needs a loaded colony.</summary>
        public static bool Unlocked(BuildingDef d)
        {
            if (DebugHandler.InstantBuildMode || (Game.Instance != null && Game.Instance.SandboxModeActive)) return true;
            TechItem ti = Db.Get().TechItems.TryGet(d.PrefabID);
            return ti == null || ti.IsComplete();
        }

        public static TechItem TechItemOf(BuildingDef d)
        {
            return Db.Get().TechItems.TryGet(d.PrefabID);
        }

        /// <summary>Ids of the buildings the player can build now in this colony (live rule). Sorted.</summary>
        public static List<string> UnlockedIds()
        {
            HashSet<string> inMenu = MenuIds();
            List<string> ids = new List<string>();
            foreach (BuildingDef d in Assets.BuildingDefs)
            {
                if (d == null || !inMenu.Contains(d.PrefabID) || !InMenu(d)) continue;
                if (!Game.IsCorrectDlcActiveForCurrentSave(d)) continue;
                if (Unlocked(d)) ids.Add(d.PrefabID);
            }
            ids.Sort(StringComparer.Ordinal);
            return ids;
        }

        private static HashSet<string> menuIds;
        /// <summary>Every building id that appears in TUNING.BUILDINGS.PLANORDER.</summary>
        public static HashSet<string> MenuIds()
        {
            if (menuIds != null) return menuIds;
            HashSet<string> s = new HashSet<string>();
            foreach (PlanScreen.PlanInfo pi in TUNING.BUILDINGS.PLANORDER)
                foreach (KeyValuePair<string, string> kv in pi.buildingAndSubcategoryData) s.Add(kv.Key);
            menuIds = s;
            return s;
        }

        public static BuildingDef FindDef(string id)
        {
            foreach (BuildingDef d in Assets.BuildingDefs) if (d != null && d.PrefabID == id) return d;
            return null;
        }

        // ------------------------------------------------------------------ material candidates

        private sealed class Cand { public string Id; public Tag Tag; }
        private static readonly Dictionary<string, List<Cand>> candCache = new Dictionary<string, List<Cand>>(StringComparer.Ordinal);
        private static int unsorted;

        /// <summary>Element id for a tag the way the export names elements; other tags (prefab materials) keep their tag text.</summary>
        public static string IdOf(Tag t)
        {
            try
            {
                Element e = ElementLoader.GetElement(t);
                if (e != null) return e.id.ToString();
            }
            catch { }
            return t.ToString();
        }

        private static List<Cand> CandidatesFor(string category)
        {
            List<Cand> l;
            if (candCache.TryGetValue(category, out l)) return l;
            List<Tag> tags = new List<Tag>();
            foreach (Tag t in MaterialSelector.GetValidMaterials(new Tag(category), false)) if (!tags.Contains(t)) tags.Add(t);
            tags.Sort(ElementSorter);       // the picker sorts its toggles with this comparer (MaterialSelector.SortElementToggles)
            l = new List<Cand>();
            foreach (Tag t in tags) l.Add(new Cand { Id = IdOf(t), Tag = t });
            candCache[category] = l;
            return l;
        }

        // Same comparer as MaterialSelector.ElementSorter (private there).
        private static int ElementSorter(Tag at, Tag bt)
        {
            GameObject ga = Assets.TryGetPrefab(at);
            IHasSortOrder sa = ga != null ? ga.GetComponent<IHasSortOrder>() : null;
            GameObject gb = Assets.TryGetPrefab(bt);
            IHasSortOrder sb = gb != null ? gb.GetComponent<IHasSortOrder>() : null;
            if (sa == null || sb == null) { unsorted++; return 0; }
            Element ea = ElementLoader.GetElement(at);
            Element eb = ElementLoader.GetElement(bt);
            if (ea != null && eb != null && ea.buildMenuSort == eb.buildMenuSort) return ea.idx.CompareTo(eb.idx);
            return sa.sortOrder.CompareTo(sb.sortOrder);
        }

        /// <summary>How many times the comparer had no sort order for a tag (0 = the order is the game's exactly).</summary>
        public static int UnsortedHits { get { return unsorted; } }

        /// <summary>The game's name of a slot: ProperName of each alternative tag joined by " or " (MaterialSelector.UpdateHeader).</summary>
        public static string SlotLabel(string category)
        {
            string[] parts = category.Split('&');
            string text = parts[0].ToTag().ProperName();
            for (int i = 1; i < parts.Length; i++) text = text + " or " + parts[i].ToTag().ProperName();
            return Txt.Clean(text);
        }

        /// <summary>Every (id, tag) any building slot can take, in a stable order: the stock list of live.json.</summary>
        public static List<KeyValuePair<string, Tag>> AllCandidates()
        {
            List<KeyValuePair<string, Tag>> all = new List<KeyValuePair<string, Tag>>();
            HashSet<string> seenCats = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> seenIds = new HashSet<string>(StringComparer.Ordinal);
            HashSet<string> inMenu = MenuIds();
            foreach (BuildingDef d in Assets.BuildingDefs)
            {
                if (d == null || d.MaterialCategory == null || !inMenu.Contains(d.PrefabID)) continue;
                foreach (string cat in d.MaterialCategory)
                {
                    if (string.IsNullOrEmpty(cat) || !seenCats.Add(cat)) continue;
                    foreach (Cand c in CandidatesFor(cat))
                        if (seenIds.Add(c.Id)) all.Add(new KeyValuePair<string, Tag>(c.Id, c.Tag));
                }
            }
            return all;
        }

        // ------------------------------------------------------------------ export pieces (called from Exporter)

        /// <summary>Extra members of one materials[] slot: label and candidates (merged into the open slot object).</summary>
        public static void SlotExtras(Json slot, string category)
        {
            try
            {
                Json s = new Json(256);
                s.Obj();
                s.P("label", SlotLabel(category));
                List<string> ids = new List<string>();
                foreach (Cand c in CandidatesFor(category)) ids.Add(c.Id);
                s.Key("candidates").StrArr(ids);
                s.EndObj();
                string t = s.ToString();
                slot.Raw(t.Substring(1, t.Length - 2));
            }
            catch (Exception ex) { WarnOnce("slot", ex); }
        }

        /// <summary>dlcActive, unlocked and lockReason of one building (merged into the open building object).</summary>
        public static void BuildingExtras(Json e, BuildingDef d)
        {
            try
            {
                Json s = new Json(256);
                s.Obj();
                s.P("dlcActive", DlcManager.IsCorrectDlcSubscribed(d));
                TechItem ti = TechItemOf(d);
                // Without a loaded colony nothing is researched yet and the research state is not known: `unlocked` is then only
                // written for buildings that need no research (always true). The live file carries the real state.
                bool colony = LiveWriter.Ready() && Research.Instance != null;
                if (ti == null) s.P("unlocked", true);
                else if (colony) s.P("unlocked", Unlocked(d));
                if (ti != null && ti.ParentTech != null && (!colony || !Unlocked(d)))
                {
                    Tech tech = ti.ParentTech;
                    s.Key("lockReason").Obj().P("techId", tech.Id).P("techName", Txt.Clean(tech.Name));
                    s.Key("cost").Obj();
                    List<string> keys = new List<string>(tech.costsByResearchTypeID.Keys);
                    keys.Sort(StringComparer.Ordinal);
                    foreach (string k in keys) s.P(k, tech.costsByResearchTypeID[k]);
                    s.EndObj().EndObj();
                }
                s.EndObj();
                string t = s.ToString();
                e.Raw(t.Substring(1, t.Length - 2));
            }
            catch (Exception ex) { WarnOnce("building", ex); }
        }

        /// <summary>Top-level `buildMenu`: the game's build menu groups, in PLANORDER, with the buildings in the game's order.</summary>
        public static void MenuSection(Json j)
        {
            j.Arr();
            int idx = -1;
            foreach (PlanScreen.PlanInfo pi in TUNING.BUILDINGS.PLANORDER)
            {
                idx++;
                if (!DlcManager.IsCorrectDlcSubscribed(pi)) continue;
                string id = HashCache.Get().Get(pi.category);
                if (string.IsNullOrEmpty(id)) id = pi.category.ToString();
                string upper = id.ToUpperInvariant();
                Json g = new Json(512);
                g.Obj().P("id", id);
                StringEntry nm;
                g.P("name", Strings.TryGet(new StringKey("STRINGS.UI.BUILDCATEGORIES." + upper + ".NAME"), out nm) ? Txt.Clean(STRINGS.UI.StripLinkFormatting(nm.String)) : id);
                string icon;
                if (PlanScreen.IconNameMap.TryGetValue(pi.category, out icon) && !string.IsNullOrEmpty(icon)) g.P("icon", icon);
                try
                {
                    // PlanScreen: hotkey i < 15 is Action 36 + i
                    if (idx < 15)
                    {
                        string hk = GameUtil.GetActionString((Action)(36 + idx));
                        if (!string.IsNullOrEmpty(hk)) g.P("hotkey", Txt.Clean(hk));
                    }
                }
                catch (Exception ex) { WarnOnce("hotkey", ex); }
                List<string> req = new List<string>();
                string[] rq = pi.GetRequiredDlcIds();
                if (rq != null) foreach (string s in rq) if (!string.IsNullOrEmpty(s) && !req.Contains(s)) req.Add(s);
                g.Key("dlc").StrArr(req);

                List<string> all = new List<string>();
                List<string> subOrder = new List<string>();
                Dictionary<string, List<string>> subs = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                foreach (KeyValuePair<string, string> kv in pi.buildingAndSubcategoryData)
                {
                    BuildingDef d = FindDef(kv.Key);
                    if (d == null || !InMenu(d) || !DlcManager.IsCorrectDlcSubscribed(d)) continue;
                    if (all.Contains(kv.Key)) continue;
                    all.Add(kv.Key);
                    List<string> l;
                    if (!subs.TryGetValue(kv.Value, out l)) { l = new List<string>(); subs[kv.Value] = l; subOrder.Add(kv.Value); }
                    l.Add(kv.Key);
                }
                g.Key("buildings").StrArr(all);
                g.Key("subgroups").Arr();
                foreach (string sid in subOrder)
                {
                    StringEntry sn;
                    string name = Strings.TryGet(new StringKey("STRINGS.UI.NEWBUILDCATEGORIES." + sid.ToUpperInvariant() + ".BUILDMENUTITLE"), out sn) ? Txt.Clean(sn.String) : sid;
                    g.Obj().P("id", sid).P("name", name).Key("buildings").StrArr(subs[sid]).EndObj();
                }
                g.EndArr();
                g.EndObj();
                j.Raw0(g.ToString());
            }
            j.EndArr();
        }

        private static readonly HashSet<string> warned = new HashSet<string>();
        internal static void WarnOnce(string what, Exception ex)
        {
            if (warned.Add(what)) Log.Warn("build info '" + what + "' failed (further failures of this kind are not logged): " + ex.GetType().Name + ": " + ex.Message);
        }

        // ------------------------------------------------------------------ build_select

        private static readonly Regex IdRx = new Regex("^[A-Za-z0-9_.\\-]{1,100}$", RegexOptions.Compiled);
        private static FieldInfo selectorsField;

        /// <summary>build_select {buildingId, materials?, facadeId?}. Acks through Commands.Finish.</summary>
        public static void Command(string path, long seq, JObject o)
        {
            string id = o["buildingId"] != null && o["buildingId"].Type == JTokenType.String ? (string)o["buildingId"] : null;
            if (id == null || !IdRx.IsMatch(id)) { Commands.Finish(path, seq, false, "Command malformed"); return; }
            List<string> mats = new List<string>();
            if (o["materials"] != null)
            {
                JArray a = o["materials"] as JArray;
                if (a == null || a.Count > 8) { Commands.Finish(path, seq, false, "Command malformed"); return; }
                foreach (JToken t in a)
                {
                    if (t.Type != JTokenType.String || !IdRx.IsMatch((string)t)) { Commands.Finish(path, seq, false, "Command malformed"); return; }
                    mats.Add((string)t);
                }
            }
            string facade = null;
            if (o["facadeId"] != null)
            {
                if (o["facadeId"].Type != JTokenType.String || !IdRx.IsMatch((string)o["facadeId"])) { Commands.Finish(path, seq, false, "Command malformed"); return; }
                facade = (string)o["facadeId"];
            }
            string msg;
            bool ok = Select(id, mats, facade, out msg);
            Commands.Finish(path, seq, ok, msg);
        }

        private static bool Select(string id, List<string> mats, string facadeId, out string msg)
        {
            if (!LiveWriter.Ready() || PlanScreen.Instance == null || Research.Instance == null) { msg = "No colony is loaded"; return false; }
            PlanScreen ps = PlanScreen.Instance;
            if (!ps.isActiveAndEnabled || ps.ProductInfoScreen == null) { msg = "The game's build menu is not open to the app"; return false; }

            BuildingDef def = FindDef(id);
            if (def == null || !InMenu(def) || !MenuIds().Contains(id) || !Game.IsCorrectDlcActiveForCurrentSave(def)) { msg = "Not available in this game"; return false; }
            if (!Unlocked(def))
            {
                TechItem ti = TechItemOf(def);
                string tn = ti != null && ti.ParentTech != null ? Txt.Clean(ti.ParentTech.Name) : null;
                msg = tn != null ? "Not researched yet: " + tn : "Not researched yet";
                return false;
            }

            Recipe recipe = def.CraftRecipe;
            if (recipe == null || recipe.Ingredients == null) { msg = "Not available in this game"; return false; }
            if (mats.Count > recipe.Ingredients.Count) { msg = "Command malformed"; return false; }

            // Check the wanted materials with the picker's own rules before touching the menu.
            string problem = null;
            Tag[] want = new Tag[mats.Count];
            bool all = DebugHandler.InstantBuildMode || Game.Instance.SandboxModeActive;
            for (int i = 0; i < mats.Count; i++)
            {
                Tag found = default(Tag);
                bool has = false;
                foreach (Cand c in CandidatesFor(def.MaterialCategory[i])) if (c.Id == mats[i]) { found = c.Tag; has = true; break; }
                if (!has) { problem = problem ?? (mats[i] + " does not fit this building"); continue; }
                string name = Txt.Clean(found.ProperName());
                if (!all && !DiscoveredResources.Instance.IsDiscovered(found)) { problem = problem ?? (name + " is not discovered yet"); continue; }
                float have = ClusterManager.Instance.activeWorld.worldInventory.GetAmount(found, true);
                if (!all && have < recipe.Ingredients[i].amount && !MaterialSelector.AllowInsufficientMaterialBuild()) { problem = problem ?? ("Not enough " + name); continue; }
                want[i] = found;
            }

            // The game's own "copy this building" path: opens the category and picks the building like a click.
            string facade = string.IsNullOrEmpty(facadeId) ? "DEFAULT_FACADE" : facadeId;
            ProductInfoScreen pis = ps.ProductInfoScreen;
            bool already = pis.currentDef == def && pis.gameObject.activeInHierarchy && ps.SelectedBuildingGameObject != null;
            try
            {
                if (!already) ps.CopyBuildingOrder(def, facade);
                else if (facadeId != null) pis.FacadeSelectionPanel.SelectedFacade = facade;
            }
            catch (Exception ex)
            {
                Log.Warn("build_select: opening " + id + " failed: " + ex.GetType().Name + ": " + ex.Message);
                msg = "Not available in this game";
                return false;
            }
            if (pis.currentDef != def) { msg = "Not available in this game"; return false; }

            // Pick the wanted materials in the game's own selectors (a click on that toggle: OnSelectMaterial).
            MaterialSelectionPanel panel = pis.materialSelectionPanel;
            List<MaterialSelector> selectors = Selectors(panel);
            for (int i = 0; i < want.Length && selectors != null && i < selectors.Count; i++)
            {
                if (want[i] == default(Tag)) continue;
                MaterialSelector sel = selectors[i];
                if (!sel.ElementToggles.ContainsKey(want[i])) { problem = problem ?? (Txt.Clean(want[i].ProperName()) + " does not fit this building"); continue; }
                if (sel.CurrentSelectedElement != want[i]) sel.OnSelectMaterial(want[i], recipe);
                if (sel.CurrentSelectedElement != want[i]) problem = problem ?? ("Could not pick " + Txt.Clean(want[i].ProperName()));
            }

            if (problem != null) { msg = problem; return false; }
            PlanScreen.RequirementsState st = ps.GetBuildableState(def);
            if (st != PlanScreen.RequirementsState.Complete && !all)
            {
                // The game opened the building anyway and shows why it cannot be placed.
                msg = Txt.Clean(ps.GetTooltipForBuildable(def));
                if (string.IsNullOrEmpty(msg)) msg = "Can't be built now";
                return false;
            }
            msg = "Build menu opened";
            return true;
        }

        private static List<MaterialSelector> Selectors(MaterialSelectionPanel panel)
        {
            if (panel == null) return null;
            if (selectorsField == null) selectorsField = typeof(MaterialSelectionPanel).GetField("materialSelectors", BindingFlags.Instance | BindingFlags.NonPublic);
            return selectorsField != null ? selectorsField.GetValue(panel) as List<MaterialSelector> : null;
        }
    }
}
