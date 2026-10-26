using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using Database;
using Klei.AI;
using TUNING;
using UnityEngine;

namespace OniCompanionLink
{
    /// <summary>
    /// Writes companion/export/gamedata-&lt;build&gt;-&lt;dlcset&gt;.json (schema: contracts/mod-export.schema.json).
    /// Every entry is built inside its own try/catch: a broken entry is skipped and counted, never fatal.
    /// </summary>
    internal static class Exporter
    {
        private static bool running;
        private static int entryErrors;

        public static string FileFor(int build, string dlcSet)
        {
            return Path.Combine(Path.Combine(Env.CompanionDir(), "export"), "gamedata-" + build + "-" + dlcSet + ".json");
        }

        public static void Run(string reason)
        {
            if (Env.Disabled || running) return;
            running = true;
            try
            {
                int build = Env.Build();
                List<string> dlc = Env.ActiveDlc();
                string path = FileFor(build, Env.DlcSetName(dlc));
                if (!((reason == "world load" || reason == "pads ready") && !exportedInWorld) && AlreadyExported(path))
                {
                    Log.Info("export up to date (" + Path.GetFileName(path) + "), skipping [" + reason + "]");
                    return;
                }
                Stopwatch sw = Stopwatch.StartNew();
                entryErrors = 0;
                string json = Build(build, dlc);
                long buildMs = sw.ElapsedMilliseconds;
                Files.WriteAtomic(path, json);
                if (reason == "world load" || reason == "pads ready")
                {
                    exportedInWorld = Actions.Ready();          // the bars may not exist yet at Game.OnSpawn: try again once they do
                    retryWhenPadsReady = !exportedInWorld;
                }
                Log.Info("export written [" + reason + "]: " + Path.GetFileName(path) + ", " + (json.Length / 1024) +
                         " KB, build " + buildMs + " ms, total " + sw.ElapsedMilliseconds + " ms, skipped entries " + entryErrors);
            }
            catch (Exception e)
            {
                Env.Disable("export failed", e);
            }
            finally { running = false; }
        }

        // v1.3: the overlay and tool bars and the per-colony unlock state exist only once a colony is loaded, so the first
        // export of a game session with a colony always runs again (a file written at the main menu lacks them).
        private static bool exportedInWorld, retryWhenPadsReady;

        /// <summary>Main thread, every frame (Commands.Pump): the second export of a session, once the bars exist.</summary>
        public static void Tick()
        {
            if (!retryWhenPadsReady || running || Env.Disabled) return;
            if (!Actions.Ready()) return;
            retryWhenPadsReady = false;
            Run("pads ready");
        }

        // Same (build, DLC set) is in the file name; modVersion is written first so a short read is enough.
        private static bool AlreadyExported(string path)
        {
            try
            {
                if (!File.Exists(path)) return false;
                char[] buf = new char[400];
                int n;
                using (StreamReader r = new StreamReader(path)) n = r.Read(buf, 0, buf.Length);
                string head = new string(buf, 0, n);
                return head.Contains("\"modVersion\":\"" + Env.ModVersion + "\"");
            }
            catch { return false; }
        }

        // ---------------------------------------------------------------- build

        private static string Build(int build, List<string> dlc)
        {
            Json j = new Json(1 << 20);
            j.Obj();
            j.PI("schema", 1);
            j.P("modVersion", Env.ModVersion);
            Env.WriteCompat(j);
            j.PI("build", build);
            j.Key("dlcIds").StrArr(dlc);
            j.P("generatedAt", Env.Now());
            Section(j, "constants", Constants);
            Section(j, "researchTypes", ResearchTypesSection);
            Section(j, "dlcNames", DlcNames);
            Section(j, "buildings", Buildings);
            Section(j, "buildMenu", BuildInfo.MenuSection);
            Section(j, "overlays", Actions.ExportOverlays);
            Section(j, "tools", Actions.ExportTools);
            Section(j, "elements", Elements);
            Section(j, "critters", Critters);
            Section(j, "plants", Plants);
            Section(j, "geysers", Geysers);
            Section(j, "foods", Foods);
            Section(j, "medicines", Medicines);
            Section(j, "recipes", Recipes);
            Section(j, "techs", Techs);
            Section(j, "traits", Traits);
            Section(j, "skills", Skills);
            Section(j, "rooms", Rooms);
            j.EndObj();
            return j.ToString();
        }

        // A failed section yields its key with an empty array (constants: skipped), so the file stays valid.
        private static void Section(Json j, string key, Action<Json> body)
        {
            Stopwatch sw = Stopwatch.StartNew();
            Json inner = new Json(1 << 16);
            try
            {
                body(inner);
                j.Key(key).Raw0(inner.ToString());
                Log.Info("export section " + key + ": " + sw.ElapsedMilliseconds + " ms");
            }
            catch (Exception e)
            {
                Log.Error("export section " + key + " failed, writing empty", e);
                if (key == "dlcNames") j.Key(key).Obj().EndObj();
                else if (key != "constants") j.Key(key).Arr().EndArr();
            }
        }

        private static void Each<T>(Json j, IEnumerable<T> items, Action<Json, T> one)
        {
            j.Arr();
            foreach (T item in items)
            {
                Json e = new Json(512);
                try
                {
                    one(e, item);
                    j.Raw0(e.ToString());
                }
                catch (Exception ex)
                {
                    entryErrors++;
                    Log.Warn("skipped one export entry: " + ex.GetType().Name + ": " + ex.Message);
                }
            }
            j.EndArr();
        }

        private static readonly HashSet<string> warned = new HashSet<string>();

        /// <summary>Optional part of an entry: built on the side and merged only if it worked.</summary>
        private static void Opt(Json e, string what, Action<Json> body)
        {
            Json s = new Json(256);
            try
            {
                s.Obj();
                body(s);
                s.EndObj();
                string t = s.ToString();
                e.Raw(t.Substring(1, t.Length - 2));
            }
            catch (Exception ex)
            {
                entryErrors++;
                if (warned.Add(what)) Log.Warn("optional part '" + what + "' failed (further failures of this kind are not logged): " + ex.GetType().Name + ": " + ex.Message);
            }
        }

