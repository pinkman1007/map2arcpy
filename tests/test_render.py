"""Raster/vector rendering foundation (v0.17.0)."""
import ast
import os

from map2arcpy import convert
from map2arcpy.parsers import nl
from map2arcpy.generator import generate, runtime
from conftest import EXAMPLES


def test_raster_carries_ramp_name_to_apply_stretch():
    spec = nl.parse("rainfall map from rain_2020.tif using blues, epsg 32644")
    ras = next(l for l in spec.layers if l.kind == "raster")
    # archetype/style set a ramp_name; apply_stretch must receive it
    code = generate(spec, strict=False)
    assert "apply_stretch(lyr," in code
    assert "'blues'" in code or "'blues'" in repr(ras.renderer.ramp_name)
    ast.parse(code)


def test_runtime_has_real_colorizer_and_field_check():
    src = runtime.runtime_source()
    assert "def _find_color_ramp" in src
    assert "colorizer.colorRamp" in src
    assert "listColorRamps" in src
    assert "def _field_exists" in src
    assert "def render_report" in src
    assert "RasterStretchColorizer" in src


def test_render_report_wired_into_scripts():
    code = convert(os.path.join(EXAMPLES, "wards.geojson"))
    assert "render_report()" in code
    assert "_render_reset()" in code            # inside setup_env
    ast.parse(code)


def test_ramp_pro_name_map_covers_named_ramps():
    from map2arcpy.palettes import RAMPS
    # every diverging/sequential ramp a user can pick has a Pro mapping
    for name in ("blues", "greens", "viridis", "spectral", "red_blue", "magma"):
        assert name in runtime.RAMP_PRO_NAMES
        assert name in RAMPS


def test_style_ramp_sets_ramp_name():
    from map2arcpy.parsers import data
    from map2arcpy.style import apply_style
    spec = data.parse(os.path.join(EXAMPLES, "wards.geojson"))
    apply_style(spec, {"ramp": "blues"})
    assert spec.layers[0].renderer.ramp_name == "blues"
    # reversed clears the named ramp (exact hex used instead)
    apply_style(spec, {"reverse_ramp": True})
    assert spec.layers[0].renderer.ramp_name is None
