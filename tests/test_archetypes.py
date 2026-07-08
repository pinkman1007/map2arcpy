"""Thematic map-type archetypes (v0.10.0)."""
import ast
import os
import struct

from map2arcpy import archetypes
from map2arcpy.parsers import nl, image
from map2arcpy.intent import apply_intent
from map2arcpy.parsers import data
from map2arcpy.generator import generate
from conftest import EXAMPLES


def test_detection_vocabulary():
    assert archetypes.detect("carbon storage map of the city")["name"] == "carbon storage"
    assert archetypes.detect("map co2 emissions per ward")["name"] == "carbon/GHG emissions"
    assert archetypes.detect("eco-sensitive zones around the sanctuary")["name"] == "eco-sensitive zones"
    assert archetypes.detect("LULC 2026")["name"] == "LULC / land use"
    assert archetypes.detect("flood inundation extent")["name"] == "flood / inundation"
    assert archetypes.detect("a nice city map") is None


def test_carbon_map_gets_green_ramp_on_raster(tmp_path):
    p = tmp_path / "carbon.tif"
    p.write_bytes(b"II*\x00\x08\x00\x00\x00\x00\x00")     # minimal tif-ish
    spec = nl.parse(f"carbon storage map from {p}, epsg 32644")
    ras = next(l for l in spec.layers if l.kind == "raster")
    assert ras.renderer.ramp == archetypes.RAMPS["greens"]
    assert any("carbon-storage convention" in n for n in spec.notes)


def test_explicit_ramp_beats_archetype(tmp_path):
    p = tmp_path / "carbon.tif"
    p.write_bytes(b"II*\x00\x08\x00\x00\x00\x00\x00")
    spec = nl.parse(f"choropleth carbon storage map from {p} using viridis, epsg 32644")
    # user said viridis -> archetype must not repaint
    grads = [l for l in spec.layers if l.renderer.type == "graduated"]
    if grads:
        assert grads[0].renderer.ramp == archetypes.RAMPS["viridis"]


def test_esz_archetype_builds_ring_buffers():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_intent(spec, "eco-sensitive zones around wards, epsg 32644")
    op = next(o for o in spec.operations if o.tool == "multi_buffer")
    assert op.inputs == ["wards"]
    assert op.params["distances"] == [1, 5, 10]
    rings = next(l for l in spec.layers if l.name == "esz_rings")
    assert rings.renderer.field == "distance"
    code = generate(spec, strict=False)
    ast.parse(code)
    assert "MultipleRingBuffer" in code and "[1, 5, 10]" in code


def test_rainfall_archetype_via_depict():
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    spec.layers[0].renderer.type = "stretch"
    spec.layers[0].renderer.ramp = []
    apply_intent(spec, "annual rainfall map, titled 'Rainfall'")
    assert spec.layers[0].renderer.ramp == archetypes.RAMPS["blues"]
    assert spec.layout.title == "Rainfall"