        private static void Dlc(Json j, string[] required)
        {
            j.Key("dlc");
            List<string> l = new List<string>();
            if (required != null) foreach (string s in required) if (!string.IsNullOrEmpty(s) && !l.Contains(s)) l.Add(s);
            j.StrArr(l);
        }

        private static string TagText(Tag t) { return t.ToString(); }

        // Element id for a tag when the tag names an element, else null.
        private static string ElementIdOf(Tag t)
        {
            try
            {
                Element e = ElementLoader.GetElement(t);
                if (e != null) return e.id.ToString();
            }
            catch { }
            return null;
        }

        private static void AmountOfTag(Json j, Tag t, double kg, double? tempC = null)
        {
            j.Obj();
            string el = ElementIdOf(t);
            if (el != null) j.P("element", el); else j.P("tag", TagText(t));
            j.P("kg", kg);
            if (tempC.HasValue) j.P("tempC", tempC.Value);
            j.EndObj();
        }

        private static void AmountOfElement(Json j, SimHashes h, double kg, double? tempC = null)
        {
            j.Obj().P("element", h.ToString()).P("kg", kg);
            if (tempC.HasValue) j.P("tempC", tempC.Value);
            j.EndObj();
        }

        // ---------------------------------------------------------------- constants (contract change requested)

        private static void Constants(Json j)
        {
            j.Obj();
            j.P("dupeO2KgPerS", TUNING.DUPLICANTSTATS.STANDARD.BaseStats.OXYGEN_USED_PER_SECOND);

            // Thresholds the game itself uses for duplicant status items. The core's "estimated" warning fallback
            // (views/colony.py) takes its numbers from here and never invents any. Each key is skipped on its own
            // when the game does not expose it. Not exposed by the game as constants (literals inside lambdas):
            // bladder (40 / 100), stamina and the health states, so no key exists for them.
            TUNING.DUPLICANTSTATS d = TUNING.DUPLICANTSTATS.STANDARD;
            Const(j, "stressStressedAt", delegate () { return PrivateConst(typeof(StressMonitor), "StressThreshold_One"); });            // StressMonitor: stressed status from here (0..100)
            Const(j, "stressBreakdownAt", delegate () { return PrivateConst(typeof(StressMonitor), "StressThreshold_Two"); });          // stress at which the duplicant acts out (0..100)
            Const(j, "caloriesHungryFraction", delegate () { return d.BaseStats.HUNGRY_THRESHOLD; });                                    // fraction of max calories
            Const(j, "caloriesStarvingFraction", delegate () { return d.BaseStats.STARVING_THRESHOLD; });                                // fraction of max calories
            Const(j, "breathRetreatAmount", delegate () { return d.Breath.RETREAT_AMOUNT; });                                            // breath units (0..100): below this the duplicant goes to recover breath
            Const(j, "breathSuffocateAmount", delegate () { return d.Breath.SUFFOCATE_AMOUNT; });                                        // breath units: suffocation warning
            Const(j, "bodyTempIdealC", delegate () { return Txt.C(d.Temperature.Internal.IDEAL); });
            Const(j, "bodyTempHypothermiaC", delegate () { return Txt.C(d.Temperature.Internal.THRESHOLD_HYPOTHERMIA); });
            Const(j, "bodyTempHyperthermiaC", delegate () { return Txt.C(d.Temperature.Internal.THRESHOLD_HYPERTHERMIA); });
            Const(j, "bodyTempFatalColdC", delegate () { return Txt.C(d.Temperature.Internal.THRESHOLD_FATAL_COLD); });
            Const(j, "bodyTempFatalHotC", delegate () { return Txt.C(d.Temperature.Internal.THRESHOLD_FATAL_HOT); });
            Const(j, "surroundingsColdC", delegate () { return Txt.C(d.Temperature.External.THRESHOLD_COLD); });                         // ambient: "chilly" below this
            Const(j, "surroundingsHotC", delegate () { return Txt.C(d.Temperature.External.THRESHOLD_HOT); });
            Const(j, "surroundingsScaldingC", delegate () { return Txt.C(d.Temperature.External.THRESHOLD_SCALDING); });

            // v1.3 calculator numbers (contract: constants.toolNumbers), each from the game's own tuning.
            j.Key("toolNumbers").Obj();
            Const(j, "dupeCo2KgPerS", delegate () { return d.BaseStats.OXYGEN_USED_PER_SECOND * d.BaseStats.OXYGEN_TO_CO2_CONVERSION; });   // kg CO2 a duplicant breathes out per second
            j.EndObj();
            j.EndObj();
        }

        private static void Const(Json j, string key, Func<double> get)
        {
            try { j.P(key, get()); }
            catch (Exception e) { Log.Warn("constant " + key + " skipped: " + e.GetType().Name + ": " + e.Message); }
        }

