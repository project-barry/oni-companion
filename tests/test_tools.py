"""Calculator tests. Numbers are hand-worked in comments; data is the synthetic export."""

import copy
import json
import os
import unittest

from tests.jsonschema_mini import Validator
from core.oni_companion.tools import (DataProblem, ToolError, UnknownTool, form_screen,
                                      list_tools, run_tool)
from core.oni_companion.tools import element_state as es
from core.oni_companion.tools import geyser, o2, critter_ranch, power, heat
from core.oni_companion.tools.common import Num

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
with open(os.path.join(ROOT, "fixtures", "synthetic", "mod", "export.json"), encoding="utf-8") as f:
    EXPORT = json.load(f)

AS_OF = "2026-10-25T12:00:00Z"


def data(**extra):
    d = copy.deepcopy(EXPORT)
    d.update(extra)
    return d


def blocks_of(screen, kind):
    return [b for b in screen["blocks"] if b["type"] == kind]


def stat_value(screen, label):
    for b in blocks_of(screen, "stats"):
        for r in b["rows"]:
            if r["label"] == label:
                return r["value"]
    raise KeyError(label)


class ScreensValidate(unittest.TestCase):
    """Every Screen the tools produce must validate against screen.schema.json."""

    @classmethod
    def setUpClass(cls):
        cls.v = Validator(CONTRACTS)

    def assertValid(self, screen):
        errs = self.v.validate(screen, "screen.schema.json")
        self.assertEqual(errs, [], errs[:3])
        json.dumps(screen)  # must serialize

    def test_every_form_screen_validates(self):
        for t in list_tools()["tools"]:
            self.assertValid(form_screen(t["id"], data()))

    def test_every_result_screen_validates(self):
        d = data(constants={"dupeO2KgPerS": 0.01})
        cases = {
            "heat": {"mass": {"value": 5, "unit": "kg"}, "element": "SynthWidgetium",
                     "deltaT": 20, "mode": "heat", "useKelvin": False},
            "element-state": {"element": "SynthWidgetium", "temperature": 150},
            "geyser-average": {"geyser": "SynthGeyser"},
            "o2-duplicants": {"supply": {"value": 100, "unit": "g/s"}},
            "critter-ranch": {"critter": "SynthBeast", "count": 10},
            "power-budget": {"building1": "SynthWidgetMaker", "building2": "SynthLamp"},
        }
        for tid, vals in cases.items():
            self.assertValid(run_tool(tid, vals, d, as_of=AS_OF))

    def test_notice_screens_validate(self):
        self.assertValid(run_tool("o2-duplicants", {"supply": 100}, data(), as_of=AS_OF))
        self.assertValid(form_screen("geyser-average", data(geysers=[])))


class Registry(unittest.TestCase):
    def test_tool_list_ids(self):
        ids = [t["id"] for t in list_tools()["tools"]]
        self.assertEqual(ids, ["heat", "element-state", "geyser-average", "o2-duplicants",
                               "critter-ranch", "power-budget"])

    def test_unknown_tool(self):
        with self.assertRaises(UnknownTool):
            form_screen("teleport", data())
        with self.assertRaises(UnknownTool):
            run_tool("teleport", {}, data())

    def test_form_defaults_filled_in(self):
        s = form_screen("heat", data())
        fields = {f["name"]: f for f in blocks_of(s, "form")[0]["fields"]}
        self.assertEqual(fields["mass"]["default"], 1)
        self.assertEqual(fields["mass"]["defaultUnit"], "kg")
        self.assertEqual(fields["deltaT"]["default"], 10)
        self.assertEqual(fields["mode"]["default"], "heat")
        self.assertIs(fields["useKelvin"]["default"], False)
        self.assertNotIn("default", fields["element"])  # no default element: user picks

    def test_prefill_after_submit(self):
        s = run_tool("heat", {"mass": {"value": 500, "unit": "g"}, "element": "SynthWidgetium",
                              "deltaT": 20}, data(), as_of=AS_OF)
        f = {x["name"]: x for x in blocks_of(s, "form")[0]["fields"]}
        self.assertEqual(f["mass"]["default"], 500)
        self.assertEqual(f["mass"]["defaultUnit"], "g")
        self.assertEqual(f["element"]["default"], "SynthWidgetium")


