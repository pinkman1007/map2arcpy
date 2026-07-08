"""Systems-thinking layer (v0.11.0) — opt-in causal analysis."""
import ast
import os

from map2arcpy import systems
from map2arcpy.parsers import nl, data
from map2arcpy.intent import apply_intent
from map2arcpy.generator import generate
from map2arcpy.cli import main
from conftest import EXAMPLES


def test_off_by_default():
    code = generate(nl.parse("flood map from flood.shp, epsg 32644"), strict=False)
    assert "SYSTEMS CONTEXT" not in code


def test_flood_names_drivers_and_coverage():
    spec = nl.parse("flood inundation map from flood_depth.shp and slope.tif "
                    "and rainfall.tif, epsg 32644")
    systems.apply(spec, "flood inundation map")
    ctx = " ".join(spec.systems_context)
    assert "STATE" in ctx.upper()
    assert "rainfall" in ctx and "slope" in ctx
    # has data for rainfall + slope; missing drainage + vegetation
    assert any("Data present for" in c for c in spec.systems_context)
    assert any("systems:" in n and "driven by" in n for n in spec.notes)


def test_stock_flow_ramp_discipline_flags_sequential_change_map():
    from map2arcpy.spec import MapSpec, Layer, Renderer
    from map2arcpy.palettes import RAMPS
    spec = MapSpec(crs_epsg=32644, source_kind="geojson",
                   layers=[Layer(name="lulc_change", source="chg.tif", kind="raster",
                                 renderer=Renderer(type="graduated", field="Value",
                                                   ramp=list(RAMPS["greens"])))])
    spec.layout.title = "LULC change 2015-2025"
    systems.apply(spec, "change map")
    assert any("SIGNED FLOW" in n and "diverging" in n for n in spec.notes)


def test_diverging_ramp_passes_discipline():
    from map2arcpy.spec import MapSpec, Layer, Renderer
    from map2arcpy.palettes import RAMPS
    spec = MapSpec(crs_epsg=32644, source_kind="geojson",
                   layers=[Layer(name="change", source="c.tif", kind="raster",
                                 renderer=Renderer(type="graduated", field="Value",
                                                   ramp=list(RAMPS["red_blue"])))])
    spec.layout.title = "change map"
    systems.apply(spec, "change loss gain map")
    assert not any("SIGNED FLOW" in n for n in spec.notes)


def test_boundary_critique_on_flow_clipped_to_admin():
    spec = nl.parse("flood map from flood.shp, clip to \"wards.shp\", epsg 32644")
    systems.apply(spec, "flood map")
    assert any("administrative boundary" in n and "watershed" in n for n in spec.notes)


def test_loops_in_header_block():
    spec = nl.parse("urban heat map from lst.tif, epsg 32644")
    systems.apply(spec, "temperature heat map")
    code = generate(spec, strict=False)
    assert "SYSTEMS CONTEXT" in code
    assert "urban heat island" in code.lower()
    ast.parse(code)


def test_no_archetype_notes_honestly():
    spec = nl.parse("map of parks.shp, epsg 32644")
    systems.apply(spec, "just a parks map")
    assert any("no thematic archetype" in n for n in spec.notes)


def test_cli_systems_flag(tmp_path):
    out = tmp_path / "s.py"
    rc = main(["generate", "carbon storage map from carbon.tif, epsg 32644",
               "-o", str(out), "--systems", "--no-profile"])
    assert rc == 0
    code = out.read_text()
    assert "SYSTEMS CONTEXT" in code
    assert "STOCK" in code
    ast.parse(code)