        // Private compile-time constants of a game class (exact numbers, no copy in this mod).
        private static double PrivateConst(Type t, string field)
        {
            System.Reflection.FieldInfo f = t.GetField(field, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
            if (f == null) throw new MissingFieldException(t.Name, field);
            object v = f.IsLiteral ? f.GetRawConstantValue() : f.GetValue(null);
            return Convert.ToDouble(v, System.Globalization.CultureInfo.InvariantCulture);
        }

        // ---------------------------------------------------------------- research types

        private static void ResearchTypesSection(Json j)
        {
            List<ResearchType> types = null;
            try { types = new ResearchTypes().Types; } catch (Exception e) { Log.Warn("ResearchTypes ctor failed: " + e.Message); }
            if (types == null) { j.Arr().EndArr(); return; }
            Each(j, types, delegate (Json e, ResearchType t)
            {
                e.Obj().P("id", t.id).P("name", Txt.Clean(t.name));
                e.EndObj();
            });
        }

        // ---------------------------------------------------------------- elements

        private static string StateOf(Element e)
        {
            if (e.IsVacuum) return "vacuum";
            if (e.IsGas) return "gas";
            if (e.IsLiquid) return "liquid";
            return "solid";
        }

        private static void Transition(Json j, string key, float tempK, SimHashes target, SimHashes ore, float oreRatio)
        {
            j.Key(key).Obj().P("tempC", Txt.C(tempK)).P("target", target.ToString());
            if (ore != SimHashes.Vacuum && oreRatio > 0f)
            {
                j.P("targetKgRatio", 1.0 - oreRatio);
                j.P("secondary", ore.ToString());
            }
            j.EndObj();
        }

        private static void Elements(Json j)
        {
            Each(j, ElementLoader.elements, delegate (Json e, Element el)
            {
                e.Obj().P("id", el.id.ToString()).P("name", Txt.Clean(el.name));
                Dlc(e, string.IsNullOrEmpty(el.dlcId) ? null : new[] { el.dlcId });
                e.P("state", StateOf(el));
                List<string> tags = new List<string>();
                if (el.materialCategory.IsValid) tags.Add(el.materialCategory.Name);
                if (el.oreTags != null) foreach (Tag t in el.oreTags) if (!tags.Contains(t.Name)) tags.Add(t.Name);
                e.Key("tags").StrArr(tags);
                e.P("specificHeat", el.specificHeatCapacity);
                e.P("thermalConductivity", el.thermalConductivity);
                e.P("molarMass", el.molarMass);
                e.P("maxMass", el.maxMass);
                e.P("hardness", el.hardness);
                if (el.HasTransitionUp)
                    Transition(e, "highTransition", el.highTemp, el.highTempTransitionTarget, el.highTempTransitionOreID, el.highTempTransitionOreMassConversion);
                if (el.lowTempTransitionTarget != 0 && el.lowTempTransitionTarget != SimHashes.Unobtanium && el.lowTempTransition != null && el.lowTempTransition != el)
                    Transition(e, "lowTransition", el.lowTemp, el.lowTempTransitionTarget, el.lowTempTransitionOreID, el.lowTempTransitionOreMassConversion);
                e.EndObj();
            });
        }

        // ---------------------------------------------------------------- buildings

        private static Dictionary<string, string> BuildingCategories()
        {
            // PlanInfo.category is a HashedString (hash only). Map the hashes of the category ids used in TUNING.BUILDINGS.PLANORDER.
            string[] known = { "Base", "Oxygen", "Power", "Food", "Plumbing", "HVAC", "Refining", "Medical", "Furniture", "Equipment",
                               "Utilities", "Automation", "Conveyance", "Rocketry", "HEP" };
            Dictionary<int, string> byHash = new Dictionary<int, string>();
            foreach (string k in known) byHash[new HashedString(k).HashValue] = k;
            Dictionary<string, string> map = new Dictionary<string, string>();
            foreach (PlanScreen.PlanInfo pi in TUNING.BUILDINGS.PLANORDER)
            {
                string cat;
                if (!byHash.TryGetValue(pi.category.HashValue, out cat)) cat = pi.category.ToString();
                foreach (KeyValuePair<string, string> kv in pi.buildingAndSubcategoryData)
                    if (!map.ContainsKey(kv.Key)) map[kv.Key] = cat;
            }
            return map;
        }

        private static Dictionary<string, string> ItemToTech()
        {
            Dictionary<string, string> map = new Dictionary<string, string>();
            foreach (Tech t in Db.Get().Techs.resources)
                foreach (string id in t.unlockedItemIDs)
                    if (!map.ContainsKey(id)) map[id] = t.Id;
            return map;
        }

        private static string PortKind(ConduitType t)
        {
            switch (t)
            {
                case ConduitType.Gas: return "gas";
                case ConduitType.Liquid: return "liquid";
                case ConduitType.Solid: return "solid";
                default: return null;
            }
        }

        private static void Port(Json j, string kind, string dir, CellOffset off, double? maxKg = null, double? maxW = null)
        {
            j.Obj().P("kind", kind).P("direction", dir);
            j.Key("offset").Obj().PI("x", off.x).PI("y", off.y).EndObj();
            if (maxKg.HasValue && !double.IsInfinity(maxKg.Value)) j.P("maxKgPerS", maxKg.Value);
            if (maxW.HasValue) j.P("maxW", maxW.Value);
            j.EndObj();
        }

        private static void Buildings(Json j)
        {
            Dictionary<string, string> cats = BuildingCategories();
            Dictionary<string, string> techOf = ItemToTech();
            List<BuildingDef> defs = new List<BuildingDef>();
            foreach (BuildingDef d in Assets.BuildingDefs) if (d != null && !d.Deprecated && !d.DebugOnly) defs.Add(d);
            defs.Sort(delegate (BuildingDef a, BuildingDef b) { return string.CompareOrdinal(a.PrefabID, b.PrefabID); });

            Each(j, defs, delegate (Json e, BuildingDef d)
            {
                GameObject go = d.BuildingComplete;
                e.Obj().P("id", d.PrefabID).P("name", Txt.Clean(d.Name));
                Dlc(e, d.RequiredDlcIds);
                e.P("desc", Txt.Clean(d.Desc)).P("effect", Txt.Clean(d.Effect));
                string cat;
                e.P("category", cats.TryGetValue(d.PrefabID, out cat) ? cat : "Uncategorized");
                e.Key("size").Obj().PI("w", d.WidthInCells).PI("h", d.HeightInCells).EndObj();
                e.P("hp", d.HitPoints);
                e.P("buildTimeS", d.ConstructionTime);

                if (d.MaterialCategory != null && d.Mass != null)
                {
                    e.Key("materials").Arr();
                    for (int i = 0; i < d.MaterialCategory.Length && i < d.Mass.Length; i++)
                    {
                        e.Obj().Key("tags").StrArr(d.MaterialCategory[i].Split('&')).P("kg", d.Mass[i]);
                        BuildInfo.SlotExtras(e, d.MaterialCategory[i]);
                        e.EndObj();
                    }
                    e.EndArr();
                }
                e.Key("decor").Obj().P("value", d.BaseDecor).P("radius", d.BaseDecorRadius).EndObj();
                e.Key("noise").Obj().P("value", d.BaseNoisePollution).P("radius", d.BaseNoisePollutionRadius).EndObj();

                e.Key("power").Obj();
                if (d.EnergyConsumptionWhenActive > 0f) e.P("usesW", d.EnergyConsumptionWhenActive);
                if (d.GeneratorWattageRating > 0f) e.P("generatesW", d.GeneratorWattageRating);
                e.EndObj();

                e.Key("heat").Obj();
                if (d.ExhaustKilowattsWhenActive != 0f) e.P("exhaustKDtuPerS", d.ExhaustKilowattsWhenActive);
                if (d.SelfHeatKilowattsWhenActive != 0f) e.P("selfKDtuPerS", d.SelfHeatKilowattsWhenActive);
                e.EndObj();

                if (d.Overheatable) e.P("overheatC", Txt.C(d.OverheatTemperature));

                Opt(e, "building.ports", delegate (Json p)
                {
                    p.Key("ports").Arr();
                    ConduitConsumer cc = go != null ? go.GetComponent<ConduitConsumer>() : null;
                    string inKind = PortKind(d.InputConduitType);
                    if (inKind != null) Port(p, inKind, "in", d.UtilityInputOffset, cc != null ? (double?)cc.consumptionRate : null);
                    string outKind = PortKind(d.OutputConduitType);
                    if (outKind != null) Port(p, outKind, "out", d.UtilityOutputOffset);
                    if (go != null)
                    {
                        foreach (ISecondaryInput si in go.GetComponents<ISecondaryInput>())
                            foreach (ConduitType t in new[] { ConduitType.Gas, ConduitType.Liquid, ConduitType.Solid })
                                if (si.HasSecondaryConduitType(t)) Port(p, PortKind(t), "in", si.GetSecondaryConduitOffset(t));
                        foreach (ISecondaryOutput so in go.GetComponents<ISecondaryOutput>())
                            foreach (ConduitType t in new[] { ConduitType.Gas, ConduitType.Liquid, ConduitType.Solid })
                                if (so.HasSecondaryConduitType(t)) Port(p, PortKind(t), "out", so.GetSecondaryConduitOffset(t));
                    }
                    if (d.RequiresPowerInput) Port(p, "power", "in", d.PowerInputOffset, null, d.EnergyConsumptionWhenActive);
                    if (d.RequiresPowerOutput) Port(p, "power", "out", d.PowerOutputOffset, null, d.GeneratorWattageRating);
                    if (d.LogicInputPorts != null) foreach (LogicPorts.Port lp in d.LogicInputPorts) LogicPort(p, "in", lp);
                    if (d.LogicOutputPorts != null) foreach (LogicPorts.Port lp in d.LogicOutputPorts) LogicPort(p, "out", lp);
                    p.EndArr();
                });

                Opt(e, "building.converters", delegate (Json p)
                {
                    p.Key("converters").Arr();
                    if (go != null) Converters(p, go);
                    p.EndArr();
                });

                if (go != null)
                    Opt(e, "building.storage", delegate (Json p)
                    {
                        float cap = 0f; bool any = false;
                        foreach (Storage st in go.GetComponents<Storage>()) { cap += st.capacityKg; any = true; }
                        if (any) p.Key("storage").Obj().P("capacityKg", cap).EndObj();
                    });

                string tech;
                if (techOf.TryGetValue(d.PrefabID, out tech)) e.P("tech", tech); else e.Key("tech").Null();
                BuildInfo.BuildingExtras(e, d);
                e.EndObj();
            });
        }

        // Logic ports: the game's building info lists a port by LogicPorts.Port.description and tooltips it with the active /
        // inactive descriptions (LogicPorts.GetDescriptors), so those are the name and the green / red texts.
        private static void LogicPort(Json j, string dir, LogicPorts.Port lp)
        {
            j.Obj().P("kind", "logic").P("direction", dir);
            j.Key("offset").Obj().PI("x", lp.cellOffset.x).PI("y", lp.cellOffset.y).EndObj();
            string name = Txt.Clean(lp.description), green = Txt.Clean(lp.activeDescription), red = Txt.Clean(lp.inactiveDescription);
            if (name.Length > 0) j.P("name", name);
            if (green.Length > 0) j.P("greenText", green);
            if (red.Length > 0) j.P("redText", red);
            j.EndObj();
        }

        // DLC id -> the game's own title (DlcManager.GetDlcTitleNoFormatting reads STRINGS.UI.<X>.NAME) for every DLC the game knows.
        private static void DlcNames(Json j)
        {
            j.Obj();
            List<string> ids = new List<string> { "EXPANSION1_ID" };
            foreach (string id in DlcManager.DLC_PACKS.Keys) if (!ids.Contains(id)) ids.Add(id);
            foreach (string id in ids)
            {
                string n = Txt.Clean(DlcManager.GetDlcTitleNoFormatting(id));
                if (n.Length > 0) j.P(id, n);
            }
            j.EndObj();
        }

        private static void Converters(Json e, GameObject go)
        {
            foreach (ElementConverter ec in go.GetComponents<ElementConverter>())
            {
                e.Obj().P("label", "ElementConverter");
                e.Key("inputs").Arr();
                if (ec.consumedElements != null)
                    foreach (ElementConverter.ConsumedElement ce in ec.consumedElements) AmountOfTag(e, ce.Tag, ce.MassConsumptionRate);
                e.EndArr();
                e.Key("outputs").Arr();
                if (ec.outputElements != null)
                    foreach (ElementConverter.OutputElement oe in ec.outputElements)
                        AmountOfElement(e, oe.elementHash, oe.massGenerationRate, oe.useEntityTemperature ? (double?)null : Txt.C(oe.minOutputTemperature));
                e.EndArr();
                e.EndObj();
            }
            foreach (EnergyGenerator eg in go.GetComponents<EnergyGenerator>())
            {
                if (eg.formula.inputs == null && eg.formula.outputs == null) continue;
                e.Obj().P("label", "EnergyGenerator");
                e.Key("inputs").Arr();
                if (eg.formula.inputs != null) foreach (EnergyGenerator.InputItem it in eg.formula.inputs) AmountOfTag(e, it.tag, it.consumptionRate);
                e.EndArr();
                e.Key("outputs").Arr();
                if (eg.formula.outputs != null) foreach (EnergyGenerator.OutputItem ot in eg.formula.outputs) AmountOfElement(e, ot.element, ot.creationRate, Txt.C(ot.minTemperature));
                e.EndArr();
                e.EndObj();
            }
            foreach (ElementConsumer ec in go.GetComponents<ElementConsumer>())
            {
                if (ec.elementToConsume == SimHashes.Vacuum) continue;
                e.Obj().P("label", "ElementConsumer");
                e.Key("inputs").Arr();
                AmountOfElement(e, ec.elementToConsume, ec.consumptionRate);
                e.EndArr();
                e.Key("outputs").Arr().EndArr();
                e.EndObj();
            }
            foreach (ElementEmitter em in go.GetComponents<ElementEmitter>())
            {
                if (em.outputElement.massGenerationRate <= 0f) continue;
                e.Obj().P("label", "ElementEmitter");
                e.Key("inputs").Arr().EndArr();
                e.Key("outputs").Arr();
                AmountOfElement(e, em.outputElement.elementHash, em.outputElement.massGenerationRate / Math.Max(em.emissionFrequency, 0.0001f),
                                em.outputElement.useEntityTemperature ? (double?)null : Txt.C(em.outputElement.minOutputTemperature));
                e.EndArr();
                e.EndObj();
            }
        }

        // ---------------------------------------------------------------- critters / plants

        private static IEnumerable<GameObject> Prefabs()
        {
            foreach (KPrefabID k in Assets.Prefabs) if (k != null) yield return k.gameObject;
        }

        private static string[] DlcOf(GameObject go)
        {
            KPrefabID k = go.GetComponent<KPrefabID>();
            return k != null ? k.requiredDlcIds : null;
        }

        private static void TempRange(Json j, float idealLo, float idealHi, float lethalLo, float lethalHi)
        {
            j.Key("temperatureC").Obj();
            j.P("idealLo", Txt.C(idealLo)).P("idealHi", Txt.C(idealHi)).P("lethalLo", Txt.C(lethalLo)).P("lethalHi", Txt.C(lethalHi));
            j.EndObj();
        }

        private static float TraitValue(string traitId, string attributeId)
        {
            Trait t = Db.Get().traits.TryGet(traitId);
            if (t == null) return 0f;
            foreach (AttributeModifier m in t.SelfModifiers) if (m.AttributeId == attributeId) return m.Value;
            return 0f;
        }

        private static void Critters(Json j)
        {
            List<GameObject> list = new List<GameObject>();
            foreach (GameObject go in Prefabs())
            {
                if (!go.HasTag(GameTags.Creature)) continue;
                StateMachineController smc = go.GetComponent<StateMachineController>();
                if (smc == null || smc.GetDef<CreatureCalorieMonitor.Def>() == null) continue;
                if (smc.GetDef<BabyMonitor.Def>() != null) continue;   // babies are covered by their adult
                list.Add(go);
            }
            list.Sort(delegate (GameObject a, GameObject b) { return string.CompareOrdinal(a.PrefabID().Name, b.PrefabID().Name); });

            Each(j, list, delegate (Json e, GameObject go)
            {
                StateMachineController smc = go.GetComponent<StateMachineController>();
                CreatureCalorieMonitor.Def cal = smc.GetDef<CreatureCalorieMonitor.Def>();
                Modifiers mods = go.GetComponent<Modifiers>();
                string traitId = mods != null && mods.initialTraits != null && mods.initialTraits.Count > 0 ? mods.initialTraits[0] : null;
                e.Obj().P("id", go.PrefabID().Name).P("name", Txt.Clean(go.GetProperName()));
                Dlc(e, DlcOf(go));

                // diets: one per Diet.Info; kg per cycle = what one full cycle of calories buys
                Opt(e, "critter.diets", delegate (Json p)
                {
                    float lossPerS = traitId != null ? -TraitValue(traitId, Db.Get().Amounts.Calories.deltaAttribute.Id) : 0f;   // cal/s
                    p.Key("diets").Arr();
                    if (cal.diet != null && cal.diet.infos != null && lossPerS > 0f)
                    {
                        foreach (Diet.Info info in cal.diet.infos)
                        {
                            if (info.caloriesPerKg <= 0f) continue;
                            float consumedKgPerCycle = lossPerS * 600f / info.caloriesPerKg;
                            p.Obj();
                            p.Key("consumes").Arr();
                            foreach (Tag t in info.consumedTags) AmountOfTag(p, t, consumedKgPerCycle);
                            p.EndArr();
                            p.Key("produces").Arr();
                            if (info.producedElement.IsValid) AmountOfTag(p, info.producedElement, consumedKgPerCycle * info.producedConversionRate);
                            p.EndArr();
                            p.P("caloriesPerCycle", lossPerS * 600f / 1000f);   // kcal
                            p.EndObj();
                        }
                    }
                    p.EndArr();
                });

                Opt(e, "critter.temperature", delegate (Json p)
                {
                    CritterTemperatureMonitor.Def tdef = smc.GetDef<CritterTemperatureMonitor.Def>();
                    if (tdef != null)
                        TempRange(p, tdef.temperatureColdUncomfortable, tdef.temperatureHotUncomfortable, tdef.temperatureColdDeadly, tdef.temperatureHotDeadly);
                });

                Opt(e, "critter.lifespan", delegate (Json p)
                {
                    if (traitId == null) return;
                    float life = TraitValue(traitId, Db.Get().Amounts.Age.maxAttribute.Id);
                    if (life > 0f) p.P("lifespanCycles", life);
                });

                Opt(e, "critter.egg", delegate (Json p)
                {
                    FertilityMonitor.Def fert = smc.GetDef<FertilityMonitor.Def>();
                    if (fert == null || !fert.eggPrefab.IsValid) return;
                    p.Key("egg").Obj().P("id", fert.eggPrefab.Name);
                    if (fert.baseFertileCycles > 0f) p.P("incubationCycles", fert.baseFertileCycles);   // base fertile cycles
                    p.EndObj();
                    if (fert.initialBreedingWeights != null)
                    {
                        List<string> morphs = new List<string>();
                        foreach (FertilityMonitor.BreedingChance bc in fert.initialBreedingWeights)
                        {
                            if (bc.egg == fert.eggPrefab) continue;
                            string n = bc.egg.Name;
                            if (n.EndsWith("Egg")) n = n.Substring(0, n.Length - 3);
                            if (!morphs.Contains(n)) morphs.Add(n);
                        }
                        p.Key("morphs").StrArr(morphs);
                    }
                });
                e.EndObj();
            });
        }

        private static void Plants(Json j)
        {
            List<GameObject> list = new List<GameObject>();
            foreach (GameObject go in Prefabs())
            {
                if (!go.HasTag(GameTags.Plant)) continue;
                if (go.GetComponent<Crop>() == null && go.GetComponent<TemperatureVulnerable>() == null) continue;
                list.Add(go);
            }
            list.Sort(delegate (GameObject a, GameObject b) { return string.CompareOrdinal(a.PrefabID().Name, b.PrefabID().Name); });

            Each(j, list, delegate (Json e, GameObject go)
            {
                StateMachineController smc = go.GetComponent<StateMachineController>();
                Crop crop = go.GetComponent<Crop>();
                e.Obj().P("id", go.PrefabID().Name).P("name", Txt.Clean(go.GetProperName()));
                Dlc(e, DlcOf(go));
                if (crop != null && crop.cropVal.cropDuration > 0f) e.P("growthCycles", crop.cropVal.cropDuration / 600f);

                Opt(e, "plant.temperature", delegate (Json p)
                {
                    TemperatureVulnerable tv = go.GetComponent<TemperatureVulnerable>();
                    if (tv != null) TempRange(p, tv.TemperatureWarningLow, tv.TemperatureWarningHigh, tv.TemperatureLethalLow, tv.TemperatureLethalHigh);
                });

                Opt(e, "plant.pressure", delegate (Json p)
                {
                    PressureVulnerable pv = go.GetComponent<PressureVulnerable>();
                    if (pv == null || !pv.pressure_sensitive) return;
                    p.Key("pressureKg").Obj().P("min", pv.pressureWarning_Low).P("max", pv.pressureWarning_High).EndObj();
                    List<string> atmo = new List<string>();
                    if (pv.safe_atmospheres != null) foreach (Element el in pv.safe_atmospheres) atmo.Add(el.id.ToString());
                    atmo.Sort(StringComparer.Ordinal);
                    p.Key("atmosphere").StrArr(atmo);
                });

                Opt(e, "plant.irrigation", delegate (Json p)
                {
                    IrrigationMonitor.Def irr = smc != null ? smc.GetDef<IrrigationMonitor.Def>() : null;
                    if (irr == null || irr.consumedElements == null) return;
                    p.Key("irrigation").Arr();
                    foreach (PlantElementAbsorber.ConsumeInfo ci in irr.consumedElements) AmountOfTag(p, ci.tag, ci.massConsumptionRate);
                    p.EndArr();
                });

                Opt(e, "plant.fertilizer", delegate (Json p)
                {
                    FertilizationMonitor.Def fer = smc != null ? smc.GetDef<FertilizationMonitor.Def>() : null;
                    if (fer == null || fer.consumedElements == null) return;
                    p.Key("fertilizer").Arr();
                    foreach (PlantElementAbsorber.ConsumeInfo ci in fer.consumedElements) AmountOfTag(p, ci.tag, ci.massConsumptionRate);
                    p.EndArr();
                });

                Opt(e, "plant.light", delegate (Json p)
                {
                    IlluminationVulnerable iv = go.GetComponent<IlluminationVulnerable>();
                    if (iv != null && !iv.prefersDarkness && iv.LightIntensityThreshold > 0) p.P("lightLux", iv.LightIntensityThreshold);
                });

                Opt(e, "plant.yield", delegate (Json p)
                {
                    if (crop == null || string.IsNullOrEmpty(crop.cropVal.cropId)) return;
                    GameObject cropPrefab = Assets.TryGetPrefab(new Tag(crop.cropVal.cropId));
                    PrimaryElement cpe = cropPrefab != null ? cropPrefab.GetComponent<PrimaryElement>() : null;
                    float unitKg = cpe != null ? cpe.Mass : 1f;
                    p.Key("yield").Arr();
                    AmountOfTag(p, new Tag(crop.cropVal.cropId), unitKg * crop.cropVal.numProduced);   // per harvest
                    p.EndArr();
                });
                e.EndObj();
            });
        }

        // ---------------------------------------------------------------- geysers

        private static void Range(Json j, string key, double min, double max)
        {
            j.Key(key).Obj().P("min", min).P("max", max).EndObj();
        }

        private static void Geysers(Json j)
        {
            FieldInfo f = typeof(GeyserConfigurator).GetField("geyserTypes", BindingFlags.NonPublic | BindingFlags.Static);
            List<GeyserConfigurator.GeyserType> types = f != null ? f.GetValue(null) as List<GeyserConfigurator.GeyserType> : null;
            if (types == null) { j.Arr().EndArr(); return; }
            List<GeyserConfigurator.GeyserType> list = new List<GeyserConfigurator.GeyserType>(types);
            list.Sort(delegate (GeyserConfigurator.GeyserType a, GeyserConfigurator.GeyserType b) { return string.CompareOrdinal(a.id, b.id); });
            Each(j, list, delegate (Json e, GeyserConfigurator.GeyserType g)
            {
                string up = g.id.ToUpperInvariant();
                e.Obj().P("id", g.id);
                e.P("name", Txt.Clean(Strings.Get("STRINGS.CREATURES.SPECIES.GEYSER." + up + ".NAME")));
                Dlc(e, g.requiredDlcIds);
                e.P("desc", Txt.Clean(Strings.Get("STRINGS.CREATURES.SPECIES.GEYSER." + up + ".DESC")));
                e.P("element", g.element.ToString());
                e.P("tempC", Txt.C(g.temperature));
                Range(e, "rateKgPerS", g.minRatePerCycle / 600.0, g.maxRatePerCycle / 600.0);          // average over a whole cycle while active
                Range(e, "massPerCycleKg", g.minRatePerCycle, g.maxRatePerCycle);                       // extra field
                Range(e, "eruptionIterationS", g.minIterationLength, g.maxIterationLength);
                Range(e, "eruptDurationFraction", g.minIterationPercent, g.maxIterationPercent);
                Range(e, "activeCycles", g.minYearLength * g.minYearPercent / 600.0, g.maxYearLength * g.maxYearPercent / 600.0);
                Range(e, "dormantCycles", g.minYearLength * (1.0 - g.maxYearPercent) / 600.0, g.maxYearLength * (1.0 - g.minYearPercent) / 600.0);
                Range(e, "activeFractionOfYear", g.minYearPercent, g.maxYearPercent);
                Range(e, "yearLengthS", g.minYearLength, g.maxYearLength);                              // extra field
                e.P("maxPressureKg", g.maxPressure);                                                   // extra field
                e.EndObj();
            });
        }

        // ---------------------------------------------------------------- foods / medicines / recipes

        private static void Foods(Json j)
        {
            List<EdiblesManager.FoodInfo> foods = new List<EdiblesManager.FoodInfo>(EdiblesManager.GetAllLoadedFoodTypes());
            foods.Sort(delegate (EdiblesManager.FoodInfo a, EdiblesManager.FoodInfo b) { return string.CompareOrdinal(a.Id, b.Id); });
            Each(j, foods, delegate (Json e, EdiblesManager.FoodInfo f)
            {
                e.Obj().P("id", f.Id).P("name", Txt.Clean(f.Name));
                Dlc(e, f.GetRequiredDlcIds());
                e.P("desc", Txt.Clean(f.Description));
                e.P("kcal", f.CaloriesPerUnit / 1000f);
                e.PI("quality", f.Quality);
                if (f.CanRot) e.P("spoilTimeS", f.SpoilTime); else e.Key("spoilTimeS").Null();
                e.Key("effects").StrArr(f.Effects);
                e.EndObj();
            });
        }

        private static void Medicines(Json j)
        {
            List<GameObject> list = new List<GameObject>();
            foreach (GameObject go in Prefabs()) if (go.GetComponent<MedicinalPill>() != null) list.Add(go);
            list.Sort(delegate (GameObject a, GameObject b) { return string.CompareOrdinal(a.PrefabID().Name, b.PrefabID().Name); });
            Each(j, list, delegate (Json e, GameObject go)
            {
                MedicineInfo info = go.GetComponent<MedicinalPill>().info;
                e.Obj().P("id", go.PrefabID().Name).P("name", Txt.Clean(go.GetProperName()));
                Dlc(e, DlcOf(go));
                e.Key("cures").StrArr(info.curedSicknesses);
                if (!string.IsNullOrEmpty(info.effect)) e.P("effect", info.effect);
                e.EndObj();
            });
        }

        private static void Recipes(Json j)
        {
            List<ComplexRecipe> list = new List<ComplexRecipe>(ComplexRecipeManager.Get().recipes);
            list.Sort(delegate (ComplexRecipe a, ComplexRecipe b) { return string.CompareOrdinal(a.id, b.id); });
            Each(j, list, delegate (Json e, ComplexRecipe r)
            {
                if (r.fabricators == null || r.fabricators.Count == 0) throw new InvalidOperationException("recipe without fabricator");
                string name = !string.IsNullOrEmpty(r.customName) ? r.customName : (r.results != null && r.results.Length > 0 ? r.results[0].material.ProperName() : r.id);
                e.Obj().P("id", r.id).P("name", Txt.Clean(name));
                Dlc(e, r.GetRequiredDlcIds());
                e.P("fabricator", r.fabricators[0].Name);
                e.Key("inputs").Arr();
                foreach (ComplexRecipe.RecipeElement el in r.ingredients) AmountOfTag(e, el.material, el.amount);
                e.EndArr();
                e.Key("outputs").Arr();
                foreach (ComplexRecipe.RecipeElement el in r.results) AmountOfTag(e, el.material, el.amount);
                e.EndArr();
                e.P("timeS", r.time);
                e.EndObj();
            });
        }

        // ---------------------------------------------------------------- research / traits / skills / rooms

        private static void Techs(Json j)
        {
            List<Tech> list = new List<Tech>(Db.Get().Techs.resources);
            list.Sort(delegate (Tech a, Tech b) { return string.CompareOrdinal(a.Id, b.Id); });
            Each(j, list, delegate (Json e, Tech t)
            {
                e.Obj().P("id", t.Id).P("name", Txt.Clean(t.Name));
                // Techs carry no DLC restriction in the game; use the DLC every unlocked item requires.
                List<string> dlc = null;
                foreach (TechItem ti in t.unlockedItems)
                {
                    string[] r = ti.requiredDlcIds;
                    if (r == null || r.Length == 0) { dlc = new List<string>(); break; }
                    if (dlc == null) dlc = new List<string>(r);
                    else dlc = dlc.Intersect(r).ToList();
                }
                Dlc(e, dlc != null ? dlc.ToArray() : null);
                e.P("desc", Txt.Clean(t.desc));
                e.Key("cost").Obj();
                foreach (KeyValuePair<string, float> kv in t.costsByResearchTypeID) e.P(kv.Key, kv.Value);
                e.EndObj();
                e.Key("requires").Arr();
                foreach (Tech r in t.requiredTech) e.Str(r.Id);
                e.EndArr();
                e.Key("unlocks").Arr();
                foreach (string id in t.unlockedItemIDs)
                {
                    BuildingDef bd = Assets.GetBuildingDef(id);
                    e.Obj().P("kind", bd != null ? "building" : "recipe").P("id", id).EndObj();
                }
                e.EndArr();
                e.EndObj();
            });
        }

        private static void Traits(Json j)
        {
            // Duplicant traits only (critter base traits live in the same set and are left out).
            Dictionary<string, string> kindOf = new Dictionary<string, string>();
            // The DLC rule of a trait lives on its TraitVal (e.g. GrantSkill_Swimming: DLC5); the Trait object made by
            // TraitUtil.CreateSkillGrantingTrait carries none (Thor, base game, 0.4.2 still crashed).
            Dictionary<string, DUPLICANTSTATS.TraitVal> valOf = new Dictionary<string, DUPLICANTSTATS.TraitVal>();
            Action<List<DUPLICANTSTATS.TraitVal>, string> add = delegate (List<DUPLICANTSTATS.TraitVal> l, string kind)
            {
                foreach (DUPLICANTSTATS.TraitVal v in l)
                    if (!string.IsNullOrEmpty(v.id) && !kindOf.ContainsKey(v.id)) { kindOf[v.id] = kind; valOf[v.id] = v; }
            };
            add(DUPLICANTSTATS.GOODTRAITS, "good");
            add(DUPLICANTSTATS.BADTRAITS, "bad");
            add(DUPLICANTSTATS.CONGENITALTRAITS, "congenital");
            add(DUPLICANTSTATS.GENESHUFFLERTRAITS, "genetic");
            add(DUPLICANTSTATS.STRESSTRAITS, "other");
            add(DUPLICANTSTATS.JOYTRAITS, "other");
            add(DUPLICANTSTATS.NEEDTRAITS, "other");
            add(DUPLICANTSTATS.SPECIALTRAITS, "other");
            add(DUPLICANTSTATS.BIONICBUGTRAITS, "bad");
            add(DUPLICANTSTATS.BIONICUPGRADETRAITS, "other");

            List<Trait> list = new List<Trait>();
            foreach (Trait t in Db.Get().traits.resources) if (kindOf.ContainsKey(t.Id)) list.Add(t);
            list.Sort(delegate (Trait a, Trait b) { return string.CompareOrdinal(a.Id, b.Id); });
            Each(j, list, delegate (Json e, Trait t)
            {
                e.Obj().P("id", t.Id).P("name", Txt.Clean(t.Name));
                DUPLICANTSTATS.TraitVal tv;
                bool hasVal = valOf.TryGetValue(t.Id, out tv);
                string[] req = t.requiredDlcIds ?? (hasVal ? tv.GetRequiredDlcIds() : null);
                Dlc(e, req);
                // Only for traits whose DLC is active: the tooltip of a DLC trait looks up DLC content (GrantSkill_Swimming ->
                // skill Swimming, DLC5) and the game logs an ERROR when it is missing, which its crash screen blames on this
                // mod (Thor, base game only, 0.4.1). try/catch cannot stop a logged error.
                string d = "";
                bool active = DlcManager.IsCorrectDlcSubscribed(t.requiredDlcIds, t.forbiddenDlcIds) &&
                              (!hasVal || DlcManager.IsCorrectDlcSubscribed(tv));
                if (active) { try { d = t.GetTooltip(); } catch { } }
                e.P("desc", Txt.Clean(d));
                e.P("kind", kindOf[t.Id]);
                e.EndObj();
            });
        }

        private static void Skills(Json j)
        {
            List<Skill> list = new List<Skill>(Db.Get().Skills.resources);
            list.Sort(delegate (Skill a, Skill b) { return string.CompareOrdinal(a.Id, b.Id); });
            Each(j, list, delegate (Json e, Skill s)
            {
                if (s.deprecated) throw new InvalidOperationException("deprecated");
                e.Obj().P("id", s.Id).P("name", Txt.Clean(s.Name));
                Dlc(e, s.requiredDlcIds);
                e.P("desc", Txt.Clean(s.description));
                e.PI("tier", s.tier);
                e.P("group", s.skillGroup ?? "");
                e.Key("requires").StrArr(s.priorSkills);
                List<string> perks = new List<string>();
                if (s.perks != null) foreach (SkillPerk p in s.perks) perks.Add(p.Id);
                e.Key("unlocks").StrArr(perks);
                e.EndObj();
            });
        }

        private static void Rooms(Json j)
        {
            List<RoomType> list = new List<RoomType>(Db.Get().RoomTypes.resources);
            list.Sort(delegate (RoomType a, RoomType b) { return string.CompareOrdinal(a.Id, b.Id); });
            Each(j, list, delegate (Json e, RoomType r)
            {
                e.Obj().P("id", r.Id).P("name", Txt.Clean(r.Name));
                Dlc(e, null);
                e.P("desc", Txt.Clean(r.description));
                List<string> eff = new List<string>();
                if (r.effects != null) eff.AddRange(r.effects);
                e.Key("effects").StrArr(eff);
                List<string> req = new List<string>();
                if (r.primary_constraint != null) req.Add(Txt.Clean(r.primary_constraint.name));
                if (r.additional_constraints != null) foreach (RoomConstraints.Constraint c in r.additional_constraints) req.Add(Txt.Clean(c.name));
                e.Key("requirements").StrArr(req);
                e.EndObj();
            });
        }
    }
}