class Heat(unittest.TestCase):
    # Hand-worked: 5 kg * c 0.5 * dT 20 = 50 kDTU.
    # 500 g = 0.5 kg: 0.5 * 0.5 * 20 = 5 kDTU.
    def test_five_kg(self):
        self.assertEqual(heat.energy_kdtu(5, 0.5, 20), 50)
        s = run_tool("heat", {"mass": {"value": 5, "unit": "kg"}, "element": "SynthWidgetium",
                              "deltaT": 20}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Energy added"), 50.0)

    def test_grams(self):
        s = run_tool("heat", {"mass": {"value": 500, "unit": "g"}, "element": "SynthWidgetium",
                              "deltaT": 20}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Energy added"), 5.0)

    def test_default_mass_unit_is_kg(self):
        s = run_tool("heat", {"mass": 2, "element": "SynthWidgetium", "deltaT": 10}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Energy added"), 2 * 0.5 * 10)

    def test_cool_reports_energy_removed(self):
        s = run_tool("heat", {"mass": 5, "element": "SynthWidgetium", "deltaT": 20, "mode": "cool"},
                     data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Energy removed"), 50.0)

    def test_element_needed(self):
        with self.assertRaises(ToolError) as cm:
            run_tool("heat", {"mass": 5, "deltaT": 20}, data(), as_of=AS_OF)
        self.assertEqual(cm.exception.message, "Element: needs a value")

    def test_unknown_element(self):
        with self.assertRaises(ToolError) as cm:
            run_tool("heat", {"element": "Nope"}, data(), as_of=AS_OF)
        self.assertEqual(cm.exception.message, "Element: that element is not in the game")

    def test_bad_unit_names_field(self):
        with self.assertRaises(ToolError) as cm:
            run_tool("heat", {"mass": {"value": 5, "unit": "lb"}, "element": "SynthWidgetium"},
                     data(), as_of=AS_OF)
        self.assertTrue(cm.exception.message.startswith("Mass:"))

    def test_negative_delta_rejected(self):
        with self.assertRaises(ToolError) as cm:
            run_tool("heat", {"element": "SynthWidgetium", "deltaT": -5}, data(), as_of=AS_OF)
        self.assertEqual(cm.exception.message, "Temperature change: use 0 or more")

    def test_bad_mode_rejected(self):
        with self.assertRaises(ToolError):
            run_tool("heat", {"element": "SynthWidgetium", "mode": "boil"}, data(), as_of=AS_OF)

    def test_values_not_object(self):
        with self.assertRaises(ToolError):
            run_tool("heat", "mass=5", data(), as_of=AS_OF)


class ElementState(unittest.TestCase):
    # Synthetic chain: Widgetium (solid) -100 C-> Liquid Widgetium -300 C-> Widget Gas.
    def setUp(self):
        self.els = {e["id"]: e for e in EXPORT["elements"]}
        self.order = es.ladder(self.els, "SynthWidgetium")

    def test_ladder_coldest_first(self):
        self.assertEqual(self.order, ["SynthWidgetium", "SynthLiquid", "SynthGas"])
        self.assertEqual(es.ladder(self.els, "SynthLiquid"), self.order)
        self.assertEqual(es.ladder(self.els, "SynthGas"), self.order)

    def test_states_by_temperature(self):
        # 20 C < 100 -> solid; 100 C is at the threshold -> liquid; 350 C -> gas.
        def state(t):
            return self.els[es.settle(self.els, "SynthWidgetium", t)[-1]]["state"]
        self.assertEqual(state(20), "solid")
        self.assertEqual(state(99.9), "solid")
        self.assertEqual(state(100), "liquid")
        self.assertEqual(state(299), "liquid")
        self.assertEqual(state(350), "gas")

    def test_settle_from_the_hot_side(self):
        # Gas cooled to 200 C is below its 300 C threshold -> liquid; to 20 C -> liquid then solid.
        self.assertEqual(es.settle(self.els, "SynthGas", 200), ["SynthGas", "SynthLiquid"])
        self.assertEqual(es.settle(self.els, "SynthGas", 20), ["SynthGas", "SynthLiquid", "SynthWidgetium"])

    def test_tool_result_fahrenheit(self):
        # 350 F = (350 - 32) * 5 / 9 = 176.67 C -> liquid
        s = run_tool("element-state", {"element": "SynthWidgetium",
                                       "temperature": {"value": 350, "unit": "F"}},
                     data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Element"), "Liquid Widgetium")
        self.assertEqual(stat_value(s, "State"), "liquid")
        self.assertEqual(stat_value(s, "Starts as"), "Widgetium")

    def test_tool_result_kelvin_boundary(self):
        # 373.15 K = 100 C exactly -> liquid (threshold takes the hotter phase)
        s = run_tool("element-state", {"element": "SynthWidgetium",
                                       "temperature": {"value": 373.15, "unit": "K"}},
                     data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "State"), "liquid")

    def test_phases_block_ranges(self):
        s = run_tool("element-state", {"element": "SynthWidgetium", "temperature": 20},
                     data(), as_of=AS_OF)
        states = blocks_of(s, "phases")[0]["states"]
        self.assertEqual([x["range"] for x in states],
                         ["Below 100 C", "100 to 300 C", "Above 300 C"])
        self.assertIsNone(states[0]["loC"])
        self.assertEqual(states[1]["target"], {"kind": "element", "id": "SynthGas"})
        self.assertNotIn("target", states[2])

    def test_no_transitions_is_one_phase(self):
        # An element with no transitions has one phase: all temperatures.
        plain = copy.deepcopy(EXPORT)
        for e in plain["elements"]:
            e.pop("lowTransition", None)
            e.pop("highTransition", None)
        s = run_tool("element-state", {"element": "SynthWidgetium", "temperature": 20},
                     plain, as_of=AS_OF)
        self.assertEqual(stat_value(s, "State"), "solid")
        states = blocks_of(s, "phases")[0]["states"]
        self.assertEqual([x["range"] for x in states], ["All temperatures"])

    def test_back_and_forth_is_plain_language(self):
        # A (hot above 100 -> B), B (cold below 200 -> A): at 150 they would swap forever.
        loop = copy.deepcopy(EXPORT)
        for e in loop["elements"]:
            if e["id"] == "SynthWidgetium":
                e["highTransition"] = {"tempC": 100, "target": "SynthLiquid"}
            if e["id"] == "SynthLiquid":
                e["lowTransition"] = {"tempC": 200, "target": "SynthWidgetium"}
        with self.assertRaises(DataProblem) as cm:
            es.settle({e["id"]: e for e in loop["elements"]}, "SynthWidgetium", 150)
        self.assertNotIn("export", str(cm.exception).lower())


class Geyser(unittest.TestCase):
    # The game's GetAverageEmission = mass per cycle / 600 * share of the year active.
    # Synthetic: rate 1..5 kg/s (mid 3 = 1800 kg per cycle); year share 0.4..0.8 (mid 0.6)
    # 3 * 0.6 = 1.8 kg/s; * 600 = 1080 kg per cycle; lowest 1*0.4 = 0.4, highest 5*0.8 = 4.
    def test_hand_worked(self):
        self.assertAlmostEqual(geyser.average_kg_per_s(1800, 0.6), 1.8)
        s = run_tool("geyser-average", {"geyser": "SynthGeyser"}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Average output"), 1.8)
        self.assertEqual(stat_value(s, "Per cycle"), 1080.0)
        self.assertEqual(stat_value(s, "Active share of its year"), 60.0)
        hint = [r for b in blocks_of(s, "stats") for r in b["rows"] if r["label"] == "Average output"][0]["hint"]
        self.assertEqual(hint, "Lowest 0.4, highest 4")

    def test_no_geysers(self):
        s = form_screen("geyser-average", data(geysers=[]), as_of=AS_OF)
        self.assertEqual(blocks_of(s, "notice")[0]["level"], "warn")

    def test_geysers_without_numbers_are_not_offered(self):
        d = data(geysers=EXPORT["geysers"] + [{"id": "Bare", "name": "Bare Spring", "dlc": []}])
        s = form_screen("geyser-average", d, as_of=AS_OF)
        opts = [o["value"] for o in blocks_of(s, "form")[0]["fields"][0]["options"]]
        self.assertEqual(opts, ["SynthGeyser"])


class Oxygen(unittest.TestCase):
    # Test value 0.01 kg/s (NOT the game value) so the arithmetic is easy to follow.
    def test_hand_worked(self):
        d = data(constants={"dupeO2KgPerS": 0.01})
        # 100 g/s = 0.1 kg/s; 0.1 / 0.01 = 10 duplicants
        s = run_tool("o2-duplicants", {"supply": {"value": 100, "unit": "g/s"}}, d, as_of=AS_OF)
        self.assertEqual(stat_value(s, "Duplicants fed"), 10)

    def test_whole_duplicants_floor(self):
        d = data(constants={"dupeO2KgPerS": 0.03})
        # 0.1 / 0.03 = 3.33 -> 3 whole
        s = run_tool("o2-duplicants", {"supply": {"value": 0.1, "unit": "kg/s"}}, d, as_of=AS_OF)
        self.assertEqual(stat_value(s, "Duplicants fed"), 3)
        self.assertEqual(stat_value(s, "Exact"), 3.33)

    def test_old_data_without_the_number_uses_the_game_value(self):
        # Marked fallback: 0.1 kg/s is OXYGEN_USED_PER_SECOND in the game. 250 g/s / 100 g/s = 2.5 -> 2.
        s = run_tool("o2-duplicants", {"supply": {"value": 250, "unit": "g/s"}}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Duplicants fed"), 2)
        self.assertEqual(stat_value(s, "Exact"), 2.5)
        self.assertEqual(stat_value(s, "Oxygen per duplicant"), 100.0)

    def test_carbon_dioxide_row_only_when_exported(self):
        d = data(constants={"dupeO2KgPerS": 0.1, "toolNumbers": {"dupeCo2KgPerS": 0.002}})
        s = run_tool("o2-duplicants", {"supply": 100}, d, as_of=AS_OF)
        self.assertEqual(stat_value(s, "Carbon dioxide per duplicant"), 2.0)
        s = run_tool("o2-duplicants", {"supply": 100}, data(), as_of=AS_OF)
        with self.assertRaises(KeyError):
            stat_value(s, "Carbon dioxide per duplicant")

    def test_zero_rate_is_plain_language(self):
        d = data(constants={"dupeO2KgPerS": 0})
        s = run_tool("o2-duplicants", {"supply": 100}, d, as_of=AS_OF)
        text = blocks_of(s, "notice")[0]["text"].lower()
        self.assertNotIn("export", text)
        self.assertNotIn("mod", text.split())


class CritterRanch(unittest.TestCase):
    # 10 critters: 140 kg food each -> 1400 kg; 50 kg out -> 500 kg; 100000 kcal -> 1000000 kcal
    def test_hand_worked(self):
        s = run_tool("critter-ranch", {"critter": "SynthBeast", "count": 10}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Food eaten per cycle"), 1400.0)
        self.assertEqual(stat_value(s, "Output per cycle"), 500.0)
        self.assertEqual(stat_value(s, "Calories per cycle"), 1000000.0)

    def test_table_has_row_per_diet(self):
        s = run_tool("critter-ranch", {"critter": "SynthBeast", "count": 1}, data(), as_of=AS_OF)
        t = blocks_of(s, "table")[0]
        self.assertEqual(len(t["rows"]), 1)
        self.assertEqual(t["rows"][0][1], "140 kg of Synth Stone")

    def test_count_zero(self):
        s = run_tool("critter-ranch", {"critter": "SynthBeast", "count": 0}, data(), as_of=AS_OF)
        self.assertEqual(stat_value(s, "Food eaten per cycle"), 0.0)

    def test_count_limits(self):
        with self.assertRaises(ToolError):
            run_tool("critter-ranch", {"critter": "SynthBeast", "count": -1}, data(), as_of=AS_OF)


class Power(unittest.TestCase):
    # 120 W + 10 W = 130 W used. Test generator 200 W made -> net 130 - 200 = -70 W.
    def test_hand_worked(self):
        d = data(buildings=EXPORT["buildings"] + [{
            "id": "SynthGen", "name": "Test Generator", "dlc": [], "category": "SynthPower",
            "size": {"w": 1, "h": 1}, "power": {"generatesW": 200}, "tech": None}])
        s = run_tool("power-budget", {"building1": "SynthWidgetMaker", "building2": "SynthLamp",
                                      "building3": "SynthGen"}, d, as_of=AS_OF)
        self.assertEqual(stat_value(s, "Uses"), 130.0)
        self.assertEqual(stat_value(s, "Makes"), 200.0)
        self.assertEqual(stat_value(s, "Net draw"), -70.0)

    def test_only_none_picked(self):
        s = run_tool("power-budget", {}, data(), as_of=AS_OF)
        self.assertEqual(blocks_of(s, "notice")[0]["level"], "info")

    def test_choice_must_be_listed(self):
        with self.assertRaises(ToolError) as cm:
            run_tool("power-budget", {"building1": "Nope"}, data(), as_of=AS_OF)
        self.assertEqual(cm.exception.message, "Building 1: pick one of the listed choices")


class CritterAlternatives(unittest.TestCase):
    def test_alternatives_are_not_added_up(self):
        # A diet lists foods the critter eats ONE of: 9 foods at 140 kg each is still 140 kg a cycle.
        crit = {"id": "Many", "name": "Many Eater", "dlc": [], "diets": [{
            "consumes": [{"tag": "A", "kg": 140}, {"tag": "B", "kg": 140}, {"tag": "C", "kg": 140}],
            "produces": [{"element": "SynthGas", "kg": 70}], "caloriesPerCycle": 700}]}
        d = data(critters=[crit], names={"A": "Apple", "B": "Bean", "C": "Corn"})
        s = run_tool("critter-ranch", {"critter": "Many", "count": 10}, d, as_of=AS_OF)
        self.assertEqual(stat_value(s, "Food eaten per cycle"), 1400.0)
        self.assertEqual(blocks_of(s, "table")[0]["rows"][0][1], "140 kg of Apple, Bean, Corn")


REAL_EXPORT = os.path.join(ROOT, "fixtures", "real", "proton-user", "companion", "export")
REAL_FILES = sorted(os.path.join(REAL_EXPORT, f) for f in os.listdir(REAL_EXPORT)) \
    if os.path.isdir(REAL_EXPORT) else []


@unittest.skipUnless(REAL_FILES, "needs the real game export in fixtures/real")
class RealGameData(unittest.TestCase):
    """Each tool against the game's own export; two cases each, hand-checked against the game's files.

    Where each expected number comes from (game ChangeList 744825):
      elements/*.yaml (specificHeatCapacity, lowTemp/highTemp in kelvin) and decompiled Assembly-CSharp:
      HatchConfig, BasePacuConfig, GeyserGenericConfig + GeyserConfigurator.GetAverageEmission,
      DUPLICANTSTATS, and the *Config.cs files for building watts.
    """

    @classmethod
    def setUpClass(cls):
        with open(REAL_FILES[0], encoding="utf-8") as f:
            cls.d = json.load(f)

    def run_(self, tool, values):
        return run_tool(tool, values, self.d, as_of=AS_OF)

    # -- heat: kDTU = kg * specificHeat (DTU/g/K) * K.  Water 4.179, Copper 0.385 (elements yaml)
    def test_heat_water(self):
        # 5 kg * 4.179 * 20 K = 417.9 kDTU
        self.assertEqual(stat_value(self.run_("heat", {"mass": 5, "element": "Water", "deltaT": 20}),
                                    "Energy added"), 417.9)

    def test_heat_copper_grams(self):
        # 2000 g = 2 kg: 2 * 0.385 * 10 = 7.7 kDTU
        s = self.run_("heat", {"mass": {"value": 2000, "unit": "g"}, "element": "Copper", "deltaT": 10})
        self.assertEqual(stat_value(s, "Energy added"), 7.7)

    # -- element state: yaml kelvin - 273.15.  Water: Ice below 272.5 K (-0.65 C), Steam from 372.5 K (99.35 C)
    def test_state_water_hot_and_cold(self):
        s = self.run_("element-state", {"element": "Water", "temperature": 120})
        self.assertEqual((stat_value(s, "Element"), stat_value(s, "State")), ("Steam", "gas"))
        s = self.run_("element-state", {"element": "Water", "temperature": -10})
        self.assertEqual((stat_value(s, "Element"), stat_value(s, "State")), ("Ice", "solid"))
        s = self.run_("element-state", {"element": "Water", "temperature": 99.34})
        self.assertEqual(stat_value(s, "Element"), "Water")

    def test_state_does_not_go_back_the_way_it_came(self):
        # Sand: highTemp 1986 K = 1712.85 C -> Molten Glass; Molten Glass: lowTemp 1400 K = 1126.85 C -> Glass
        s = self.run_("element-state", {"element": "Sand", "temperature": 2000})
        self.assertEqual(stat_value(s, "Element"), "Molten Glass")
        s = self.run_("element-state", {"element": "MoltenGlass", "temperature": 20})
        self.assertEqual((stat_value(s, "Element"), stat_value(s, "State")), ("Glass", "solid"))

    def test_state_works_for_every_element(self):
        for e in self.d["elements"]:
            for t in (-250, 20, 5000):
                run_tool("element-state", {"element": e["id"], "temperature": t}, self.d, as_of=AS_OF)

    # -- geyser: GetAverageEmission = massPerCycle / 600 * yearShare, mids of the ranges
    def test_geyser_chlorine(self):
        # 70..140 kg a cycle (mid 105), year share 0.4..0.8 (mid 0.6): 105 / 600 * 0.6 = 0.105 kg/s
        s = self.run_("geyser-average", {"geyser": "chlorine_gas"})
        self.assertEqual(stat_value(s, "Average output"), 0.105)
        self.assertEqual(stat_value(s, "Per cycle"), 63.0)

    def test_geyser_steam_and_volcano(self):
        # steam 1000..2000 kg: 1500 / 600 * 0.6 = 1.5 kg/s.  big_volcano 800..1600: 1200 / 600 * 0.6 = 1.2 kg/s
        self.assertEqual(stat_value(self.run_("geyser-average", {"geyser": "steam"}), "Average output"), 1.5)
        self.assertEqual(stat_value(self.run_("geyser-average", {"geyser": "big_volcano"}), "Average output"), 1.2)

    # -- oxygen: DUPLICANTSTATS OXYGEN_USED_PER_SECOND = 0.1 kg/s
    def test_oxygen_300_and_250(self):
        self.assertEqual(self.d["constants"]["dupeO2KgPerS"], 0.1)
        self.assertEqual(stat_value(self.run_("o2-duplicants", {"supply": {"value": 300, "unit": "g/s"}}),
                                    "Duplicants fed"), 3)
        self.assertEqual(stat_value(self.run_("o2-duplicants", {"supply": {"value": 0.25, "unit": "kg/s"}}),
                                    "Duplicants fed"), 2)

    # -- critters: HatchConfig 140 kg rock a cycle, 700000 cal, x0.5 -> 70 kg coal; Pacu 7.5 kg algae, 100000 cal, x2/3
    def test_ranch_hatch(self):
        s = self.run_("critter-ranch", {"critter": "Hatch", "count": 10})
        self.assertEqual(stat_value(s, "Food eaten per cycle"), 1400.0)
        self.assertEqual(stat_value(s, "Output per cycle"), 700.0)
        self.assertEqual(stat_value(s, "Calories per cycle"), 7000.0)

    def test_ranch_pacu(self):
        s = self.run_("critter-ranch", {"critter": "Pacu", "count": 10})
        self.assertEqual(stat_value(s, "Food eaten per cycle"), 75.0)
        self.assertEqual(stat_value(s, "Output per cycle"), 50.0)
        self.assertEqual(stat_value(s, "Calories per cycle"), 1000.0)

    # -- power: Coal Generator GeneratorWattageRating 600; Soldering Station 480; Oxygen Diffuser 120; Electrolyzer 120; Rock Crusher 240
    def test_power_generator_against_consumer(self):
        s = self.run_("power-budget", {"building1": "Generator", "building2": "AdvancedCraftingTable"})
        self.assertEqual((stat_value(s, "Uses"), stat_value(s, "Makes"), stat_value(s, "Net draw")),
                         (480.0, 600.0, -120.0))

    def test_power_three_consumers(self):
        s = self.run_("power-budget", {"building1": "MineralDeoxidizer", "building2": "Electrolyzer",
                                       "building3": "RockCrusher"})
        self.assertEqual((stat_value(s, "Uses"), stat_value(s, "Net draw")), (480.0, 480.0))

    def test_every_tool_answers_for_every_choice(self):
        # No tool may show a data complaint or crash for anything it offers.
        for tid, key in (("geyser-average", "geyser"), ("critter-ranch", "critter"),
                         ("power-budget", "building1")):
            form = form_screen(tid, self.d)["blocks"][0]["fields"]
            field = [f for f in form if f["name"] == key][0]
            for o in field["options"]:
                if not o["value"]:
                    continue
                s = run_tool(tid, {key: o["value"]}, self.d, as_of=AS_OF)
                self.assertEqual([n for n in blocks_of(s, "notice") if n["level"] == "warn"], [], o)
        for e in self.d["elements"]:
            s = run_tool("heat", {"element": e["id"]}, self.d, as_of=AS_OF)
            self.assertEqual([n for n in blocks_of(s, "notice") if n["level"] == "warn"], [], e["id"])

    def test_no_tool_text_talks_about_the_mod(self):
        import re
        for tid, vals in (("heat", {"element": "Water"}), ("element-state", {"element": "Water"}),
                          ("geyser-average", {"geyser": "steam"}), ("o2-duplicants", {}),
                          ("critter-ranch", {"critter": "Hatch"}), ("power-budget", {})):
            text = json.dumps(self.run_(tid, vals)["blocks"]).lower()
            self.assertIsNone(re.search(r"\b(mod|export)\b", text), tid)


if __name__ == "__main__":
    unittest.main()


class Limits(unittest.TestCase):
    def bad(self, tid, vals):
        with self.assertRaises(ToolError):
            run_tool(tid, vals, data(), as_of=AS_OF)

    def test_below_absolute_zero(self):
        for t in ({"value": -300, "unit": "C"}, {"value": -500, "unit": "K"}, {"value": -500, "unit": "F"}):
            self.bad("element-state", {"element": "SynthWidgetium", "temperature": t})

    def test_huge_numbers_are_refused(self):
        self.bad("heat", {"mass": 1e30, "element": "SynthWidgetium"})
        self.bad("heat", {"mass": 5, "element": "SynthWidgetium", "deltaT": 1e12})
        self.bad("o2-duplicants", {"supply": 1e30})
