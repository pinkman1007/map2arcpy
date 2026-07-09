"""The live plan: what the tool understood, stated before generation."""
from map2arcpy.detect import parse_any
from map2arcpy.parsers import steps
from map2arcpy.plan import describe
from map2arcpy.spec import MapSpec, Layer, Renderer
from map2arcpy import intent

RECIPE = """1. decadal average of "C:/GIS/rain/rain_20*.tif"
2. rainfall map
3. titled 'Decadal Average Rainfall', A3 landscape"""


def _dc_spec(years=range(2015, 2023), extra_2025=True, instruction=True):
    spec = MapSpec(source_kind="zip")
    for y in list(years) + ([2025] if extra_2025 else []):
        spec.layers.append(Layer(name=f"PERSIANN_1y{y}",
                                 source=f"C:/x/PERSIANN_1y{y}.tif",
                                 kind="raster", renderer=Renderer(type="stretch")))
    if instruction:
        intent.apply_intent(spec, "decadal average rainfall map")
    return spec


def test_analysis_plan_is_stated():
    plan = describe(steps.parse(RECIPE), instruction_given=True)
    assert plan["will_analyse"] is True
    assert any(i.startswith("ANALYSE: Cell Statistics MEAN") for i in plan["intentions"])
    assert any("layout:" in i and "A3L" in i for i in plan["intentions"])
    assert any("ANALYSIS METHOD" in m for m in plan["methods"])


def test_display_only_without_instruction_warns_loudly():
    plan = describe(_dc_spec(instruction=False), instruction_given=False)
    assert plan["will_analyse"] is False
    assert any("NO INSTRUCTION" in w and "DISPLAY" in w for w in plan["warnings"])


def test_instruction_given_no_display_only_warning():
    plan = describe(_dc_spec(instruction=True), instruction_given=True)
    assert plan["will_analyse"] is True
    assert not any("NO INSTRUCTION" in w for w in plan["warnings"])


def test_year_gaps_detected():
    plan = describe(_dc_spec(), instruction_given=True)
    d = plan["data"]
    assert d["years"][0] == 2015 and d["years"][-1] == 2025
    assert 2023 in d["year_gaps"] and 2024 in d["year_gaps"]
    assert any("gaps" in w for w in plan["warnings"])


def test_data_summary_lists_fields_and_years():
    spec = _dc_spec(instruction=False)
    spec.layers.append(Layer(name="wards", source="w.shp", kind="vector",
                             extra={"fields": [{"name": "pop", "type": "numeric"},
                                               {"name": "ward_name", "type": "text"}]}))
    d = describe(spec, instruction_given=False)["data"]
    wards = next(l for l in d["layers"] if l["name"] == "wards")
    assert wards["fields"] == ["pop", "ward_name"]
    assert d["n_rasters"] == 9 and d["n_vectors"] == 1


def test_sa_need_flagged_against_profile():
    plan = describe(steps.parse(RECIPE), instruction_given=True,
                    profile={"extensions": {"Spatial Analyst": False}})
    assert any("NOT available" in w for w in plan["warnings"])
    plan2 = describe(steps.parse(RECIPE), instruction_given=True,
                     profile={"extensions": {"Spatial Analyst": True}})
    assert not any("NOT available" in w for w in plan2["warnings"])
    assert any("Spatial Analyst" in i for i in plan2["intentions"])


def test_not_understood_steps_surface_in_plan():
    spec = steps.parse("1. load wards.shp\n2. frobnicate the doohickey")
    plan = describe(spec, instruction_given=True)
    assert any("NOT UNDERSTOOD" in w for w in plan["warnings"])


def test_preflight_checks_traffic_lights():
    plan = describe(steps.parse(RECIPE), instruction_given=True)
    checks = {c["name"]: c["status"] for c in plan["checks"]}
    assert checks["instruction"] == "ok"
    assert checks["analysis"] == "ok"
    assert checks["understood"] == "ok"
    # display-only, no instruction -> warn
    plan2 = describe(_dc_spec(instruction=False), instruction_given=False)
    checks2 = {c["name"]: c["status"] for c in plan2["checks"]}
    assert checks2["instruction"] == "warn"
    assert checks2["analysis"] == "na"
