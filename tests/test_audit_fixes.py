"""Regression tests for the v0.18.0 audit fixes."""
import ast
import os

from map2arcpy.parsers import nl, data
from map2arcpy.intent import apply_intent
from map2arcpy import systems, discover, dynamics
from map2arcpy.generator import generate
from map2arcpy.spec import MapSpec, Layer, Operation, Renderer
from map2arcpy.palettes import RAMPS
from conftest import EXAMPLES


# --- NL CRS false positive ------------------------------------------------
def test_bare_number_in_where_does_not_set_crs():
    spec = nl.parse('map roads.shp select where "POP > 3857"')
    assert spec.crs_epsg == 4326                     # not 3857
    assert nl.parse("map roads.shp, web mercator").crs_epsg == 3857
    assert nl.parse("map roads.shp, epsg:3857").crs_epsg == 3857


# --- substring driver matching --------------------------------------------
def test_terrain_does_not_count_as_rainfall_driver():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    spec.layers[0].name = "terrain_dem"
    systems.apply(spec, "flood map")
    note = next(n for n in spec.notes if "driven by" in n)
    # slope/terrain present (dem), but rainfall NOT (rain not in terrain)
    assert "you have 1" in note
    assert "rainfall" not in note.split("you have")[1].split(";")[0]


def test_kw_hit_boundaries():
    assert systems._kw_hit("rain", "rainfall rain_2015")
    assert not systems._kw_hit("rain", "terrain drainage")
    assert not systems._kw_hit("road", "railroad")
    assert systems._kw_hit("built", "built_up builtarea")


# --- diverging ramp detection ---------------------------------------------
def test_even_and_pale_diverging_ramps_detected():
    assert systems._looks_diverging(RAMPS["spectral"])          # 6-colour
    assert systems._looks_diverging(RAMPS["red_yellow_green"])  # 6-colour
    assert systems._looks_diverging(RAMPS["red_blue"])          # 5-colour white
    assert systems._looks_diverging(RAMPS["sensitivity"])       # pale centre
    assert not systems._looks_diverging(RAMPS["blues"])         # sequential


def test_spectral_change_map_no_false_sequential_warning():
    spec = MapSpec(crs_epsg=32644, source_kind="geojson",
                   layers=[Layer(name="lulc_change", source="c.tif", kind="raster",
                                 renderer=Renderer(type="graduated", field="Value",
                                                   ramp=list(RAMPS["spectral"])))])
    spec.layout.title = "LULC change 2015-2025"
    systems.apply(spec, "change map")
    assert not any("SIGNED FLOW" in n for n in spec.notes)


# --- intent leading clip ---------------------------------------------------
def test_leading_clip_targets_the_data_layer():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_intent(spec, 'clip to "city_boundary.shp"')
    clip = next(o for o in spec.operations if o.tool == "clip")
    assert clip.inputs[0] == "wards"                 # not city_boundary by itself
    assert clip.inputs[1] == "city_boundary"


def test_unknown_named_layer_not_silently_redirected():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_intent(spec, "buffer rivers by 500 m")     # rivers never uploaded
    buf = next(o for o in spec.operations if o.tool == "buffer")
    assert buf.inputs[0] == "rivers"                 # kept, surfaces as unresolved


# --- ESZ caveat + CRS gate -------------------------------------------------
def test_esz_carries_legal_caveat_and_crs_gate():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))  # geojson -> 4326
    apply_intent(spec, "eco-sensitive zones around wards")
    blob = " ".join(spec.notes)
    assert "Supreme Court" in blob and "26-Apr-2023" in blob
    assert "PROJECTED CRS" in blob                   # geographic-CRS warning fired


# --- classify_pair convergence --------------------------------------------
def test_pair_convergence_is_not_success_to_successful():
    res = dynamics.classify_pair([10, 30, 50], [90, 70, 50])   # converging
    assert res.get("archetype") != "success to the successful"
    div = dynamics.classify_pair([10, 22, 40, 70, 120], [10, 12, 14, 16, 18])
    assert div["archetype"] == "success to the successful"


# --- op-output identifier safety ------------------------------------------
def test_weird_op_output_still_generates_valid_python():
    spec = MapSpec(crs_epsg=32644,
                   layers=[Layer(name="roads", source="roads.shp")],
                   operations=[Operation(tool="buffer", inputs=["roads"],
                                         output="buffer 500m-zone",
                                         params={"distance": "500 Meters"})])
    code = generate(spec, strict=False)
    ast.parse(code)                                  # must not be a SyntaxError
    assert "buffer_500m_zone" in code


# --- discover: 2-epoch change map + no false themes ------------------------
def test_two_epoch_change_map_offered():
    spec = MapSpec(source_kind="zip",
                   layers=[Layer(name=f"r{y}", source=f"r{y}.tif", kind="raster",
                                 renderer=Renderer(type="stretch"))
                           for y in (2015, 2025)])
    titles = [s["title"] for s in discover.suggest(spec)]
    assert any("Change map" in t for t in titles)


def test_discover_no_rainfall_from_drainage():
    spec = MapSpec(source_kind="shapefile",
                   layers=[Layer(name="drainage_network", source="drain.shp",
                                 kind="vector", geometry="line",
                                 renderer=Renderer(type="simple", color="#00f"),
                                 extra={"fields": []})])
    depicts = " ".join(s["depict"] for s in discover.suggest(spec))
    assert "rainfall map" not in depicts
