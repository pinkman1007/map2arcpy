import ast
import os

import pytest

from map2arcpy import convert, parse_any
from map2arcpy.generator import generate
from map2arcpy.spec import MapSpec, Layer, Operation, Renderer
from conftest import EXAMPLES

ALL_EXAMPLES = ["describe_choropleth.txt", "describe_buffer.txt",
                "wards.geojson", "landuse.lyrx", "webmap.json"]


@pytest.mark.parametrize("name", ALL_EXAMPLES)
def test_every_example_generates_valid_python(name):
    code = convert(os.path.join(EXAMPLES, name))
    ast.parse(code)                                   # must compile
    assert "def main():" in code
    assert "setup_env" in code
    assert "export_layout" in code
    assert "CONFIG = {" in code


def test_generated_script_contains_ops_and_symbology():
    code = convert(os.path.join(EXAMPLES, "describe_buffer.txt"))
    assert "PairwiseBuffer" in code
    assert "'500 Meters'" in code
    assert "PairwiseClip" in code
    assert "32644" in code                            # UTM 44N
    assert "addBasemap('Topographic')" in code
    assert "apply_simple" in code                     # teal fill on result


def test_geojson_choropleth_script():
    code = convert(os.path.join(EXAMPLES, "wards.geojson"))
    assert "apply_graduated(lyr, 'population'" in code
    assert "$feature.ward_name" in code


def test_strict_mode_raises_on_bad_spec():
    spec = MapSpec(layers=[Layer(name="x", source="")])  # no source
    with pytest.raises(ValueError):
        generate(spec, strict=True)
    # non-strict embeds the problem instead
    code = generate(spec, strict=False)
    assert "# TODO (spec issue)" in code
    ast.parse(code)


def test_op_output_added_as_layer_automatically():
    spec = MapSpec(
        crs_epsg=32644,
        layers=[Layer(name="roads", source="roads.shp")],
        operations=[Operation(tool="buffer", inputs=["roads"], output="roadbuf",
                              params={"distance": "100 Meters"})],
    )
    code = generate(spec)
    ast.parse(code)
    assert "os.path.join(results, 'roadbuf')" in code
    assert "# -- layer: roadbuf" in code


def test_unknown_op_rejected():
    spec = MapSpec(layers=[Layer(name="a", source="a.shp")],
                   operations=[Operation(tool="teleport", inputs=["a"])])
    errs = spec.validate()
    assert any("unknown operation" in e for e in errs)


def test_spec_roundtrip_json():
    spec = parse_any(os.path.join(EXAMPLES, "wards.geojson"))
    again = MapSpec.from_json(spec.to_json())
    assert again.to_dict() == spec.to_dict()


def test_runtime_importable_without_arcpy():
    from map2arcpy.generator import runtime
    assert runtime._HAS_ARCPY in (True, False)
    assert runtime.hex_to_rgb("#1A9641") == [26, 150, 65, 100]
    src = runtime.runtime_source()
    ast.parse(src)
    assert "def setup_env" in src and "def export_layout" in src
