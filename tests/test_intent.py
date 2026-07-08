"""Depict instructions (v0.9.0) — data + plain-English intent, merged."""
import ast
import os

from map2arcpy.intent import apply_intent
from map2arcpy.parsers import data
from map2arcpy.generator import generate
from map2arcpy.cli import main
from conftest import EXAMPLES


def _wards():
    return data.parse(os.path.join(EXAMPLES, "wards.geojson"))


def test_symbology_and_labels_retarget_real_layer():
    spec = _wards()
    apply_intent(spec, "unique values by zone, labeled with ward_name")
    lyr = spec.layers[0]
    assert lyr.renderer.type == "unique" and lyr.renderer.field == "zone"
    assert lyr.label_field == "ward_name"
    assert any("depict instruction applied" in n for n in spec.notes)


def test_ops_target_the_named_data_layer():
    spec = _wards()
    apply_intent(spec, "buffer wards by 1 km and clip to \"city_boundary.shp\", "
                       "epsg 32644, titled 'Ward Buffers', A3 landscape, export to PNG")
    tools = [(o.tool, o.inputs) for o in spec.operations]
    assert ("buffer", ["wards"]) == tools[0]           # real layer, not scaffold
    assert tools[1][0] == "clip" and tools[1][1][0] == "buffered"
    assert any(l.name == "city_boundary" for l in spec.layers)   # file from text
    assert spec.crs_epsg == 32644
    assert spec.layout.title == "Ward Buffers"
    assert spec.layout.page == "A3L"
    assert spec.layout.export.endswith(".png")
    code = generate(spec, strict=False)
    ast.parse(code)


def test_select_where_and_no_legend():
    spec = _wards()
    apply_intent(spec, "select where \"population > 40000\", without a legend")
    sel = next(o for o in spec.operations if o.tool == "select")
    assert sel.inputs == ["wards"]
    assert sel.params["where"] == "population > 40000"
    assert spec.layout.legend is False


def test_unrecognised_instruction_notes_honestly():
    spec = _wards()
    apply_intent(spec, "make it pop and feel cinematic")
    assert any("nothing recognised" in n for n in spec.notes)
    assert not spec.operations                          # nothing invented


def test_cli_depict_flag(tmp_path):
    out = tmp_path / "d.py"
    rc = main(["generate", os.path.join(EXAMPLES, "wards.geojson"),
               "-o", str(out), "--no-profile",
               "--depict", "unique values by zone, titled 'Zones'"])
    assert rc == 0
    code = out.read_text()
    assert "apply_unique(lyr, 'zone'" in code
    assert "'title': 'Zones'" in code
