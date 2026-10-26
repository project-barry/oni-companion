"""Heat: energy to change the temperature of a mass of one element.

Q [kDTU] = m [kg] * c * dT
  c is `specificHeat` in DTU per g per K (mod-export.schema.json). Mass in g is
  1000 x mass in kg, and 1 kDTU = 1000 DTU, so the factors cancel:
  Q [kDTU] = m_kg * c * dT.
Heat only: melting, boiling and other phase changes are not counted.

Hand-worked in tests/test_tools.py:
  5 kg, c = 0.5, dT = 20 K  ->  5 * 0.5 * 20 = 50 kDTU
  500 g (= 0.5 kg), same    ->  0.5 * 0.5 * 20 = 5 kDTU
"""

from . import common as c


MAX_MASS_KG = 1000000.0
MAX_DELTA_C = 100000.0


def energy_kdtu(mass_kg, specific_heat, delta_c):
    """Signed-free energy magnitude in kDTU for a temperature step."""
    return mass_kg * specific_heat * delta_c


def _fields(data):
    if not data.get("elements"):
        raise c.DataProblem("No elements are loaded yet.")
    return [
        c.number_field("mass", "Mass", 1, units=c.MASS_UNITS, default_unit="kg", min=0),
        c.element_field("element", "Element"),
        c.number_field("deltaT", "Temperature change", 10, unit="C", min=0),
        c.choice_field("mode", "Mode", [("heat", "Heat"), ("cool", "Cool")], default="heat"),
        c.toggle_field("useKelvin", "Show Kelvin", default=False),
    ]


def _run(p, data):
    els = c.index_by_id(data, "elements")
    el = els[p["element"]]
    spec = el.get("specificHeat")
    if spec is None:
        raise c.DataProblem("%s has no specific heat in the game." % el["name"])
    if spec <= 0:
        return [c.notice("info", "%s has a specific heat of zero in the game, so it takes no energy to change its temperature." % el["name"])]
    mass = p["mass"]
    mass_kg = mass.value * c.MASS_TO_KG[mass.unit]
    if mass_kg > MAX_MASS_KG:
        raise c.ToolError("mass", "use %s kg or less" % c.fmt_num(MAX_MASS_KG), label="Mass")
    dt = p["deltaT"].value
    if dt > MAX_DELTA_C:
        raise c.ToolError("deltaT", "use %s or less" % c.fmt_num(MAX_DELTA_C), label="Temperature change")
    q = abs(energy_kdtu(mass_kg, spec, dt))
    cooling = p["mode"] == "cool"
    unit_t = "K" if p["useKelvin"] else "C"
    rows = [
        c.stat("Energy removed" if cooling else "Energy added", c.round_num(q), unit="kDTU", tone="info"),
        c.stat("Element", el["name"], ref=c.element_ref(el["id"])),
        c.stat("Mass", c.round_num(mass_kg, 3), unit="kg"),
        c.stat("Specific heat", c.round_num(spec, 3), unit="DTU/g/K"),
        c.stat("Temperature change", c.round_num(dt), unit=unit_t),
    ]
    return [
        c.stats_block(rows, title="Result"),
        c.notice("info", "Heat only. Melting or boiling needs more energy and is not counted."),
    ]


TOOL = c.Tool(
    "heat", "Heat", "Energy to change a temperature",
    _fields, _run,
)
